from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

import train_hgb3_expanded_v2 as base


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data/experiments/model_expansion/vm_expansion_v2"

REPORT = OUT_DIR / "hgb3_xgb_v2_comparison.json"
PREDICTIONS = OUT_DIR / "hgb3_xgb_v2_comparison.csv"

FEATURES = base.FEATURES
SEED = base.SEED


def make_xgb():
    return XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=1.0,
        colsample_bytree=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        reg_lambda=1.0,
        random_state=SEED,
        n_jobs=4,
    )


def model_variants(model, train, calibration, evaluation):
    x_train = train[FEATURES].to_numpy(dtype=float)
    y_train = train["label_yes"].to_numpy(dtype=int)
    x_cal = calibration[FEATURES].to_numpy(dtype=float)
    y_cal = calibration["label_yes"].to_numpy(dtype=int)
    x_eval = evaluation[FEATURES].to_numpy(dtype=float)

    if np.unique(y_train).tolist() != [0, 1]:
        raise RuntimeError("Training partition must have both classes")

    if np.unique(y_cal).tolist() != [0, 1]:
        raise RuntimeError("Calibration partition must have both classes")

    model.fit(x_train, y_train)

    raw_cal = model.predict_proba(x_cal)[:, 1]

    weights = base.market_weights(calibration)

    platt = LogisticRegression(
        solver="lbfgs",
        max_iter=2000,
        random_state=SEED,
    )

    platt.fit(
        base.logit(raw_cal).reshape(-1, 1),
        y_cal,
        sample_weight=weights,
    )

    isotonic = IsotonicRegression(
        y_min=0.0,
        y_max=1.0,
        increasing=True,
        out_of_bounds="clip",
    )

    isotonic.fit(
        raw_cal,
        y_cal,
        sample_weight=weights,
    )

    raw_eval = model.predict_proba(x_eval)[:, 1]

    variants = {
        "raw": base.clipped(raw_eval),
        "platt": base.clipped(
            platt.predict_proba(base.logit(raw_eval).reshape(-1, 1))[:, 1]
        ),
        "isotonic": base.clipped(isotonic.predict(raw_eval)),
    }

    for name, p in variants.items():
        if (
            len(p) != len(evaluation)
            or not np.isfinite(p).all()
            or np.any(p < 0)
            or np.any(p > 1)
        ):
            raise RuntimeError(f"Invalid predictions: {name}")

    return variants


def paired_market_brier(predictions, left, right):
    """
    Equal-market comparison. Resample markets,
    not individual horizons.
    Positive delta means the left predictor is worse.
    """
    data = predictions[["condition_id", "label_yes", left, right]].dropna().copy()

    if data.empty:
        raise RuntimeError("No paired observations")

    y = data["label_yes"].to_numpy(dtype=float)
    p_left = data[left].to_numpy(dtype=float)
    p_right = data[right].to_numpy(dtype=float)

    data["difference"] = (p_left - y) ** 2 - (p_right - y) ** 2

    market_differences = (
        data.groupby("condition_id")["difference"].mean().to_numpy(dtype=float)
    )

    rng = np.random.default_rng(SEED)
    n = len(market_differences)
    boot = np.empty(2000, dtype=float)

    for i in range(len(boot)):
        indices = rng.integers(0, n, size=n)
        boot[i] = market_differences[indices].mean()

    lower, upper = np.quantile(boot, [0.025, 0.975])

    return {
        "paired_rows": int(len(data)),
        "paired_markets": int(n),
        "equal_market_mean_brier_delta": float(market_differences.mean()),
        "bootstrap_95pct_interval": [
            float(lower),
            float(upper),
        ],
        "positive_means_left_worse": True,
    }


