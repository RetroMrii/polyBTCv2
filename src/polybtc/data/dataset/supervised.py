from __future__ import annotations

import csv
from polybtc.data.dataset.history_features import (
    build_history_features,
)
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from polybtc.data.dataset.features import (
    build_snapshot_features,
)
from polybtc.data.dataset.horizons import (
    HorizonSelection,
)
from polybtc.data.schema import SnapshotRecord


DATASET_VERSION = "p4_v1"
FEATURE_VERSION = "snapshot_history_v1"
EXPECTED_LABEL_VERSION = "p3_v1"


@dataclass(frozen=True, slots=True)
class SupervisedDatasetRow:
    condition_id: str

    target_horizon_seconds: int
    prediction_timestamp: datetime
    snapshot_observed_at: datetime
    actual_seconds_to_expiry: float
    horizon_gap_seconds: float

    snapshot_id: str

    reference_price: float
    strike: float

    distance_from_strike: float
    absolute_distance_from_strike: float
    relative_distance_from_strike: float

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

    momentum_60s: float | None
    volatility_60s: float | None

    reference_return_30s: float | None
    reference_return_60s: float | None
    reference_return_120s: float | None

    reference_abs_return_30s: float | None
    reference_abs_return_60s: float | None
    reference_abs_return_120s: float | None

    realized_volatility_60s: float | None
    realized_volatility_120s: float | None

    label_yes: int
    label_version: str

    eligible_reference_features: bool
    eligible_book_features: bool
    row_status: str

    dataset_version: str
    feature_version: str


@dataclass(frozen=True, slots=True)
class LabelValue:
    condition_id: str
    label_yes: int
    label_version: str


def load_valid_labels(
    path: Path,
) -> dict[str, LabelValue]:
    labels: dict[str, LabelValue] = {}

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        for row_number, row in enumerate(
            rows,
            start=2,
        ):
            condition_id = row["condition_id"].strip().lower()

            if not condition_id:
                raise RuntimeError(f"missing condition_id at label row {row_number}")

            validation_status = row["validation_status"].strip()

            if validation_status != "VALID":
                continue

            raw_label = row["label_yes"].strip()

            if raw_label not in {"0", "1"}:
                raise RuntimeError(
                    f"invalid label_yes at row {row_number}: {raw_label!r}"
                )

            label_version = row["label_version"].strip()

            if label_version != EXPECTED_LABEL_VERSION:
                raise RuntimeError(
                    f"unexpected label_version for {condition_id}: {label_version!r}"
                )

            if condition_id in labels:
                raise RuntimeError(f"duplicate valid label for {condition_id}")

            labels[condition_id] = LabelValue(
                condition_id=condition_id,
                label_yes=int(raw_label),
                label_version=label_version,
            )

    return labels


def _prediction_timestamp(
    snapshot: SnapshotRecord,
    target_horizon_seconds: int,
) -> datetime:
    if snapshot.market_end_at is None:
        raise RuntimeError(f"market_end_at missing for {snapshot.snapshot_id}")

    return snapshot.market_end_at - timedelta(seconds=target_horizon_seconds)


