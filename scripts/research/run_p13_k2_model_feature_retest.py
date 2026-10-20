from __future__ import annotations

import csv
import json

from collections import defaultdict
from datetime import datetime, timedelta, timezone
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

DEVELOPMENT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_expanded_development_pre_block1.csv"
)

BTC_CONTEXT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "btc_1m_context_features.csv"
)

OUTPUT_REPORT = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_k2_model_feature_retest_report.json"
)

OUTPUT_PREDICTIONS = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_k2_model_feature_retest_predictions.csv"
)


BLOCK_1_START = datetime.fromisoformat("2026-10-03T20:45:00+00:00")

FEATURES_3 = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

FEATURES_4 = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
    "btc_return_1m",
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
BOOTSTRAP_SAMPLES = 10000


def parse_timestamp(
    value: str,
) -> datetime:
    value = value.strip()

    if not value:
        raise ValueError("empty timestamp")

    # Support Unix seconds used by historical BTC context files.
    try:
        numeric = float(value)

        return datetime.fromtimestamp(
            numeric,
            tz=timezone.utc,
        )

    except ValueError:
        pass

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def load_btc_context() -> list[dict]:
    rows = []

    with BTC_CONTEXT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        fieldnames = set(reader.fieldnames or [])

        if "btc_return_1m" not in fieldnames:
            raise RuntimeError(f"btc_return_1m missing from {BTC_CONTEXT_FILE}")

        for row in reader:
            raw_timestamp = (
                row.get("timestamp") or row.get("bar_start_at") or ""
            ).strip()

            if not raw_timestamp:
                continue

            timestamp = parse_timestamp(raw_timestamp)

            value = optional_float(row.get("btc_return_1m"))

            if value is None:
                continue

            # Historical minute-bar semantics:
            # bar timestamp is minute start.
            # Feature is usable only after minute completion.
            available_at = timestamp + timedelta(seconds=60)

            rows.append(
                {
                    "bar_start_at": (timestamp),
                    "available_at": (available_at),
                    "btc_return_1m": (value),
                }
            )

    rows.sort(key=lambda row: row["available_at"])

    return rows


def latest_available_context(
    context_rows: list[dict],
    prediction_timestamp: datetime,
) -> dict | None:
    left = 0
    right = len(context_rows)

    while left < right:
        middle = (left + right) // 2

        if context_rows[middle]["available_at"] <= prediction_timestamp:
            left = middle + 1
        else:
            right = middle

    index = left - 1

    if index < 0:
        return None

    candidate = context_rows[index]

    age_seconds = (prediction_timestamp - candidate["available_at"]).total_seconds()

    # Preserve historical P13 join semantics:
    # completed minute context should be 0-30 sec old.
    if age_seconds < 0 or age_seconds > 30:
        return None

    return candidate


def load_development_rows(
    context_rows: list[dict],
) -> list[dict]:
    rows = []

    with DEVELOPMENT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            condition_id = row["condition_id"].strip().lower()

            prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

            if prediction_timestamp >= BLOCK_1_START:
                raise RuntimeError(f"BLOCK 1 LEAKAGE DETECTED: {condition_id}")

            label_raw = row.get("label_yes", "").strip()

            if label_raw not in {
                "0",
                "1",
            }:
                continue

            three_features = {
                feature: optional_float(row.get(feature)) for feature in FEATURES_3
            }

            if any(value is None for value in three_features.values()):
                continue

            context = latest_available_context(
                context_rows,
                prediction_timestamp,
            )

            if context is None:
                continue

            rows.append(
                {
                    "condition_id": (condition_id),
                    "prediction_timestamp": (prediction_timestamp),
                    "target_horizon_seconds": int(float(row["target_horizon_seconds"])),
                    "relative_distance_from_strike": (
                        three_features["relative_distance_from_strike"]
                    ),
                    "reference_return_30s": (three_features["reference_return_30s"]),
                    "btc_return_1m": (context["btc_return_1m"]),
                    "btc_context_available_at": (context["available_at"]),
                    "label_yes": int(label_raw),
                    "normalized_yes_mid": (
                        optional_float(row.get("normalized_yes_mid"))
                    ),
                }
            )

    return rows


