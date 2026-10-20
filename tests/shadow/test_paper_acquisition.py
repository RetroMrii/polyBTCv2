"""Real paper runtime integration with synthetic upstream responses, no flag mocks."""
from dataclasses import replace
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace

import pytest
import socket

from scripts.operations.collect_vnext_local import COLUMNS, append_snapshot
from scripts.operations.run_vnext_shadow import build_runtime, DEFAULT_MODEL_PATH
from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore, PaperAcquisitionVerifier
from polybtc.shadow.converter_vnext import convert_v1_tail_row
from polybtc.shadow.operating_mode_vnext import OperatingMode
from polybtc.shadow.settlement_vnext import VNextSettlementService, VerifiedResolution
from tests.shadow import test_source_verification_vnext as sources
from tests.shadow import test_fee_provenance_vnext as fees
from tests.shadow import test_stream_driver_vnext as stream


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args,**kwargs):
        raise AssertionError('Paper decision/replay tests cannot access a network')
    monkeypatch.setattr(socket.socket,'connect',blocked)


def upstream(row):
    def ref(value,at):
        return dict(topic='crypto_prices_twap_sixty',type='update',payload=dict(
            symbol='btc/usd',window_s=60,value=value,timestamp=int(at.timestamp()*1000)))
    def book(side):
        return dict(market=row.condition_id,asset_id=getattr(row,side+'_token_id'),
            timestamp=int(getattr(row,side+'_book_timestamp').timestamp()*1000),
            tick_size='.01',min_order_size='5',
            bids=[dict(price=str(getattr(row,side+'_bid')),size='10')],
            asks=[dict(price=str(getattr(row,side+'_ask')),size='10')])
    return dict(market=dict(conditionId=row.condition_id,outcomes=['Up','Down'],clobTokenIds=['101','202'],
        endDate=row.market_end_at.isoformat(),slug='btc-updown-5m-'+str(int(row.market_end_at.timestamp()-300))),
        reference=ref(row.reference_price,row.reference_timestamp),
        strike=ref(row.strike,row.market_end_at-timedelta(seconds=300)),yes=book('yes'),no=book('no'))


def telemetry(row):
    values={k:'' for k in COLUMNS}
    values.update(observed_at=row.observed_at.isoformat(),market_id=row.condition_id,
        btc_price=row.reference_price,strike=row.strike,market_end_at=row.market_end_at.isoformat(),
        seconds_to_expiry=(row.market_end_at-row.observed_at).total_seconds(),
        reference_timestamp=row.reference_timestamp.isoformat(),collector_version='polybtc_vnext_local_v1')
    for side in ('yes','no'):
        for k in ('bid','ask','token_id','tick_size','min_order_size'):
            values[side+'_'+k]=getattr(row,side+'_'+k)
        values[side+'_bid_size']=values[side+'_ask_size']=10
        values[side+'_book_timestamp']=getattr(row,side+'_book_timestamp').isoformat()
    return values


def record(store,values,raw):
    strings={k:str(v) for k,v in values.items()}
    row=convert_v1_tail_row(SimpleNamespace(row_id='',values=strings),source_file='input.csv')
    store.record(row,raw,row.observed_at)
    return row


def test_acquisition_diagnostics_distinguish_lookup_and_raw_failures(tmp_path):
    store = AcquisitionEvidenceStore(tmp_path / 'diagnostics.db', create=True)
    row = sources.snapshots()[1]
    normalized = record(store, telemetry(row), upstream(row))
    imported = replace(normalized, snapshot_id='runtime-generated-id', source_file='another-path.csv',
                       ingested_at=normalized.observed_at)
    verifier = PaperAcquisitionVerifier(store)
    ev, error = verifier._bound_result(imported, stream.TARGET)
    assert ev is not None and error is None
    assert ev.snapshot.snapshot_id == imported.snapshot_id
    assert verifier._bound_result(replace(imported, reference_price=1), stream.TARGET)[1] == 'missing_evidence'

    # Isolated corrupt store fixture, never a production evidence database.
    from polybtc.shadow.acquisition_evidence import binding, digest
    key = digest(binding(imported))
    with sqlite3.connect(store.path) as db:
        db.execute('DROP TRIGGER immutable_UPDATE')
        raw = upstream(row)
        raw['yes']['asset_id'] = '202'
        db.execute('UPDATE acquisition SET raw=? WHERE id=?', (json.dumps(raw), key))
    assert verifier._bound_result(imported, stream.TARGET)[1] == 'book_identity_mismatch'
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE acquisition SET raw=? WHERE id=?', ('{}', key))
    assert verifier._bound_result(imported, stream.TARGET)[1] == 'malformed_acquisition_evidence'
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE acquisition SET snapshot=? WHERE id=?', ('{}', key))
    assert verifier._bound_result(imported, stream.TARGET)[1] == 'canonical_snapshot_mismatch'


