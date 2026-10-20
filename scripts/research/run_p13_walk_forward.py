from __future__ import annotations

import csv
import json

from collections import defaultdict
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
    / "p13_walk_forward_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_walk_forward_predictions.csv"
)


REPORT_VERSION = "p13_walk_forward_v1"

FOLD_COUNT = 5


BASELINE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


BTC_CONTEXT_FEATURES = (
    "btc_return_1m",
    "btc_return_3m",
    "btc_return_5m",
    "btc_realized_vol_5m",
    "btc_realized_vol_15m",
    "btc_range_5m",
    "btc_volume_zscore_30m",
)


MODEL_A_FEATURES = BASELINE_FEATURES

MODEL_B_FEATURES = BASELINE_FEATURES + BTC_CONTEXT_FEATURES


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
        "positive_rate": float(np.mean(y)),
        "mean_probability": float(np.mean(probabilities)),
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
    rows = []

    all_features = BASELINE_FEATURES + BTC_CONTEXT_FEATURES

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
            condition_id = row["condition_id"].strip().lower()

            label_raw = row["label_yes"].strip()

            if label_raw not in {
                "0",
                "1",
            }:
                raise RuntimeError(f"invalid label at row {row_number}: {label_raw!r}")

            values = {
                feature: optional_float(row.get(feature)) for feature in all_features
            }

            common_complete = all(
                values[feature] is not None for feature in all_features
            )

            rows.append(
                {
                    "condition_id": (condition_id),
                    "prediction_timestamp": (
                        parse_timestamp(row["prediction_timestamp"])
                    ),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "label_yes": int(label_raw),
                    "normalized_yes_mid": (
                        optional_float(row.get("normalized_yes_mid"))
                    ),
                    "common_complete": (common_complete),
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
    market_count = len(markets)

    initial_train_count = market_count // 2

    initial_train = markets[:initial_train_count]

    remaining = markets[initial_train_count:]

    fold_sizes = [len(remaining) // FOLD_COUNT for _ in range(FOLD_COUNT)]

    remainder = len(remaining) % FOLD_COUNT

    for index in range(remainder):
        fold_sizes[index] += 1

    folds = []

    cursor = 0

    for size in fold_sizes:
        folds.append(remaining[cursor : cursor + size])

        cursor += size

    if cursor != len(remaining):
        raise RuntimeError("walk-forward fold allocation mismatch")

    return (
        initial_train,
        folds,
    )


def rows_for_markets(
    rows: list[dict],
    market_ids: set[str],
) -> list[dict]:
    return [row for row in rows if row["condition_id"] in market_ids]


def by_horizon_metrics(
    rows: list[dict],
    probabilities: np.ndarray,
) -> dict:
    result = {}

    for horizon in HORIZONS:
        indices = [
            index
            for index, row in enumerate(rows)
            if (row["target_horizon_seconds"] == horizon)
        ]

        if not indices:
            continue

        y = np.array(
            [rows[index]["label_yes"] for index in indices],
            dtype=int,
        )

        p = np.array(
            [probabilities[index] for index in indices],
            dtype=float,
        )

        result[str(horizon)] = calculate_metrics(
            y,
            p,
        )

    return result


def market_comparison(
    rows: list[dict],
    model_probabilities: np.ndarray,
) -> dict:
    indices = [
        index
        for index, row in enumerate(rows)
        if (row["normalized_yes_mid"] is not None)
    ]

    if not indices:
        return {
            "rows": 0,
        }

    y = np.array(
        [rows[index]["label_yes"] for index in indices],
        dtype=int,
    )

    model_p = np.array(
        [model_probabilities[index] for index in indices],
        dtype=float,
    )

    market_p = np.array(
        [rows[index]["normalized_yes_mid"] for index in indices],
        dtype=float,
    )

    model_result = calculate_metrics(
        y,
        model_p,
    )

    market_result = calculate_metrics(
        y,
        market_p,
    )

    return {
        "rows": len(indices),
        "model": (model_result),
        "market": (market_result),
        "model_minus_market": {
            "brier": (model_result["brier"] - market_result["brier"]),
            "log_loss": (model_result["log_loss"] - market_result["log_loss"]),
            "accuracy": (model_result["accuracy"] - market_result["accuracy"]),
        },
    }


def main() -> None:
    all_rows = load_rows()

    rows = [row for row in all_rows if row["common_complete"]]

    excluded_missing = len(all_rows) - len(rows)

    markets = ordered_markets(rows)

    (
        initial_train_markets,
        forward_folds,
    ) = split_forward_markets(markets)

    training_market_ids = set(initial_train_markets)

    fold_reports = []

    prediction_rows = []

    all_oos_rows = []

    all_a_probabilities = []

    all_b_probabilities = []

    for fold_index, fold_markets in enumerate(
        forward_folds,
        start=1,
    ):
        test_market_ids = set(fold_markets)

        overlap = training_market_ids & test_market_ids

        if overlap:
            raise RuntimeError(f"fold {fold_index} train/test market overlap")

        train_rows = rows_for_markets(
            rows,
            training_market_ids,
        )

        test_rows = rows_for_markets(
            rows,
            test_market_ids,
        )

        if not train_rows:
            raise RuntimeError(f"fold {fold_index} has no training rows")

        if not test_rows:
            raise RuntimeError(f"fold {fold_index} has no test rows")

        model_a = build_model()
        model_b = build_model()

        x_a_train, y_train = build_matrix(
            train_rows,
            MODEL_A_FEATURES,
        )

        x_b_train, _ = build_matrix(
            train_rows,
            MODEL_B_FEATURES,
        )

        x_a_test, y_test = build_matrix(
            test_rows,
            MODEL_A_FEATURES,
        )

        x_b_test, _ = build_matrix(
            test_rows,
            MODEL_B_FEATURES,
        )

        model_a.fit(
            x_a_train,
            y_train,
        )

        model_b.fit(
            x_b_train,
            y_train,
        )

        a_probabilities = model_a.predict_proba(x_a_test)[:, 1]

        b_probabilities = model_b.predict_proba(x_b_test)[:, 1]

        a_metrics = calculate_metrics(
            y_test,
            a_probabilities,
        )

        b_metrics = calculate_metrics(
            y_test,
            b_probabilities,
        )

        fold_report = {
            "fold": (fold_index),
            "train_markets": len(training_market_ids),
            "train_rows": len(train_rows),
            "test_markets": len(test_market_ids),
            "test_rows": len(test_rows),
            "test_first_timestamp": (
                min(row["prediction_timestamp"] for row in test_rows).isoformat()
            ),
            "test_last_timestamp": (
                max(row["prediction_timestamp"] for row in test_rows).isoformat()
            ),
            "A_BASELINE": {
                **a_metrics,
                "by_horizon": (
                    by_horizon_metrics(
                        test_rows,
                        a_probabilities,
                    )
                ),
            },
            "B_BASELINE_PLUS_CONTEXT": {
                **b_metrics,
                "by_horizon": (
                    by_horizon_metrics(
                        test_rows,
                        b_probabilities,
                    )
                ),
            },
            "B_minus_A": {
                "brier": (b_metrics["brier"] - a_metrics["brier"]),
                "log_loss": (b_metrics["log_loss"] - a_metrics["log_loss"]),
                "accuracy": (b_metrics["accuracy"] - a_metrics["accuracy"]),
            },
            "B_vs_market_common_rows": (
                market_comparison(
                    test_rows,
                    b_probabilities,
                )
            ),
        }

        fold_reports.append(fold_report)

        all_oos_rows.extend(test_rows)

        all_a_probabilities.extend(a_probabilities.tolist())

        all_b_probabilities.extend(b_probabilities.tolist())

        for index, row in enumerate(test_rows):
            prediction_rows.append(
                {
                    "fold": (fold_index),
                    "condition_id": (row["condition_id"]),
                    "prediction_timestamp": (row["prediction_timestamp"].isoformat()),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "label_yes": (row["label_yes"]),
                    "normalized_yes_mid": (row["normalized_yes_mid"]),
                    "A_BASELINE_probability": (a_probabilities[index]),
                    "B_BASELINE_PLUS_CONTEXT_probability": (b_probabilities[index]),
                }
            )

        # Expanding-window step:
        # this completed test fold becomes
        # available for the next fold's training.
        training_market_ids.update(test_market_ids)

    all_a_probabilities_array = np.array(
        all_a_probabilities,
        dtype=float,
    )

    all_b_probabilities_array = np.array(
        all_b_probabilities,
        dtype=float,
    )

    all_y = np.array(
        [row["label_yes"] for row in all_oos_rows],
        dtype=int,
    )

    overall_a = calculate_metrics(
        all_y,
        all_a_probabilities_array,
    )

    overall_b = calculate_metrics(
        all_y,
        all_b_probabilities_array,
    )

    overall_market_comparison = market_comparison(
        all_oos_rows,
        all_b_probabilities_array,
    )

    brier_fold_wins = sum(
        1 for fold in fold_reports if (fold["B_minus_A"]["brier"] < 0)
    )

    log_loss_fold_wins = sum(
        1 for fold in fold_reports if (fold["B_minus_A"]["log_loss"] < 0)
    )

    accuracy_fold_wins = sum(
        1 for fold in fold_reports if (fold["B_minus_A"]["accuracy"] > 0)
    )

    by_horizon = {}

    for horizon in HORIZONS:
        indices = [
            index
            for index, row in enumerate(all_oos_rows)
            if (row["target_horizon_seconds"] == horizon)
        ]

        if not indices:
            continue

        y = np.array(
            [all_oos_rows[index]["label_yes"] for index in indices],
            dtype=int,
        )

        a_p = np.array(
            [all_a_probabilities_array[index] for index in indices],
            dtype=float,
        )

        b_p = np.array(
            [all_b_probabilities_array[index] for index in indices],
            dtype=float,
        )

        a_result = calculate_metrics(
            y,
            a_p,
        )

        b_result = calculate_metrics(
            y,
            b_p,
        )

        by_horizon[str(horizon)] = {
            "A_BASELINE": (a_result),
            "B_BASELINE_PLUS_CONTEXT": (b_result),
            "B_minus_A": {
                "brier": (b_result["brier"] - a_result["brier"]),
                "log_loss": (b_result["log_loss"] - a_result["log_loss"]),
                "accuracy": (b_result["accuracy"] - a_result["accuracy"]),
            },
        }

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "dataset": ("p13_enriched_supervised.csv"),
            "initial_training_fraction": (0.50),
            "forward_folds": (FOLD_COUNT),
            "training_mode": ("expanding_window_by_market"),
            "market_overlap": ("forbidden"),
            "models": ("StandardScaler + LogisticRegression"),
            "hyperparameter_search": (False),
            "calibration": ("none"),
            "feature_selection": (False),
        },
        "input_rows": len(all_rows),
        "common_complete_rows": len(rows),
        "excluded_missing_common_features": (excluded_missing),
        "markets": len(markets),
        "initial_train_markets": len(initial_train_markets),
        "forward_test_markets": (len(markets) - len(initial_train_markets)),
        "folds": (fold_reports),
        "overall_oos": {
            "rows": len(all_oos_rows),
            "markets": len({row["condition_id"] for row in all_oos_rows}),
            "A_BASELINE": {
                **overall_a,
                "by_horizon": (
                    by_horizon_metrics(
                        all_oos_rows,
                        all_a_probabilities_array,
                    )
                ),
            },
            "B_BASELINE_PLUS_CONTEXT": {
                **overall_b,
                "by_horizon": (
                    by_horizon_metrics(
                        all_oos_rows,
                        all_b_probabilities_array,
                    )
                ),
            },
            "B_minus_A": {
                "brier": (overall_b["brier"] - overall_a["brier"]),
                "log_loss": (overall_b["log_loss"] - overall_a["log_loss"]),
                "accuracy": (overall_b["accuracy"] - overall_a["accuracy"]),
            },
            "B_vs_market_common_rows": (overall_market_comparison),
            "by_horizon": (by_horizon),
        },
        "fold_win_counts": {
            "B_better_brier": (brier_fold_wins),
            "B_better_log_loss": (log_loss_fold_wins),
            "B_better_accuracy": (accuracy_fold_wins),
            "folds": (FOLD_COUNT),
        },
    }

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(prediction_rows[0].keys()),
        )

        writer.writeheader()

        writer.writerows(prediction_rows)

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P13 walk-forward validation complete")

    print()
    print(
        "common_complete_rows=",
        len(rows),
    )
    print(
        "markets=",
        len(markets),
    )
    print(
        "initial_train_markets=",
        len(initial_train_markets),
    )
    print(
        "forward_test_markets=",
        (len(markets) - len(initial_train_markets)),
    )

    print()
    print("FOLD RESULTS")

    for fold in fold_reports:
        print()
        print(
            "fold",
            fold["fold"],
            "train_markets=",
            fold["train_markets"],
            "test_markets=",
            fold["test_markets"],
        )

        print(
            " A brier=",
            fold["A_BASELINE"]["brier"],
            "log_loss=",
            fold["A_BASELINE"]["log_loss"],
            "accuracy=",
            fold["A_BASELINE"]["accuracy"],
        )

        print(
            " B brier=",
            fold["B_BASELINE_PLUS_CONTEXT"]["brier"],
            "log_loss=",
            fold["B_BASELINE_PLUS_CONTEXT"]["log_loss"],
            "accuracy=",
            fold["B_BASELINE_PLUS_CONTEXT"]["accuracy"],
        )

        print(
            " B-A=",
            fold["B_minus_A"],
        )

        market = fold["B_vs_market_common_rows"]

        print(
            " B vs market common rows=",
            market.get("rows"),
            "delta=",
            market.get("model_minus_market"),
        )

    print()
    print("OVERALL OOS")

    print(
        "A=",
        overall_a,
    )

    print(
        "B=",
        overall_b,
    )

    print(
        "B-A=",
        report["overall_oos"]["B_minus_A"],
    )

    print()
    print("FOLD WIN COUNTS")

    print(report["fold_win_counts"])

    print()
    print("BY HORIZON")

    for horizon in HORIZONS:
        result = by_horizon[str(horizon)]

        print(
            horizon,
            "A_brier=",
            result["A_BASELINE"]["brier"],
            "B_brier=",
            result["B_BASELINE_PLUS_CONTEXT"]["brier"],
            "delta=",
            result["B_minus_A"]["brier"],
        )

    print()
    print("FAIR B VS MARKET")

    print(overall_market_comparison)

    print()
    print(f"Wrote {OUTPUT_REPORT}")

    print(f"Wrote {OUTPUT_PREDICTIONS}")


if __name__ == "__main__":
    main()
