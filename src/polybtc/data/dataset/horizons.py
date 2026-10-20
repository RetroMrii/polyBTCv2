from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from polybtc.data.schema import SnapshotRecord
from datetime import timedelta

DEFAULT_HORIZONS_SECONDS = (
    240,
    180,
    120,
    90,
    60,
    30,
)

MAX_HORIZON_LAG_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class HorizonSelection:
    condition_id: str
    target_seconds_to_expiry: int
    snapshot: SnapshotRecord | None
    actual_seconds_to_expiry: float | None
    horizon_gap_seconds: float | None
    status: str


def select_market_horizons(
    snapshots: list[SnapshotRecord],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS_SECONDS,
    require_received_by_target: bool = False,
    max_horizon_lag_seconds: float = MAX_HORIZON_LAG_SECONDS,
) -> list[HorizonSelection]:
    by_market: dict[str, list[SnapshotRecord]] = defaultdict(list)

    for snapshot in snapshots:
        by_market[snapshot.condition_id].append(snapshot)

    selections: list[HorizonSelection] = []

    for condition_id, market_rows in sorted(by_market.items()):
        ordered = sorted(
            market_rows,
            key=lambda row: row.observed_at,
        )

        for horizon in horizons:
            eligible = []

            for row in ordered:
                if row.market_end_at is None:
                    continue

                prediction_timestamp = row.market_end_at - timedelta(seconds=horizon)

                if row.observed_at <= prediction_timestamp:
                    eligible.append(row)

            if not eligible:
                selections.append(
                    HorizonSelection(
                        condition_id=condition_id,
                        target_seconds_to_expiry=horizon,
                        snapshot=None,
                        actual_seconds_to_expiry=None,
                        horizon_gap_seconds=None,
                        status="MISSING_HORIZON",
                    )
                )
                continue

            if require_received_by_target:
                causal = [
                    row for row in eligible
                    if row.ingested_at <= row.market_end_at - timedelta(seconds=horizon)
                ]
                # Preserve the late-arrival diagnostic when no causal candidate
                # exists. The runtime still rejects that row before evaluation.
                # Historical research keeps its observation-only default.
                if causal:
                    eligible = causal

            selected = max(
                eligible,
                key=lambda row: row.observed_at,
            )

            if selected.market_end_at is None:
                raise RuntimeError("selected snapshot missing market_end_at")

            prediction_timestamp = selected.market_end_at - timedelta(seconds=horizon)

            horizon_gap = (prediction_timestamp - selected.observed_at).total_seconds()

            if horizon_gap > max_horizon_lag_seconds:
                selections.append(
                    HorizonSelection(
                        condition_id=condition_id,
                        target_seconds_to_expiry=horizon,
                        snapshot=None,
                        actual_seconds_to_expiry=None,
                        horizon_gap_seconds=horizon_gap,
                        status="STALE_HORIZON",
                    )
                )
                continue

            actual = (selected.market_end_at - selected.observed_at).total_seconds()

            selections.append(
                HorizonSelection(
                    condition_id=condition_id,
                    target_seconds_to_expiry=horizon,
                    snapshot=selected,
                    actual_seconds_to_expiry=actual,
                    horizon_gap_seconds=horizon_gap,
                    status="SELECTED",
                )
            )

    return selections
