from __future__ import annotations

from dataclasses import dataclass
from math import log


EPSILON = 1e-15


@dataclass(frozen=True, slots=True)
class ProbabilityMetrics:
    rows: int
    brier_score: float
    log_loss: float
    accuracy: float


def evaluate_probabilities(
    labels: list[int],
    probabilities: list[float],
) -> ProbabilityMetrics:
    if len(labels) != len(probabilities):
        raise ValueError("labels and probabilities must have equal length")

    if not labels:
        raise ValueError("cannot evaluate empty probability set")

    brier_total = 0.0
    log_loss_total = 0.0
    correct = 0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        if label not in {0, 1}:
            raise ValueError(f"invalid binary label: {label}")

        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability outside [0, 1]: {probability}")

        brier_total += (probability - label) ** 2

        clipped = min(
            1.0 - EPSILON,
            max(EPSILON, probability),
        )

        log_loss_total += -(label * log(clipped) + (1 - label) * log(1.0 - clipped))

        predicted_label = 1 if probability >= 0.5 else 0

        if predicted_label == label:
            correct += 1

    count = len(labels)

    return ProbabilityMetrics(
        rows=count,
        brier_score=brier_total / count,
        log_loss=log_loss_total / count,
        accuracy=correct / count,
    )
