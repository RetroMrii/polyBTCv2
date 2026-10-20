from __future__ import annotations

import csv
import json
import math
import sys

from collections import defaultdict
from datetime import datetime
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

PARTITIONS_FILE = ROOT / "data" / "normalized" / "p11_market_partitions.csv"

OUTPUT_PREDICTIONS = ROOT / "data" / "normalized" / "p11_walk_forward_predictions.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_walk_forward_model_report.json"


REPORT_VERSION = "p11_walk_forward_model_v1"

FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.strip().replace(
            "Z",
            "+00:00",
        )
    )


def complete_feature_row(
    row: dict[str, str],
) -> bool:
    return all(row[feature].strip() for feature in FEATURES)


def feature_vector(
    row: dict[str, str],
) -> list[float]:
    return [float(row[feature]) for feature in FEATURES]


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

    epsilon = 1e-15

    accuracy = sum(
        int(probability >= 0.5) == label
        for label, probability in zip(
            labels,
            probabilities,
        )
    ) / len(labels)

    brier = sum(
        (probability - label) ** 2
        for label, probability in zip(
            labels,
            probabilities,
        )
    ) / len(labels)

    loss = 0.0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        p = min(
            max(
                probability,
                epsilon,
            ),
            1.0 - epsilon,
        )

        loss -= label * math.log(p) + (1 - label) * math.log(1.0 - p)

    loss /= len(labels)

    return {
        "rows": len(labels),
        "accuracy": accuracy,
        "brier_score": brier,
        "log_loss": loss,
    }


def market_day(
    row: dict[str, str],
) -> str:
    return parse_dt(row["prediction_timestamp"]).date().isoformat()


