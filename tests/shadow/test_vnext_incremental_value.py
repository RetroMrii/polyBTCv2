import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "operations" / "run_vnext_incremental_value.py"
)

spec = importlib.util.spec_from_file_location(
    "vnext_incremental_value",
    SCRIPT,
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample_row(market="market-1", label=1):
    return {
        "condition_id": market,
        "horizon_seconds": 120,
        "target_at_utc": "2026-10-09T18:00:00+00:00",
        "label_yes": label,
        "model_probability_yes": 0.8,
        "market_probability_yes": 0.6,
    }


def test_loss_difference_zero_for_market_only():
    row = sample_row()

    brier, log_loss = module.loss_difference(row, 0.0)

    assert brier == pytest.approx(0.0)
    assert log_loss == pytest.approx(0.0)


def test_bootstrap_detects_consistent_improvement():
    rows = []

    for index in range(20):
        rows.append(
            {
                **sample_row(
                    market=f"market-{index}",
                    label=1,
                ),
                "market_probability_yes": 0.5,
                "model_probability_yes": 0.9,
            }
        )

    result = module.cluster_bootstrap(
        rows,
        1.0,
        resamples=200,
        seed=42,
    )

    assert result["status"] == "EVALUATED"
    assert result["markets"] == 20

    assert result["brier"]["difference"] < 0
    assert result["brier"]["ci_95_upper"] < 0

    assert result["log_loss"]["difference"] < 0
    assert result["log_loss"]["ci_95_upper"] < 0


def test_bootstrap_counts_markets_not_horizons():
    rows = [
        sample_row(market="market-a"),
        {
            **sample_row(market="market-a"),
            "horizon_seconds": 60,
        },
        sample_row(market="market-b"),
    ]

    result = module.cluster_bootstrap(
        rows,
        1.0,
        resamples=100,
        seed=42,
    )

    assert result["markets"] == 2
    assert result["prediction_rows"] == 3
    assert result["unit"] == "market"


def test_bootstrap_is_reproducible():
    rows = [sample_row(market=f"market-{i}") for i in range(10)]

    first = module.cluster_bootstrap(rows, 0.5, resamples=100, seed=123)

    second = module.cluster_bootstrap(rows, 0.5, resamples=100, seed=123)

    assert first == second


def test_bootstrap_insufficient_sample():
    result = module.cluster_bootstrap(
        [sample_row()],
        1.0,
    )

    assert result["status"] == "INSUFFICIENT_SAMPLE"
    assert result["markets"] == 1


def test_bootstrap_preserves_market_balancing():
    rows = [
        {
            **sample_row(market="a", label=1),
            "market_probability_yes": 0.5,
            "model_probability_yes": 0.9,
        },
        {
            **sample_row(market="a", label=1),
            "horizon_seconds": 60,
            "market_probability_yes": 0.5,
            "model_probability_yes": 0.9,
        },
        {
            **sample_row(market="b", label=1),
            "market_probability_yes": 0.9,
            "model_probability_yes": 0.5,
        },
    ]

    result = module.cluster_bootstrap(
        rows,
        1.0,
        resamples=100,
        seed=42,
    )

    # Market A: 0.01 - 0.25 = -0.24
    # Market B: 0.25 - 0.01 = +0.24
    # Equal market weighting cancels them exactly.
    assert result["brier"]["difference"] == pytest.approx(0.0)
