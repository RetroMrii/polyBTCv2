from __future__ import annotations

import csv
import json
import sys

from collections import Counter
from datetime import datetime
from pathlib import Path
from dataclasses import asdict
from polybtc.modeling.metrics import (
    evaluate_probabilities,
)
from polybtc.modeling.baselines import (
    fit_logistic_baseline,
    predict_logistic_probabilities,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.modeling.splits import (
    chronological_market_split,
)


DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p5_baseline_report.json"

REFERENCE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
)

REFERENCE_HISTORY_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
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
        raise RuntimeError("P4 supervised dataset is empty")

    return rows


def rows_for_split(
    rows: list[dict[str, str]],
    split_lookup: dict[str, str],
    split_name: str,
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if split_lookup[row["condition_id"].strip().lower()] == split_name
    ]


def labels_from_rows(
    rows: list[dict[str, str]],
) -> list[int]:
    return [int(row["label_yes"]) for row in rows]


def base_rate_probability(
    rows: list[dict[str, str]],
) -> float:
    labels = labels_from_rows(rows)

    if not labels:
        raise RuntimeError("cannot compute base rate from empty rows")

    return sum(labels) / len(labels)


def complete_feature_rows(
    rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> list[dict[str, str]]:
    return [row for row in rows if all(row[name].strip() for name in feature_names)]


def feature_matrix(
    rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> list[list[float]]:
    return [[float(row[name]) for name in feature_names] for row in rows]


def evaluate_logistic_model(
    train_rows: list[dict[str, str]],
    evaluation_rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> dict:
    train_complete = complete_feature_rows(
        train_rows,
        feature_names,
    )

    eval_complete = complete_feature_rows(
        evaluation_rows,
        feature_names,
    )

    model = fit_logistic_baseline(
        feature_matrix(
            train_complete,
            feature_names,
        ),
        labels_from_rows(train_complete),
        feature_names=feature_names,
    )

    probabilities = predict_logistic_probabilities(
        model,
        feature_matrix(
            eval_complete,
            feature_names,
        ),
    )

    metrics = evaluate_probabilities(
        labels_from_rows(eval_complete),
        probabilities,
    )

    return {
        "features": list(feature_names),
        "train_rows": len(train_complete),
        "evaluation_rows": len(eval_complete),
        "metrics": asdict(metrics),
    }


def book_eligible_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if (
            row["eligible_book_features"].strip() == "True"
            and row["normalized_yes_mid"].strip()
        )
    ]


def evaluate_constant_probability(
    rows: list[dict[str, str]],
    probability: float,
) -> dict:
    labels = labels_from_rows(rows)

    metrics = evaluate_probabilities(
        labels,
        [probability] * len(labels),
    )

    return asdict(metrics)


def evaluate_market_probability(
    rows: list[dict[str, str]],
) -> dict:
    eligible = [
        row
        for row in rows
        if (
            row["eligible_book_features"].strip() == "True"
            and row["normalized_yes_mid"].strip()
        )
    ]

    labels = labels_from_rows(eligible)

    probabilities = [float(row["normalized_yes_mid"]) for row in eligible]

    metrics = evaluate_probabilities(
        labels,
        probabilities,
    )

    return asdict(metrics)


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

    split_lookup = {}

    for condition_id in split.train_markets:
        split_lookup[condition_id] = "train"

    for condition_id in split.validation_markets:
        split_lookup[condition_id] = "validation"

    for condition_id in split.test_markets:
        split_lookup[condition_id] = "test"

    train_rows = rows_for_split(
        rows,
        split_lookup,
        "train",
    )

    validation_rows = rows_for_split(
        rows,
        split_lookup,
        "validation",
    )

    test_rows = rows_for_split(
        rows,
        split_lookup,
        "test",
    )

    train_base_rate = base_rate_probability(train_rows)

    probability_baselines = {}

    for name, split_rows in (
        (
            "validation",
            validation_rows,
        ),
        (
            "test",
            test_rows,
        ),
    ):
        book_rows = [
            row
            for row in split_rows
            if (
                row["eligible_book_features"].strip() == "True"
                and row["normalized_yes_mid"].strip()
            )
        ]

        probability_baselines[name] = {
            "all_rows": {
                "train_base_rate": (
                    evaluate_constant_probability(
                        split_rows,
                        train_base_rate,
                    )
                ),
            },
            "book_eligible_rows": {
                "train_base_rate": (
                    evaluate_constant_probability(
                        book_rows,
                        train_base_rate,
                    )
                ),
                "market_normalized_yes_mid": (evaluate_market_probability(split_rows)),
            },
        }

    learned_baselines = {}

    for name, split_rows in (
        (
            "validation",
            validation_rows,
        ),
        (
            "test",
            test_rows,
        ),
    ):
        learned_baselines[name] = {
            "reference_logistic": (
                evaluate_logistic_model(
                    train_rows,
                    split_rows,
                    REFERENCE_FEATURES,
                )
            ),
            "reference_history_30s_logistic": (
                evaluate_logistic_model(
                    train_rows,
                    split_rows,
                    REFERENCE_HISTORY_FEATURES,
                )
            ),
        }

    common_subset_comparison = {}

    for name, split_rows in (
        (
            "validation",
            validation_rows,
        ),
        (
            "test",
            test_rows,
        ),
    ):
        common_rows = book_eligible_rows(split_rows)

        common_subset_comparison[name] = {
            "rows": len(common_rows),
            "train_base_rate": (
                evaluate_constant_probability(
                    common_rows,
                    train_base_rate,
                )
            ),
            "market_normalized_yes_mid": (evaluate_market_probability(common_rows)),
            "reference_logistic": (
                evaluate_logistic_model(
                    train_rows,
                    common_rows,
                    REFERENCE_FEATURES,
                )
            ),
            "reference_history_30s_logistic": (
                evaluate_logistic_model(
                    train_rows,
                    common_rows,
                    REFERENCE_HISTORY_FEATURES,
                )
            ),
        }

    row_counts = Counter()
    market_counts = Counter()
    label_counts = {
        "train": Counter(),
        "validation": Counter(),
        "test": Counter(),
    }

    for condition_id, name in split_lookup.items():
        market_counts[name] += 1

    for row in rows:
        condition_id = row["condition_id"].strip().lower()

        name = split_lookup[condition_id]

        row_counts[name] += 1

        label_counts[name][row["label_yes"]] += 1

    train_max = max(market_times[m] for m in split.train_markets)

    validation_min = min(market_times[m] for m in split.validation_markets)

    validation_max = max(market_times[m] for m in split.validation_markets)

    test_min = min(market_times[m] for m in split.test_markets)

    if train_max > validation_min:
        raise RuntimeError("chronological split overlap: train after validation")

    if validation_max > test_min:
        raise RuntimeError("chronological split overlap: validation after test")

    report = {
        "dataset": str(DATASET_FILE.relative_to(ROOT)),
        "markets": len(market_times),
        "rows": len(rows),
        "split": {
            "train": {
                "markets": (market_counts["train"]),
                "rows": (row_counts["train"]),
                "labels": dict(label_counts["train"]),
            },
            "validation": {
                "markets": (market_counts["validation"]),
                "rows": (row_counts["validation"]),
                "labels": dict(label_counts["validation"]),
            },
            "test": {
                "markets": (market_counts["test"]),
                "rows": (row_counts["test"]),
                "labels": dict(label_counts["test"]),
            },
        },
        "train_markets": list(split.train_markets),
        "validation_markets": list(split.validation_markets),
        "test_markets": list(split.test_markets),
        "baseline_configuration": {
            "train_base_rate_probability": (train_base_rate),
        },
        "probability_baselines": (probability_baselines),
        "learned_baselines": learned_baselines,
        "common_subset_comparison": common_subset_comparison,
    }

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
