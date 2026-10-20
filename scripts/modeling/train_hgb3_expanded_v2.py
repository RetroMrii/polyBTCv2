from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


ROOT = Path(__file__).resolve().parents[2]

BASE = ROOT / "data/experiments/model_expansion/vm_expansion_v2"

DATASET = BASE / "hgb3_expanded_v2.csv"
DATASET_REPORT = BASE / "hgb3_expanded_v2_report.json"

REPORT = BASE / "hgb3_expanded_v2_training_report.json"
PREDICTIONS = BASE / "hgb3_expanded_v2_evaluation_predictions.csv"

MODEL_ID = "hgb3_expanded_v2"
MODEL_DIR = ROOT / "data/models/challengers"
ARTIFACT = MODEL_DIR / f"{MODEL_ID}.joblib"
MANIFEST = MODEL_DIR / f"{MODEL_ID}.json"

FEATURES = [
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
]

HORIZONS = {240, 180, 120, 90, 60, 30}
SEED = 1337


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def make_model():
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=200,
        max_depth=3,
        l2_regularization=1.0,
        random_state=SEED,
    )


def clipped(values):
    return np.clip(
        np.asarray(values, dtype=float),
        1e-15,
        1.0 - 1e-15,
    )


def logit(values):
    p = clipped(values)
    return np.log(p / (1.0 - p))


def metrics(y, probabilities):
    p = clipped(probabilities)
    y = np.asarray(y, dtype=int)

    if len(y) == 0:
        return None

    return {
        "rows": int(len(y)),
        "accuracy": float(np.mean((p >= 0.5) == y)),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(-(y * np.log(p) + (1 - y) * np.log1p(-p)))),
    }


def market_weights(df):
    counts = (
        df.groupby("condition_id")["condition_id"]
        .transform("size")
        .to_numpy(dtype=float)
    )
    return 1.0 / counts


