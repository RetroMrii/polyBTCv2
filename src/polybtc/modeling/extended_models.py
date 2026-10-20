from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)


@dataclass(frozen=True, slots=True)
class ProbabilityModel:
    name: str
    feature_names: tuple[str, ...]
    model: object


def fit_random_forest(
    x: list[list[float]],
    y: list[int],
    *,
    feature_names: tuple[str, ...],
    n_estimators: int = 300,
    max_depth: int | None = 6,
    min_samples_leaf: int = 10,
) -> ProbabilityModel:
    if not x:
        raise ValueError("training feature matrix is empty")

    if len(x) != len(y):
        raise ValueError("x and y must have equal length")

    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=int),
    )

    return ProbabilityModel(
        name="random_forest",
        feature_names=feature_names,
        model=model,
    )


def fit_hist_gradient_boosting(
    x: list[list[float]],
    y: list[int],
    *,
    feature_names: tuple[str, ...],
    learning_rate: float = 0.05,
    max_iter: int = 200,
    max_leaf_nodes: int = 15,
    min_samples_leaf: int = 20,
    l2_regularization: float = 1.0,
) -> ProbabilityModel:
    if not x:
        raise ValueError("training feature matrix is empty")

    if len(x) != len(y):
        raise ValueError("x and y must have equal length")

    model = HistGradientBoostingClassifier(
        learning_rate=learning_rate,
        max_iter=max_iter,
        max_leaf_nodes=max_leaf_nodes,
        min_samples_leaf=min_samples_leaf,
        l2_regularization=l2_regularization,
        random_state=42,
    )

    model.fit(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=int),
    )

    return ProbabilityModel(
        name="hist_gradient_boosting",
        feature_names=feature_names,
        model=model,
    )


def predict_probability(
    fitted: ProbabilityModel,
    x: list[list[float]],
) -> list[float]:
    if not x:
        return []

    probabilities = fitted.model.predict_proba(
        np.asarray(
            x,
            dtype=float,
        )
    )[:, 1]

    return [float(value) for value in probabilities]
