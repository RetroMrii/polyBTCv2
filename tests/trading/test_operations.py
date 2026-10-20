from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from polybtc.operations import status_report, live_status, atomic_status, model_identity
from polybtc.execution.clob_adapter import ClobAdapterError
from polybtc.execution.lifecycle import UNKNOWN
from polybtc.shadow.service_runtime_vnext import VNextServiceRuntime, RuntimeConfig
from tests.shadow.test_service_runtime_vnext import FakeService, unverified_sources
from tests.trading.test_clob_adapter import setup, submit, NOW, charge


def runtime(tmp_path,**kwargs):
    model=tmp_path/'model.bin'
    model.write_bytes(b'fixture-model')
    return VNextServiceRuntime(service=FakeService(),sources=unverified_sources(),
        status_path=tmp_path/'runtime_status.json',model_path=model,clock=lambda:NOW,**kwargs)


def test_heartbeat_stop_and_no_processing_after_stop(tmp_path):
    r=runtime(tmp_path)
    r.run_once()
    assert status_report(tmp_path,r.model_path,now=NOW)['process']['status']=='healthy'
    assert status_report(tmp_path,r.model_path,now=NOW+timedelta(seconds=6))['process']['status']=='unknown'
    r.stop()
    assert status_report(tmp_path,r.model_path,now=NOW)['process']['status']=='stopped'
    with pytest.raises(RuntimeError,match='stopped'): r.run_once()
    assert len(r.service.calls)==1


def test_cycle_failure_is_explicit_and_stops_even_legacy_continue_setting(tmp_path):
    r=runtime(tmp_path,config=RuntimeConfig(stop_on_error=False))
    r.service.fail=True
    with pytest.raises(RuntimeError): r.run_forever()
    state=json.loads(r.status_path.read_text())
    assert state['state']=='failed' and state['failure']=='runtime_cycle_failed'
    assert 'injected_failure' not in r.status_path.read_text()
    assert r._stop.is_set()


def test_model_drift_stops_before_next_cycle(tmp_path):
    r=runtime(tmp_path)
    r.run_once()
    r.model_path.write_bytes(b'changed-model-artifact')
    with pytest.raises(RuntimeError,match='artifact changed'): r.run_once()
    assert len(r.service.calls)==1
    assert json.loads(r.status_path.read_text())['state']=='failed'


