from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "experiments" / "model_expansion"

INPUT = BASE / "hgb3_expanded_v1.csv"
INPUT_REPORT = BASE / "hgb3_expanded_v1_report.json"

OUTPUT_REPORT = BASE / "hgb3_expanded_calibration_v1_report.json"
OUTPUT_PREDICTIONS = BASE / "hgb3_expanded_calibration_v1_predictions.csv"

RUN_VERSION = "hgb3_expanded_calibration_v1"
SEED = 1337

FEATURES = [
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
]

HORIZONS = {240, 180, 120, 90, 60, 30}
EPS = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clipped(probabilities):
    return np.clip(
        np.asarray(probabilities, dtype=float),
        EPS,
        1.0 - EPS,
    )


def logit(probabilities):
    p = clipped(probabilities)
    return np.log(p / (1.0 - p))


def scores(y, probabilities) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.asarray(probabilities, dtype=float)

    if len(y) == 0:
        return {"rows": 0}

    if not np.isfinite(p).all():
        raise RuntimeError("Nonfinite model probabilities")

    if np.any((p < 0) | (p > 1)):
        raise RuntimeError("Probability outside [0,1]")

    p = clipped(p)

    return {
        "rows": int(len(y)),
        "positive_rate": float(np.mean(y)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "mean_probability": float(np.mean(p)),
    }


def reliability(y, probabilities, bins=10):
    y = np.asarray(y, dtype=int)
    p = np.asarray(probabilities, dtype=float)

    result = []

    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins

        if index == bins - 1:
            mask = (p >= lower) & (p <= upper)
        else:
            mask = (p >= lower) & (p < upper)

        count = int(mask.sum())

        result.append(
            {
                "lower": lower,
                "upper": upper,
                "rows": count,
                "mean_predicted": (float(p[mask].mean()) if count else None),
                "observed_yes_rate": (float(y[mask].mean()) if count else None),
            }
        )

    return result


def load_data():
    if not INPUT.exists() or not INPUT_REPORT.exists():
        raise FileNotFoundError("Expanded dataset or its manifest is missing")

    with INPUT_REPORT.open("r", encoding="utf-8") as file:
        manifest = json.load(file)

    if manifest.get("dataset_version") != "hgb3_expanded_v1":
        raise RuntimeError("Unexpected input dataset version")

    if manifest.get("features") != FEATURES:
        raise RuntimeError("Feature contract mismatch")

    if sha256(INPUT) != manifest.get("output_sha256"):
        raise RuntimeError("Input dataset SHA-256 mismatch")

    df = pd.read_csv(
        INPUT,
        dtype={"condition_id": "string"},
    )

    required = set(FEATURES) | {
        "condition_id",
        "prediction_timestamp",
        "snapshot_observed_at",
        "label_yes",
        "source_dataset",
        "normalized_yes_mid",
    }

    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"Missing dataset columns: {sorted(missing)}")

    df["condition_id"] = df["condition_id"].str.strip().str.lower()

    if df["condition_id"].isna().any():
        raise RuntimeError("Missing condition IDs")

    if (df["condition_id"].str.len() == 0).any():
        raise RuntimeError("Empty condition IDs")

    for name in [
        "prediction_timestamp",
        "snapshot_observed_at",
    ]:
        df[name] = pd.to_datetime(df[name], utc=True, errors="coerce")

        if df[name].isna().any():
            raise RuntimeError(f"Invalid {name}")

    if (df["snapshot_observed_at"] > df["prediction_timestamp"]).any():
        raise RuntimeError("Future snapshot detected")

    for column in FEATURES + ["label_yes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if not np.isfinite(df[FEATURES].to_numpy(dtype=float)).all():
        raise RuntimeError("Missing or nonfinite features")

    if not df["label_yes"].isin([0, 1]).all():
        raise RuntimeError("Invalid binary labels")

    df["label_yes"] = df["label_yes"].astype(int)

    if not df["target_horizon_seconds"].isin(HORIZONS).all():
        raise RuntimeError("Unexpected prediction horizon")

    if df.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate market/horizon rows")

    label_counts = df.groupby("condition_id")["label_yes"].nunique()

    if (label_counts != 1).any():
        raise RuntimeError("Conflicting market labels")

    source_counts = df.groupby("condition_id")["source_dataset"].nunique()

    if (source_counts != 1).any():
        raise RuntimeError("A market appears in multiple sources")

    if df["source_dataset"].isna().any():
        raise RuntimeError("Missing source provenance")

    if len(df) != manifest["eligible_rows"]:
        raise RuntimeError("Dataset row count mismatch")

    if df["condition_id"].nunique() != manifest["eligible_markets"]:
        raise RuntimeError("Dataset market count mismatch")

    df["normalized_yes_mid"] = pd.to_numeric(df["normalized_yes_mid"], errors="coerce")

    market_p = df["normalized_yes_mid"]
    if (market_p.notna() & ~market_p.between(0, 1)).any():
        raise RuntimeError("Invalid market probability")

    return df, manifest


def split_markets(df):
    markets = (
        df.groupby("condition_id", as_index=False)
        .agg(
            first_prediction=("prediction_timestamp", "min"),
            last_prediction=("prediction_timestamp", "max"),
        )
        .sort_values(["first_prediction", "condition_id"])
        .reset_index(drop=True)
    )

    n = len(markets)

    if n < 500:
        raise RuntimeError("Insufficient markets")

    train_end = int(n * 0.60)
    calibration_end = int(n * 0.80)

    train_m = markets.iloc[:train_end]
    calibration_m = markets.iloc[train_end:calibration_end]
    evaluation_m = markets.iloc[calibration_end:]

    if not (
        train_m["last_prediction"].max() < calibration_m["first_prediction"].min()
        and calibration_m["last_prediction"].max()
        < evaluation_m["first_prediction"].min()
    ):
        raise RuntimeError("Chronological partitions overlap in time")

    partitions = {}

    for name, subset in [
        ("train", train_m),
        ("calibration", calibration_m),
        ("evaluation", evaluation_m),
    ]:
        ids = set(subset["condition_id"])

        part = df.loc[df["condition_id"].isin(ids)].copy()

        part = part.sort_values(
            [
                "prediction_timestamp",
                "condition_id",
                "target_horizon_seconds",
            ],
            ascending=[True, True, False],
        ).reset_index(drop=True)

        partitions[name] = part

    def describe(name, subset):
        return {
            "markets": int(len(subset)),
            "rows": int(len(partitions[name])),
            "first_prediction": (subset["first_prediction"].min().isoformat()),
            "last_prediction": (subset["last_prediction"].max().isoformat()),
            "sources": (
                partitions[name]
                .groupby("source_dataset")["condition_id"]
                .nunique()
                .to_dict()
            ),
        }

    split_report = {
        "split_method": (
            "chronological market-grouped 60/20/20; "
            "ordered by first prediction timestamp"
        ),
        "train": describe("train", train_m),
        "calibration": describe("calibration", calibration_m),
        "evaluation": describe("evaluation", evaluation_m),
    }

    return partitions, split_report


def make_models():
    models = {
        "logistic": make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=2000,
                solver="lbfgs",
                random_state=SEED,
            ),
        ),
        "hgb3": HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=200,
            max_depth=3,
            l2_regularization=1.0,
            random_state=SEED,
        ),
    }

    xgboost_status = {
        "available": False,
        "reason": "not installed",
    }

    try:
        from xgboost import XGBClassifier
    except ImportError:
        return models, xgboost_status

    models["xgboost"] = XGBClassifier(
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

    xgboost_status = {
        "available": True,
        "reason": None,
    }

    return models, xgboost_status


def market_balanced_weights(df):
    # All snapshots of one market share one label.
    counts = (
        df.groupby("condition_id")["condition_id"]
        .transform("size")
        .to_numpy(dtype=float)
    )

    return 1.0 / counts


def fit_calibrators(raw, y, weights):
    z = logit(raw).reshape(-1, 1)

    platt = LogisticRegression(
        solver="lbfgs",
        max_iter=2000,
        random_state=SEED,
    )

    platt.fit(
        z,
        y,
        sample_weight=weights,
    )

    isotonic = IsotonicRegression(
        y_min=0.0,
        y_max=1.0,
        increasing=True,
        out_of_bounds="clip",
    )

    isotonic.fit(
        raw,
        y,
        sample_weight=weights,
    )

    return platt, isotonic


def calibrated_probabilities(raw, platt, isotonic):
    return {
        "raw": clipped(raw),
        "platt": clipped(platt.predict_proba(logit(raw).reshape(-1, 1))[:, 1]),
        "isotonic": clipped(isotonic.predict(raw)),
    }


def report_variants(df, variants):
    y = df["label_yes"].to_numpy(dtype=int)

    results = {}

    for variant, p in variants.items():
        results[variant] = {
            "metrics": scores(y, p),
            "reliability_bins": reliability(y, p),
        }

    return results


def subset_metrics(df, variants, mask):
    y = df.loc[mask, "label_yes"].to_numpy(dtype=int)

    output = {}

    for name, p in variants.items():
        output[name] = scores(y, p[mask])

    return output


def evaluate_details(df, variants):
    result = {
        "all_rows": {},
        "market_probability_common_rows": {},
        "by_horizon": {},
        "by_source": {},
    }

    y = df["label_yes"].to_numpy(dtype=int)

    result["all_rows"] = report_variants(df, variants)

    market = df["normalized_yes_mid"].to_numpy(dtype=float)
    common = np.isfinite(market)

    result["market_probability_common_rows"] = {
        "market_rows": int(common.sum()),
        "market_markets": int(df.loc[common, "condition_id"].nunique()),
        "market_probability": scores(y[common], market[common]),
        "model_variants": subset_metrics(df, variants, common),
    }

    horizons = sorted(
        df["target_horizon_seconds"].unique(),
        reverse=True,
    )

    for horizon in horizons:
        mask = df["target_horizon_seconds"].to_numpy() == horizon

        key = str(int(horizon))

        result["by_horizon"][key] = {
            "markets": int(df.loc[mask, "condition_id"].nunique()),
            "variants": subset_metrics(df, variants, mask),
        }

    for source in sorted(df["source_dataset"].unique()):
        mask = df["source_dataset"].to_numpy() == source

        result["by_source"][str(source)] = {
            "markets": int(df.loc[mask, "condition_id"].nunique()),
            "variants": subset_metrics(df, variants, mask),
        }

    return result


def main():
    if OUTPUT_REPORT.exists() or OUTPUT_PREDICTIONS.exists():
        raise FileExistsError(
            "Calibration outputs already exist. "
            "Use a new run version; refusing overwrite."
        )

    df, input_manifest = load_data()

    partitions, split_report = split_markets(df)

    train = partitions["train"]
    calibration = partitions["calibration"]
    evaluation = partitions["evaluation"]

    x_train = train[FEATURES].to_numpy(dtype=float)
    y_train = train["label_yes"].to_numpy(dtype=int)

    x_cal = calibration[FEATURES].to_numpy(dtype=float)
    y_cal = calibration["label_yes"].to_numpy(dtype=int)

    x_eval = evaluation[FEATURES].to_numpy(dtype=float)

    if len(np.unique(y_train)) != 2:
        raise RuntimeError("Single-class training set")

    if len(np.unique(y_cal)) != 2:
        raise RuntimeError("Single-class calibration set")

    cal_weights = market_balanced_weights(calibration)

    models, xgboost_status = make_models()

    report = {
        "run_version": RUN_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dataset_version": (input_manifest["dataset_version"]),
        "input_sha256": sha256(INPUT),
        "features": FEATURES,
        "seed": SEED,
        "partitions": split_report,
        "xgboost": xgboost_status,
        "reference_provider_status": ("unverified_per_source"),
        "calibration": {
            "primary_candidate": "platt",
            "alternative": "isotonic",
            "fitting_population": ("chronological calibration partition"),
            "weighting": ("one total weight per market"),
            "platt_input": "logit(raw_probability)",
        },
        "results": {},
        "model_artifacts_saved": False,
        "production_approved": False,
        "evaluation_status": (
            "retrospective chronological evaluation; "
            "not an untouched prospective holdout"
        ),
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

    for name, model in models.items():
        print(f"\nTraining {name}...", flush=True)

        model.fit(x_train, y_train)

        raw_cal = model.predict_proba(x_cal)[:, 1]

        raw_eval = model.predict_proba(x_eval)[:, 1]

        platt, isotonic = fit_calibrators(
            raw_cal,
            y_cal,
            cal_weights,
        )

        variants_cal = calibrated_probabilities(raw_cal, platt, isotonic)

        variants_eval = calibrated_probabilities(raw_eval, platt, isotonic)

        report["results"][name] = {
            "model_class": (type(model).__name__),
            "model_params": {
                key: (
                    value
                    if isinstance(value, (str, int, float, bool, type(None)))
                    else repr(value)
                )
                for key, value in model.get_params(deep=False).items()
            },
            "calibration_partition": (report_variants(calibration, variants_cal)),
            "evaluation": evaluate_details(evaluation, variants_eval),
            "platt_parameters": {
                "coefficient": float(platt.coef_[0, 0]),
                "intercept": float(platt.intercept_[0]),
            },
        }

        for variant, values in variants_eval.items():
            predictions[f"{name}_{variant}"] = values

        metrics = report["results"][name]["evaluation"]["all_rows"]

        for variant in ("raw", "platt", "isotonic"):
            m = metrics[variant]["metrics"]
            print(f"  {variant}: Brier={m['brier']:.8f} LogLoss={m['log_loss']:.8f}")

    BASE.mkdir(parents=True, exist_ok=True)

    # Report first; only completed reports are useful.
    # Existing outputs are never silently overwritten.
    report["prediction_rows"] = int(len(predictions))
    report["prediction_markets"] = int(predictions["condition_id"].nunique())
    report["output_predictions"] = str(OUTPUT_PREDICTIONS.relative_to(ROOT))

    predictions.to_csv(
        OUTPUT_PREDICTIONS,
        index=False,
        mode="x",
    )

    report["output_predictions_sha256"] = sha256(OUTPUT_PREDICTIONS)

    with OUTPUT_REPORT.open("x", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    print("\nEXPANDED MODEL CALIBRATION COMPLETE")
    print(
        "train_markets=",
        split_report["train"]["markets"],
    )
    print(
        "calibration_markets=",
        split_report["calibration"]["markets"],
    )
    print(
        "evaluation_markets=",
        split_report["evaluation"]["markets"],
    )
    print("models=", list(report["results"]))
    print("report=", OUTPUT_REPORT)
    print("predictions=", OUTPUT_PREDICTIONS)


if __name__ == "__main__":
    main()
