from polybtc.modeling.metrics import (
    evaluate_probabilities,
)


def test_probability_metrics() -> None:
    result = evaluate_probabilities(
        labels=[1, 0],
        probabilities=[0.8, 0.2],
    )

    assert result.rows == 2

    assert abs(result.brier_score - 0.04) < 1e-12

    assert result.log_loss > 0

    assert result.accuracy == 1.0
