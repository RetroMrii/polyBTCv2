from __future__ import annotations

import csv
import json

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from xgboost import XGBClassifier


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_expanded_development_pre_block1.csv"
)

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_model_family_retest_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_model_family_retest_predictions.csv"
)


BLOCK_1_START = datetime.fromisoformat("2026-10-03T20:45:00+00:00")

FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

HORIZONS = (
    240,
    180,
    120,
    90,
    60,
    30,
)

INITIAL_TRAIN_FRACTION = 0.50
N_FOLDS = 5

RANDOM_SEED = 1337


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def load_rows() -> list[dict]:
    rows = []

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            condition_id = row["condition_id"].strip().lower()

            prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

            if prediction_timestamp >= BLOCK_1_START:
                raise RuntimeError(
                    "BLOCK 1 LEAKAGE DETECTED: "
                    f"{condition_id} "
                    f"{prediction_timestamp.isoformat()}"
                )

            label_raw = row.get(
                "label_yes",
                "",
            ).strip()

            if label_raw not in {
                "0",
                "1",
            }:
                continue

            feature_values = {
                feature: optional_float(row.get(feature)) for feature in FEATURES
            }

            if any(value is None for value in feature_values.values()):
                continue

            rows.append(
                {
                    "condition_id": (condition_id),
                    "prediction_timestamp": (prediction_timestamp),
                    "target_horizon_seconds": int(float(row["target_horizon_seconds"])),
                    "label_yes": int(label_raw),
                    "normalized_yes_mid": (
                        optional_float(row.get("normalized_yes_mid"))
                    ),
                    **feature_values,
                }
            )

    return rows


def build_logistic() -> Pipeline:
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


def build_hgb() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=3,
        l2_regularization=1.0,
        random_state=RANDOM_SEED,
    )


def build_xgb() -> XGBClassifier:
    return XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        min_child_weight=5.0,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=-1,
        random_state=RANDOM_SEED,
    )


def build_matrix(
    rows: list[dict],
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    x = np.asarray(
        [[float(row[feature]) for feature in FEATURES] for row in rows],
        dtype=float,
    )

    y = np.asarray(
        [row["label_yes"] for row in rows],
        dtype=int,
    )

    return x, y


def metrics(
    y: np.ndarray,
    p: np.ndarray,
) -> dict:
    predicted = (p >= 0.5).astype(int)

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
                p,
            )
        ),
        "log_loss": float(
            log_loss(
                y,
                p,
                labels=[
                    0,
                    1,
                ],
            )
        ),
    }


def chronological_markets(
    rows: list[dict],
) -> list[str]:
    first_timestamp = {}

    for row in rows:
        condition_id = row["condition_id"]

        timestamp = row["prediction_timestamp"]

        previous = first_timestamp.get(condition_id)

        if previous is None or timestamp < previous:
            first_timestamp[condition_id] = timestamp

    return [
        condition_id
        for (condition_id, _) in sorted(
            first_timestamp.items(),
            key=lambda item: item[1],
        )
    ]