def load_dataset():
    if not DATASET.is_file() or not DATASET_REPORT.is_file():
        raise FileNotFoundError("Expanded v2 dataset missing")

    manifest = json.loads(DATASET_REPORT.read_text(encoding="utf-8"))

    if manifest.get("dataset_version") != MODEL_ID:
        raise RuntimeError("Unexpected dataset version")

    expected_hash = manifest.get("source_sha256", {}).get("existing_hgb3_dataset")

    if not expected_hash:
        raise RuntimeError("Missing source provenance")

    df = pd.read_csv(DATASET, dtype={"condition_id": "string"})

    required = set(FEATURES) | {
        "condition_id",
        "prediction_timestamp",
        "snapshot_observed_at",
        "label_yes",
        "source_dataset",
        "normalized_yes_mid",
    }

    if not required.issubset(df.columns):
        raise RuntimeError(f"Missing columns: {sorted(required - set(df.columns))}")

    df["condition_id"] = df["condition_id"].str.strip().str.lower()

    if df["condition_id"].isna().any() or (df["condition_id"].str.len() == 0).any():
        raise RuntimeError("Invalid market IDs")

    for column in (
        "prediction_timestamp",
        "snapshot_observed_at",
    ):
        df[column] = pd.to_datetime(df[column], utc=True, errors="coerce")
        if df[column].isna().any():
            raise RuntimeError(f"Invalid {column}")

    if (df["snapshot_observed_at"] > df["prediction_timestamp"]).any():
        raise RuntimeError("Future snapshot detected")

    for column in FEATURES + ["label_yes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if not np.isfinite(df[FEATURES].to_numpy(dtype=float)).all():
        raise RuntimeError("Missing/nonfinite features")

    if not df["label_yes"].isin([0, 1]).all():
        raise RuntimeError("Invalid labels")

    if not df["target_horizon_seconds"].isin(HORIZONS).all():
        raise RuntimeError("Unexpected horizon")

    if df.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate market/horizon")

    if (df.groupby("condition_id")["label_yes"].nunique() != 1).any():
        raise RuntimeError("Conflicting market labels")

    if (df.groupby("condition_id")["source_dataset"].nunique() != 1).any():
        raise RuntimeError("Mixed provenance within market")

    df["label_yes"] = df["label_yes"].astype(int)

    df["normalized_yes_mid"] = pd.to_numeric(df["normalized_yes_mid"], errors="coerce")

    p = df["normalized_yes_mid"]

    if (p.notna() & ~p.between(0, 1)).any():
        raise RuntimeError("Invalid market probabilities")

    stats = manifest["statistics"]

    if len(df) != stats["total_rows"]:
        raise RuntimeError("Dataset row count mismatch")

    if df["condition_id"].nunique() != stats["total_markets"]:
        raise RuntimeError("Dataset market count mismatch")

    return df


def split_markets(df):
    markets = (
        df.groupby("condition_id", as_index=False)
        .agg(
            first=("prediction_timestamp", "min"),
            last=("prediction_timestamp", "max"),
        )
        .sort_values(["first", "condition_id"])
        .reset_index(drop=True)
    )

    n = len(markets)

    if n < 500:
        raise RuntimeError("Insufficient markets")

    a = int(n * 0.60)
    b = int(n * 0.80)

    groups = {
        "train": markets.iloc[:a],
        "calibration": markets.iloc[a:b],
        "evaluation": markets.iloc[b:],
    }

    if not (
        groups["train"]["last"].max() < groups["calibration"]["first"].min()
        and groups["calibration"]["last"].max() < groups["evaluation"]["first"].min()
    ):
        raise RuntimeError("Chronological partition overlap")

    partitions = {}
    summary = {}

    for name, group in groups.items():
        part = df.loc[df["condition_id"].isin(group["condition_id"])].copy()

        part = part.sort_values(
            [
                "prediction_timestamp",
                "condition_id",
                "target_horizon_seconds",
            ]
        ).reset_index(drop=True)

        partitions[name] = part

        summary[name] = {
            "markets": int(group.shape[0]),
            "rows": int(len(part)),
            "first_prediction": group["first"].min().isoformat(),
            "last_prediction": group["last"].max().isoformat(),
            "sources": part.groupby("source_dataset")["condition_id"]
            .nunique()
            .to_dict(),
        }

    return partitions, summary


def evaluate_candidate(parts):
    train = parts["train"]
    cal = parts["calibration"]
    evaluation = parts["evaluation"]

    for name, part in parts.items():
        if part["label_yes"].nunique() != 2:
            raise RuntimeError(f"Single-class {name} partition")

    model = make_model()

    model.fit(
        train[FEATURES].to_numpy(dtype=float),
        train["label_yes"].to_numpy(dtype=int),
    )

    raw_cal = model.predict_proba(cal[FEATURES].to_numpy(dtype=float))[:, 1]

    weights = market_weights(cal)
    y_cal = cal["label_yes"].to_numpy(dtype=int)

    platt = LogisticRegression(
        solver="lbfgs",
        max_iter=2000,
        random_state=SEED,
    )
    platt.fit(
        logit(raw_cal).reshape(-1, 1),
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

    raw_eval = model.predict_proba(evaluation[FEATURES].to_numpy(dtype=float))[:, 1]

    variants = {
        "raw": clipped(raw_eval),
        "platt": clipped(platt.predict_proba(logit(raw_eval).reshape(-1, 1))[:, 1]),
        "isotonic": clipped(isotonic.predict(raw_eval)),
    }

    y_eval = evaluation["label_yes"].to_numpy(dtype=int)

    result = {name: metrics(y_eval, values) for name, values in variants.items()}

    market = evaluation["normalized_yes_mid"].to_numpy(dtype=float)
    common = np.isfinite(market)

    paired = {
        "rows": int(common.sum()),
        "markets": int(evaluation.loc[common, "condition_id"].nunique()),
        "market": metrics(y_eval[common], market[common]),
        "model": {
            name: metrics(y_eval[common], values[common])
            for name, values in variants.items()
        },
    }

    predictions = evaluation[
        [
            "condition_id",
            "prediction_timestamp",
            "target_horizon_seconds",
            "label_yes",
            "normalized_yes_mid",
            "source_dataset",
        ]
    ].copy()

    for name, values in variants.items():
        predictions[f"hgb3_{name}"] = values

    return result, paired, predictions


def run():
    for path in (ARTIFACT, MANIFEST, REPORT, PREDICTIONS):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite: {path}")

    df = load_dataset()
    parts, split = split_markets(df)

    results, paired, predictions = evaluate_candidate(parts)

    # This is the actual expanded all-data candidate.
    # Do not describe retrospective evaluation scores
    # as performance of this full-data refit.
    final_model = make_model()
    final_model.fit(
        df[FEATURES].to_numpy(dtype=float),
        df["label_yes"].to_numpy(dtype=int),
    )

    probe = df[FEATURES].head(20).to_numpy(dtype=float)
    expected = final_model.predict_proba(probe)[:, 1]

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    joblib.dump(final_model, ARTIFACT)

    restored = joblib.load(ARTIFACT)
    actual = restored.predict_proba(probe)[:, 1]

    if not np.allclose(expected, actual, atol=1e-12, rtol=0):
        ARTIFACT.unlink(missing_ok=True)
        raise RuntimeError("Serialization mismatch")

    metadata = {
        "model_version": MODEL_ID,
        "status": "frozen_research_candidate_not_approved",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_class": type(final_model).__name__,
        "features": FEATURES,
        "feature_order_locked": True,
        "probability_variant": "raw",
        "seed": SEED,
        "model_params": final_model.get_params(deep=False),
        "training_dataset": str(DATASET.relative_to(ROOT)),
        "training_dataset_sha256": sha256(DATASET),
        "training_rows": len(df),
        "training_markets": int(df["condition_id"].nunique()),
        "first_training_timestamp": (df["prediction_timestamp"].min().isoformat()),
        "last_training_timestamp": (df["prediction_timestamp"].max().isoformat()),
        "training_source_markets": (
            df.groupby("source_dataset")["condition_id"].nunique().to_dict()
        ),
        "evaluation_reference": str(REPORT.relative_to(ROOT)),
        "evaluation_predictions_reference": str(PREDICTIONS.relative_to(ROOT)),
        "full_data_refit": True,
        "production_approved": False,
        "calibration_attached": False,
        "evaluation_status": (
            "Retrospective development model evaluation; "
            "not an independent evaluation of the "
            "full-data refitted artifact"
        ),
    }

    report = {
        "run_version": "hgb3_expanded_v2_training_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": sha256(DATASET),
        "features": FEATURES,
        "partition_method": ("chronological market-grouped 60/20/20"),
        "partitions": split,
        "retrospective_evaluation": results,
        "paired_market_comparison": paired,
        "saved_artifact": str(ARTIFACT.relative_to(ROOT)),
        "artifact_sha256": sha256(ARTIFACT),
        "full_data_model_evaluated_independently": False,
        "production_approved": False,
    }

    predictions.to_csv(PREDICTIONS, index=False, mode="x")

    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    MANIFEST.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    run()
