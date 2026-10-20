from __future__ import annotations

from dataclasses import dataclass

from polybtc.data.schema import SnapshotRecord


@dataclass(frozen=True, slots=True)
class SnapshotFeatures:
    distance_from_strike: float | None
    absolute_distance_from_strike: float | None
    relative_distance_from_strike: float | None

    yes_mid: float | None
    no_mid: float | None

    yes_spread: float | None
    no_spread: float | None

    yes_top_depth: float | None
    no_top_depth: float | None

    yes_book_imbalance: float | None
    no_book_imbalance: float | None

    normalized_yes_mid: float | None

    reference_age_ms: float | None
    yes_book_age_ms: float | None
    no_book_age_ms: float | None

    yes_book_latency_ms: float | None
    no_book_latency_ms: float | None
    snapshot_build_latency_ms: float | None


def _mid(
    bid: float | None,
    ask: float | None,
) -> float | None:
    if bid is None or ask is None:
        return None

    return (bid + ask) / 2.0


def _spread(
    bid: float | None,
    ask: float | None,
) -> float | None:
    if bid is None or ask is None:
        return None

    return ask - bid


def _top_depth(
    bid_size: float | None,
    ask_size: float | None,
) -> float | None:
    if bid_size is None or ask_size is None:
        return None

    return bid_size + ask_size


def _imbalance(
    bid_size: float | None,
    ask_size: float | None,
) -> float | None:
    if bid_size is None or ask_size is None:
        return None

    total = bid_size + ask_size

    if total <= 0:
        return None

    return (bid_size - ask_size) / total


def build_snapshot_features(
    snapshot: SnapshotRecord,
) -> SnapshotFeatures:
    distance = None
    absolute_distance = None
    relative_distance = None

    if snapshot.reference_price is not None and snapshot.strike is not None:
        distance = snapshot.reference_price - snapshot.strike

        absolute_distance = abs(distance)

        if snapshot.strike != 0:
            relative_distance = distance / snapshot.strike

    yes_mid = _mid(
        snapshot.yes_bid,
        snapshot.yes_ask,
    )

    no_mid = _mid(
        snapshot.no_bid,
        snapshot.no_ask,
    )

    normalized_yes_mid = None

    if yes_mid is not None and no_mid is not None:
        total_mid = yes_mid + no_mid

        if total_mid > 0:
            normalized_yes_mid = yes_mid / total_mid

    return SnapshotFeatures(
        distance_from_strike=distance,
        absolute_distance_from_strike=(absolute_distance),
        relative_distance_from_strike=(relative_distance),
        yes_mid=yes_mid,
        no_mid=no_mid,
        yes_spread=_spread(
            snapshot.yes_bid,
            snapshot.yes_ask,
        ),
        no_spread=_spread(
            snapshot.no_bid,
            snapshot.no_ask,
        ),
        yes_top_depth=_top_depth(
            snapshot.yes_bid_size,
            snapshot.yes_ask_size,
        ),
        no_top_depth=_top_depth(
            snapshot.no_bid_size,
            snapshot.no_ask_size,
        ),
        yes_book_imbalance=_imbalance(
            snapshot.yes_bid_size,
            snapshot.yes_ask_size,
        ),
        no_book_imbalance=_imbalance(
            snapshot.no_bid_size,
            snapshot.no_ask_size,
        ),
        normalized_yes_mid=(normalized_yes_mid),
        reference_age_ms=(snapshot.reference_age_ms),
        yes_book_age_ms=(snapshot.yes_book_age_ms),
        no_book_age_ms=(snapshot.no_book_age_ms),
        yes_book_latency_ms=(snapshot.yes_book_latency_ms),
        no_book_latency_ms=(snapshot.no_book_latency_ms),
        snapshot_build_latency_ms=(snapshot.snapshot_build_latency_ms),
    )
