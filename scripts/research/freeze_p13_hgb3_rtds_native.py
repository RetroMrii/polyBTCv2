from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from run_p13_rtds_native_walkforward import (
    INPUT,
    FEATURES3,
    load_dataset,
    make_hgb,
)

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "models"

OUTPUT_MODEL = MODELS / "p13_hgb3_rtds_native_v1.joblib"
OUTPUT_META = MODELS / "p13_hgb3_rtds_native_v1.json"

MODEL_VERSION = "p13_hgb3_rtds_native_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if OUTPUT_MODEL.exists() or OUTPUT_META.exists():
        raise FileExistsError("Candidate already frozen. Refusing to overwrite.")

    df = load_dataset()

    if df["condition_id"].nunique() != 1382:
        raise RuntimeError(
            "Expected 1382 complete RTDS markets. "
            "The dataset has changed; inspect before freezing."
        )

    x = df[FEATURES3].to_numpy(dtype=float)
    y = df["label_yes"].to_numpy(dtype=int)

    if not np.isfinite(x).all():
        raise RuntimeError("Nonfinite training features.")

    if np.unique(y).tolist() != [0, 1]:
        raise RuntimeError("Invalid or single-class labels.")

    if df["market_end_at"].isna().any():
        raise RuntimeError("Missing market end timestamps.")

    model = make_hgb()
    model.fit(x, y)

    probe = model.predict_proba(x[:10])[:, 1]
    if not np.isfinite(probe).all():
        raise RuntimeError("Invalid fitted probabilities.")

    MODELS.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, OUTPUT_MODEL)

    saved_model = joblib.load(OUTPUT_MODEL)
    restored = saved_model.predict_proba(x[:10])[:, 1]

    if not np.allclose(probe, restored, rtol=0, atol=1e-12):
        OUTPUT_MODEL.unlink(missing_ok=True)
        raise RuntimeError("Saved model verification failed.")

    metadata = {
        "model_version": MODEL_VERSION,
        "status": "frozen_research_candidate",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_source": str(INPUT.relative_to(ROOT)),
        "training_source_sha256": sha256(INPUT),
        "features": list(FEATURES3),
        "feature_order_locked": True,
        "model_class": type(model).__name__,
        "model_params": model.get_params(),
        "training_rows": int(len(df)),
        "training_markets": int(df["condition_id"].nunique()),
        "first_prediction_timestamp": (df["prediction_timestamp"].min().isoformat()),
        "last_prediction_timestamp": (df["prediction_timestamp"].max().isoformat()),
        "last_market_end_at": (df["market_end_at"].max().isoformat()),
        "label_version": "p3_v1",
        "frozen_model_sha256": sha256(OUTPUT_MODEL),
        "evaluation_reference": ("p13_rtds_native_walkforward_report.json"),
        "evaluation_status": (
            "exploratory chronological out-of-sample; "
            "full-data artifact itself has no untouched test"
        ),
        "production_approved": False,
        "calibrated": False,
    }

    OUTPUT_META.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("HGB3 RTDS CANDIDATE FROZEN")
    print("version=", MODEL_VERSION)
    print("rows=", len(df))
    print("markets=", df["condition_id"].nunique())
    print("last_market_end=", metadata["last_market_end_at"])
    print("sha256=", metadata["frozen_model_sha256"])
    print("model=", OUTPUT_MODEL)
    print("metadata=", OUTPUT_META)


if __name__ == "__main__":
    main()
