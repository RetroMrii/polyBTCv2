from __future__ import annotations

from dataclasses import dataclass
from math import log

import numpy as np

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


EPSILON = 1e-15


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    rows: int
    brier_score: float
    log_loss: float


def _clip_probability(
    probability: float,
) -> float:
    return min(
        1.0 - EPSILON,
        max(EPSILON, probability),
    )


def _probability_to_logit(
    probability: float,
) -> float:
    clipped = _clip_probability(probability)

    return log(clipped / (1.0 - clipped))


def evaluate_calibration(
    labels: list[int],
    probabilities: list[float],
) -> CalibrationMetrics:
    if len(labels) != len(probabilities):
        raise ValueError("labels and probabilities must have equal length")

    if not labels:
        raise ValueError("cannot evaluate empty probability set")

    brier_total = 0.0
    log_loss_total = 0.0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        if label not in {0, 1}:
            raise ValueError(f"invalid label: {label}")

        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"invalid probability: {probability}")

        brier_total += (probability - label) ** 2

        clipped = _clip_probability(probability)

        log_loss_total += -(label * log(clipped) + (1 - label) * log(1.0 - clipped))

    count = len(labels)

    return CalibrationMetrics(
        rows=count,
        brier_score=brier_total / count,
        log_loss=log_loss_total / count,
    )


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower_bound: float
    upper_bound: float
    rows: int
    mean_probability: float | None
    observed_rate: float | None
    absolute_gap: float | None


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    model: LogisticRegression


def fit_platt_calibrator(
    probabilities: list[float],
    labels: list[int],
) -> PlattCalibrator:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have equal length")

    if len(set(labels)) < 2:
        raise ValueError("calibration labels must contain both classes")

    logits = [_probability_to_logit(probability) for probability in probabilities]

    x = np.asarray(
        logits,
        dtype=float,
    ).reshape(-1, 1)

    y = np.asarray(
        labels,
        dtype=int,
    )

    model = LogisticRegression(
        solver="lbfgs",
        max_iter=1000,
    )

    model.fit(
        x,
        y,
    )

    return PlattCalibrator(model=model)


def apply_platt_calibrator(
    calibrator: PlattCalibrator,
    probabilities: list[float],
) -> list[float]:
    logits = [_probability_to_logit(probability) for probability in probabilities]

    x = np.asarray(
        logits,
        dtype=float,
    ).reshape(-1, 1)

    calibrated = calibrator.model.predict_proba(x)[:, 1]

    return [float(value) for value in calibrated]


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    model: IsotonicRegression


def fit_isotonic_calibrator(
    probabilities: list[float],
    labels: list[int],
) -> IsotonicCalibrator:
    if len(probabilities) != len(labels):
        raise ValueError("probabilities and labels must have equal length")

    if len(set(labels)) < 2:
        raise ValueError("calibration labels must contain both classes")

    model = IsotonicRegression(
        out_of_bounds="clip",
    )

    model.fit(
        np.asarray(
            probabilities,
            dtype=float,
        ),
        np.asarray(
            labels,
            dtype=int,
        ),
    )

    return IsotonicCalibrator(model=model)


def apply_isotonic_calibrator(
    calibrator: IsotonicCalibrator,
    probabilities: list[float],
) -> list[float]:
    calibrated = calibrator.model.predict(
        np.asarray(
            probabilities,
            dtype=float,
        )
    )

    return [float(value) for value in calibrated]


def reliability_bins(
    labels: list[int],
    probabilities: list[float],
    *,
    bin_count: int = 10,
) -> list[ReliabilityBin]:
    if len(labels) != len(probabilities):
        raise ValueError("labels and probabilities must have equal length")

    if bin_count <= 0:
        raise ValueError("bin_count must be positive")

    result: list[ReliabilityBin] = []

    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count

        members: list[tuple[int, float]] = []

        for label, probability in zip(
            labels,
            probabilities,
        ):
            if index == bin_count - 1:
                inside = lower <= probability <= upper
            else:
                inside = lower <= probability < upper

            if inside:
                members.append((label, probability))

        if not members:
            result.append(
                ReliabilityBin(
                    lower_bound=lower,
                    upper_bound=upper,
                    rows=0,
                    mean_probability=None,
                    observed_rate=None,
                    absolute_gap=None,
                )
            )
            continue

        member_labels = [label for label, _ in members]

        member_probabilities = [probability for _, probability in members]

        mean_probability = sum(member_probabilities) / len(member_probabilities)

        observed_rate = sum(member_labels) / len(member_labels)

        result.append(
            ReliabilityBin(
                lower_bound=lower,
                upper_bound=upper,
                rows=len(members),
                mean_probability=mean_probability,
                observed_rate=observed_rate,
                absolute_gap=abs(mean_probability - observed_rate),
            )
        )

    return result


def expected_calibration_error(
    bins: list[ReliabilityBin],
) -> float:
    total_rows = sum(item.rows for item in bins)

    if total_rows == 0:
        raise ValueError("cannot calculate ECE from empty bins")

    return sum(
        (item.rows / total_rows) * item.absolute_gap
        for item in bins
        if item.absolute_gap is not None
    )


def maximum_calibration_error(
    bins: list[ReliabilityBin],
) -> float:
    gaps = [
        item.absolute_gap
        for item in bins
        if (item.rows > 0 and item.absolute_gap is not None)
    ]

    if not gaps:
        raise ValueError("cannot calculate MCE from empty bins")

    return max(gaps)


def extreme_probability_counts(
    probabilities: list[float],
    *,
    threshold: float = 1e-6,
) -> dict[str, int]:
    return {
        "near_zero": sum(value <= threshold for value in probabilities),
        "near_one": sum(value >= 1.0 - threshold for value in probabilities),
    }