def test_model_drift_with_preserved_size_and_timestamp_stops(tmp_path):
    r=runtime(tmp_path)
    original=r.model_path.stat()
    r.model_path.write_bytes(b'changed-model')
    os.utime(r.model_path,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert r.model_path.stat().st_size==original.st_size
    with pytest.raises(RuntimeError,match='artifact changed'): r.run_once()
    assert len(r.service.calls)==0


def test_missing_inputs_report_unknown_without_creating_state(tmp_path):
    target=tmp_path/'absent'
    report=status_report(target,target/'model',live_ledger=target/'live.db',fee_cache=target/'fee.db',now=NOW)
    assert not target.exists()
    assert report['process']['status']=='unknown' and report['live']['status']=='unavailable'
    assert not report['live_ready'] and report['status']=='blocked'


def test_status_command_works_without_csv_or_runtime_start(tmp_path):
    target=tmp_path/'absent'
    result=subprocess.run([sys.executable,'-m','scripts.operations.run_vnext_shadow','--status','--state-dir',str(target)],
                          capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    assert not report['live_ready'] and report['model']['approved']
    assert not target.exists()


def test_sources_ages_and_fee_freshness_are_explicit(tmp_path):
    payload=dict(snapshot_id='fixture',reference_timestamp=NOW.isoformat(),
        yes_book_timestamp=(NOW-timedelta(seconds=1)).isoformat(),
        no_book_timestamp=(NOW+timedelta(seconds=1)).isoformat())
    with sqlite3.connect(tmp_path/'snapshot_history.sqlite3') as db:
        db.execute('CREATE TABLE snapshots(record_json TEXT,observed_at_utc TEXT)')
        db.execute('INSERT INTO snapshots VALUES (?,?)',(json.dumps(payload),NOW.isoformat()))
    fees=tmp_path/'fees.sqlite3'
    with sqlite3.connect(fees) as db:
        db.execute('CREATE TABLE fee_policies(condition_id TEXT,retrieved_at_utc TEXT)')
        db.execute('CREATE TABLE fee_conflicts(id TEXT)')
        db.execute('INSERT INTO fee_policies VALUES (?,?)',('fixture',(NOW-timedelta(days=2)).isoformat()))
    report=status_report(tmp_path,tmp_path/'model',fee_cache=fees,now=NOW)
    assert report['sources']['reference']['status']=='fresh'
    assert report['sources']['yes_book']['status']=='stale'
    assert report['sources']['no_book']['status']=='future'
    assert report['fees']['policies'][0]['status']=='stale'
    assert not report['fees']['applicability_verified']


def test_live_status_readonly_and_close_retains_liability(setup):
    s=setup
    submit(s)
    s.adapter.reconcile(s.oid,fee_evidence=charge)
    before=hashlib.sha256(s.store.path.read_bytes()).hexdigest()
    report=live_status(s.store.path,NOW)
    assert hashlib.sha256(s.store.path.read_bytes()).hexdigest()==before
    assert report['pending_liabilities']=={'pUSD':'2.79'}
    assert report['positions'][0]['quantity_after_known_fees']=='1.98'
    s.adapter.close()
    report=live_status(s.store.path,NOW)
    assert report['recovery_required'] and report['last_operation']['action']=='shutdown'
    assert report['last_operation']['kill_switch'] and report['pending_liabilities']=={'pUSD':'2.79'}
    s.client.cancel_order.assert_not_called()
    s.adapter.close()
    s.client.close.assert_called_once()


def test_failed_reconciliation_latches_mutations_but_allows_investigation(setup):
    s=setup
    submit(s)
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=lambda _:None)
    report=live_status(s.store.path,NOW)
    assert report['failures'][-1]['action']=='reconcile'
    assert s.adapter.config.kill_switch and not s.adapter.config.live_enabled
    assert s.store.get(s.oid).state==UNKNOWN
    s.adapter.reconcile(s.oid,fee_evidence=charge)
    assert s.adapter.config.kill_switch


def test_status_does_not_migrate_legacy_or_shadow_db(tmp_path):
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE shadow_records(id TEXT)')
        db.execute('PRAGMA user_version=1')
    before=path.read_bytes()
    report=status_report(tmp_path,tmp_path/'model',live_ledger=path,now=NOW)
    assert report['live']['status']=='unavailable' and path.read_bytes()==before


def test_interrupt_during_post_is_quarantined_and_recorded(setup):
    s=setup
    s.client.post_order.side_effect=KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): submit(s)
    assert s.store.get(s.oid).state==UNKNOWN
    report=live_status(s.store.path,NOW)
    assert report['pending_liabilities']=={'pUSD':'4'}
    assert report['failures'][-1]['action']=='submit'


def test_corrupt_heartbeat_is_not_healthy(tmp_path):
    (tmp_path/'runtime_status.json').write_text('{broken')
    assert status_report(tmp_path,tmp_path/'model',now=NOW)['process']['status']=='unknown'


def test_shutdown_failure_is_sanitized_and_releases_process_lock(setup):
    s=setup
    submit(s)
    s.client.close.side_effect=RuntimeError('SENSITIVE-CREDENTIAL')
    with pytest.raises(ClobAdapterError,match='shutdown failed') as error: s.adapter.close()
    assert 'SENSITIVE' not in str(error.value)
    assert s.adapter._lock.closed and s.adapter.config.kill_switch
    report=live_status(s.store.path,NOW)
    assert report['last_operation']['status']=='failed'
    assert report['pending_liabilities']=={'pUSD':'4'}
    assert b'SENSITIVE' not in s.store.path.read_bytes()


def test_stop_requested_during_cycle_drains_then_records_stopped(tmp_path):
    r=runtime(tmp_path)
    original=r.service.run_once
    def cycle(**kwargs):
        r.stop()
        assert json.loads(r.status_path.read_text())['state']=='stopping'
        return original(**kwargs)
    r.service.run_once=cycle
    r.run_once()
    assert json.loads(r.status_path.read_text())['state']=='stopped'


