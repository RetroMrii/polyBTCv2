"""Consolidation recovery tests; upstream fixtures are synthetic, never live proof."""

from contextlib import closing
from datetime import timedelta
import json
import sqlite3
from types import SimpleNamespace
import socket
import pytest
from scripts.operations.collect_vnext_local import COLUMNS, append_snapshot
from scripts.operations.run_vnext_shadow import build_runtime, DEFAULT_MODEL_PATH
from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore
from polybtc.shadow.operating_mode_vnext import OperatingMode
from polybtc.shadow.migration_vnext import migrate
from polybtc.shadow.paper_store_vnext import PaperStore
from polybtc.shadow.input_stream_vnext import SQLiteInputTailer
from polybtc.shadow.collector_bridge_vnext import VNextCollectorBridge
from polybtc.data.resolution_handoff_vnext import ResolutionWorker
from polybtc.shadow.settlement_vnext import VerifiedResolution
from tests.shadow import test_paper_acquisition as acquisition
from tests.shadow import test_fee_provenance_vnext as fees
from tests.shadow import test_source_verification_vnext as sources
from tests.shadow import test_stream_driver_vnext as stream


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        socket.socket, "connect", lambda *a, **k: pytest.fail("No network allowed")
    )


def legacy(tmp_path, rows=(), enable_fills=False):
    csv = tmp_path / "input.csv"
    csv.write_text(",".join(COLUMNS) + "\n")
    cache = fees.attach_cache(SimpleNamespace(), tmp_path, fees.policy())
    evidence = AcquisitionEvidenceStore(tmp_path / "evidence.sqlite3", create=True)
    state = tmp_path / "legacy"
    runtime = build_runtime(
        csv,
        state,
        DEFAULT_MODEL_PATH,
        cache.path,
        mode=OperatingMode.PAPER_EXECUTION,
        evidence_path=evidence.path,
        enable_paper_fills=enable_fills,
    )
    runtime.service.bridge.clock = lambda: stream.TARGET - timedelta(seconds=31)
    runtime.run_once()
    for row in rows:
        values = acquisition.telemetry(row)
        acquisition.record(evidence, values, acquisition.upstream(row))
        append_snapshot(csv, values)
        runtime.service.bridge.clock = lambda: row.observed_at
        runtime.run_once()
    runtime.stop()
    evidence.close()
    return state, csv, cache, evidence


def migrated(tmp_path, rows=()):
    state, csv, cache, evidence = legacy(tmp_path, rows)
    manifest = migrate(
        state_dir=state,
        evidence_db=evidence.path,
        fee_cache=cache.path,
        destination=tmp_path / "copy",
    )
    assert manifest["status"] == "complete"
    return tmp_path / "copy" / "state", tmp_path / "copy" / "input.sqlite3", manifest


def build(state, input_path):
    return build_runtime(
        None,
        state,
        DEFAULT_MODEL_PATH,
        mode=OperatingMode.PAPER_EXECUTION,
        input_path=input_path,
        enable_paper_fills=True,
    )


def test_migration_preserves_receipts_decisions_and_restart(tmp_path):
    state, input_path, manifest = migrated(tmp_path, sources.snapshots())
    assert manifest["legacy_receipts_mapped"] == len(sources.snapshots())
    with closing(sqlite3.connect(state / "paper.sqlite3")) as db:
        before = db.execute("SELECT * FROM decisions").fetchall()
    runtime = build(state, input_path)
    runtime.service.bridge.clock = lambda: stream.NOW
    runtime.run_once()
    runtime.stop()
    with closing(sqlite3.connect(state / "paper.sqlite3")) as db:
        assert db.execute("SELECT * FROM decisions").fetchall() == before
    assert len(list(state.glob("*.sqlite3"))) == 1


def test_typed_input_verified_fill_atomic_settlement_restart(tmp_path):
    import threading

    state, input_path, manifest = migrated(tmp_path)
    runtime = build(state, input_path)
    evidence = AcquisitionEvidenceStore(input_path, create=True, stream=True)
    for row in sources.snapshots():
        acquisition.record(
            evidence, acquisition.telemetry(row), acquisition.upstream(row)
        )
        runtime.service.bridge.clock = lambda: row.observed_at
        runtime.run_once()
    ledger = runtime.service.driver.runner.ledger
    assert len(ledger.positions()) == 1, runtime.service.driver.journal.decisions()
    assert ledger.positions()[0].status == "FILLED"
    worker = ResolutionWorker(input_path, state, threading.Event())
    worker.register(
        VerifiedResolution(
            fees.MARKET,
            1,
            stream.END,
            "fixture:official-resolution",
            "fixture:resolved-market",
        )
    )
    worker.drain()
    runtime.service.bridge.clock = lambda: stream.END + timedelta(seconds=1)
    runtime.maintenance.__self__.next_check = 0
    runtime.run_once()
    assert ledger.positions()[0].status == "SETTLED"
    assert ledger.positions()[0].realized_pnl == pytest.approx(1.62146)
    before = runtime.service.driver.journal.decisions()
    runtime.stop()
    evidence.close()
    restarted = build(state, input_path)
    restarted.service.bridge.clock = lambda: stream.END + timedelta(seconds=2)
    restarted.run_once()
    assert restarted.service.driver.journal.decisions() == before
    assert restarted.service.driver.runner.ledger.positions()[0].status == "SETTLED"
    restarted.stop()


