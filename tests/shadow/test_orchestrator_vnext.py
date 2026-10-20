from datetime import datetime, timedelta, timezone

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.orchestrator_vnext import (
    OrchestratorConfig,
    VNextDecisionOrchestrator,
)


END = datetime(2026, 10, 8, 15, 5, tzinfo=timezone.utc)
TARGET = END - timedelta(seconds=60)


def make_snapshot(
    *,
    snapshot_id="snapshot-001",
    observed_at=TARGET,
    ingested_at=TARGET,
    market="market-a",
    end=END,
):
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        condition_id=market,
        observed_at=observed_at,
        ingested_at=ingested_at,
        source_name="orchestrator_test",
        market_end_at=end,
        reference_price=40000.0,
        strike=40000.0,
    )


@pytest.fixture
def orchestrator(tmp_path):
    return VNextDecisionOrchestrator(
        journal_path=tmp_path / "decisions.sqlite3",
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2.0,
        ),
    )


def test_finalized_horizon_is_recorded(orchestrator):
    results = orchestrator.process(
        snapshots=[make_snapshot()],
        processing_at_utc=TARGET + timedelta(seconds=2),
    )

    assert len(results) == 1
    assert results[0].status == ("AWAITING_EXECUTION_ADAPTER")

    assert len(orchestrator.decisions()) == 1


def test_no_early_finalization(orchestrator):
    results = orchestrator.process(
        snapshots=[make_snapshot()],
        processing_at_utc=TARGET + timedelta(seconds=1),
    )

    assert results == []
    assert orchestrator.decisions() == []


def test_restart_prevents_duplicate(tmp_path):
    path = tmp_path / "restart.sqlite3"

    first = VNextDecisionOrchestrator(
        journal_path=path,
        config=OrchestratorConfig(horizons=(60,)),
    )

    assert (
        len(
            first.process(
                snapshots=[make_snapshot()],
                processing_at_utc=TARGET + timedelta(seconds=3),
            )
        )
        == 1
    )

    reopened = VNextDecisionOrchestrator(
        journal_path=path,
        config=OrchestratorConfig(horizons=(60,)),
    )

    assert (
        reopened.process(
            snapshots=[make_snapshot()],
            processing_at_utc=TARGET + timedelta(seconds=4),
        )
        == []
    )

    assert len(reopened.decisions()) == 1


def test_future_ingestion_is_excluded(orchestrator):
    future_row = make_snapshot(
        ingested_at=TARGET + timedelta(seconds=10),
    )

    results = orchestrator.process(
        snapshots=[future_row],
        processing_at_utc=TARGET + timedelta(seconds=2),
    )

    assert results == []


def test_late_arriving_snapshot_abstains(orchestrator):
    late_row = make_snapshot(
        ingested_at=TARGET + timedelta(seconds=1),
    )

    results = orchestrator.process(
        snapshots=[late_row],
        processing_at_utc=TARGET + timedelta(seconds=2),
    )

    assert len(results) == 1
    assert results[0].status == "ABSTAIN"
    assert results[0].reason == ("snapshot_arrived_after_target")


def test_stale_horizon_abstains(orchestrator):
    stale_row = make_snapshot(
        observed_at=TARGET - timedelta(seconds=15),
        ingested_at=TARGET - timedelta(seconds=15),
    )

    results = orchestrator.process(
        snapshots=[stale_row],
        processing_at_utc=TARGET + timedelta(seconds=2),
    )

    assert len(results) == 1
    assert results[0].status == "ABSTAIN"
    assert results[0].reason == "stale_horizon"