def test_actual_paper_pipeline_fills_settles_and_restarts(tmp_path):
    csv=tmp_path/'input.csv'
    csv.write_text(','.join(COLUMNS)+'\n')
    cache=fees.attach_cache(SimpleNamespace(),tmp_path,fees.policy())
    evidence=AcquisitionEvidenceStore(tmp_path/'evidence.db',create=True)
    state=tmp_path/'paper'
    def build():
        return build_runtime(csv,state,DEFAULT_MODEL_PATH,cache.path,mode=OperatingMode.PAPER_EXECUTION,
            enable_paper_fills=True,evidence_path=evidence.path)
    runtime=build()
    runtime.service.bridge.clock=lambda:stream.TARGET-timedelta(seconds=31)
    runtime.run_once()  # Establish the documented initial EOF checkpoint.
    for row in sources.snapshots():
        values=telemetry(row)
        record(evidence,values,upstream(row))
        append_snapshot(csv,values)
        runtime.service.bridge.clock=lambda:row.observed_at
        runtime.run_once()
    ledger=runtime.service.driver.adapter.runner.ledger
    assert len(ledger.positions())==1, runtime.service.driver.journal.decisions()
    decision=runtime.service.driver.journal.decisions()[-1]
    assert 'paper_cash_taker_full_precision_v1' in json.dumps(decision)
    restarted=build()
    restarted.service.bridge.clock=lambda:stream.NOW
    restarted.run_once()
    assert len(restarted.service.driver.adapter.runner.ledger.positions())==1
    settlement=VNextSettlementService(registry_path=state/'resolutions.sqlite3',ledger=ledger)
    result=settlement.register(VerifiedResolution(fees.MARKET,1,stream.END,
        'fixture:official-resolution','fixture:resolved-market'))
    assert result.status in ('VERIFIED','SETTLED')
    settlement.settle(condition_id=fees.MARKET,at=stream.END+timedelta(seconds=1))
    assert ledger.positions()[0].status=='SETTLED'
    assert ledger.positions()[0].realized_pnl==pytest.approx(5-5*.66-5*.07*.66*.34)
    settlement.settle(condition_id=fees.MARKET,at=stream.END+timedelta(seconds=2))
    from polybtc.operations import status_report
    report=status_report(state,DEFAULT_MODEL_PATH,fee_cache=cache.path,now=stream.END)
    assert report['paper']['pending_liabilities']==0
    assert report['paper']['open_cost']==0
    assert report['paper']['realized_pnl']==pytest.approx(1.62146)
    assert report['live_ready'] is False


def test_evidence_tamper_missing_and_immutable(tmp_path):
    store=AcquisitionEvidenceStore(tmp_path/'evidence.db',create=True)
    source=sources.snapshots()[0]
    row=record(store,telemetry(source),upstream(source))
    assert store.lookup(row) is not None
    assert store.lookup(replace(row,reference_price=row.reference_price+1)) is None
    raw=upstream(source)
    raw['yes']['asset_id']='202'
    with pytest.raises(ValueError,match='identity'):
        store.record(row,raw,row.observed_at)
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('DELETE FROM acquisition')


def test_polybolt_decimal_and_sequence_gap(monkeypatch):
    from scripts.operations.collect_vnext_local import PolyBoltFeed
    feed=PolyBoltFeed(dict(apiKey='fixture',secret='fixture',passphrase='fixture'))
    monkeypatch.setattr('time.time',lambda:stream.NOW.timestamp())
    frame=dict(v=1,seq=1,ts=int(stream.NOW.timestamp()*1000),channel='price.crypto.twap',
        payload=dict(symbol='btcusd',source='chainlink',window_seconds=60,
                     timestamp=int(stream.NOW.timestamp()*1000),value=40010,
                     full_accuracy_value='40010.123456789'))
    feed.ingest(frame)
    assert feed._samples[-1]['value']==pytest.approx(40010.123456789)
    assert feed._samples[-1]['evidence']['channel']=='price.crypto.twap'
    with pytest.raises(ValueError,match='sequence gap'): feed.ingest(dict(frame,seq=3))
    assert not feed._samples