def run():
    if REPORT.exists() or PREDICTIONS.exists():
        raise FileExistsError("Comparison output already exists; refusing overwrite")

    df = base.load_dataset()
    partitions, partition_report = base.split_markets(df)

    train = partitions["train"]
    cal = partitions["calibration"]
    evaluation = partitions["evaluation"]

    models = {
        "hgb3": base.make_model(),
        "xgb": make_xgb(),
    }

    predictions = evaluation[
        [
            "condition_id",
            "prediction_timestamp",
            "target_horizon_seconds",
            "source_dataset",
            "label_yes",
            "normalized_yes_mid",
        ]
    ].copy()

    y = evaluation["label_yes"].to_numpy(dtype=int)

    results = {}
    horizon_results = {}

    for model_name, model in models.items():
        print(f"Training {model_name}...", flush=True)

        variants = model_variants(model, train, cal, evaluation)

        results[model_name] = {}

        for variant, probabilities in variants.items():
            column = f"{model_name}_{variant}"
            predictions[column] = probabilities
            results[model_name][variant] = base.metrics(y, probabilities)

        print(f"Finished {model_name}", flush=True)

    market = predictions["normalized_yes_mid"].to_numpy(dtype=float)
    common = np.isfinite(market)

    if common.sum() == 0:
        raise RuntimeError("No market baseline observations")

    paired_metrics = {"market": base.metrics(y[common], market[common])}

    for model_name in models:
        for variant in ("raw", "platt", "isotonic"):
            column = f"{model_name}_{variant}"
            paired_metrics[column] = base.metrics(
                y[common],
                predictions[column].to_numpy(dtype=float)[common],
            )

    for horizon in sorted(base.HORIZONS, reverse=True):
        subset = predictions.loc[predictions["target_horizon_seconds"] == horizon]

        labels = subset["label_yes"].to_numpy(dtype=int)
        horizon_results[str(horizon)] = {
            "markets": int(subset["condition_id"].nunique()),
            "market": base.metrics(
                labels[subset["normalized_yes_mid"].notna().to_numpy()],
                subset.loc[
                    subset["normalized_yes_mid"].notna(),
                    "normalized_yes_mid",
                ].to_numpy(dtype=float),
            ),
            "hgb3_raw": base.metrics(
                labels,
                subset["hgb3_raw"].to_numpy(dtype=float),
            ),
            "xgb_raw": base.metrics(
                labels,
                subset["xgb_raw"].to_numpy(dtype=float),
            ),
        }

    comparisons = {
        "xgb_raw_minus_hgb3_raw": paired_market_brier(
            predictions, "xgb_raw", "hgb3_raw"
        ),
        "hgb3_raw_minus_market": paired_market_brier(
            predictions, "hgb3_raw", "normalized_yes_mid"
        ),
        "xgb_raw_minus_market": paired_market_brier(
            predictions, "xgb_raw", "normalized_yes_mid"
        ),
    }

    report = {
        "run_version": "hgb3_xgb_expanded_v2_comparison_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": base.sha256(base.DATASET),
        "features": FEATURES,
        "seed": SEED,
        "partitions": partition_report,
        "models": {
            name: model.get_params(deep=False) for name, model in models.items()
        },
        "all_evaluation_rows": results,
        "paired_market_baseline_rows": {
            "rows": int(common.sum()),
            "markets": int(evaluation.loc[common, "condition_id"].nunique()),
            "metrics": paired_metrics,
        },
        "by_horizon": horizon_results,
        "paired_market_brier": comparisons,
        "interpretation": (
            "Retrospective development comparison of models "
            "trained on the chronological train partition. "
            "Not an evaluation of full-data refitted artifacts."
        ),
        "artifacts_saved": False,
        "production_approved": False,
    }

    predictions.to_csv(
        PREDICTIONS,
        index=False,
        mode="x",
    )

    report["predictions_sha256"] = base.sha256(PREDICTIONS)

    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("\nPaired evaluation:")
    print(json.dumps(paired_metrics, indent=2, sort_keys=True))

    print("\nEqual-market Brier differences:")
    print(json.dumps(comparisons, indent=2, sort_keys=True))

    print("\nReport:", REPORT)


if __name__ == "__main__":
    run()
