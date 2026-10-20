from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "experiments" / "p13_model_improvement"

INPUT = DATA / "p13_prospective_supervised.csv"
FROZEN = ROOT / "data" / "models" / "p13_hgb4_candidate_v1.joblib"

REPORT = DATA / "p13_rtds_native_walkforward_report.json"
PREDICTIONS = DATA / "p13_rtds_native_walkforward_predictions.csv"

FEATURES3 = [
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
]
FEATURES4 = FEATURES3 + ["rtds_ohlc_return_1m"]

HORIZONS = {240, 180, 120, 90, 60, 30}
SEED = 1337


def make_hgb():
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=3,
        l2_regularization=1.0,
        random_state=SEED,
    )


def make_logistic():
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            max_iter=1000,
            solver="lbfgs",
        ),
    )


def load_dataset():
    df = pd.read_csv(INPUT)
    df["condition_id"] = df["condition_id"].astype(str).str.strip().str.lower()

    for column in [
        "prediction_timestamp",
        "market_end_at",
        "rtds_available_at",
    ]:
        df[column] = pd.to_datetime(df[column], utc=True, errors="coerce")

    required = [
        "snapshot_complete",
        "reference_return_30s_complete",
        "rtds_context_complete",
    ]

    for column in required:
        df[column] = df[column].astype(str).str.lower() == "true"

    complete = df[required].all(axis=1)

    for column in FEATURES4 + ["label_yes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    complete &= df[FEATURES4 + ["label_yes"]].notna().all(axis=1)
    complete &= df["label_yes"].isin([0, 1])
    complete &= df["target_horizon_seconds"].isin(HORIZONS)
    complete &= df["prediction_timestamp"].notna()
    complete &= df["market_end_at"].notna()
    complete &= df["rtds_available_at"].notna()

    result = df.loc[complete].copy()

    if result.empty:
        raise RuntimeError("No complete RTDS rows.")

    if (result["rtds_available_at"] > result["prediction_timestamp"]).any():
        raise RuntimeError("Future RTDS feature detected.")

    if (result["prediction_timestamp"] >= result["market_end_at"]).any():
        raise RuntimeError("Invalid prediction timestamps.")

    if result.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate market/horizon keys.")

    labels_per_market = result.groupby("condition_id")["label_yes"].nunique()

    if (labels_per_market != 1).any():
        raise RuntimeError("Conflicting market labels.")

    end_per_market = result.groupby("condition_id")["market_end_at"].nunique()

    if (end_per_market != 1).any():
        raise RuntimeError("Conflicting market end times.")

    return result


def market_folds(df):
    markets = (
        df.groupby("condition_id", as_index=False)
        .agg(market_end_at=("market_end_at", "first"))
        .sort_values(["market_end_at", "condition_id"])
        .reset_index(drop=True)
    )

    n = len(markets)
    initial = n // 2

    if initial < 100 or n - initial < 5:
        raise RuntimeError("Insufficient markets for five folds.")

    test_positions = np.array_split(np.arange(initial, n), 5)

    for number, positions in enumerate(test_positions, 1):
        first_test_end = markets.loc[positions[0], "market_end_at"]

        # Strict temporal purge:
        # training markets must end before the first
        # test market ends. No market identity overlap.
        train_ids = set(
            markets.loc[
                markets["market_end_at"] < first_test_end,
                "condition_id",
            ]
        )

        test_ids = set(markets.iloc[positions]["condition_id"])

        if train_ids & test_ids:
            raise RuntimeError("Train/test market overlap.")

        train = df[df["condition_id"].isin(train_ids)].copy()
        test = df[df["condition_id"].isin(test_ids)].copy()

        if len(train) == 0 or len(test) == 0:
            raise RuntimeError("Empty training/test fold.")

        if train["label_yes"].nunique() != 2:
            raise RuntimeError("Training fold has one class.")

        if train["market_end_at"].max() >= test["market_end_at"].min():
            raise RuntimeError("Temporal isolation failed.")

        yield number, train, test


def losses(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    y = np.asarray(y, dtype=int)

    return (
        (p - y) ** 2,
        -(y * np.log(p) + (1 - y) * np.log(1 - p)),
    )


def metrics(df, column):
    y = df["label_yes"].to_numpy(dtype=int)
    p = df[column].to_numpy(dtype=float)

    brier, logloss = losses(y, p)

    return {
        "rows": int(len(df)),
        "markets": int(df["condition_id"].nunique()),
        "accuracy": float(np.mean((p >= 0.5) == y)),
        "brier": float(np.mean(brier)),
        "log_loss": float(np.mean(logloss)),
    }


def main():
    if not FROZEN.exists():
        raise FileNotFoundError(f"Missing preserved HGB4: {FROZEN}")

    df = load_dataset()
    frozen = joblib.load(FROZEN)

    # Fail safely if artifact is a container rather than estimator.
    if isinstance(frozen, dict):
        raise RuntimeError(
            "HGB4 artifact is a dictionary. Inspect its "
            "schema before adapting this script."
        )

    predictions = []
    folds = []

    for fold, train, test in market_folds(df):
        models = {
            "logistic3_native": (make_logistic(), FEATURES3),
            "hgb3_native": (make_hgb(), FEATURES3),
            "hgb4_native": (make_hgb(), FEATURES4),
        }

        output = test[
            [
                "condition_id",
                "market_end_at",
                "prediction_timestamp",
                "target_horizon_seconds",
                "label_yes",
                "normalized_yes_mid",
            ]
        ].copy()

        output["fold"] = fold

        for name, (model, features) in models.items():
            model.fit(
                train[features].to_numpy(dtype=float),
                train["label_yes"].to_numpy(dtype=int),
            )

            output[name] = model.predict_proba(test[features].to_numpy(dtype=float))[
                :, 1
            ]

        output["hgb4_bitstamp_frozen"] = frozen.predict_proba(
            test[FEATURES4].to_numpy(dtype=float)
        )[:, 1]

        fold_report = {
            "fold": fold,
            "train_markets": train["condition_id"].nunique(),
            "test_markets": test["condition_id"].nunique(),
            "train_last_end": train["market_end_at"].max().isoformat(),
            "test_first_end": test["market_end_at"].min().isoformat(),
            "models": {},
        }

        for name in [
            "logistic3_native",
            "hgb3_native",
            "hgb4_native",
            "hgb4_bitstamp_frozen",
        ]:
            fold_report["models"][name] = metrics(output, name)

        folds.append(fold_report)
        predictions.append(output)

        print(
            f"Fold {fold}: "
            f"train={fold_report['train_markets']} "
            f"test={fold_report['test_markets']}"
        )

    result = pd.concat(predictions, ignore_index=True)

    model_names = [
        "logistic3_native",
        "hgb3_native",
        "hgb4_native",
        "hgb4_bitstamp_frozen",
    ]

    overall = {name: metrics(result, name) for name in model_names}

    by_horizon = {}

    for horizon, group in result.groupby("target_horizon_seconds"):
        by_horizon[str(int(horizon))] = {
            name: metrics(group, name) for name in model_names
        }

    comparisons = {}

    for challenger, baseline in [
        ("hgb4_native", "hgb3_native"),
        ("hgb4_native", "logistic3_native"),
        ("hgb4_native", "hgb4_bitstamp_frozen"),
        ("hgb3_native", "logistic3_native"),
    ]:
        key = f"{challenger}_minus_{baseline}"

        comparisons[key] = {
            "brier": (overall[challenger]["brier"] - overall[baseline]["brier"]),
            "log_loss": (
                overall[challenger]["log_loss"] - overall[baseline]["log_loss"]
            ),
            "accuracy": (
                overall[challenger]["accuracy"] - overall[baseline]["accuracy"]
            ),
        }

    market = result[
        pd.to_numeric(
            result["normalized_yes_mid"],
            errors="coerce",
        ).between(0, 1, inclusive="both")
    ].copy()

    if not market.empty:
        market["normalized_yes_mid"] = pd.to_numeric(market["normalized_yes_mid"])

        market_metrics = {
            "market": metrics(market, "normalized_yes_mid"),
            "models": {name: metrics(market, name) for name in model_names},
        }
    else:
        market_metrics = {"status": "no_common_market_probabilities"}

    report = {
        "experiment": "rtds_native_expanding_walkforward_v1",
        "status": "exploratory_previously_inspected_period",
        "input": str(INPUT),
        "frozen_reference": str(FROZEN),
        "complete_source_rows": len(df),
        "complete_source_markets": df["condition_id"].nunique(),
        "oos_rows": len(result),
        "oos_markets": result["condition_id"].nunique(),
        "features3": FEATURES3,
        "features4": FEATURES4,
        "folds": folds,
        "overall": overall,
        "by_horizon": by_horizon,
        "model_comparisons": comparisons,
        "market_comparison": market_metrics,
        "notes": [
            "Training uses only earlier RTDS-native markets.",
            "Frozen Bitstamp HGB4 is not retrained.",
            "Results are exploratory, not a new untouched test.",
            "No production or shadow model is modified.",
        ],
    }

    REPORT.write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    result.to_csv(PREDICTIONS, index=False)

    print("\nRTDS-NATIVE WALK-FORWARD COMPLETE")
    print("complete_markets=", df["condition_id"].nunique())
    print("oos_markets=", result["condition_id"].nunique())
    print("oos_rows=", len(result))
    print("\nOVERALL")

    for name, value in overall.items():
        print(name, value)

    print("\nMODEL COMPARISONS")
    for name, value in comparisons.items():
        print(name, value)

    print("\nBY HORIZON")
    for horizon, values in by_horizon.items():
        print(horizon, values)

    print("\nMARKET BENCHMARK")
    print(json.dumps(market_metrics, indent=2))

    print("\nreport=", REPORT)
    print("predictions=", PREDICTIONS)


if __name__ == "__main__":
    main()
