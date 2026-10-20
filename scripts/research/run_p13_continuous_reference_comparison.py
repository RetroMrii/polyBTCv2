from __future__ import annotations

import csv
import json

from datetime import datetime
from pathlib import Path

import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_continuous_reference_supervised.csv"
)

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_continuous_reference_comparison_report.json"
)

REPORT_VERSION = "p13_continuous_reference_comparison_v1"

FOLD_COUNT = 5


BASELINE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


MODEL_FEATURES = {
    "A_BASELINE": (BASELINE_FEATURES),
    "B_EXTERNAL_1M": (BASELINE_FEATURES + ("btc_return_1m",)),
    "C_CONTINUOUS_LIVE_60S": (BASELINE_FEATURES + ("continuous_reference_return_60s",)),
    "D_BOTH": (
        BASELINE_FEATURES
        + (
            "btc_return_1m",
            "continuous_reference_return_60s",
        )
    ),
}


HORIZONS = (
    240,
    180,
    120,
    90,
    60,
    30,
)


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def build_model() -> Pipeline:
    return Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "logistic",
                LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def calculate_metrics(
    y: np.ndarray,
    probabilities: np.ndarray,
) -> dict:
    predicted = (probabilities >= 0.5).astype(int)

    return {
        "rows": int(len(y)),
        "accuracy": float(
            accuracy_score(
                y,
                predicted,
            )
        ),
        "brier": float(
            brier_score_loss(
                y,
                probabilities,
            )
        ),
        "log_loss": float(
            log_loss(
                y,
                probabilities,
                labels=[
                    0,
                    1,
                ],
            )
        ),
    }


