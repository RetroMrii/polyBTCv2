from datetime import datetime, timedelta, timezone

from polybtc.data.dataset.history_features import (
    build_history_features,
)
from polybtc.data.schema import SnapshotRecord


def make_snapshot(
    timestamp: datetime,
    price: float,
) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=timestamp.isoformat(),
        condition_id="0xabc",
        observed_at=timestamp,
        source_name="test",
        ingested_at=timestamp,
        reference_price=price,
    )


def test_history_features_use_only_past_rows() -> None:
    start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    history = [
        make_snapshot(
            start + timedelta(seconds=i),
            100.0 + i * 0.01,
        )
        for i in range(
            0,
            125,
            5,
        )
    ]

    current = history[-1]

    features = build_history_features(
        history,
        current,
    )

    assert features.reference_return_30s is not None
    assert features.reference_return_60s is not None
    assert features.reference_return_120s is not None

    assert features.reference_abs_return_30s is not None
    assert features.realized_volatility_60s is not None
    assert features.realized_volatility_120s is not None


def test_long_history_features_require_full_window() -> None:
    start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    history = [
        make_snapshot(
            start + timedelta(seconds=i),
            100.0 + i * 0.01,
        )
        for i in range(
            0,
            65,
            5,
        )
    ]

    current = history[-1]

    features = build_history_features(
        history,
        current,
    )

    assert features.reference_return_30s is not None
    assert features.reference_return_60s is not None
    assert features.reference_return_120s is None

    assert features.realized_volatility_60s is not None
    assert features.realized_volatility_120s is None
