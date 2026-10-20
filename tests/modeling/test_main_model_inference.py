from pathlib import Path

import numpy as np
import pytest

from polybtc.modeling.inference import (
    FrozenProbabilityModel,
)


ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "data" / "models" / "main" / "hgb3_expanded_v2.joblib"


@pytest.fixture(scope="module")
def predictor():
    return FrozenProbabilityModel(MODEL_PATH)


def test_valid_prediction(predictor):
    prediction = predictor.predict(
        {
            "relative_distance_from_strike": 0.00025,
            "target_horizon_seconds": 60,
            "reference_return_30s": 0.00012,
        }
    )

    assert prediction.model_version == "hgb3_expanded_v2"
    assert prediction.calibration_version == "identity_v1"

    assert 0.0 <= prediction.probability_yes <= 1.0
    assert 0.0 <= prediction.probability_no <= 1.0

    assert np.isclose(
        prediction.probability_yes + prediction.probability_no,
        1.0,
        atol=1e-12,
    )


def test_deterministic_prediction(predictor):
    features = {
        "relative_distance_from_strike": -0.0004,
        "target_horizon_seconds": 120,
        "reference_return_30s": -0.0002,
    }

    first = predictor.predict(features)
    second = predictor.predict(features)

    assert first == second


@pytest.mark.parametrize(
    "bad_value",
    [None, float("nan"), float("inf"), True, "invalid"],
)
def test_reject_invalid_feature(predictor, bad_value):
    with pytest.raises(ValueError):
        predictor.predict(
            {
                "relative_distance_from_strike": bad_value,
                "target_horizon_seconds": 60,
                "reference_return_30s": 0.0001,
            }
        )


def test_reject_unsupported_horizon(predictor):
    with pytest.raises(ValueError):
        predictor.predict(
            {
                "relative_distance_from_strike": 0.0001,
                "target_horizon_seconds": 75,
                "reference_return_30s": 0.0001,
            }
        )


def test_reject_missing_feature(predictor):
    with pytest.raises(ValueError):
        predictor.predict(
            {
                "relative_distance_from_strike": 0.0001,
                "target_horizon_seconds": 60,
            }
        )


def test_reject_extra_feature(predictor):
    with pytest.raises(ValueError):
        predictor.predict(
            {
                "relative_distance_from_strike": 0.0001,
                "target_horizon_seconds": 60,
                "reference_return_30s": 0.0001,
                "yes_ask": 0.55,
            }
        )
