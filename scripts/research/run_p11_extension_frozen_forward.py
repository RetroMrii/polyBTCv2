from __future__ import annotations

import csv
import json
import math
import sys

from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(
        0,
        str(SRC),
    )


from polybtc.modeling.baselines import (
    fit_logistic_baseline,
    predict_logistic_probabilities,
)


P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

P5_REPORT_FILE = ROOT / "data" / "normalized" / "p5_baseline_report.json"

P6_PREDICTIONS_FILE = ROOT / "data" / "normalized" / "p6_calibration_predictions.csv"

PARTITIONS_FILE = ROOT / "data" / "normalized" / "p11_extension_market_partitions.csv"

OUTPUT_PREDICTIONS = (
    ROOT / "data" / "normalized" / "p11_extension_frozen_predictions.csv"
)

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_extension_frozen_report.json"

REPORT_VERSION = "p11_extension_frozen_v1"

FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

REPRODUCTION_TOLERANCE = 1e-12


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def complete_feature_row(
    row: dict[str, str],
) -> bool:
    return all(row[feature].strip() for feature in FEATURES)


def feature_vector(
    row: dict[str, str],
) -> list[float]:
    return [float(row[feature]) for feature in FEATURES]


def prediction_key(
    row: dict[str, str],
) -> tuple[str, int, str]:
    return (
        row["condition_id"].strip().lower(),
        int(row["target_horizon_seconds"]),
        row["prediction_timestamp"].strip(),
    )


def accuracy(
    labels: list[int],
    probabilities: list[float],
) -> float:
    correct = sum(
        int(probability >= 0.5) == label
        for label, probability in zip(
            labels,
            probabilities,
        )
    )

    return correct / len(labels)


def brier_score(
    labels: list[int],
    probabilities: list[float],
) -> float:
    return sum(
        (probability - label) ** 2
        for label, probability in zip(
            labels,
            probabilities,
        )
    ) / len(labels)


def log_loss(
    labels: list[int],
    probabilities: list[float],
) -> float:
    epsilon = 1e-15

    total = 0.0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        probability = min(
            max(
                probability,
                epsilon,
            ),
            1.0 - epsilon,
        )

        total -= label * math.log(probability) + (1 - label) * math.log(
            1.0 - probability
        )

    return total / len(labels)


def evaluate(
    labels: list[int],
    probabilities: list[float],
) -> dict:
    if not labels:
        return {
            "rows": 0,
            "accuracy": None,
            "brier_score": None,
            "log_loss": None,
        }

    return {
        "rows": len(labels),
        "accuracy": accuracy(
            labels,
            probabilities,
        ),
        "brier_score": brier_score(
            labels,
            probabilities,
        ),
        "log_loss": log_loss(
            labels,
            probabilities,
        ),
    }