def build_supervised_rows(
    selections: list[HorizonSelection],
    labels: dict[str, LabelValue],
    snapshots: list[SnapshotRecord],
) -> list[SupervisedDatasetRow]:

    rows: list[SupervisedDatasetRow] = []

    seen_keys: set[tuple[str, int]] = set()

    for selection in selections:
        if selection.status != "SELECTED":
            continue

        snapshot = selection.snapshot

        if snapshot is None:
            raise RuntimeError("SELECTED horizon has no snapshot")

        condition_id = selection.condition_id.strip().lower()

        key = (
            condition_id,
            selection.target_seconds_to_expiry,
        )

        if key in seen_keys:
            raise RuntimeError(f"duplicate dataset key: {key}")

        seen_keys.add(key)

        label = labels.get(condition_id)

        if label is None:
            raise RuntimeError(f"missing valid label for {condition_id}")

        if snapshot.reference_price is None:
            raise RuntimeError(f"reference_price missing for {snapshot.snapshot_id}")

        if snapshot.strike is None:
            raise RuntimeError(f"strike missing for {snapshot.snapshot_id}")

        if selection.actual_seconds_to_expiry is None:
            raise RuntimeError("selected horizon missing actual expiry")

        if selection.horizon_gap_seconds is None:
            raise RuntimeError("selected horizon missing horizon gap")

        prediction_timestamp = _prediction_timestamp(
            snapshot,
            selection.target_seconds_to_expiry,
        )

        if snapshot.observed_at > prediction_timestamp:
            raise RuntimeError(
                "future leakage: snapshot observed after "
                f"prediction timestamp: "
                f"{snapshot.snapshot_id}"
            )

        for name, source_timestamp in (
            (
                "reference_timestamp",
                snapshot.reference_timestamp,
            ),
            (
                "yes_book_timestamp",
                snapshot.yes_book_timestamp,
            ),
            (
                "no_book_timestamp",
                snapshot.no_book_timestamp,
            ),
        ):
            if source_timestamp is not None and source_timestamp > prediction_timestamp:
                raise RuntimeError(
                    f"future leakage: {name} after "
                    f"prediction timestamp for "
                    f"{snapshot.snapshot_id}"
                )

        features = build_snapshot_features(snapshot)

        history_features = build_history_features(
            snapshots,
            snapshot,
        )

        if (
            features.distance_from_strike is None
            or features.absolute_distance_from_strike is None
            or features.relative_distance_from_strike is None
        ):
            raise RuntimeError(f"reference features missing for {snapshot.snapshot_id}")

        eligible_reference = True

        book_values = (
            features.yes_mid,
            features.no_mid,
            features.yes_spread,
            features.no_spread,
            features.yes_top_depth,
            features.no_top_depth,
            features.yes_book_imbalance,
            features.no_book_imbalance,
            features.normalized_yes_mid,
        )

        eligible_book = all(value is not None for value in book_values)

        row_status = "COMPLETE" if eligible_book else "MISSING_BOOK"

        rows.append(
            SupervisedDatasetRow(
                condition_id=condition_id,
                target_horizon_seconds=(selection.target_seconds_to_expiry),
                prediction_timestamp=prediction_timestamp,
                snapshot_observed_at=(snapshot.observed_at),
                actual_seconds_to_expiry=(selection.actual_seconds_to_expiry),
                horizon_gap_seconds=(selection.horizon_gap_seconds),
                snapshot_id=snapshot.snapshot_id,
                reference_price=(snapshot.reference_price),
                strike=snapshot.strike,
                distance_from_strike=(features.distance_from_strike),
                absolute_distance_from_strike=(features.absolute_distance_from_strike),
                relative_distance_from_strike=(features.relative_distance_from_strike),
                yes_mid=features.yes_mid,
                no_mid=features.no_mid,
                yes_spread=features.yes_spread,
                no_spread=features.no_spread,
                yes_top_depth=(features.yes_top_depth),
                no_top_depth=(features.no_top_depth),
                yes_book_imbalance=(features.yes_book_imbalance),
                no_book_imbalance=(features.no_book_imbalance),
                normalized_yes_mid=(features.normalized_yes_mid),
                reference_age_ms=(features.reference_age_ms),
                yes_book_age_ms=(features.yes_book_age_ms),
                no_book_age_ms=(features.no_book_age_ms),
                yes_book_latency_ms=(features.yes_book_latency_ms),
                no_book_latency_ms=(features.no_book_latency_ms),
                snapshot_build_latency_ms=(features.snapshot_build_latency_ms),
                momentum_60s=(snapshot.momentum_60s),
                volatility_60s=(snapshot.volatility_60s),
                reference_return_30s=(history_features.reference_return_30s),
                reference_return_60s=(history_features.reference_return_60s),
                reference_return_120s=(history_features.reference_return_120s),
                reference_abs_return_30s=(history_features.reference_abs_return_30s),
                reference_abs_return_60s=(history_features.reference_abs_return_60s),
                reference_abs_return_120s=(history_features.reference_abs_return_120s),
                realized_volatility_60s=(history_features.realized_volatility_60s),
                realized_volatility_120s=(history_features.realized_volatility_120s),
                label_yes=label.label_yes,
                label_version=label.label_version,
                eligible_reference_features=(eligible_reference),
                eligible_book_features=(eligible_book),
                row_status=row_status,
                dataset_version=DATASET_VERSION,
                feature_version=FEATURE_VERSION,
            )
        )

    return rows
