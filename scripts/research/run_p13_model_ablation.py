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
    / "p13_model_ablation_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_model_ablation_predictions.csv"
)


REPORT_VERSION = "p13_model_ablation_v1"


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


MODEL_FEATURES = {
    "A_BASELINE": (BASELINE_FEATURES),
    "B_BASELINE_PLUS_CONTEXT": (BASELINE_FEATURES + BTC_CONTEXT_FEATURES),
    "C_CONTEXT_ONLY": (BTC_CONTEXT_FEATURES),
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


def load_rows() -> list[dict]:
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
            condition_id = row["condition_id"].strip().lower()

            if not condition_id:
                raise RuntimeError(f"missing condition_id at row {row_number}")

            label_raw = row["label_yes"].strip()

            if label_raw not in {
                "0",
                "1",
            }:
                raise RuntimeError(
                    f"invalid label_yes at row {row_number}: {label_raw!r}"
                )

            prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

            feature_values = {}

            all_features = BASELINE_FEATURES + BTC_CONTEXT_FEATURES

            for feature in all_features:
                feature_values[feature] = optional_float(row.get(feature))

            # All models must be compared on
            # exactly the same observations.
            common_complete = all(
                feature_values[feature] is not None for feature in all_features
            )

            rows.append(
                {
                    "row_number": (row_number),
                    "condition_id": (condition_id),
                    "prediction_timestamp": (prediction_timestamp),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "label_yes": int(label_raw),
                    "normalized_yes_mid": (
                        optional_float(row.get("normalized_yes_mid"))
                    ),
                    "eligible_book_features": (
                        row.get(
                            "eligible_book_features",
                            "",
                        )
                        .strip()
                        .lower()
                        == "true"
                    ),
                    "common_complete": (common_complete),
                    **feature_values,
                }
            )

    return rows


def assign_market_splits(
    rows: list[dict],
) -> dict[str, str]:
    first_prediction_by_market = {}

    for row in rows:
        condition_id = row["condition_id"]

        timestamp = row["prediction_timestamp"]

        existing = first_prediction_by_market.get(condition_id)

        if existing is None or timestamp < existing:
            first_prediction_by_market[condition_id] = timestamp

    ordered_markets = sorted(
        first_prediction_by_market,
        key=lambda condition_id: (
            first_prediction_by_market[condition_id],
            condition_id,
        ),
    )

    market_count = len(ordered_markets)

    train_end = int(market_count * 0.60)

    validation_end = int(market_count * 0.80)

    if train_end <= 0 or validation_end <= train_end or validation_end >= market_count:
        raise RuntimeError("invalid chronological split sizes")

    split_by_market = {}

    for index, condition_id in enumerate(ordered_markets):
        if index < train_end:
            split = "TRAIN"
        elif index < validation_end:
            split = "VALIDATION"
        else:
            split = "HOLDOUT"

        split_by_market[condition_id] = split

    return split_by_market


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
        "positive_rate": float(np.mean(y)),
        "mean_probability": float(np.mean(probabilities)),
    }


