from datetime import datetime, timedelta, timezone

from polybtc.data.dataset.horizons import (
    select_market_horizons,
)
from polybtc.data.schema import SnapshotRecord


def make_snapshot(
    seconds_to_expiry: float,
    offset_seconds: int,
) -> SnapshotRecord:
    observed_at = datetime(
        2026,
        1,
        1,
        0,
        0,
        offset_seconds,
        tzinfo=timezone.utc,
    )

    market_end_at = observed_at + timedelta(seconds=seconds_to_expiry)

    return SnapshotRecord(
        snapshot_id=f"s{offset_seconds}",
        condition_id="0xabc",
        observed_at=observed_at,
        source_name="test",
        ingested_at=datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        seconds_to_expiry=seconds_to_expiry,
        market_end_at=market_end_at,
    )


def test_selects_last_snapshot_before_horizon() -> None:
    snapshots = [
        make_snapshot(124, 1),
        make_snapshot(119, 2),
        make_snapshot(114, 3),
    ]

    result = select_market_horizons(
        snapshots,
        horizons=(120,),
    )

    assert len(result) == 1

    selected = result[0]

    assert selected.status == "SELECTED"
    assert selected.actual_seconds_to_expiry == 124
    assert selected.horizon_gap_seconds == 4
    assert selected.snapshot is not None
    assert selected.snapshot.snapshot_id == "s1"


def test_receipt_filter_is_opt_in_for_historical_research():
    from dataclasses import replace
    earlier = make_snapshot(124, 1)
    target = earlier.market_end_at - timedelta(seconds=120)
    later = replace(earlier, snapshot_id='late', observed_at=target,
                    ingested_at=target+timedelta(seconds=1))
    assert select_market_horizons([earlier, later], horizons=(120,))[0].snapshot == later
    assert select_market_horizons([earlier, later], horizons=(120,),
                                 require_received_by_target=True)[0].snapshot == earlier


def test_missing_horizon_is_explicit() -> None:
    snapshots = [
        make_snapshot(59, 1),
        make_snapshot(54, 2),
    ]

    result = select_market_horizons(
        snapshots,
        horizons=(60,),
    )

    assert result[0].status == "MISSING_HORIZON"
    assert result[0].snapshot is None


def test_stale_horizon_is_rejected() -> None:
    market_end = datetime(
        2026,
        1,
        1,
        0,
        5,
        0,
        tzinfo=timezone.utc,
    )

    snapshot = SnapshotRecord(
        snapshot_id="stale",
        condition_id="0xabc",
        observed_at=(market_end - timedelta(seconds=135)),
        source_name="test",
        ingested_at=market_end,
        seconds_to_expiry=135,
        market_end_at=market_end,
    )

    result = select_market_horizons(
        [snapshot],
        horizons=(120,),
    )

    assert len(result) == 1
    assert result[0].status == "STALE_HORIZON"
    assert result[0].snapshot is None
    assert result[0].horizon_gap_seconds == 15


def test_horizon_at_max_lag_is_allowed() -> None:
    market_end = datetime(
        2026,
        1,
        1,
        0,
        5,
        0,
        tzinfo=timezone.utc,
    )

    snapshot = SnapshotRecord(
        snapshot_id="boundary",
        condition_id="0xabc",
        observed_at=(market_end - timedelta(seconds=130)),
        source_name="test",
        ingested_at=market_end,
        seconds_to_expiry=130,
        market_end_at=market_end,
    )

    result = select_market_horizons(
        [snapshot],
        horizons=(120,),
    )

    assert result[0].status == "SELECTED"
    assert result[0].snapshot is not None
    assert result[0].horizon_gap_seconds == 10
