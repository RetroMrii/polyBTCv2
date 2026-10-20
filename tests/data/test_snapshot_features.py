from datetime import datetime, timezone

from polybtc.data.dataset.features import (
    build_snapshot_features,
)
from polybtc.data.schema import SnapshotRecord


def make_snapshot() -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id="s1",
        condition_id="0xabc",
        observed_at=datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        source_name="test",
        ingested_at=datetime(
            2026,
            1,
            1,
            tzinfo=timezone.utc,
        ),
        reference_price=101.0,
        strike=100.0,
        yes_bid=0.60,
        yes_ask=0.62,
        no_bid=0.38,
        no_ask=0.40,
        yes_bid_size=30.0,
        yes_ask_size=10.0,
        no_bid_size=20.0,
        no_ask_size=20.0,
        reference_age_ms=2000.0,
        yes_book_age_ms=120.0,
        no_book_age_ms=40.0,
        yes_book_latency_ms=90.0,
        no_book_latency_ms=80.0,
        snapshot_build_latency_ms=190.0,
    )


def test_snapshot_features() -> None:
    features = build_snapshot_features(make_snapshot())

    assert features.distance_from_strike == 1.0
    assert features.absolute_distance_from_strike == 1.0
    assert features.relative_distance_from_strike == 0.01

    assert features.yes_mid == 0.61
    assert features.no_mid == 0.39

    assert (
        round(
            features.yes_spread,
            10,
        )
        == 0.02
    )

    assert (
        round(
            features.no_spread,
            10,
        )
        == 0.02
    )

    assert features.yes_top_depth == 40.0
    assert features.no_top_depth == 40.0

    assert features.yes_book_imbalance == 0.5
    assert features.no_book_imbalance == 0.0

    assert features.normalized_yes_mid == 0.61


def test_missing_market_data_stays_missing() -> None:
    snapshot = make_snapshot()

    snapshot = SnapshotRecord(
        snapshot_id=snapshot.snapshot_id,
        condition_id=snapshot.condition_id,
        observed_at=snapshot.observed_at,
        source_name=snapshot.source_name,
        ingested_at=snapshot.ingested_at,
        reference_price=snapshot.reference_price,
        strike=snapshot.strike,
    )

    features = build_snapshot_features(snapshot)

    assert features.yes_mid is None
    assert features.no_mid is None
    assert features.normalized_yes_mid is None
