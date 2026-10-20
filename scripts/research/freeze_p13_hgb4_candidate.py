from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import sklearn

from run_p13_k2_model_feature_retest import (
    BLOCK_1_START,
    FEATURES_4,
    build_hgb,
    load_btc_context,
    load_development_rows,
    matrix,
)


ROOT = Path(__file__).resolve().parents[2]

MODEL_DIR = ROOT / "data" / "models"

MODEL_FILE = MODEL_DIR / "p13_hgb4_candidate_v1.joblib"

MANIFEST_FILE = MODEL_DIR / "p13_hgb4_candidate_v1.json"

MODEL_ID = "p13_hgb4_candidate_v1"


def sha256_file(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def main() -> None:
    context_rows = load_btc_context()

    rows = load_development_rows(context_rows)

    if not rows:
        raise RuntimeError("No eligible training rows found.")

    markets = {row["condition_id"] for row in rows}

    # Redundant safety assertion:
    # the K2 loader already enforces this.
    for row in rows:
        if row["prediction_timestamp"] >= BLOCK_1_START:
            raise RuntimeError(
                "BLOCK 1 LEAKAGE DETECTED: "
                f"{row['condition_id']} "
                f"{row['prediction_timestamp']}"
            )

    x, y = matrix(
        rows,
        FEATURES_4,
    )

    model = build_hgb()

    model.fit(
        x,
        y,
    )

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        model,
        MODEL_FILE,
    )

    model_hash = sha256_file(MODEL_FILE)

    prediction_times = [row["prediction_timestamp"] for row in rows]

    yes_count = int(y.sum())

    no_count = int(len(y) - yes_count)

    manifest = {
        "model_id": MODEL_ID,
        "status": ("candidate_not_production_frozen"),
        "created_at": (datetime.now(timezone.utc).isoformat()),
        "model_family": ("HistGradientBoostingClassifier"),
        "features": list(FEATURES_4),
        "feature_order_required": list(FEATURES_4),
        "feature_semantics": {
            "relative_distance_from_strike": ("(reference_price - strike) / strike"),
            "target_horizon_seconds": ("prediction horizon before market expiry"),
            "reference_return_30s": (
                "same-market reference return using P4 leakage-safe history semantics"
            ),
            "btc_return_1m": (
                "historical Bitstamp completed-minute "
                "BTC return; minute bar available only "
                "after completion"
            ),
        },
        "training": {
            "rows": int(len(rows)),
            "markets": int(len(markets)),
            "yes_labels": (yes_count),
            "no_labels": (no_count),
            "first_prediction_timestamp": (min(prediction_times).isoformat()),
            "last_prediction_timestamp": (max(prediction_times).isoformat()),
            "block1_start": (BLOCK_1_START.isoformat()),
            "block1_consumed": False,
            "block2_consumed": False,
        },
        "hyperparameters": {
            "learning_rate": 0.05,
            "max_iter": 200,
            "max_depth": 3,
            "l2_regularization": 1.0,
            "random_state": 1337,
        },
        "calibration": ("none"),
        "selection_evidence": {
            "experiment": ("P13-K2"),
            "walk_forward_rows": 8517,
            "hgb4_brier": (0.12057097436376296),
            "hgb4_log_loss": (0.37570452586575387),
            "hgb4_accuracy": (0.8278736644358342),
            "xgb4_brier": (0.12054448339807033),
            "xgb4_log_loss": (0.3756381258100122),
            "reason_selected": (
                "HGB4 and XGB4 were effectively tied; "
                "HGB4 retained for simpler sklearn-only "
                "runtime and dependency surface."
            ),
        },
        "known_limitation": (
            "Fourth feature was trained using historical "
            "Bitstamp btc_return_1m. Production-native "
            "RTDS/Chainlink minute returns have different "
            "distributional semantics and must receive "
            "fresh prospective validation before this "
            "candidate is promoted."
        ),
        "promotion_rule": (
            "Do not promote or use as P12 model. "
            "Validate later on untouched production-native "
            "prospective data before final P13 freeze."
        ),
        "software": {
            "sklearn_version": (sklearn.__version__),
            "serialization": ("joblib"),
        },
        "artifact": {
            "path": str(MODEL_FILE),
            "sha256": (model_hash),
        },
    }

    MANIFEST_FILE.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    # Reload immediately to verify artifact integrity.
    reloaded = joblib.load(MODEL_FILE)

    probe = reloaded.predict_proba(x[:10])

    if probe.shape != (
        min(10, len(rows)),
        2,
    ):
        raise RuntimeError("Reloaded model produced unexpected prediction shape.")

    print("P13 HGB4 candidate preserved")

    print()

    print(
        "model_id=",
        MODEL_ID,
    )

    print("status=candidate_not_production_frozen")

    print()

    print(
        "training_rows=",
        len(rows),
    )

    print(
        "training_markets=",
        len(markets),
    )

    print(
        "yes_labels=",
        yes_count,
    )

    print(
        "no_labels=",
        no_count,
    )

    print()

    print(
        "first_prediction_timestamp=",
        min(prediction_times).isoformat(),
    )

    print(
        "last_prediction_timestamp=",
        max(prediction_times).isoformat(),
    )

    print(
        "block1_start=",
        BLOCK_1_START.isoformat(),
    )

    print()

    print("BLOCK 1 CONSUMED=False")

    print("BLOCK 2 CONSUMED=False")

    print()

    print("features=")

    for feature in FEATURES_4:
        print(
            " ",
            feature,
        )

    print()

    print(
        "model=",
        MODEL_FILE,
    )

    print(
        "manifest=",
        MANIFEST_FILE,
    )

    print(
        "sha256=",
        model_hash,
    )

    print()

    print("reload_check=PASS")


if __name__ == "__main__":
    main()
