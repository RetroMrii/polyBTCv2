from __future__ import annotations

import csv
import json

from datetime import datetime
from pathlib import Path

import joblib
import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

MODEL_DIR = ROOT / "data" / "models"

MODEL_FILE = MODEL_DIR / "p12_shadow_model_v1.joblib"

METADATA_FILE = MODEL_DIR / "p12_shadow_model_v1.json"


MODEL_VERSION = "p12_shadow_model_v1"

RESEARCH_CUTOFF = "2026-10-01T17:09:30+00:00"

FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


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


def make_pipeline() -> Pipeline:
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


def main() -> None:
    rows = load_csv(P4_FILE)

    cutoff = parse_timestamp(RESEARCH_CUTOFF)

    training_rows = []

    excluded_after_cutoff = 0
    excluded_missing_feature = 0

    for row in rows:
        prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

        if prediction_timestamp > cutoff:
            excluded_after_cutoff += 1
            continue

        relative_distance = optional_float(row.get("relative_distance_from_strike"))

        reference_return_30s = optional_float(row.get("reference_return_30s"))

        if relative_distance is None or reference_return_30s is None:
            excluded_missing_feature += 1
            continue

        training_rows.append(row)

    if not training_rows:
        raise RuntimeError("no usable P12 training rows")

    x = np.array(
        [
            [
                float(row["relative_distance_from_strike"]),
                float(row["target_horizon_seconds"]),
                float(row["reference_return_30s"]),
            ]
            for row in training_rows
        ],
        dtype=float,
    )

    y = np.array(
        [int(row["label_yes"]) for row in training_rows],
        dtype=int,
    )

    model = make_pipeline()

    model.fit(
        x,
        y,
    )

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        {
            "model_version": (MODEL_VERSION),
            "research_cutoff": (RESEARCH_CUTOFF),
            "features": (list(FEATURES)),
            "pipeline": (model),
        },
        MODEL_FILE,
    )

    markets = {row["condition_id"].strip().lower() for row in training_rows}

    labels = [int(row["label_yes"]) for row in training_rows]

    metadata = {
        "model_version": (MODEL_VERSION),
        "research_cutoff": (RESEARCH_CUTOFF),
        "features": list(FEATURES),
        "training_rows": len(training_rows),
        "training_markets": len(markets),
        "yes_rows": sum(labels),
        "no_rows": (len(labels) - sum(labels)),
        "excluded_after_cutoff": (excluded_after_cutoff),
        "excluded_missing_feature": (excluded_missing_feature),
        "pipeline": (
            "StandardScaler + LogisticRegression(max_iter=1000, solver=lbfgs)"
        ),
        "calibration": "none",
        "purpose": ("Fixed P12 prospective shadow-model artifact."),
        "important_notes": [
            (
                "All observations through the "
                "research cutoff are treated as "
                "research/training data."
            ),
            (
                "This artifact must not be retrained "
                "during the P12 prospective shadow period."
            ),
            (
                "The model provides independent BTC "
                "confirmation and is not itself an "
                "order-placement strategy."
            ),
        ],
    }

    METADATA_FILE.write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P12 shadow model frozen")

    print(
        "model_version=",
        MODEL_VERSION,
    )

    print(
        "research_cutoff=",
        RESEARCH_CUTOFF,
    )

    print(
        "training_rows=",
        len(training_rows),
    )

    print(
        "training_markets=",
        len(markets),
    )

    print(
        "excluded_missing_feature=",
        excluded_missing_feature,
    )

    print(
        "excluded_after_cutoff=",
        excluded_after_cutoff,
    )

    print()

    print(f"Wrote {MODEL_FILE}")

    print(f"Wrote {METADATA_FILE}")


if __name__ == "__main__":
    main()