def make_folds(
    markets: list[str],
) -> list[
    tuple[
        set[str],
        set[str],
    ]
]:
    total = len(markets)

    initial_train = int(total * INITIAL_TRAIN_FRACTION)

    remaining = total - initial_train

    fold_sizes = [remaining // N_FOLDS] * N_FOLDS

    for index in range(remaining % N_FOLDS):
        fold_sizes[index] += 1

    folds = []

    test_start = initial_train

    for fold_size in fold_sizes:
        test_end = test_start + fold_size

        train_markets = set(markets[:test_start])

        test_markets = set(markets[test_start:test_end])

        folds.append(
            (
                train_markets,
                test_markets,
            )
        )

        test_start = test_end

    return folds


def evaluate_market(
    rows: list[dict],
    probabilities: np.ndarray,
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

    y = np.asarray(
        [rows[index]["label_yes"] for index in indices],
        dtype=int,
    )

    model_p = np.asarray(
        [probabilities[index] for index in indices],
        dtype=float,
    )

    market_p = np.asarray(
        [rows[index]["normalized_yes_mid"] for index in indices],
        dtype=float,
    )

    model_result = metrics(
        y,
        model_p,
    )

    market_result = metrics(
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
    rows = load_rows()

    markets = chronological_markets(rows)

    folds = make_folds(markets)

    print("P13 model-family retest")

    print(
        "complete_rows=",
        len(rows),
    )

    print(
        "markets=",
        len(markets),
    )

    print("block1_consumed=False")

    print("block2_consumed=False")

    all_predictions = {
        "LOGISTIC": [],
        "HGB": [],
        "XGB": [],
    }

    all_labels = []

    prediction_rows = []

    fold_results = []

    for (
        fold_number,
        (
            train_markets,
            test_markets,
        ),
    ) in enumerate(
        folds,
        start=1,
    ):
        train_rows = [row for row in rows if row["condition_id"] in train_markets]

        test_rows = [row for row in rows if row["condition_id"] in test_markets]

        train_market_overlap = train_markets & test_markets

        if train_market_overlap:
            raise RuntimeError("train/test market overlap")

        x_train, y_train = build_matrix(train_rows)

        x_test, y_test = build_matrix(test_rows)

        models = {
            "LOGISTIC": (build_logistic()),
            "HGB": (build_hgb()),
            "XGB": (build_xgb()),
        }

        fold_result = {
            "fold": (fold_number),
            "train_markets": (len(train_markets)),
            "test_markets": (len(test_markets)),
            "train_rows": (len(train_rows)),
            "test_rows": (len(test_rows)),
            "models": {},
        }

        fold_probabilities = {}

        for (
            model_name,
            model,
        ) in models.items():
            model.fit(
                x_train,
                y_train,
            )

            probabilities = model.predict_proba(x_test)[:, 1]

            fold_probabilities[model_name] = probabilities

            model_metrics = metrics(
                y_test,
                probabilities,
            )

            fold_result["models"][model_name] = model_metrics

            all_predictions[model_name].extend(probabilities.tolist())

        all_labels.extend(y_test.tolist())

        for index, row in enumerate(test_rows):
            prediction_rows.append(
                {
                    "fold": (fold_number),
                    "condition_id": (row["condition_id"]),
                    "prediction_timestamp": (row["prediction_timestamp"].isoformat()),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "label_yes": (row["label_yes"]),
                    "normalized_yes_mid": (
                        ""
                        if row["normalized_yes_mid"] is None
                        else row["normalized_yes_mid"]
                    ),
                    "logistic_probability": (fold_probabilities["LOGISTIC"][index]),
                    "hgb_probability": (fold_probabilities["HGB"][index]),
                    "xgb_probability": (fold_probabilities["XGB"][index]),
                }
            )

        fold_results.append(fold_result)

        print()
        print(
            "FOLD",
            fold_number,
        )

        print(
            "train_markets=",
            len(train_markets),
            "test_markets=",
            len(test_markets),
        )

        for model_name in (
            "LOGISTIC",
            "HGB",
            "XGB",
        ):
            print(
                model_name,
                fold_result["models"][model_name],
            )

    y_all = np.asarray(
        all_labels,
        dtype=int,
    )

    overall = {}

    for model_name in (
        "LOGISTIC",
        "HGB",
        "XGB",
    ):
        probabilities = np.asarray(
            all_predictions[model_name],
            dtype=float,
        )

        overall[model_name] = metrics(
            y_all,
            probabilities,
        )

    by_horizon = {}

    for horizon in HORIZONS:
        horizon_rows = [
            row
            for row in prediction_rows
            if int(row["target_horizon_seconds"]) == horizon
        ]

        if not horizon_rows:
            continue

        y = np.asarray(
            [int(row["label_yes"]) for row in horizon_rows],
            dtype=int,
        )

        by_horizon[str(horizon)] = {}

        for (
            model_name,
            column,
        ) in (
            (
                "LOGISTIC",
                "logistic_probability",
            ),
            (
                "HGB",
                "hgb_probability",
            ),
            (
                "XGB",
                "xgb_probability",
            ),
        ):
            p = np.asarray(
                [float(row[column]) for row in horizon_rows],
                dtype=float,
            )

            by_horizon[str(horizon)][model_name] = metrics(
                y,
                p,
            )

    market_comparison = {}

    for (
        model_name,
        column,
    ) in (
        (
            "LOGISTIC",
            "logistic_probability",
        ),
        (
            "HGB",
            "hgb_probability",
        ),
        (
            "XGB",
            "xgb_probability",
        ),
    ):
        model_rows = []

        probabilities = []

        for row in prediction_rows:
            model_rows.append(
                {
                    "label_yes": int(row["label_yes"]),
                    "normalized_yes_mid": (
                        None
                        if row["normalized_yes_mid"] == ""
                        else float(row["normalized_yes_mid"])
                    ),
                }
            )

            probabilities.append(float(row[column]))

        market_comparison[model_name] = evaluate_market(
            model_rows,
            np.asarray(
                probabilities,
                dtype=float,
            ),
        )

    fold_wins = {
        "HGB_vs_LOGISTIC": {
            "brier": 0,
            "log_loss": 0,
            "accuracy": 0,
        },
        "XGB_vs_LOGISTIC": {
            "brier": 0,
            "log_loss": 0,
            "accuracy": 0,
        },
        "XGB_vs_HGB": {
            "brier": 0,
            "log_loss": 0,
            "accuracy": 0,
        },
    }

    comparisons = (
        (
            "HGB_vs_LOGISTIC",
            "HGB",
            "LOGISTIC",
        ),
        (
            "XGB_vs_LOGISTIC",
            "XGB",
            "LOGISTIC",
        ),
        (
            "XGB_vs_HGB",
            "XGB",
            "HGB",
        ),
    )

    for fold in fold_results:
        for (
            comparison_name,
            challenger,
            baseline,
        ) in comparisons:
            challenger_metrics = fold["models"][challenger]

            baseline_metrics = fold["models"][baseline]

            if challenger_metrics["brier"] < baseline_metrics["brier"]:
                fold_wins[comparison_name]["brier"] += 1

            if challenger_metrics["log_loss"] < baseline_metrics["log_loss"]:
                fold_wins[comparison_name]["log_loss"] += 1

            if challenger_metrics["accuracy"] > baseline_metrics["accuracy"]:
                fold_wins[comparison_name]["accuracy"] += 1

    report = {
        "report_version": ("p13_model_family_retest_v1"),
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "dataset": ("p4_expanded_development_pre_block1.csv"),
        "features": list(FEATURES),
        "initial_train_fraction": (INITIAL_TRAIN_FRACTION),
        "folds": (N_FOLDS),
        "complete_rows": (len(rows)),
        "markets": (len(markets)),
        "block1_consumed": False,
        "block2_consumed": False,
        "model_configuration": {
            "LOGISTIC": {
                "scaler": ("StandardScaler"),
                "solver": ("lbfgs"),
                "max_iter": 1000,
            },
            "HGB": {
                "learning_rate": 0.05,
                "max_iter": 200,
                "max_depth": 3,
                "l2_regularization": 1.0,
            },
            "XGB": {
                "n_estimators": 200,
                "max_depth": 3,
                "learning_rate": 0.05,
                "min_child_weight": 5.0,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "reg_lambda": 1.0,
            },
        },
        "overall": (overall),
        "fold_results": (fold_results),
        "fold_wins": (fold_wins),
        "by_horizon": (by_horizon),
        "market_comparison": (market_comparison),
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

    print()
    print("OVERALL")

    for model_name in (
        "LOGISTIC",
        "HGB",
        "XGB",
    ):
        print(
            model_name,
            overall[model_name],
        )

    print()
    print("FOLD WINS")

    print(fold_wins)

    print()
    print("BY HORIZON")

    for horizon in HORIZONS:
        result = by_horizon.get(str(horizon))

        if result is None:
            continue

        print()
        print(
            "horizon",
            horizon,
        )

        for model_name in (
            "LOGISTIC",
            "HGB",
            "XGB",
        ):
            print(
                model_name,
                result[model_name],
            )

    print()
    print("MARKET COMPARISON")

    for model_name in (
        "LOGISTIC",
        "HGB",
        "XGB",
    ):
        print()
        print(
            model_name,
            market_comparison[model_name],
        )

    print()
    print("BLOCK 1 CONSUMED=False")

    print("BLOCK 2 CONSUMED=False")

    print()
    print(f"Wrote {OUTPUT_REPORT}")

    print(f"Wrote {OUTPUT_PREDICTIONS}")


if __name__ == "__main__":
    main()