def main() -> None:
    p4_rows = load_csv(P4_FILE)

    partition_rows = load_csv(PARTITIONS_FILE)

    partition_lookup = {
        row["condition_id"].strip().lower(): row["partition"].strip()
        for row in partition_rows
    }

    frozen_market_ids = {
        condition_id
        for (
            condition_id,
            partition,
        ) in partition_lookup.items()
        if (partition == "FROZEN_RESEARCH")
    }

    forward_market_ids = {
        condition_id
        for (
            condition_id,
            partition,
        ) in partition_lookup.items()
        if (partition == "STRICT_FORWARD")
    }

    if frozen_market_ids & forward_market_ids:
        raise RuntimeError("frozen and forward market partitions overlap")

    rows_by_market = defaultdict(list)

    for row in p4_rows:
        condition_id = row["condition_id"].strip().lower()

        rows_by_market[condition_id].append(row)

    forward_market_days = {}

    for condition_id in forward_market_ids:
        rows = rows_by_market.get(
            condition_id,
            [],
        )

        if not rows:
            raise RuntimeError(f"forward market missing from P4: {condition_id}")

        days = {market_day(row) for row in rows}

        if len(days) != 1:
            raise RuntimeError(
                f"market spans multiple UTC days: {condition_id} {sorted(days)}"
            )

        forward_market_days[condition_id] = next(iter(days))

    test_days = sorted(set(forward_market_days.values()))

    predictions = []

    folds = {}

    all_labels = []

    all_probabilities = []

    for fold_number, test_day in enumerate(
        test_days,
        start=1,
    ):
        prior_forward_markets = {
            condition_id
            for (
                condition_id,
                day,
            ) in (forward_market_days.items())
            if day < test_day
        }

        train_market_ids = frozen_market_ids | prior_forward_markets

        test_market_ids = {
            condition_id
            for (
                condition_id,
                day,
            ) in (forward_market_days.items())
            if day == test_day
        }

        overlap = train_market_ids & test_market_ids

        if overlap:
            raise RuntimeError("walk-forward train/test market overlap")

        train_rows = [
            row
            for row in p4_rows
            if (
                row["condition_id"].strip().lower() in train_market_ids
                and complete_feature_row(row)
            )
        ]

        test_rows = [
            row
            for row in p4_rows
            if (
                row["condition_id"].strip().lower() in test_market_ids
                and complete_feature_row(row)
            )
        ]

        if not train_rows:
            raise RuntimeError(f"empty training fold: {test_day}")

        if not test_rows:
            raise RuntimeError(f"empty test fold: {test_day}")

        x_train = [feature_vector(row) for row in train_rows]

        y_train = [int(row["label_yes"]) for row in train_rows]

        model = fit_logistic_baseline(
            x_train,
            y_train,
            feature_names=FEATURES,
        )

        probabilities = predict_logistic_probabilities(
            model,
            [feature_vector(row) for row in test_rows],
        )

        labels = [int(row["label_yes"]) for row in test_rows]

        metrics = evaluate(
            labels,
            probabilities,
        )

        common_indices = [
            index
            for index, row in enumerate(test_rows)
            if (
                row["eligible_book_features"].strip() == "True"
                and row["normalized_yes_mid"].strip()
            )
        ]

        common_labels = [labels[index] for index in common_indices]

        common_model_probs = [probabilities[index] for index in common_indices]

        market_probs = [
            float(test_rows[index]["normalized_yes_mid"]) for index in common_indices
        ]

        common_model_metrics = evaluate(
            common_labels,
            common_model_probs,
        )

        market_metrics = evaluate(
            common_labels,
            market_probs,
        )

        pipeline = model.pipeline

        scaler = pipeline.named_steps["scale"]

        estimator = pipeline.named_steps["model"]

        folds[test_day] = {
            "fold_number": (fold_number),
            "train_markets": len(train_market_ids),
            "train_rows": len(train_rows),
            "test_markets": len(test_market_ids),
            "test_rows": len(test_rows),
            "metrics": metrics,
            "common_book_subset": {
                "model": (common_model_metrics),
                "market": (market_metrics),
            },
            "model_state": {
                "scaler_mean": [float(value) for value in scaler.mean_],
                "scaler_scale": [float(value) for value in scaler.scale_],
                "coefficients_scaled": [float(value) for value in estimator.coef_[0]],
                "intercept_scaled": (float(estimator.intercept_[0])),
            },
        }

        for row, probability in zip(
            test_rows,
            probabilities,
        ):
            predictions.append(
                {
                    "evaluation_version": (REPORT_VERSION),
                    "fold_number": (fold_number),
                    "test_day": (test_day),
                    "condition_id": (row["condition_id"].strip().lower()),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "prediction_timestamp": (row["prediction_timestamp"].strip()),
                    "snapshot_observed_at": (row["snapshot_observed_at"].strip()),
                    "label_yes": int(row["label_yes"]),
                    "walk_forward_probability": (probability),
                    "normalized_yes_mid": (row["normalized_yes_mid"].strip()),
                    "eligible_book_features": (row["eligible_book_features"].strip()),
                }
            )

        all_labels.extend(labels)

        all_probabilities.extend(probabilities)

    overall = evaluate(
        all_labels,
        all_probabilities,
    )

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(predictions[0].keys()),
        )

        writer.writeheader()

        writer.writerows(predictions)

    report = {
        "report_version": (REPORT_VERSION),
        "evaluation_type": ("expanding_window_walk_forward"),
        "model": {
            "features": list(FEATURES),
            "preprocessing": ("StandardScaler"),
            "estimator": ("LogisticRegression"),
            "solver": ("lbfgs"),
            "max_iter": 1000,
            "calibration": ("none"),
        },
        "rules": {
            "initial_training_partition": ("all FROZEN_RESEARCH markets"),
            "future_fold_training": (
                "all frozen markets plus strict-forward markets from earlier UTC days"
            ),
            "same_day_training": False,
            "market_overlap_allowed": False,
            "hyperparameter_changes": False,
        },
        "overall": (overall),
        "folds": (folds),
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

    print("P11 walk-forward model evaluation complete")

    print()

    print(
        "folds=",
        len(test_days),
    )

    print(
        "prediction rows=",
        len(predictions),
    )

    print()

    for day in test_days:
        fold = folds[day]

        print(
            day,
            "train_markets=",
            fold["train_markets"],
            "test_markets=",
            fold["test_markets"],
            "Brier=",
            round(
                fold["metrics"]["brier_score"],
                6,
            ),
            "logloss=",
            round(
                fold["metrics"]["log_loss"],
                6,
            ),
            "accuracy=",
            round(
                fold["metrics"]["accuracy"],
                6,
            ),
        )

        print(
            "  common model Brier=",
            round(
                fold["common_book_subset"]["model"]["brier_score"],
                6,
            ),
            "market Brier=",
            round(
                fold["common_book_subset"]["market"]["brier_score"],
                6,
            ),
        )

    print()

    print(
        "OVERALL",
        overall,
    )

    print()

    print(f"Wrote {OUTPUT_PREDICTIONS}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
