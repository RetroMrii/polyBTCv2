from __future__ import annotations

import csv
import json
import math
import sys

from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.modeling.splits import (
    chronological_market_split,
)


DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p7_residual_audit.json"


AUDIT_FEATURES = (
    "relative_distance_from_strike",
    "reference_return_30s",
    "reference_return_60s",
    "reference_return_120s",
    "realized_volatility_60s",
    "realized_volatility_120s",
    "yes_spread",
    "no_spread",
    "yes_top_depth",
    "no_top_depth",
    "yes_book_imbalance",
    "no_book_imbalance",
    "reference_age_ms",
    "yes_book_age_ms",
    "no_book_age_ms",
)


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_rows() -> list[dict[str, str]]:
    with DATASET_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise RuntimeError("P4 dataset is empty")

    return rows


def market_probability(
    row: dict[str, str],
) -> float | None:
    value = row.get(
        "normalized_yes_mid",
        "",
    ).strip()

    if not value:
        return None

    return float(value)


def residual(
    row: dict[str, str],
) -> float | None:
    probability = market_probability(row)

    label = row.get(
        "label_yes",
        "",
    ).strip()

    if probability is None or not label:
        return None

    return int(label) - probability


def feature_value(
    row: dict[str, str],
    feature_name: str,
) -> float | None:
    value = row.get(
        feature_name,
        "",
    ).strip()

    if not value:
        return None

    result = float(value)

    if not math.isfinite(result):
        return None

    return result


def percentile(
    values: list[float],
    probability: float,
) -> float:
    if not values:
        raise ValueError("cannot calculate percentile from empty values")

    ordered = sorted(values)

    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * probability

    lower_index = math.floor(position)

    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return ordered[lower_index]

    fraction = position - lower_index

    return ordered[lower_index] * (1.0 - fraction) + ordered[upper_index] * fraction


def quintile_edges(
    rows: list[dict[str, str]],
    feature_name: str,
) -> list[float]:
    values = [
        value
        for row in rows
        if (
            value := feature_value(
                row,
                feature_name,
            )
        )
        is not None
    ]

    if not values:
        raise ValueError(f"no training values for {feature_name}")

    return [
        percentile(
            values,
            0.20,
        ),
        percentile(
            values,
            0.40,
        ),
        percentile(
            values,
            0.60,
        ),
        percentile(
            values,
            0.80,
        ),
    ]


def bucket_index(
    value: float,
    edges: list[float],
) -> int:
    for index, edge in enumerate(edges):
        if value <= edge:
            return index

    return len(edges)


def summarize_bucket(
    rows: list[dict[str, str]],
    feature_name: str,
) -> dict:
    feature_values: list[float] = []
    probabilities: list[float] = []
    labels: list[int] = []
    residuals: list[float] = []
    markets: set[str] = set()

    for row in rows:
        value = feature_value(
            row,
            feature_name,
        )

        probability = market_probability(row)

        market_residual = residual(row)

        if value is None or probability is None or market_residual is None:
            continue

        feature_values.append(value)

        probabilities.append(probability)

        labels.append(int(row["label_yes"]))

        residuals.append(market_residual)

        markets.add(row["condition_id"].strip().lower())

    if not residuals:
        return {
            "rows": 0,
            "markets": 0,
            "mean_feature_value": None,
            "mean_market_probability": None,
            "observed_yes_rate": None,
            "mean_residual": None,
        }

    return {
        "rows": len(residuals),
        "markets": len(markets),
        "mean_feature_value": (sum(feature_values) / len(feature_values)),
        "mean_market_probability": (sum(probabilities) / len(probabilities)),
        "observed_yes_rate": (sum(labels) / len(labels)),
        "mean_residual": (sum(residuals) / len(residuals)),
    }


def feature_bucket_report(
    rows: list[dict[str, str]],
    feature_name: str,
    edges: list[float],
) -> list[dict]:
    buckets: list[list[dict[str, str]]] = [[] for _ in range(len(edges) + 1)]

    for row in rows:
        value = feature_value(
            row,
            feature_name,
        )

        if value is None:
            continue

        index = bucket_index(
            value,
            edges,
        )

        buckets[index].append(row)

    result = []

    for index, bucket_rows in enumerate(buckets):
        if index == 0:
            lower_bound = None
        else:
            lower_bound = edges[index - 1]

        if index == len(edges):
            upper_bound = None
        else:
            upper_bound = edges[index]

        summary = summarize_bucket(
            bucket_rows,
            feature_name,
        )

        summary.update(
            {
                "bucket": index + 1,
                "lower_bound": (lower_bound),
                "upper_bound": (upper_bound),
            }
        )

        result.append(summary)

    return result


def horizon_report(
    rows: list[dict[str, str]],
) -> dict:
    result = {}

    horizons = sorted(
        {int(row["target_horizon_seconds"]) for row in rows},
        reverse=True,
    )

    for horizon in horizons:
        selected = [
            row
            for row in rows
            if int(row["target_horizon_seconds"]) == horizon
            and residual(row) is not None
        ]

        residual_values = [residual(row) for row in selected]

        probabilities = [market_probability(row) for row in selected]

        labels = [int(row["label_yes"]) for row in selected]

        markets = {row["condition_id"].strip().lower() for row in selected}

        if not selected:
            continue

        result[str(horizon)] = {
            "rows": len(selected),
            "markets": len(markets),
            "mean_market_probability": (sum(probabilities) / len(probabilities)),
            "observed_yes_rate": (sum(labels) / len(labels)),
            "mean_residual": (sum(residual_values) / len(residual_values)),
        }

    return result


def main() -> None:
    rows = load_rows()

    market_times: dict[
        str,
        datetime,
    ] = {}

    for row in rows:
        condition_id = row["condition_id"].strip().lower()

        timestamp = parse_dt(row["prediction_timestamp"])

        previous = market_times.get(condition_id)

        if previous is None or timestamp < previous:
            market_times[condition_id] = timestamp

    split = chronological_market_split(market_times)

    train_markets = set(split.train_markets)

    validation_markets = set(split.validation_markets)

    test_markets = set(split.test_markets)

    train_rows = [
        row for row in rows if (row["condition_id"].strip().lower() in train_markets)
    ]

    validation_rows = [
        row
        for row in rows
        if (row["condition_id"].strip().lower() in validation_markets)
    ]

    test_rows = [
        row for row in rows if (row["condition_id"].strip().lower() in test_markets)
    ]

    feature_reports = {}

    for feature_name in AUDIT_FEATURES:
        edges = quintile_edges(
            train_rows,
            feature_name,
        )

        feature_reports[feature_name] = {
            "training_quintile_edges": (edges),
            "validation": (
                feature_bucket_report(
                    validation_rows,
                    feature_name,
                    edges,
                )
            ),
            "test": (
                feature_bucket_report(
                    test_rows,
                    feature_name,
                    edges,
                )
            ),
        }

    report = {
        "definition": {
            "residual": ("label_yes - normalized_yes_mid"),
            "positive_residual": ("market underestimated YES"),
            "negative_residual": ("market overestimated YES"),
            "bucket_boundaries": ("training-period quintiles"),
        },
        "markets": {
            "train": len(train_markets),
            "validation": len(validation_markets),
            "test": len(test_markets),
        },
        "horizon_residuals": {
            "validation": (horizon_report(validation_rows)),
            "test": (horizon_report(test_rows)),
        },
        "features": feature_reports,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