def test_polybolt_auth_failure_does_not_subscribe_or_log_secret(monkeypatch,caplog):
    import threading
    from unittest.mock import Mock
    from scripts.operations.collect_vnext_local import PolyBoltFeed
    stop=threading.Event()
    socket=Mock()
    socket.recv.return_value=json.dumps(dict(op='error',secret='DO-NOT-LOG'))
    socket.close.side_effect=stop.set
    monkeypatch.setattr('websocket.create_connection',lambda *a,**k:socket)
    # Avoid the bounded reconnect wait in this deterministic test.
    stop.wait=lambda _:False
    feed=PolyBoltFeed(dict(apiKey='fixture',secret='DO-NOT-LOG',passphrase='fixture'))
    feed.run(stop)
    assert socket.send.call_count==1
    assert 'DO-NOT-LOG' not in caplog.text


def test_acquisition_and_history_keep_full_durability_with_wal(tmp_path):
    from polybtc.shadow.collector_service_vnext import VNextSnapshotHistory
    store = AcquisitionEvidenceStore(tmp_path/'durable.sqlite3', create=True)
    history = VNextSnapshotHistory(tmp_path/'history.sqlite3')
    for path in (store.path, history.path):
        with sqlite3.connect(path) as db:
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            assert db.execute('PRAGMA synchronous').fetchone()[0] == 2
    row = sources.snapshots()[0]
    retained = record(store, telemetry(row), upstream(row))
    history.store([retained])
    assert AcquisitionEvidenceStore(store.path).lookup(retained) is not None
    assert VNextSnapshotHistory(history.path).load() == [retained]


def test_cache_failure_after_decision_replays_receipt_without_second_evaluation(tmp_path, monkeypatch):
    csv = tmp_path/'input.csv'
    csv.write_text(','.join(COLUMNS)+'\n', encoding='utf-8')
    cache = fees.attach_cache(SimpleNamespace(),tmp_path,fees.policy())
    evidence = AcquisitionEvidenceStore(tmp_path/'evidence.db',create=True)
    state = tmp_path/'paper'
    def build():
        return build_runtime(csv,state,DEFAULT_MODEL_PATH,cache.path,
            mode=OperatingMode.PAPER_EXECUTION,enable_paper_fills=True,evidence_path=evidence.path)
    runtime = build()
    runtime.service.bridge.clock=lambda:stream.TARGET-timedelta(seconds=31)
    runtime.run_once()
    for row in sources.snapshots()[:2]:
        values=telemetry(row);record(evidence,values,upstream(row));append_snapshot(csv,values)
        runtime.service.bridge.clock=lambda:row.observed_at
        runtime.run_once()
    row=sources.snapshots()[2]
    values=telemetry(row);record(evidence,values,upstream(row));append_snapshot(csv,values)
    runtime.service.bridge.clock=lambda:row.observed_at
    before=runtime.service.tailer.checkpoint()
    monkeypatch.setattr(runtime.service.history,'store',lambda rows: (_ for _ in ()).throw(OSError('cache commit failed')))
    with pytest.raises(OSError,match='cache commit failed'):
        runtime.run_once()
    original=runtime.service.driver.journal.decisions()
    assert len(runtime.service.driver.adapter.runner.ledger.positions()) == 1
    assert runtime.service.tailer.checkpoint() == before
    reopened=build()
    reopened.service.bridge.clock=lambda:stream.NOW+timedelta(seconds=1)
    def forbidden(*a,**kw):raise AssertionError('Finalized decision evaluated again')
    monkeypatch.setattr(reopened.service.driver.adapter.runner,'evaluate',forbidden)
    summary=reopened.run_once()
    assert summary.new_receipts == 0 and summary.source_rows == 1
    assert reopened.service.driver.journal.decisions() == original
    assert len(reopened.service.driver.adapter.runner.ledger.positions()) == 1
    assert len(reopened.service.history.load()) == 3
    assert reopened.service.tailer.checkpoint() > before