def main() -> None:
    p4_rows = load_csv(P4_FILE)

    p5_report = json.loads(P5_REPORT_FILE.read_text(encoding="utf-8"))

    p6_rows = load_csv(P6_PREDICTIONS_FILE)

    partition_rows = load_csv(PARTITIONS_FILE)

    train_market_ids = {
        condition_id.strip().lower() for condition_id in p5_report["train_markets"]
    }

    strict_forward_ids = {
        row["condition_id"].strip().lower()
        for row in partition_rows
        if (row["partition"] == "P11_EXTENSION")
    }

    if train_market_ids & strict_forward_ids:
        raise RuntimeError("training markets overlap strict-forward markets")

    train_rows = [
        row
        for row in p4_rows
        if (
            row["condition_id"].strip().lower() in train_market_ids
            and complete_feature_row(row)
        )
    ]

    if len(train_rows) != 2658:
        raise RuntimeError(
            "unexpected frozen training "
            "row count: "
            f"expected=2658 "
            f"actual={len(train_rows)}"
        )

    x_train = [feature_vector(row) for row in train_rows]

    y_train = [int(row["label_yes"]) for row in train_rows]

    model = fit_logistic_baseline(
        x_train,
        y_train,
        feature_names=FEATURES,
    )

    p4_index = {prediction_key(row): row for row in p4_rows}

    old_rows = []

    expected_probabilities = []

    for prediction in p6_rows:
        key = prediction_key(prediction)

        source = p4_index.get(key)

        if source is None:
            raise RuntimeError(f"P6 reproduction row missing from refreshed P4: {key}")

        if not complete_feature_row(source):
            raise RuntimeError(
                f"P6 reproduction row has missing frozen-model feature: {key}"
            )

        old_rows.append(source)

        expected_probabilities.append(float(prediction["raw_probability"]))

    reproduced_probabilities = predict_logistic_probabilities(
        model,
        [feature_vector(row) for row in old_rows],
    )

    reproduction_differences = [
        abs(actual - expected)
        for actual, expected in zip(
            reproduced_probabilities,
            expected_probabilities,
        )
    ]

    max_reproduction_difference = max(reproduction_differences)

    if max_reproduction_difference > REPRODUCTION_TOLERANCE:
        raise RuntimeError(
            "frozen model reproduction "
            "failed: "
            f"max_difference="
            f"{max_reproduction_difference}"
        )

    forward_rows = [
        row
        for row in p4_rows
        if (row["condition_id"].strip().lower() in strict_forward_ids)
    ]

    forward_complete = [row for row in forward_rows if complete_feature_row(row)]

    forward_missing = len(forward_rows) - len(forward_complete)

    forward_probabilities = predict_logistic_probabilities(
        model,
        [feature_vector(row) for row in forward_complete],
    )

    labels = [int(row["label_yes"]) for row in forward_complete]

    overall_model = evaluate(
        labels,
        forward_probabilities,
    )

    horizon_metrics = {}

    for horizon in (
        240,
        180,
        120,
        90,
        60,
        30,
    ):
        indices = [
            index
            for index, row in enumerate(forward_complete)
            if (int(row["target_horizon_seconds"]) == horizon)
        ]

        horizon_labels = [labels[index] for index in indices]

        horizon_probabilities = [forward_probabilities[index] for index in indices]

        horizon_metrics[str(horizon)] = evaluate(
            horizon_labels,
            horizon_probabilities,
        )

    common_indices = [
        index
        for index, row in enumerate(forward_complete)
        if (
            row["eligible_book_features"].strip() == "True"
            and row["normalized_yes_mid"].strip()
        )
    ]

    common_labels = [labels[index] for index in common_indices]

    common_model_probabilities = [
        forward_probabilities[index] for index in common_indices
    ]

    market_probabilities = [
        float(forward_complete[index]["normalized_yes_mid"]) for index in common_indices
    ]

    model_common = evaluate(
        common_labels,
        common_model_probabilities,
    )

    market_common = evaluate(
        common_labels,
        market_probabilities,
    )

    output_rows = []

    for row, probability in zip(
        forward_complete,
        forward_probabilities,
    ):
        output_rows.append(
            {
                "evaluation_version": (REPORT_VERSION),
                "condition_id": (row["condition_id"].strip().lower()),
                "target_horizon_seconds": int(row["target_horizon_seconds"]),
                "prediction_timestamp": (row["prediction_timestamp"].strip()),
                "snapshot_observed_at": (row["snapshot_observed_at"].strip()),
                "label_yes": int(row["label_yes"]),
                "raw_probability": (probability),
                "normalized_yes_mid": (row["normalized_yes_mid"].strip()),
                "eligible_book_features": (row["eligible_book_features"].strip()),
            }
        )

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(output_rows[0].keys()),
        )

        writer.writeheader()

        writer.writerows(output_rows)

    forward_market_count = len(
        {row["condition_id"].strip().lower() for row in forward_complete}
    )

    report = {
        "report_version": (REPORT_VERSION),
        "model": {
            "type": ("logistic_regression"),
            "features": list(FEATURES),
            "preprocessing": ("StandardScaler"),
            "solver": ("lbfgs"),
            "max_iter": 1000,
            "calibration": ("none"),
        },
        "training": {
            "markets": len(train_market_ids),
            "complete_rows": len(train_rows),
        },
        "reproduction_gate": {
            "rows_checked": len(old_rows),
            "tolerance": (REPRODUCTION_TOLERANCE),
            "maximum_probability_difference": (max_reproduction_difference),
            "passed": True,
        },
        "strict_forward": {
            "partition_markets": len(strict_forward_ids),
            "eligible_model_markets": (forward_market_count),
            "p4_rows": len(forward_rows),
            "complete_model_rows": len(forward_complete),
            "missing_model_feature_rows": (forward_missing),
        },
        "frozen_model_metrics": (overall_model),
        "by_horizon": (horizon_metrics),
        "common_book_subset": {
            "rows": len(common_indices),
            "frozen_model": (model_common),
            "market_probability": (market_common),
        },
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

    print("P11 frozen forward evaluation complete")

    print()

    print(
        "reproduction rows=",
        len(old_rows),
    )

    print(
        "max reproduction difference=",
        max_reproduction_difference,
    )

    print("reproduction passed=True")

    print()

    print(
        "strict forward markets=",
        len(strict_forward_ids),
    )

    print(
        "strict forward rows=",
        len(forward_rows),
    )

    print(
        "complete model rows=",
        len(forward_complete),
    )

    print(
        "missing model feature rows=",
        forward_missing,
    )

    print()

    print("FROZEN MODEL")

    print(overall_model)

    print()

    print("COMMON BOOK SUBSET")

    print(
        "model=",
        model_common,
    )

    print(
        "market=",
        market_common,
    )

    print()

    print("BY HORIZON")

    for horizon in (
        "240",
        "180",
        "120",
        "90",
        "60",
        "30",
    ):
        print(
            horizon,
            horizon_metrics[horizon],
        )

    print()

    print(f"Wrote {OUTPUT_PREDICTIONS}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
