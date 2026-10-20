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
    / "p13_enriched_supervised.csv"
)

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_feature_ablation_report.json"
)

REPORT_VERSION = "p13_feature_ablation_v1"

FOLD_COUNT = 5


BASELINE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


MODEL_FEATURES = {
    "A_BASELINE": (BASELINE_FEATURES),
    "B1_PLUS_1M_RETURN": (BASELINE_FEATURES + ("btc_return_1m",)),
    "B2_PLUS_MOMENTUM_BLOCK": (
        BASELINE_FEATURES
        + (
            "btc_return_1m",
            "btc_return_3m",
            "btc_return_5m",
        )
    ),
    "B3_PLUS_VOLATILITY_BLOCK": (
        BASELINE_FEATURES
        + (
            "btc_realized_vol_5m",
            "btc_realized_vol_15m",
            "btc_range_5m",
        )
    ),
    "B4_PLUS_VOLUME": (BASELINE_FEATURES + ("btc_volume_zscore_30m",)),
    "B5_PLUS_ALL_CONTEXT": (
        BASELINE_FEATURES
        + (
            "btc_return_1m",
            "btc_return_3m",
            "btc_return_5m",
            "btc_realized_vol_5m",
            "btc_realized_vol_15m",
            "btc_range_5m",
            "btc_volume_zscore_30m",
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


def metrics(
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
    all_features = sorted(
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
                feature: optional_float(row.get(feature)) for feature in all_features
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

    markets = ordered_markets(rows)

    initial_train_markets, folds = split_forward_markets(markets)

    training_market_ids = set(initial_train_markets)

    model_fold_results = {model_name: [] for model_name in MODEL_FEATURES}

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
                raise RuntimeError("model comparison rows differ")

            model = build_model()

            model.fit(
                x_train,
                y_train,
            )

            probabilities = model.predict_proba(x_test)[:, 1]

            result = metrics(
                y_test,
                probabilities,
            )

            model_fold_results[model_name].append(
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

    baseline_result = None

    for model_name in MODEL_FEATURES:
        probabilities = np.array(
            overall_predictions[model_name],
            dtype=float,
        )

        result = metrics(
            y_all,
            probabilities,
        )

        if model_name == "A_BASELINE":
            baseline_result = result

        overall_results[model_name] = {
            **result,
            "folds": (model_fold_results[model_name]),
        }

    if baseline_result is None:
        raise RuntimeError("baseline result missing")

    for model_name in overall_results:
        result = overall_results[model_name]

        result["delta_vs_baseline"] = {
            "brier": (result["brier"] - baseline_result["brier"]),
            "log_loss": (result["log_loss"] - baseline_result["log_loss"]),
            "accuracy": (result["accuracy"] - baseline_result["accuracy"]),
        }

        fold_brier_wins = 0
        fold_log_loss_wins = 0
        fold_accuracy_wins = 0

        baseline_folds = model_fold_results["A_BASELINE"]

        candidate_folds = model_fold_results[model_name]

        for (
            baseline_fold,
            candidate_fold,
        ) in zip(
            baseline_folds,
            candidate_folds,
        ):
            if candidate_fold["brier"] < baseline_fold["brier"]:
                fold_brier_wins += 1

            if candidate_fold["log_loss"] < baseline_fold["log_loss"]:
                fold_log_loss_wins += 1

            if candidate_fold["accuracy"] > baseline_fold["accuracy"]:
                fold_accuracy_wins += 1

        result["fold_wins_vs_baseline"] = {
            "brier": (fold_brier_wins),
            "log_loss": (fold_log_loss_wins),
            "accuracy": (fold_accuracy_wins),
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

            horizon_results[model_name] = metrics(
                horizon_y,
                probabilities,
            )

        baseline_horizon = horizon_results["A_BASELINE"]

        for model_name in horizon_results:
            result = horizon_results[model_name]

            result["delta_vs_baseline"] = {
                "brier": (result["brier"] - baseline_horizon["brier"]),
                "log_loss": (result["log_loss"] - baseline_horizon["log_loss"]),
                "accuracy": (result["accuracy"] - baseline_horizon["accuracy"]),
            }

        by_horizon[str(horizon)] = horizon_results

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "dataset": ("p13_enriched_supervised.csv"),
            "initial_training_fraction": (0.50),
            "forward_folds": (FOLD_COUNT),
            "training_mode": ("expanding_window_by_market"),
            "comparison_rows": ("identical complete rows for every model"),
            "model_family": ("StandardScaler + LogisticRegression"),
            "hyperparameter_search": (False),
            "calibration": ("none"),
        },
        "input_rows": len(all_rows),
        "complete_rows": len(rows),
        "markets": len(markets),
        "initial_train_markets": len(initial_train_markets),
        "forward_test_markets": (len(markets) - len(initial_train_markets)),
        "models": (overall_results),
        "by_horizon": (by_horizon),
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

    print("P13 feature ablation complete")

    print()
    print(
        "complete_rows=",
        len(rows),
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
    print("BY HORIZON — BRIER")

    for horizon in HORIZONS:
        print()
        print(
            "horizon",
            horizon,
        )

        horizon_results = by_horizon[str(horizon)]

        for model_name in MODEL_FEATURES:
            result = horizon_results[model_name]

            print(
                " ",
                model_name,
                "brier=",
                result["brier"],
                "delta=",
                result["delta_vs_baseline"]["brier"],
            )

    print()
    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