def build_matrix(
    rows: list[dict],
    features: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    x = np.array(
        [[float(row[feature]) for feature in features] for row in rows],
        dtype=float,
    )

    y = np.array(
        [int(row["label_yes"]) for row in rows],
        dtype=int,
    )

    return (
        x,
        y,
    )


def load_rows() -> list[dict]:
    required_features = sorted(
        {feature for features in MODEL_FEATURES.values() for feature in features}
    )

    rows = []

    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            label_raw = row["label_yes"].strip()

            if label_raw not in {
                "0",
                "1",
            }:
                raise RuntimeError(f"invalid label at row {row_number}")

            values = {
                feature: optional_float(row.get(feature))
                for feature in required_features
            }

            complete = all(value is not None for value in values.values())

            rows.append(
                {
                    "condition_id": (row["condition_id"].strip().lower()),
                    "prediction_timestamp": (
                        parse_timestamp(row["prediction_timestamp"])
                    ),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "label_yes": int(label_raw),
                    "complete": (complete),
                    **values,
                }
            )

    return rows


def ordered_markets(
    rows: list[dict],
) -> list[str]:
    first_timestamp = {}

    for row in rows:
        condition_id = row["condition_id"]

        timestamp = row["prediction_timestamp"]

        existing = first_timestamp.get(condition_id)

        if existing is None or timestamp < existing:
            first_timestamp[condition_id] = timestamp

    return sorted(
        first_timestamp,
        key=lambda condition_id: (
            first_timestamp[condition_id],
            condition_id,
        ),
    )


def split_forward_markets(
    markets: list[str],
) -> tuple[
    list[str],
    list[list[str]],
]:
    initial_train_count = len(markets) // 2

    initial_train = markets[:initial_train_count]

    remaining = markets[initial_train_count:]

    base_size = len(remaining) // FOLD_COUNT

    remainder = len(remaining) % FOLD_COUNT

    folds = []

    cursor = 0

    for fold_index in range(FOLD_COUNT):
        size = base_size + (1 if fold_index < remainder else 0)

        folds.append(remaining[cursor : cursor + size])

        cursor += size

    return (
        initial_train,
        folds,
    )


def rows_for_markets(
    rows: list[dict],
    market_ids: set[str],
) -> list[dict]:
    return [row for row in rows if row["condition_id"] in market_ids]


def main() -> None:
    all_rows = load_rows()

    rows = [row for row in all_rows if row["complete"]]

    excluded_missing = len(all_rows) - len(rows)

    markets = ordered_markets(rows)

    (
        initial_train_markets,
        folds,
    ) = split_forward_markets(markets)

    training_market_ids = set(initial_train_markets)

    fold_results = {model_name: [] for model_name in MODEL_FEATURES}

    overall_predictions = {model_name: [] for model_name in MODEL_FEATURES}

    overall_labels = []

    overall_rows = []

    for fold_index, fold_markets in enumerate(
        folds,
        start=1,
    ):
        test_market_ids = set(fold_markets)

        if training_market_ids & test_market_ids:
            raise RuntimeError(f"market overlap in fold {fold_index}")

        train_rows = rows_for_markets(
            rows,
            training_market_ids,
        )

        test_rows = rows_for_markets(
            rows,
            test_market_ids,
        )

        y_test_reference = None

        for (
            model_name,
            features,
        ) in MODEL_FEATURES.items():
            x_train, y_train = build_matrix(
                train_rows,
                features,
            )

            x_test, y_test = build_matrix(
                test_rows,
                features,
            )

            if y_test_reference is None:
                y_test_reference = y_test

            elif not np.array_equal(
                y_test_reference,
                y_test,
            ):
                raise RuntimeError("comparison rows differ")

            model = build_model()

            model.fit(
                x_train,
                y_train,
            )

            probabilities = model.predict_proba(x_test)[:, 1]

            result = calculate_metrics(
                y_test,
                probabilities,
            )

            fold_results[model_name].append(
                {
                    "fold": (fold_index),
                    "train_markets": len(training_market_ids),
                    "test_markets": len(test_market_ids),
                    **result,
                }
            )

            overall_predictions[model_name].extend(probabilities.tolist())

        overall_labels.extend(y_test_reference.tolist())

        overall_rows.extend(test_rows)

        training_market_ids.update(test_market_ids)

    y_all = np.array(
        overall_labels,
        dtype=int,
    )

    overall_results = {}

    for model_name in MODEL_FEATURES:
        probabilities = np.array(
            overall_predictions[model_name],
            dtype=float,
        )

        overall_results[model_name] = calculate_metrics(
            y_all,
            probabilities,
        )

    baseline = overall_results["A_BASELINE"]

    external = overall_results["B_EXTERNAL_1M"]

    continuous = overall_results["C_CONTINUOUS_LIVE_60S"]

    both = overall_results["D_BOTH"]

    for model_name, result in overall_results.items():
        result["delta_vs_baseline"] = {
            "brier": (result["brier"] - baseline["brier"]),
            "log_loss": (result["log_loss"] - baseline["log_loss"]),
            "accuracy": (result["accuracy"] - baseline["accuracy"]),
        }

        brier_wins = 0
        log_loss_wins = 0
        accuracy_wins = 0

        for (
            baseline_fold,
            candidate_fold,
        ) in zip(
            fold_results["A_BASELINE"],
            fold_results[model_name],
        ):
            if candidate_fold["brier"] < baseline_fold["brier"]:
                brier_wins += 1

            if candidate_fold["log_loss"] < baseline_fold["log_loss"]:
                log_loss_wins += 1

            if candidate_fold["accuracy"] > baseline_fold["accuracy"]:
                accuracy_wins += 1

        result["fold_wins_vs_baseline"] = {
            "brier": (brier_wins),
            "log_loss": (log_loss_wins),
            "accuracy": (accuracy_wins),
            "folds": (FOLD_COUNT),
        }

    by_horizon = {}

    for horizon in HORIZONS:
        indices = [
            index
            for index, row in enumerate(overall_rows)
            if (row["target_horizon_seconds"] == horizon)
        ]

        if not indices:
            continue

        horizon_y = np.array(
            [overall_rows[index]["label_yes"] for index in indices],
            dtype=int,
        )

        horizon_results = {}

        for model_name in MODEL_FEATURES:
            probabilities = np.array(
                [overall_predictions[model_name][index] for index in indices],
                dtype=float,
            )

            result = calculate_metrics(
                horizon_y,
                probabilities,
            )

            horizon_results[model_name] = result

        baseline_horizon = horizon_results["A_BASELINE"]

        for model_name, result in horizon_results.items():
            result["delta_vs_baseline"] = {
                "brier": (result["brier"] - baseline_horizon["brier"]),
                "log_loss": (result["log_loss"] - baseline_horizon["log_loss"]),
                "accuracy": (result["accuracy"] - baseline_horizon["accuracy"]),
            }

        by_horizon[str(horizon)] = horizon_results

    external_values = np.array(
        [row["btc_return_1m"] for row in rows],
        dtype=float,
    )

    continuous_values = np.array(
        [row["continuous_reference_return_60s"] for row in rows],
        dtype=float,
    )

    difference = external_values - continuous_values

    signal_comparison = {
        "rows": int(len(rows)),
        "pearson_correlation": float(
            np.corrcoef(
                external_values,
                continuous_values,
            )[0, 1]
        ),
        "mean_difference_external_minus_continuous": float(np.mean(difference)),
        "mean_absolute_difference": float(np.mean(np.abs(difference))),
        "root_mean_squared_difference": float(np.sqrt(np.mean(difference**2))),
    }

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "dataset": ("p13_continuous_reference_supervised.csv"),
            "forward_folds": (FOLD_COUNT),
            "initial_training_fraction": (0.50),
            "training_mode": ("expanding_window_by_market"),
            "comparison_rows": ("identical complete rows"),
            "model_family": ("StandardScaler + LogisticRegression"),
            "hyperparameter_search": (False),
            "calibration": ("none"),
        },
        "input_rows": len(all_rows),
        "complete_rows": len(rows),
        "excluded_missing": (excluded_missing),
        "markets": len(markets),
        "models": (overall_results),
        "folds": (fold_results),
        "by_horizon": (by_horizon),
        "signal_comparison": (signal_comparison),
        "direct_model_comparisons": {
            "continuous_minus_external": {
                "brier": (continuous["brier"] - external["brier"]),
                "log_loss": (continuous["log_loss"] - external["log_loss"]),
                "accuracy": (continuous["accuracy"] - external["accuracy"]),
            },
            "both_minus_external": {
                "brier": (both["brier"] - external["brier"]),
                "log_loss": (both["log_loss"] - external["log_loss"]),
                "accuracy": (both["accuracy"] - external["accuracy"]),
            },
            "both_minus_continuous": {
                "brier": (both["brier"] - continuous["brier"]),
                "log_loss": (both["log_loss"] - continuous["log_loss"]),
                "accuracy": (both["accuracy"] - continuous["accuracy"]),
            },
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

    print("P13 continuous-reference comparison complete")

    print()
    print(
        "input_rows=",
        len(all_rows),
    )

    print(
        "complete_rows=",
        len(rows),
    )

    print(
        "excluded_missing=",
        excluded_missing,
    )

    print(
        "markets=",
        len(markets),
    )

    print()
    print("OVERALL OOS")

    for model_name in MODEL_FEATURES:
        result = overall_results[model_name]

        print()
        print(model_name)

        print(
            " accuracy=",
            result["accuracy"],
        )

        print(
            " brier=",
            result["brier"],
        )

        print(
            " log_loss=",
            result["log_loss"],
        )

        print(
            " delta_vs_baseline=",
            result["delta_vs_baseline"],
        )

        print(
            " fold_wins=",
            result["fold_wins_vs_baseline"],
        )

    print()
    print("DIRECT MODEL COMPARISONS")

    for (
        name,
        values,
    ) in report["direct_model_comparisons"].items():
        print(
            name,
            values,
        )

    print()
    print("SIGNAL COMPARISON")

    print(signal_comparison)

    print()
    print("BY HORIZON — BRIER")

    for horizon in HORIZONS:
        horizon_key = str(horizon)

        print()
        print(
            "horizon",
            horizon,
        )

        if horizon_key not in by_horizon:
            print(" no complete rows")
            continue

        for model_name in MODEL_FEATURES:
            result = by_horizon[horizon_key][model_name]

            print(
                " ",
                model_name,
                "rows=",
                result["rows"],
                "brier=",
                result["brier"],
                "delta=",
                result["delta_vs_baseline"]["brier"],
            )

    print()
    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