def chronological_markets(
    rows: list[dict],
) -> list[str]:
    first_time = {}

    for row in rows:
        market = row["condition_id"]

        timestamp = row["prediction_timestamp"]

        if market not in first_time or timestamp < first_time[market]:
            first_time[market] = timestamp

    return [
        market
        for market, _ in sorted(
            first_time.items(),
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

        folds.append(
            (
                set(markets[:test_start]),
                set(markets[test_start:test_end]),
            )
        )

        test_start = test_end

    return folds


def matrix(
    rows: list[dict],
    features: tuple[str, ...],
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    x = np.asarray(
        [[float(row[feature]) for feature in features] for row in rows],
        dtype=float,
    )

    y = np.asarray(
        [row["label_yes"] for row in rows],
        dtype=int,
    )

    return x, y


def build_logistic() -> Pipeline:
    return Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "model",
                LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def build_hgb():
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=3,
        l2_regularization=1.0,
        random_state=RANDOM_SEED,
    )


def build_xgb():
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


def metrics(
    y: np.ndarray,
    probabilities: np.ndarray,
) -> dict:
    prediction = (probabilities >= 0.5).astype(int)

    return {
        "rows": int(len(y)),
        "accuracy": float(
            accuracy_score(
                y,
                prediction,
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


def paired_delta(
    y: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
) -> dict:
    first_metrics = metrics(
        y,
        first,
    )

    second_metrics = metrics(
        y,
        second,
    )

    return {
        "brier": (first_metrics["brier"] - second_metrics["brier"]),
        "log_loss": (first_metrics["log_loss"] - second_metrics["log_loss"]),
        "accuracy": (first_metrics["accuracy"] - second_metrics["accuracy"]),
    }


def market_cluster_bootstrap(
    rows: list[dict],
    probability_column: str,
) -> dict:
    usable = [row for row in rows if row["normalized_yes_mid"] is not None]

    by_market = defaultdict(list)

    for row in usable:
        by_market[row["condition_id"]].append(row)

    markets = list(by_market.keys())

    if not markets:
        return {
            "markets": 0,
            "rows": 0,
        }

    rng = np.random.default_rng(RANDOM_SEED)

    brier_deltas = []
    log_loss_deltas = []

    for _ in range(BOOTSTRAP_SAMPLES):
        sampled_markets = rng.choice(
            markets,
            size=len(markets),
            replace=True,
        )

        sample = []

        for market in sampled_markets:
            sample.extend(by_market[market])

        y = np.asarray(
            [row["label_yes"] for row in sample],
            dtype=int,
        )

        model_p = np.asarray(
            [row[probability_column] for row in sample],
            dtype=float,
        )

        market_p = np.asarray(
            [row["normalized_yes_mid"] for row in sample],
            dtype=float,
        )

        model_metrics = metrics(
            y,
            model_p,
        )

        market_metrics = metrics(
            y,
            market_p,
        )

        brier_deltas.append(model_metrics["brier"] - market_metrics["brier"])

        log_loss_deltas.append(model_metrics["log_loss"] - market_metrics["log_loss"])

    brier_array = np.asarray(brier_deltas)

    logloss_array = np.asarray(log_loss_deltas)

    return {
        "markets": len(markets),
        "rows": len(usable),
        "bootstrap_samples": (BOOTSTRAP_SAMPLES),
        "brier_model_minus_market": {
            "mean": float(np.mean(brier_array)),
            "ci95_low": float(
                np.quantile(
                    brier_array,
                    0.025,
                )
            ),
            "ci95_high": float(
                np.quantile(
                    brier_array,
                    0.975,
                )
            ),
            "probability_model_better": float(np.mean(brier_array < 0)),
        },
        "log_loss_model_minus_market": {
            "mean": float(np.mean(logloss_array)),
            "ci95_low": float(
                np.quantile(
                    logloss_array,
                    0.025,
                )
            ),
            "ci95_high": float(
                np.quantile(
                    logloss_array,
                    0.975,
                )
            ),
            "probability_model_better": float(np.mean(logloss_array < 0)),
        },
    }


def main() -> None:
    context_rows = load_btc_context()

    rows = load_development_rows(context_rows)

    markets = chronological_markets(rows)

    folds = make_folds(markets)

    print("P13-K2 model + feature retest")

    print(
        "complete_common_rows=",
        len(rows),
    )

    print(
        "markets=",
        len(markets),
    )

    print("block1_consumed=False")

    print("block2_consumed=False")

    model_specs = {
        "LOG3": (
            FEATURES_3,
            build_logistic,
        ),
        "HGB3": (
            FEATURES_3,
            build_hgb,
        ),
        "LOG4": (
            FEATURES_4,
            build_logistic,
        ),
        "HGB4": (
            FEATURES_4,
            build_hgb,
        ),
        "XGB4": (
            FEATURES_4,
            build_xgb,
        ),
    }

    all_predictions = {name: [] for name in model_specs}

    all_labels = []

    prediction_rows = []

    fold_results = []

    for fold_number, (
        train_markets,
        test_markets,
    ) in enumerate(
        folds,
        start=1,
    ):
        if train_markets & test_markets:
            raise RuntimeError("train/test market overlap")

        train_rows = [row for row in rows if row["condition_id"] in train_markets]

        test_rows = [row for row in rows if row["condition_id"] in test_markets]

        fold_result = {
            "fold": (fold_number),
            "train_markets": len(train_markets),
            "test_markets": len(test_markets),
            "train_rows": len(train_rows),
            "test_rows": len(test_rows),
            "models": {},
        }

        fold_probabilities = {}

        for model_name, (
            features,
            builder,
        ) in model_specs.items():
            x_train, y_train = matrix(
                train_rows,
                features,
            )

            x_test, y_test = matrix(
                test_rows,
                features,
            )

            model = builder()

            model.fit(
                x_train,
                y_train,
            )

            probabilities = model.predict_proba(x_test)[:, 1]

            fold_probabilities[model_name] = probabilities

            fold_result["models"][model_name] = metrics(
                y_test,
                probabilities,
            )

            all_predictions[model_name].extend(probabilities.tolist())

        all_labels.extend(y_test.tolist())

        for index, row in enumerate(test_rows):
            prediction_row = {
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
            }

            for model_name in model_specs:
                prediction_row[f"{model_name.lower()}_probability"] = (
                    fold_probabilities[model_name][index]
                )

            prediction_rows.append(prediction_row)

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

        for model_name in model_specs:
            print(
                model_name,
                fold_result["models"][model_name],
            )

    y_all = np.asarray(
        all_labels,
        dtype=int,
    )

    overall = {}

    for model_name in model_specs:
        overall[model_name] = metrics(
            y_all,
            np.asarray(
                all_predictions[model_name],
                dtype=float,
            ),
        )

    comparisons = {
        "HGB3_minus_LOG3": (
            "HGB3",
            "LOG3",
        ),
        "LOG4_minus_LOG3": (
            "LOG4",
            "LOG3",
        ),
        "HGB4_minus_HGB3": (
            "HGB4",
            "HGB3",
        ),
        "HGB4_minus_LOG4": (
            "HGB4",
            "LOG4",
        ),
        "XGB4_minus_LOG4": (
            "XGB4",
            "LOG4",
        ),
        "XGB4_minus_HGB4": (
            "XGB4",
            "HGB4",
        ),
    }

    overall_deltas = {}

    for name, (
        first,
        second,
    ) in comparisons.items():
        overall_deltas[name] = paired_delta(
            y_all,
            np.asarray(all_predictions[first]),
            np.asarray(all_predictions[second]),
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

        result = {}

        for model_name in model_specs:
            column = f"{model_name.lower()}_probability"

            probabilities = np.asarray(
                [float(row[column]) for row in horizon_rows],
                dtype=float,
            )

            result[model_name] = metrics(
                y,
                probabilities,
            )

        by_horizon[str(horizon)] = result

    # Prepare numeric prediction rows for cluster bootstrap.
    numeric_predictions = []

    for row in prediction_rows:
        numeric = {
            "condition_id": (row["condition_id"]),
            "label_yes": int(row["label_yes"]),
            "normalized_yes_mid": (
                None
                if row["normalized_yes_mid"] == ""
                else float(row["normalized_yes_mid"])
            ),
        }

        for model_name in model_specs:
            numeric[f"{model_name.lower()}_probability"] = float(
                row[f"{model_name.lower()}_probability"]
            )

        numeric_predictions.append(numeric)

    market_bootstrap = {}

    for model_name in (
        "LOG3",
        "HGB3",
        "LOG4",
        "HGB4",
        "XGB4",
    ):
        market_bootstrap[model_name] = market_cluster_bootstrap(
            numeric_predictions,
            f"{model_name.lower()}_probability",
        )

    report = {
        "report_version": ("p13_k2_model_feature_retest_v1"),
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "block1_consumed": False,
        "block2_consumed": False,
        "common_rows": (len(rows)),
        "markets": (len(markets)),
        "features_3": list(FEATURES_3),
        "features_4": list(FEATURES_4),
        "overall": (overall),
        "overall_deltas": (overall_deltas),
        "fold_results": (fold_results),
        "by_horizon": (by_horizon),
        "market_cluster_bootstrap": (market_bootstrap),
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

    if prediction_rows:
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

    for model_name in model_specs:
        print(
            model_name,
            overall[model_name],
        )

    print()
    print("OVERALL DELTAS")

    for name, result in overall_deltas.items():
        print(
            name,
            result,
        )

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

        for model_name in model_specs:
            print(
                model_name,
                result[model_name],
            )

    print()
    print("MARKET-CLUSTER BOOTSTRAP")

    for model_name in model_specs:
        print()
        print(
            model_name,
            market_bootstrap[model_name],
        )

    print()
    print("BLOCK 1 CONSUMED=False")

    print("BLOCK 2 CONSUMED=False")

    print()
    print(
        "report=",
        OUTPUT_REPORT,
    )

    print(
        "predictions=",
        OUTPUT_PREDICTIONS,
    )


if __name__ == "__main__":
    main()
