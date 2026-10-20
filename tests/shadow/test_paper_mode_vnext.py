"""Paper boundaries; positive fee attestations below are synthetic test data only."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.operations.run_vnext_shadow import build_runtime, DEFAULT_MODEL_PATH
from polybtc.shadow.operating_mode_vnext import OperatingMode as Mode, bind_state_directory
from polybtc.shadow.service_runtime_vnext import RuntimeConfig, VNextServiceRuntime
from polybtc.shadow.runner_vnext import VerifiedSources
from tests.shadow import test_source_verification_vnext as verification
from tests.shadow import test_fee_provenance_vnext as fees
from tests.shadow import test_stream_driver_vnext as stream
from tests.shadow import test_collector_service_vnext as collector


def setup_runtime(tmp_path, monkeypatch, armed=False, verified=False):
    csv = tmp_path / 'input.csv'
    csv.write_text('observed_at\n', encoding='utf-8')
    cache = fees.attach_cache(SimpleNamespace(), tmp_path, fees.policy())
    monkeypatch.setattr('polybtc.data.fee_policy_cache_vnext.fetch_market_fee_policy',
                        Mock(side_effect=AssertionError('Network forbidden')))
    runtime = build_runtime(csv, tmp_path / 'paper', DEFAULT_MODEL_PATH, cache.path,
                            mode=Mode.PAPER_EXECUTION, enable_paper_fills=armed)
    rows = verification.snapshots()
    runtime.service.history.store(rows)
    runtime.service.bridge.clock = lambda: stream.NOW
    verifier = verification.verifier(rows)
    if verified:
        original = verifier.verify
        # Test-only hypothetical fee attestation, never operational evidence.
        monkeypatch.setattr(verifier, 'verify', lambda **kw: replace(
            original(**kw), sources=VerifiedSources(True, True, True, True), reasons=()))
    runtime.service.driver.source_verifier = verifier
    return runtime, csv, cache


@pytest.mark.parametrize('config', [
    {'mode': Mode.LIVE_EXECUTION}, {'paper_execution_enabled': True},
    {'kill_switch': 0}, {'paper_execution_enabled': 'true'},
])
def test_invalid_modes_and_controls(config):
    with pytest.raises(ValueError):
        RuntimeConfig(**config)


def test_state_ownership_restart_and_nesting(tmp_path):
    paper = tmp_path / 'paper'
    assert bind_state_directory(paper, Mode.PAPER_EXECUTION) == paper.resolve()
    assert bind_state_directory(paper, Mode.PAPER_EXECUTION) == paper.resolve()
    for path, mode in [(paper, Mode.RESEARCH_SHADOW), (paper / 'nested', Mode.PAPER_EXECUTION),
                       (tmp_path, Mode.RESEARCH_SHADOW)]:
        with pytest.raises(ValueError):
            bind_state_directory(path, mode)
    (paper / 'runtime_mode.json').write_text('broken', encoding='utf-8')
    with pytest.raises(ValueError, match='Unreadable'):
        bind_state_directory(paper, Mode.PAPER_EXECUTION)


def test_legacy_research_cannot_be_adopted_as_paper(tmp_path):
    old = tmp_path / 'trades.sqlite3'
    old.write_bytes(b'preserve')
    with pytest.raises(ValueError, match='fresh'):
        bind_state_directory(tmp_path, Mode.PAPER_EXECUTION)
    assert old.read_bytes() == b'preserve'
    bind_state_directory(tmp_path, Mode.RESEARCH_SHADOW)
    with pytest.raises(ValueError):
        bind_state_directory(tmp_path, Mode.PAPER_EXECUTION)


def test_collection_advances_intake_without_decisions(tmp_path):
    (tmp_path / 'source.csv').write_bytes(collector.HEADER + collector.ROW)
    service, driver = collector.build_service(tmp_path, collector.T0)
    runtime = VNextServiceRuntime(service=service, sources=collector.sources(),
        config=RuntimeConfig(mode=Mode.DATA_COLLECTION))
    result = runtime.run_once()
    assert result.source_rows == result.new_receipts == 1
    assert result.decisions == 0 and result.kill_switch
    assert not driver.calls
    assert service.history.load()
    assert runtime.run_once().source_rows == 0


@pytest.mark.parametrize('armed,verified,kill,filled', [
    (False, True, True, False), (True, False, False, False),
    (True, True, True, False), (True, True, False, True),
])
def test_paper_gates_durable_fill_and_restart(tmp_path, monkeypatch, armed, verified, kill, filled):
    runtime, csv, cache = setup_runtime(tmp_path, monkeypatch, armed, verified)
    runtime.config = replace(runtime.config, kill_switch=kill)
    result = runtime.run_once()
    assert result.mode == 'paper_execution'
    assert result.kill_switch == (kill or not armed)
    driver = runtime.service.driver
    positions = driver.adapter.runner.ledger.positions()
    assert len(positions) == int(filled)
    decisions = driver.journal.decisions()
    assert decisions
    if filled:
        assert positions[0].execution_price == pytest.approx(0.66)
        assert json.loads(decisions[-1]['fee_provenance_json']) == fees.policy().provenance()
    restarted = build_runtime(csv, tmp_path / 'paper', DEFAULT_MODEL_PATH, cache.path,
                             mode=Mode.PAPER_EXECUTION, enable_paper_fills=armed)
    restarted.service.bridge.clock = lambda: stream.NOW
    restarted.run_once()
    assert len(restarted.service.driver.adapter.runner.ledger.positions()) == int(filled)
    assert restarted.service.driver.journal.decisions() == decisions


def test_paper_requires_cache_and_simulator(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='existing fee cache'):
        build_runtime(tmp_path / 'in.csv', tmp_path / 'state', DEFAULT_MODEL_PATH,
                      mode=Mode.PAPER_EXECUTION)
    runtime, _, _ = setup_runtime(tmp_path, monkeypatch)
    runtime.service.driver.adapter.runner.executor = object()
    with pytest.raises(ValueError, match='shadow-only'):
        VNextServiceRuntime(service=runtime.service, sources=runtime.sources, config=runtime.config)


def test_paper_rejects_mixed_database_directories(tmp_path, monkeypatch):
    runtime, _, _ = setup_runtime(tmp_path, monkeypatch)
    runtime.service.history.path = tmp_path / 'research' / 'snapshot_history.sqlite3'
    with pytest.raises(ValueError, match='Every paper runtime database'):
        VNextServiceRuntime(service=runtime.service, sources=runtime.sources, config=runtime.config)


def test_research_cannot_be_armed_even_with_verified_flags(tmp_path):
    service, _ = collector.build_service(tmp_path, collector.T0)
    with pytest.raises(ValueError, match='use paper mode'):
        VNextServiceRuntime(service=service, sources=VerifiedSources(True, True, True, True),
                            fee_rate=0.07, config=RuntimeConfig(kill_switch=False))


def test_status_records_effective_paper_configuration(tmp_path, monkeypatch):
    runtime, csv, cache = setup_runtime(tmp_path, monkeypatch)
    status = json.loads(runtime.status_path.read_text())
    config = status['operating_configuration']
    assert status['poll_interval_seconds'] == .25
    assert config['csv_path'] == str(csv.resolve())
    assert config['fee_cache_path'] == str(cache.path.resolve())
    assert config['max_reference_age_ms'] == 3000
    assert config['max_book_age_ms'] == 500
    assert config['execution_wait_seconds'] == 1
    assert status['live_enabled'] is False
    runtime.stop()