def test_latest_late_receipt_does_not_mask_earlier_causal_snapshot(orchestrator):
    earlier = make_snapshot(snapshot_id="causal", observed_at=TARGET-timedelta(seconds=2),
                            ingested_at=TARGET-timedelta(seconds=1))
    late = make_snapshot(snapshot_id="late", observed_at=TARGET-timedelta(milliseconds=5),
                         ingested_at=TARGET+timedelta(milliseconds=300))
    results = orchestrator.process(snapshots=[earlier, late], processing_at_utc=TARGET+timedelta(seconds=2))
    assert results[0].status == "AWAITING_EXECUTION_ADAPTER"
    assert results[0].snapshot_id == "causal"
    original = orchestrator.decisions()
    assert orchestrator.process(snapshots=[earlier, late], processing_at_utc=TARGET+timedelta(seconds=3)) == []
    assert orchestrator.decisions() == original


def test_causal_fallback_keeps_ten_second_lag_limit(orchestrator):
    old = make_snapshot(snapshot_id="old", observed_at=TARGET-timedelta(seconds=11),
                        ingested_at=TARGET-timedelta(seconds=10))
    late = make_snapshot(snapshot_id="late", ingested_at=TARGET+timedelta(milliseconds=1))
    result = orchestrator.process(snapshots=[old, late], processing_at_utc=TARGET+timedelta(seconds=2))[0]
    assert result.reason == "stale_horizon"


def test_causal_receipt_at_exact_target_is_eligible(orchestrator):
    exact = make_snapshot(snapshot_id="exact", observed_at=TARGET-timedelta(seconds=10), ingested_at=TARGET)
    late = make_snapshot(snapshot_id="late", ingested_at=TARGET+timedelta(milliseconds=1))
    result = orchestrator.process(snapshots=[exact, late], processing_at_utc=TARGET+timedelta(seconds=2))[0]
    assert result.snapshot_id == "exact"
    assert result.status == "AWAITING_EXECUTION_ADAPTER"


def test_previously_finalized_late_horizon_is_not_replayed(orchestrator):
    late = make_snapshot(snapshot_id="late", ingested_at=TARGET+timedelta(milliseconds=300))
    orchestrator.process(snapshots=[late], processing_at_utc=TARGET+timedelta(seconds=2))
    original = orchestrator.decisions()
    assert original[0]["reason"] == "snapshot_arrived_after_target"
    earlier = make_snapshot(snapshot_id="earlier", observed_at=TARGET-timedelta(seconds=2),
                            ingested_at=TARGET-timedelta(seconds=1))
    assert orchestrator.process(snapshots=[earlier, late], processing_at_utc=TARGET+timedelta(seconds=3)) == []
    assert orchestrator.decisions() == original


def test_multiple_markets(orchestrator):
    snapshots = [
        make_snapshot(market="market-a"),
        make_snapshot(
            snapshot_id="snapshot-b",
            market="market-b",
        ),
    ]

    results = orchestrator.process(
        snapshots=snapshots,
        processing_at_utc=TARGET + timedelta(seconds=2),
    )

    assert len(results) == 2
    assert len(orchestrator.decisions()) == 2


def test_conflicting_market_expiry_rejected(orchestrator):
    snapshots = [
        make_snapshot(),
        make_snapshot(
            snapshot_id="other",
            observed_at=TARGET - timedelta(seconds=1),
            ingested_at=TARGET - timedelta(seconds=1),
            end=END + timedelta(seconds=5),
        ),
    ]

    with pytest.raises(RuntimeError):
        orchestrator.process(
            snapshots=snapshots,
            processing_at_utc=TARGET + timedelta(seconds=2),
        )


def test_repeated_poll_does_not_write_sequence(orchestrator):
    import sqlite3
    at = TARGET + timedelta(seconds=2)
    orchestrator.process(snapshots=[make_snapshot()], processing_at_utc=at)
    with sqlite3.connect(orchestrator.path) as db:
        before = db.execute("SELECT seq FROM sqlite_sequence WHERE name='decisions'").fetchone()
    assert orchestrator.process(snapshots=[make_snapshot()], processing_at_utc=at) == []
    with sqlite3.connect(orchestrator.path) as db:
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='decisions'").fetchone() == before
    assert len(orchestrator.decisions(status="AWAITING_EXECUTION_ADAPTER")) == 1
    assert orchestrator.decisions(status="PROCESSING") == []
