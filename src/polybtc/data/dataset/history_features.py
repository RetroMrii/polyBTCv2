from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import sqrt

from polybtc.data.schema import SnapshotRecord


MAX_HISTORY_ANCHOR_LAG_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class HistoryFeatures:
    reference_return_30s: float | None
    reference_return_60s: float | None
    reference_return_120s: float | None

    reference_abs_return_30s: float | None
    reference_abs_return_60s: float | None
    reference_abs_return_120s: float | None

    realized_volatility_60s: float | None
    realized_volatility_120s: float | None


def _find_anchor(
    history: list[SnapshotRecord],
    current: SnapshotRecord,
    lag_seconds: int,
) -> SnapshotRecord | None:
    target_time = current.observed_at - timedelta(seconds=lag_seconds)

    eligible = [
        row
        for row in history
        if (
            row.condition_id == current.condition_id
            and row.observed_at <= target_time
            and row.reference_price is not None
        )
    ]

    if not eligible:
        return None

    anchor = max(
        eligible,
        key=lambda row: row.observed_at,
    )

    lag_error = (target_time - anchor.observed_at).total_seconds()

    if lag_error > MAX_HISTORY_ANCHOR_LAG_SECONDS:
        return None

    return anchor


def _reference_return(
    history: list[SnapshotRecord],
    current: SnapshotRecord,
    lag_seconds: int,
) -> float | None:
    if current.reference_price is None:
        return None

    anchor = _find_anchor(
        history,
        current,
        lag_seconds,
    )

    if anchor is None or anchor.reference_price is None or anchor.reference_price == 0:
        return None

    return current.reference_price / anchor.reference_price - 1.0


def _realized_volatility(
    history: list[SnapshotRecord],
    current: SnapshotRecord,
    window_seconds: int,
) -> float | None:
    anchor = _find_anchor(
        history,
        current,
        window_seconds,
    )

    if anchor is None:
        return None

    rows = [
        row
        for row in history
        if (
            row.condition_id == current.condition_id
            and anchor.observed_at <= row.observed_at <= current.observed_at
            and row.reference_price is not None
        )
    ]

    rows.sort(key=lambda row: row.observed_at)

    if len(rows) < 3:
        return None

    returns: list[float] = []

    for previous, following in zip(
        rows,
        rows[1:],
    ):
        if (
            previous.reference_price is None
            or following.reference_price is None
            or previous.reference_price == 0
        ):
            continue

        returns.append(following.reference_price / previous.reference_price - 1.0)

    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)

    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)

    return sqrt(variance)


def build_history_features(
    history: list[SnapshotRecord],
    current: SnapshotRecord,
) -> HistoryFeatures:
    return_30s = _reference_return(
        history,
        current,
        30,
    )

    return_60s = _reference_return(
        history,
        current,
        60,
    )

    return_120s = _reference_return(
        history,
        current,
        120,
    )

    return HistoryFeatures(
        reference_return_30s=return_30s,
        reference_return_60s=return_60s,
        reference_return_120s=return_120s,
        reference_abs_return_30s=(abs(return_30s) if return_30s is not None else None),
        reference_abs_return_60s=(abs(return_60s) if return_60s is not None else None),
        reference_abs_return_120s=(
            abs(return_120s) if return_120s is not None else None
        ),
        realized_volatility_60s=(
            _realized_volatility(
                history,
                current,
                60,
            )
        ),
        realized_volatility_120s=(
            _realized_volatility(
                history,
                current,
                120,
            )
        ),
    )