def test_receipts_and_cursor_rollback_together(tmp_path):
    state, input_path, _ = migrated(tmp_path)
    evidence = AcquisitionEvidenceStore(input_path, create=True, stream=True)
    acquisition.record(
        evidence,
        acquisition.telemetry(sources.snapshots()[0]),
        acquisition.upstream(sources.snapshots()[0]),
    )
    store = PaperStore(state / "paper.sqlite3")
    tail = SQLiteInputTailer(input_path, store)
    bridge = VNextCollectorBridge(
        state_path=store.path, store=store, clock=lambda: stream.TARGET
    )
    batch = tail.poll()
    with pytest.raises(RuntimeError):
        with store.atomic():
            bridge.ingest([r.snapshot for r in batch.rows])
            tail.ack(batch)
            raise RuntimeError("power loss before commit")
    assert tail.checkpoint() == 0
    assert store.connection.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0
    tail.close()
    store.close()
    evidence.close()


def test_outcome_rollback_retains_claim_without_position(tmp_path, monkeypatch):
    state, input_path, _ = migrated(tmp_path)
    runtime = build(state, input_path)
    evidence = AcquisitionEvidenceStore(input_path, create=True, stream=True)
    journal = runtime.service.driver.journal

    def fail(*a, **k):
        raise RuntimeError("crash completing decision")

    monkeypatch.setattr(runtime.service.driver.reconciler, "reconcile", fail)
    with pytest.raises(RuntimeError, match="crash completing"):
        for row in sources.snapshots():
            acquisition.record(
                evidence, acquisition.telemetry(row), acquisition.upstream(row)
            )
            runtime.service.bridge.clock = lambda: row.observed_at
            runtime.run_once()
    with closing(sqlite3.connect(state / "paper.sqlite3")) as db:
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM decisions WHERE status='PROCESSING'"
            ).fetchone()[0]
            == 1
        )
    evidence.close()


def test_collector_numeric_codec_matches_csv_and_optional_export(tmp_path):
    from polybtc.shadow.converter_vnext import convert_v1_tail_row
    from polybtc.shadow.acquisition_evidence import binding

    for row in sources.snapshots():
        values = acquisition.telemetry(row)
        typed = convert_v1_tail_row(
            SimpleNamespace(row_id="", values=values), source_file=None
        )
        csv = convert_v1_tail_row(
            SimpleNamespace(row_id="", values={k: str(v) for k, v in values.items()}),
            source_file="export.csv",
        )
        assert binding(typed) == binding(csv)


@pytest.mark.parametrize("settled", [False, True])
def test_migration_preserves_filled_and_settled_accounting(tmp_path, settled):
    from polybtc.shadow.ledger_vnext import VNextShadowLedger
    from polybtc.shadow.settlement_vnext import VNextSettlementService

    state, csv, cache, evidence = legacy(
        tmp_path, sources.snapshots(), enable_fills=True
    )
    ledger = VNextShadowLedger(state / "trades.sqlite3")
    assert ledger.positions()[0].status == "FILLED"
    if settled:
        service = VNextSettlementService(
            registry_path=state / "resolutions.sqlite3", ledger=ledger
        )
        service.register(
            VerifiedResolution(
                fees.MARKET, 1, stream.END, "fixture:official", "fixture:outcome"
            )
        )
        service.settle(condition_id=fees.MARKET, at=stream.END + timedelta(seconds=1))
    before = ledger.positions()
    migrate(
        state_dir=state,
        evidence_db=evidence.path,
        fee_cache=cache.path,
        destination=tmp_path / "copy",
    )
    owner = PaperStore(tmp_path / "copy/state/paper.sqlite3")
    copied = VNextShadowLedger(owner.path, store=owner)
    assert copied.positions() == before
    for table in ("entries", "entry_events", "entry_decision_context"):
        with closing(sqlite3.connect(state / "trades.sqlite3")) as old:
            assert old.execute("SELECT * FROM " + table).fetchall() == [
                tuple(row) for row in owner.connection.execute("SELECT * FROM " + table)
            ]
    owner.close()


def test_missing_cursor_is_not_reinitialized(tmp_path):
    from polybtc.shadow.csv_tail_vnext import SourceChanged

    state, input_path, _ = migrated(tmp_path)
    store = PaperStore(state / "paper.sqlite3")
    store.connection.execute("DELETE FROM input_cursor")
    with pytest.raises(SourceChanged, match="Missing migrated"):
        SQLiteInputTailer(input_path, store)
    assert (
        store.connection.execute("SELECT count(*) FROM input_cursor").fetchone()[0] == 0
    )
    store.close()


def test_resolution_conflict_with_existing_registry_is_not_skipped(tmp_path):
    from polybtc.data.resolution_handoff_vnext import initialize
    from polybtc.shadow.settlement_handoff_vnext import SettlementHandoff
    from polybtc.shadow.ledger_vnext import VNextShadowLedger

    state, input_path, _ = migrated(tmp_path)
    initialize(input_path)
    store = PaperStore(state / "paper.sqlite3")
    ledger = VNextShadowLedger(store.path, store=store)
    handoff = SettlementHandoff(
        input_path, store, ledger, lambda: stream.END + timedelta(seconds=1)
    )
    original = VerifiedResolution(
        fees.MARKET, 1, stream.END, "fixture:official", "fixture:yes"
    )
    handoff.service.register(original)
    payload = dict(
        condition_id=fees.MARKET,
        label_yes=0,
        resolved_at_utc=stream.END.isoformat(),
        evidence_source="fixture:official",
        evidence_id="fixture:no",
    )
    with closing(sqlite3.connect(input_path)) as db, db:
        db.execute(
            "INSERT INTO input_resolutions VALUES (?,?)",
            (fees.MARKET, json.dumps(payload)),
        )
    with pytest.raises(ValueError):
        handoff.run_once()
    assert handoff.service.resolutions()[0]["label_yes"] == 1
    handoff.close()
    store.close()
