from datetime import timezone
from pathlib import Path

from polybtc.data.importers.v1_market_snapshots import (
    import_v1_market_snapshots,
)


def test_v14_snapshot_import() -> None:
    path = Path("data/raw/v1.1/btc_5m_market_snapshots_v1_4.csv")

    assert path.exists(), f"required v1.4 telemetry file missing: {path}"

    snapshots = import_v1_market_snapshots(path)

    assert snapshots

    for snapshot in snapshots:
        assert snapshot.observed_at.tzinfo is not None
        assert snapshot.observed_at.utcoffset() == timezone.utc.utcoffset(
            snapshot.observed_at
        )

        assert snapshot.condition_id.startswith("0x")

        assert snapshot.reference_price is not None
        assert snapshot.strike is not None

        for price in (
            snapshot.yes_bid,
            snapshot.yes_ask,
            snapshot.no_bid,
            snapshot.no_ask,
        ):
            if price is not None:
                assert 0 <= price <= 1

        for size in (
            snapshot.yes_bid_size,
            snapshot.yes_ask_size,
            snapshot.no_bid_size,
            snapshot.no_ask_size,
        ):
            if size is not None:
                assert size >= 0

        if snapshot.yes_book_timestamp is not None:
            assert snapshot.yes_book_timestamp <= snapshot.observed_at

        if snapshot.no_book_timestamp is not None:
            assert snapshot.no_book_timestamp <= snapshot.observed_at

        if snapshot.reference_timestamp is not None:
            assert snapshot.reference_timestamp <= snapshot.observed_at

        assert snapshot.collector_version == "1.4"
