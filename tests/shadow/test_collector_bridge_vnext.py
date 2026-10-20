from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.collector_bridge_vnext import (
    VNextCollectorBridge,
)


T0 = datetime(
    2026,
    10,
    8,
    15,
    4,
    0,
    tzinfo=timezone.utc,
)


def snapshot(
    snapshot_id="snapshot-001",
    observed_at=T0,
):
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        condition_id="bridge-market",
        observed_at=observed_at,
        ingested_at=observed_at,
        source_name="v1_market_snapshots",
        market_end_at=T0 + timedelta(seconds=60),
        reference_price=40010.0,
        reference_timestamp=observed_at,
        strike=40000.0,
    )


def make_bridge(path, at):
    return VNextCollectorBridge(
        state_path=path,
        clock=lambda: at,
    )


def test_first_receipt_uses_bridge_time(tmp_path):
    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        T0 + timedelta(seconds=2),
    )

    intake = bridge.ingest([snapshot()])

    assert intake.new_records == 1
    assert intake.previously_received == 0

    assert intake.snapshots[0].ingested_at == (T0 + timedelta(seconds=2))


def test_restart_preserves_original_receipt(tmp_path):
    path = tmp_path / "receipts.sqlite3"

    original = make_bridge(
        path,
        T0 + timedelta(seconds=2),
    )

    original.ingest([snapshot()])

    reopened = make_bridge(
        path,
        T0 + timedelta(seconds=10),
    )

    intake = reopened.ingest([snapshot()])

    assert intake.new_records == 0
    assert intake.previously_received == 1
    assert intake.snapshots[0].ingested_at == (T0 + timedelta(seconds=2))
    assert reopened.receipt_count() == 1


def test_conflicting_source_record_rejected(tmp_path):
    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        T0 + timedelta(seconds=2),
    )

    bridge.ingest([snapshot()])

    conflicting = replace(
        snapshot(),
        reference_price=41000.0,
    )

    with pytest.raises(
        ValueError,
        match="conflicting source contents",
    ):
        bridge.ingest([conflicting])

    assert bridge.receipt_count() == 1


def test_batch_conflict_is_atomic(tmp_path):
    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        T0 + timedelta(seconds=2),
    )

    first = snapshot("same-id")
    second = replace(
        first,
        reference_price=43000.0,
    )

    with pytest.raises(
        ValueError,
        match="Conflicting snapshot_id",
    ):
        bridge.ingest([first, second])

    assert bridge.receipt_count() == 0


def test_future_observation_rejected(tmp_path):
    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        T0,
    )

    future = snapshot(observed_at=T0 + timedelta(seconds=1))

    with pytest.raises(
        ValueError,
        match="in the future",
    ):
        bridge.ingest([future])

    assert bridge.receipt_count() == 0


def test_historical_import_not_backdated(tmp_path):
    import_time = T0 + timedelta(days=2)

    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        import_time,
    )

    historical = snapshot()

    intake = bridge.ingest([historical])

    assert intake.snapshots[0].observed_at == T0
    assert intake.snapshots[0].ingested_at == import_time

    assert intake.snapshots[0].ingested_at > historical.market_end_at


def test_duplicate_input_does_not_duplicate_receipt(tmp_path):
    bridge = make_bridge(
        tmp_path / "receipts.sqlite3",
        T0 + timedelta(seconds=1),
    )

    intake = bridge.ingest(
        [
            snapshot(),
            snapshot(),
        ]
    )

    assert intake.new_records == 1
    assert len(intake.snapshots) == 1
    assert bridge.receipt_count() == 1