def test_heartbeat_write_failure_stops_processing(tmp_path,monkeypatch):
    r=runtime(tmp_path)
    def fail(*args,**kwargs): raise OSError('disk unavailable')
    monkeypatch.setattr('polybtc.operations.atomic_status',fail)
    with pytest.raises(OSError): r.run_once()
    assert r._stop.is_set()
    with pytest.raises(RuntimeError,match='stopped'): r.run_once()


@pytest.mark.parametrize('code', [5, 32, 33])
def test_heartbeat_transient_windows_conflict_does_not_replay_cycle(tmp_path, monkeypatch, code):
    r = runtime(tmp_path)
    original = os.replace
    calls = []
    sleeps = []
    old = r.status_path.read_bytes()
    def replace(source, destination):
        calls.append(source)
        if len(calls) < 3:
            assert r.status_path.read_bytes() == old
            error = PermissionError('temporary Windows file contention')
            error.winerror = code
            raise error
        original(source, destination)
    monkeypatch.setattr('polybtc.operations.os.replace', replace)
    monkeypatch.setattr('polybtc.operations.time.sleep', sleeps.append)
    r.run_once()
    assert len(r.service.calls) == 1
    assert not r._stop.is_set()
    assert len(calls) == 3 and len(set(calls)) == 1
    assert sleeps == [0.025, 0.05]
    assert json.loads(r.status_path.read_text())['state'] == 'running'
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('code,attempts', [(5, 7), (32, 7), (33, 7), (112, 1), (None, 1)])
def test_atomic_status_failure_is_bounded_and_preserves_previous_file(tmp_path, monkeypatch, code, attempts):
    path = tmp_path / 'status.json'
    atomic_status(path, {'state': 'old'})
    calls = []
    sleeps = []
    error = OSError('publication blocked')
    if code is not None:
        error.winerror = code
    def fail(*args):
        calls.append(args)
        raise error
    monkeypatch.setattr('polybtc.operations.os.replace', fail)
    monkeypatch.setattr('polybtc.operations.time.sleep', sleeps.append)
    with pytest.raises(OSError) as caught:
        atomic_status(path, {'state': 'new'})
    assert caught.value is error
    assert len(calls) == attempts and len(sleeps) == attempts - 1
    assert sum(sleeps) < 1.2
    assert json.loads(path.read_text()) == {'state': 'old'}
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows delete-sharing behavior')
def test_atomic_status_recovers_from_real_windows_reader_lock(tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes
    path = tmp_path / 'status.json'
    atomic_status(path, {'state': 'old'})
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Permit reads but not deletion, just like a reader without FILE_SHARE_DELETE.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    waits = []
    def release(delay):
        nonlocal handle
        waits.append(delay)
        assert json.loads(path.read_text()) == {'state': 'old'}
        assert kernel.CloseHandle(handle)
        handle = None
    monkeypatch.setattr('polybtc.operations.time.sleep', release)
    try:
        atomic_status(path, {'state': 'new'})
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    assert waits == [0.025]
    assert json.loads(path.read_text()) == {'state': 'new'}
    assert not list(tmp_path.glob('*.tmp'))


def test_keyboard_interrupt_finishes_controlled_stop(tmp_path):
    r=runtime(tmp_path)
    def interrupt(**kwargs): raise KeyboardInterrupt()
    r.service.run_once=interrupt
    r.run_forever()
    assert json.loads(r.status_path.read_text())['state']=='stopped'


def test_ambiguous_nonexception_response_is_also_a_paused_failure(setup):
    s=setup
    s.client.post_order.return_value.ok=False
    assert submit(s).state==UNKNOWN
    assert s.adapter.config.kill_switch and not s.adapter.config.live_enabled
    assert live_status(s.store.path,NOW)['last_operation']['status']=='failed'


def test_refused_cancellation_is_reported_as_failure(setup):
    s=setup
    submit(s)
    s.client.cancel_order.return_value.canceled=[]
    s.client.cancel_order.return_value.not_canceled={'exchange1':'fixture:refused'}
    assert not s.adapter.cancel(s.oid,user_authorization='fixture:cancel')
    assert s.adapter.config.kill_switch
    assert live_status(s.store.path,NOW)['last_operation']['status']=='failed'
