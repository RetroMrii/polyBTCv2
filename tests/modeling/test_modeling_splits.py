from datetime import (
    datetime,
    timedelta,
    timezone,
)

from polybtc.modeling.splits import (
    chronological_market_split,
)


def test_chronological_market_split() -> None:
    start = datetime(
        2026,
        1,
        1,
        tzinfo=timezone.utc,
    )

    market_times = {f"market_{i}": (start + timedelta(minutes=i)) for i in range(10)}

    split = chronological_market_split(market_times)

    assert len(split.train_markets) == 6

    assert len(split.validation_markets) == 2

    assert len(split.test_markets) == 2

    assert set(split.train_markets).isdisjoint(split.validation_markets)

    assert set(split.train_markets).isdisjoint(split.test_markets)

    assert set(split.validation_markets).isdisjoint(split.test_markets)
