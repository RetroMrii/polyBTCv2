from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True, slots=True)
class LogisticBaseline:
    feature_names: tuple[str, ...]
    pipeline: Pipeline


def fit_logistic_baseline(
    x: list[list[float]],
    y: list[int],
    *,
    feature_names: tuple[str, ...],
) -> LogisticBaseline:
    if not x:
        raise ValueError("training feature matrix is empty")

    if len(x) != len(y):
        raise ValueError("x and y must have equal length")

    if len(set(y)) < 2:
        raise ValueError("training labels must contain both classes")

    pipeline = Pipeline(
        steps=[
            (
                "scale",
                StandardScaler(),
            ),
            (
                "model",
                LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )

    pipeline.fit(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=int),
    )

    return LogisticBaseline(
        feature_names=feature_names,
        pipeline=pipeline,
    )


def predict_logistic_probabilities(
    model: LogisticBaseline,
    x: list[list[float]],
) -> list[float]:
    if not x:
        return []

    probabilities = model.pipeline.predict_proba(np.asarray(x, dtype=float))[:, 1]

    return [float(value) for value in probabilities]