def test_idle_wal_readers_do_not_hold_transactions_or_prevent_checkpoints(tmp_path):
    from polybtc.shadow.sqlite_wal_vnext import WALReaders
    path=tmp_path/'wal.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE sample(value)')
    readers=WALReaders([path])
    assert all(not c.in_transaction for c in readers.connections)
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sample VALUES (1)');db.commit()
        assert db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
    readers.close();readers.close()
    assert readers.connections == []


def waiting_driver(tmp_path):
    from polybtc.shadow.stream_driver_vnext import StreamDriverConfig
    rows=[replace(row,yes_bid_size=10,no_bid_size=10) for row in sources.snapshots()]
    rows[2]=replace(rows[2],reference_timestamp=stream.NOW-timedelta(milliseconds=3001))
    store=AcquisitionEvidenceStore(tmp_path/'wait_evidence.db',create=True)
    for row in rows:store.record(row,upstream(row),row.observed_at)
    driver,journal,runner=stream.build_driver(tmp_path)
    driver.config=StreamDriverConfig(execution_wait_seconds=1)
    driver.source_verifier=PaperAcquisitionVerifier(store)
    if (tmp_path/"fees.sqlite3").exists():
        from polybtc.data.fee_policy_cache_vnext import VNextFeePolicyCache
        driver.fee_cache=VNextFeePolicyCache(tmp_path/"fees.sqlite3")
    else:
        fees.attach_cache(driver,tmp_path,fees.policy())
    return driver,journal,runner,store,rows


def test_paper_handoff_waits_without_claim_and_evaluates_once_on_real_new_input(tmp_path):
    driver,journal,runner,store,rows=waiting_driver(tmp_path)
    assert stream.run(driver,rows) == []
    selected=journal.decisions()[0]
    assert selected['status'] == 'AWAITING_EXECUTION_ADAPTER'
    assert selected['claim_token'] is None and selected['source_verification_json'] is None
    assert runner.ledger.positions() == []
    driver,journal,runner,store,rows=waiting_driver(tmp_path)
    assert journal.decisions()[0] == selected  # Pending handoff survives restart.
    later=stream.NOW+timedelta(milliseconds=500)
    fresh=replace(rows[2],snapshot_id='new-execution',observed_at=later,ingested_at=later,
                  reference_timestamp=later-timedelta(milliseconds=100),
                  yes_book_timestamp=later-timedelta(milliseconds=100),no_book_timestamp=later-timedelta(milliseconds=100))
    store.record(fresh,upstream(fresh),later)
    results=driver.process(snapshots=[*rows,fresh],at=later,sources=sources.VerifiedSources(False,False,False,False),fee_rate=.07)
    assert len(results)==1 and results[0].status=='SHADOW_FILLED'
    final=journal.decisions()[0]
    assert final['snapshot_id']==selected['snapshot_id']
    assert len(runner.ledger.positions())==1
    assert driver.process(snapshots=[*rows,fresh],at=later,sources=sources.VerifiedSources(False,False,False,False),fee_rate=.07)==[]
    assert journal.decisions()[0]==final


def test_paper_handoff_timeout_is_terminal_and_not_retried(tmp_path):
    driver,journal,runner,store,rows=waiting_driver(tmp_path)
    assert stream.run(driver,rows)==[]
    results=driver.process(snapshots=rows,at=stream.NOW+timedelta(seconds=1),sources=sources.VerifiedSources(False,False,False,False),fee_rate=.07)
    assert len(results)==1 and results[0].reason=='unverified_input_provenance'
    before=journal.decisions()[0]
    assert stream.run(driver,rows)==[]
    assert journal.decisions()[0]==before
    assert runner.ledger.positions()==[]


def test_paper_handoff_never_waits_on_untrusted_prediction(tmp_path):
    driver,journal,runner,store,rows=waiting_driver(tmp_path)
    rows[1]=replace(rows[1],reference_price=rows[1].reference_price+1)
    results=stream.run(driver,rows)
    assert len(results)==1 and results[0].reason=='unverified_input_provenance'
    assert journal.decisions()[0]['status']=='ABSTAIN'
