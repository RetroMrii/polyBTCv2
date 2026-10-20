from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np


EXPECTED_MODEL_VERSION = "hgb3_expanded_v1"
EXPECTED_CALIBRATION_VERSION = "identity_v1"
SUPPORTED_MODEL_ROLES = {
    "hgb3_expanded_v1": "main",
    "hgb3_expanded_v2": "challengers",
}

EXPECTED_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

ALLOWED_HORIZONS = frozenset({240, 180, 120, 90, 60, 30})


@dataclass(frozen=True, slots=True)
class PredictionResult:
    model_version: str
    calibration_version: str
    probability_yes: float
    probability_no: float


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def validated_number(
    name: str,
    value: Any,
) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be numeric")

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be numeric") from exc

    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")

    return number


class FrozenProbabilityModel:
    """Read-only probability inference for one frozen model."""

    def __init__(
        self,
        model_path: Path,
        metadata_path: Path | None = None,
    ) -> None:
        model_path = Path(model_path)

        if metadata_path is None:
            metadata_path = model_path.with_suffix(".json")

        metadata_path = Path(metadata_path)

        if not model_path.is_file():
            raise FileNotFoundError(model_path)

        if not metadata_path.is_file():
            raise FileNotFoundError(metadata_path)

        with metadata_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            metadata = json.load(file)

        if not isinstance(metadata, dict):
            raise RuntimeError("Invalid model metadata")

        model_version = metadata.get("model_version")

        if model_version not in SUPPORTED_MODEL_ROLES:
            raise RuntimeError("Unexpected model version")

        expected_role = SUPPORTED_MODEL_ROLES[model_version]

        if metadata.get("role") != expected_role:
            raise RuntimeError("Artifact role mismatch")

        if metadata.get("features") != list(EXPECTED_FEATURES):
            raise RuntimeError("Model feature contract mismatch")

        if metadata.get("feature_order_locked") is not True:
            raise RuntimeError("Model feature order is not locked")

        if metadata.get("model_class") != "HistGradientBoostingClassifier":
            raise RuntimeError("Unexpected model class in metadata")

        calibration = metadata.get("calibration_policy")

        if not isinstance(calibration, dict):
            raise RuntimeError("Missing calibration policy")

        if (
            calibration.get("version") != EXPECTED_CALIBRATION_VERSION
            or calibration.get("method") != "identity"
            or calibration.get("fitted") is not False
            or calibration.get("output") != "raw_predict_proba_yes"
        ):
            raise RuntimeError("Unsupported calibration policy")

        expected_hash = metadata.get("frozen_model_sha256")

        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise RuntimeError("Missing or invalid model checksum")

        actual_hash = file_sha256(model_path)

        if actual_hash != expected_hash:
            raise RuntimeError("Model SHA-256 mismatch")

        # joblib uses pickle internally. Load only
        # project-controlled, trusted artifacts.
        model = joblib.load(model_path)

        if type(model).__name__ != "HistGradientBoostingClassifier":
            raise RuntimeError("Loaded estimator has wrong model class")

        if not callable(getattr(model, "predict_proba", None)):
            raise RuntimeError("Loaded estimator lacks predict_proba")

        classes = np.asarray(
            getattr(model, "classes_", []),
        )

        if not np.array_equal(
            classes,
            np.array([0, 1]),
        ):
            raise RuntimeError("Unexpected model class ordering")

        self._model = model
        self.model_version = model_version
        self.calibration_version = EXPECTED_CALIBRATION_VERSION
        self.model_sha256 = actual_hash
        self.feature_names = EXPECTED_FEATURES

    def predict(
        self,
        features: Mapping[str, Any],
    ) -> PredictionResult:
        if not isinstance(features, Mapping):
            raise TypeError("Features must be a mapping")

        expected = set(EXPECTED_FEATURES)
        received = set(features.keys())

        missing = expected - received
        extra = received - expected

        if missing or extra:
            raise ValueError(
                "Feature contract mismatch: "
                f"missing={sorted(missing)}, "
                f"extra={sorted(extra)}"
            )

        values = [
            validated_number(
                name,
                features[name],
            )
            for name in EXPECTED_FEATURES
        ]

        horizon = values[1]

        if horizon not in ALLOWED_HORIZONS:
            raise ValueError(f"Unsupported prediction horizon: {horizon}")

        feature_vector = np.asarray(
            [values],
            dtype=float,
        )

        probabilities = np.asarray(
            self._model.predict_proba(feature_vector),
            dtype=float,
        )

        if probabilities.shape != (1, 2):
            raise RuntimeError("Unexpected probability output shape")

        if not np.isfinite(probabilities).all():
            raise RuntimeError("Nonfinite model probability")

        if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
            raise RuntimeError("Model probability outside [0, 1]")

        probability_yes = float(probabilities[0, 1])

        # Identity calibration:
        # no fitted probability transformation.
        probability_no = 1.0 - probability_yes

        return PredictionResult(
            model_version=self.model_version,
            calibration_version=(self.calibration_version),
            probability_yes=probability_yes,
            probability_no=probability_no,
        )
