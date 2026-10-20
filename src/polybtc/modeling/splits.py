from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketSplit:
    train_markets: tuple[str, ...]
    validation_markets: tuple[str, ...]
    test_markets: tuple[str, ...]


def chronological_market_split(
    market_times: dict[str, datetime],
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
) -> MarketSplit:
    if not market_times:
        raise ValueError("market_times is empty")

    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")

    if not 0 <= validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")

    if train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction + validation_fraction must be less than 1")

    ordered = sorted(
        market_times,
        key=lambda condition_id: (
            market_times[condition_id],
            condition_id,
        ),
    )

    market_count = len(ordered)

    if market_count < 3:
        raise ValueError("at least 3 markets are required")

    train_count = max(
        1,
        int(market_count * train_fraction),
    )

    validation_count = max(
        1,
        int(market_count * validation_fraction),
    )

    if train_count + validation_count >= market_count:
        validation_count = 1
        train_count = market_count - validation_count - 1

    train_end = train_count

    validation_end = train_count + validation_count

    return MarketSplit(
        train_markets=tuple(ordered[:train_end]),
        validation_markets=tuple(ordered[train_end:validation_end]),
        test_markets=tuple(ordered[validation_end:]),
    )