def evaluate_by_horizon(
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

        result[str(horizon)] = metrics(
            y,
            p,
        )

    return result


def market_benchmark(
    rows: list[dict],
) -> dict:
    comparable = [row for row in rows if (row["normalized_yes_mid"] is not None)]

    if not comparable:
        return {
            "rows": 0,
        }

    y = np.array(
        [row["label_yes"] for row in comparable],
        dtype=int,
    )

    p = np.array(
        [row["normalized_yes_mid"] for row in comparable],
        dtype=float,
    )

    result = metrics(
        y,
        p,
    )

    result["by_horizon"] = {}

    for horizon in HORIZONS:
        horizon_rows = [
            row for row in comparable if (row["target_horizon_seconds"] == horizon)
        ]

        if not horizon_rows:
            continue

        horizon_y = np.array(
            [row["label_yes"] for row in horizon_rows],
            dtype=int,
        )

        horizon_p = np.array(
            [row["normalized_yes_mid"] for row in horizon_rows],
            dtype=float,
        )

        result["by_horizon"][str(horizon)] = metrics(
            horizon_y,
            horizon_p,
        )

    return result


def main() -> None:
    all_rows = load_rows()

    complete_rows = [row for row in all_rows if row["common_complete"]]

    excluded_missing = len(all_rows) - len(complete_rows)

    split_by_market = assign_market_splits(complete_rows)

    for row in complete_rows:
        row["split"] = split_by_market[row["condition_id"]]

    rows_by_split = {
        split: [row for row in complete_rows if (row["split"] == split)]
        for split in (
            "TRAIN",
            "VALIDATION",
            "HOLDOUT",
        )
    }

    markets_by_split = {
        split: len({row["condition_id"] for row in rows})
        for split, rows in (rows_by_split.items())
    }

    # Explicit leakage check.
    train_markets = {row["condition_id"] for row in rows_by_split["TRAIN"]}

    validation_markets = {row["condition_id"] for row in rows_by_split["VALIDATION"]}

    holdout_markets = {row["condition_id"] for row in rows_by_split["HOLDOUT"]}

    overlap = (
        (train_markets & validation_markets)
        | (train_markets & holdout_markets)
        | (validation_markets & holdout_markets)
    )

    if overlap:
        raise RuntimeError(f"market leakage across splits: {len(overlap)} markets")

    model_reports = {}

    prediction_rows = []

    holdout_prediction_map = {}

    for (
        model_name,
        feature_names,
    ) in MODEL_FEATURES.items():
        train_rows = rows_by_split["TRAIN"]

        validation_rows = rows_by_split["VALIDATION"]

        holdout_rows = rows_by_split["HOLDOUT"]

        x_train, y_train = build_matrix(
            train_rows,
            feature_names,
        )

        x_validation, y_validation = build_matrix(
            validation_rows,
            feature_names,
        )

        x_holdout, y_holdout = build_matrix(
            holdout_rows,
            feature_names,
        )

        model = build_model()

        model.fit(
            x_train,
            y_train,
        )

        validation_probabilities = model.predict_proba(x_validation)[:, 1]

        holdout_probabilities = model.predict_proba(x_holdout)[:, 1]

        holdout_prediction_map[model_name] = holdout_probabilities

        logistic = model.named_steps["logistic"]

        model_reports[model_name] = {
            "features": list(feature_names),
            "train": {
                "rows": len(train_rows),
                "markets": (markets_by_split["TRAIN"]),
            },
            "validation": {
                **metrics(
                    y_validation,
                    validation_probabilities,
                ),
                "by_horizon": (
                    evaluate_by_horizon(
                        validation_rows,
                        validation_probabilities,
                    )
                ),
            },
            "holdout": {
                **metrics(
                    y_holdout,
                    holdout_probabilities,
                ),
                "by_horizon": (
                    evaluate_by_horizon(
                        holdout_rows,
                        holdout_probabilities,
                    )
                ),
            },
            "standardized_coefficients": {
                feature: float(coefficient)
                for feature, coefficient in zip(
                    feature_names,
                    logistic.coef_[0],
                )
            },
            "intercept": float(logistic.intercept_[0]),
        }

    holdout_rows = rows_by_split["HOLDOUT"]

    for index, row in enumerate(holdout_rows):
        prediction_rows.append(
            {
                "condition_id": (row["condition_id"]),
                "prediction_timestamp": (row["prediction_timestamp"].isoformat()),
                "target_horizon_seconds": (row["target_horizon_seconds"]),
                "label_yes": (row["label_yes"]),
                "normalized_yes_mid": (row["normalized_yes_mid"]),
                "A_BASELINE_probability": (holdout_prediction_map["A_BASELINE"][index]),
                "B_BASELINE_PLUS_CONTEXT_probability": (
                    holdout_prediction_map["B_BASELINE_PLUS_CONTEXT"][index]
                ),
                "C_CONTEXT_ONLY_probability": (
                    holdout_prediction_map["C_CONTEXT_ONLY"][index]
                ),
            }
        )

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

    baseline_holdout = model_reports["A_BASELINE"]["holdout"]

    context_holdout = model_reports["B_BASELINE_PLUS_CONTEXT"]["holdout"]

    context_only_holdout = model_reports["C_CONTEXT_ONLY"]["holdout"]

    incremental_context = {
        "brier_delta_B_minus_A": (context_holdout["brier"] - baseline_holdout["brier"]),
        "log_loss_delta_B_minus_A": (
            context_holdout["log_loss"] - baseline_holdout["log_loss"]
        ),
        "accuracy_delta_B_minus_A": (
            context_holdout["accuracy"] - baseline_holdout["accuracy"]
        ),
    }

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "dataset": ("p13_enriched_supervised.csv"),
            "comparison_rows": ("identical complete rows for all three models"),
            "split": ("chronological 60/20/20 by condition_id"),
            "model_family": ("StandardScaler + LogisticRegression"),
            "hyperparameter_search": (False),
            "calibration": ("none"),
        },
        "input_rows": len(all_rows),
        "common_complete_rows": len(complete_rows),
        "excluded_missing_common_features": (excluded_missing),
        "markets": len(split_by_market),
        "split_counts": {
            split: {
                "rows": len(rows_by_split[split]),
                "markets": (markets_by_split[split]),
            }
            for split in (
                "TRAIN",
                "VALIDATION",
                "HOLDOUT",
            )
        },
        "market_overlap_across_splits": (len(overlap)),
        "models": (model_reports),
        "holdout_market_benchmark": (market_benchmark(holdout_rows)),
        "incremental_context_holdout": (incremental_context),
        "interpretation_rule": {
            "B_improves_brier_if": ("brier_delta_B_minus_A < 0"),
            "B_improves_log_loss_if": ("log_loss_delta_B_minus_A < 0"),
            "B_improves_accuracy_if": ("accuracy_delta_B_minus_A > 0"),
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

    print("P13 model ablation complete")

    print()
    print(
        "input_rows=",
        len(all_rows),
    )
    print(
        "common_complete_rows=",
        len(complete_rows),
    )
    print(
        "excluded_missing=",
        excluded_missing,
    )
    print(
        "markets=",
        len(split_by_market),
    )
    print(
        "market_overlap=",
        len(overlap),
    )

    print()
    print("SPLITS")

    for split in (
        "TRAIN",
        "VALIDATION",
        "HOLDOUT",
    ):
        print(
            split,
            rows_by_split[split].__len__(),
            "rows",
            markets_by_split[split],
            "markets",
        )

    print()
    print("HOLDOUT RESULTS")

    for model_name in (
        "A_BASELINE",
        "B_BASELINE_PLUS_CONTEXT",
        "C_CONTEXT_ONLY",
    ):
        result = model_reports[model_name]["holdout"]

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
            " by_horizon_brier=",
            {
                horizon: values["brier"]
                for horizon, values in (result["by_horizon"].items())
            },
        )

    print()
    print("INCREMENTAL CONTEXT")

    print(incremental_context)

    print()
    print("MARKET BENCHMARK")

    market_result = report["holdout_market_benchmark"]

    print(
        " rows=",
        market_result.get("rows"),
    )

    if market_result.get(
        "rows",
        0,
    ):
        print(
            " brier=",
            market_result["brier"],
        )
        print(
            " log_loss=",
            market_result["log_loss"],
        )

    print()
    print("B CONTEXT COEFFICIENTS")

    for (
        feature,
        coefficient,
    ) in model_reports["B_BASELINE_PLUS_CONTEXT"]["standardized_coefficients"].items():
        print(
            feature,
            coefficient,
        )

    print()
    print(f"Wrote {OUTPUT_REPORT}")
    print(f"Wrote {OUTPUT_PREDICTIONS}")


if __name__ == "__main__":
    main()
