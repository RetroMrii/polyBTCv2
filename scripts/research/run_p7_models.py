from __future__ import annotations

import csv
import json
import sys
from math import log
from dataclasses import asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.modeling.extended_models import (
    fit_hist_gradient_boosting,
    fit_random_forest,
    predict_probability,
)
from polybtc.modeling.metrics import (
    evaluate_probabilities,
)
from polybtc.modeling.splits import (
    chronological_market_split,
)
from polybtc.modeling.baselines import (
    fit_logistic_baseline,
    predict_logistic_probabilities,
)

DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p7_model_report.json"


REFERENCE_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
    "reference_return_60s",
    "reference_return_120s",
    "realized_volatility_60s",
    "realized_volatility_120s",
)


MARKET_FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
    "reference_return_60s",
    "reference_return_120s",
    "realized_volatility_60s",
    "realized_volatility_120s",
    "normalized_yes_mid",
    "yes_spread",
    "no_spread",
    "yes_top_depth",
    "no_top_depth",
    "yes_book_imbalance",
    "no_book_imbalance",
    "reference_age_ms",
    "yes_book_age_ms",
    "no_book_age_ms",
)

INCREMENTAL_MARKET_FEATURES = (
    "market_logit",
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_rows() -> list[dict[str, str]]:
    with DATASET_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise RuntimeError("P4 dataset is empty")

    return rows


def complete_rows(
    rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> list[dict[str, str]]:
    return [row for row in rows if all(row[name].strip() for name in feature_names)]


def feature_matrix(
    rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> list[list[float]]:
    return [[float(row[name]) for name in feature_names] for row in rows]


def labels(
    rows: list[dict[str, str]],
) -> list[int]:
    return [int(row["label_yes"]) for row in rows]


def market_logit(
    probability: float,
) -> float:
    epsilon = 1e-6

    clipped = min(
        1.0 - epsilon,
        max(epsilon, probability),
    )

    return log(clipped / (1.0 - clipped))


def add_market_logit(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    result = []

    for row in rows:
        copied = dict(row)

        raw_probability = copied["normalized_yes_mid"].strip()

        if raw_probability:
            copied["market_logit"] = str(market_logit(float(raw_probability)))
        else:
            copied["market_logit"] = ""

        result.append(copied)

    return result


def evaluate_model(
    model,
    rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> dict:
    probabilities = predict_probability(
        model,
        feature_matrix(
            rows,
            feature_names,
        ),
    )

    metrics = evaluate_probabilities(
        labels(rows),
        probabilities,
    )

    return asdict(metrics)


def evaluate_logistic(
    train_rows: list[dict[str, str]],
    evaluation_rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> dict:
    model = fit_logistic_baseline(
        feature_matrix(
            train_rows,
            feature_names,
        ),
        labels(train_rows),
        feature_names=feature_names,
    )

    probabilities = predict_logistic_probabilities(
        model,
        feature_matrix(
            evaluation_rows,
            feature_names,
        ),
    )

    return asdict(
        evaluate_probabilities(
            labels(evaluation_rows),
            probabilities,
        )
    )


def evaluate_market_mid(
    rows: list[dict[str, str]],
) -> dict:
    probabilities = [float(row["normalized_yes_mid"]) for row in rows]

    return asdict(
        evaluate_probabilities(
            labels(rows),
            probabilities,
        )
    )


def common_subset_comparison(
    train_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
    *,
    include_market_mid: bool,
) -> dict:
    train_complete = complete_rows(
        train_rows,
        feature_names,
    )

    validation_complete = complete_rows(
        validation_rows,
        feature_names,
    )

    test_complete = complete_rows(
        test_rows,
        feature_names,
    )

    x_train = feature_matrix(
        train_complete,
        feature_names,
    )

    y_train = labels(train_complete)

    rf = fit_random_forest(
        x_train,
        y_train,
        feature_names=feature_names,
    )

    hgb = fit_hist_gradient_boosting(
        x_train,
        y_train,
        feature_names=feature_names,
    )

    result = {
        "rows": {
            "train": len(train_complete),
            "validation": len(validation_complete),
            "test": len(test_complete),
        },
        "validation": {
            "logistic": evaluate_logistic(
                train_complete,
                validation_complete,
                feature_names,
            ),
            "random_forest": evaluate_model(
                rf,
                validation_complete,
                feature_names,
            ),
            "hist_gradient_boosting": evaluate_model(
                hgb,
                validation_complete,
                feature_names,
            ),
        },
        "test": {
            "logistic": evaluate_logistic(
                train_complete,
                test_complete,
                feature_names,
            ),
            "random_forest": evaluate_model(
                rf,
                test_complete,
                feature_names,
            ),
            "hist_gradient_boosting": evaluate_model(
                hgb,
                test_complete,
                feature_names,
            ),
        },
    }

    if include_market_mid:
        result["validation"]["market_normalized_yes_mid"] = evaluate_market_mid(
            validation_complete
        )

        result["test"]["market_normalized_yes_mid"] = evaluate_market_mid(test_complete)

    return result


def run_feature_track(
    train_rows: list[dict[str, str]],
    validation_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    feature_names: tuple[str, ...],
) -> dict:
    train_complete = complete_rows(
        train_rows,
        feature_names,
    )

    validation_complete = complete_rows(
        validation_rows,
        feature_names,
    )

    test_complete = complete_rows(
        test_rows,
        feature_names,
    )

    x_train = feature_matrix(
        train_complete,
        feature_names,
    )

    y_train = labels(train_complete)

    random_forest = fit_random_forest(
        x_train,
        y_train,
        feature_names=feature_names,
    )

    gradient_boosting = fit_hist_gradient_boosting(
        x_train,
        y_train,
        feature_names=feature_names,
    )

    return {
        "features": list(feature_names),
        "rows": {
            "train": len(train_complete),
            "validation": len(validation_complete),
            "test": len(test_complete),
        },
        "random_forest": {
            "validation": evaluate_model(
                random_forest,
                validation_complete,
                feature_names,
            ),
            "test": evaluate_model(
                random_forest,
                test_complete,
                feature_names,
            ),
        },
        "hist_gradient_boosting": {
            "validation": evaluate_model(
                gradient_boosting,
                validation_complete,
                feature_names,
            ),
            "test": evaluate_model(
                gradient_boosting,
                test_complete,
                feature_names,
            ),
        },
        "reference_common_subset": (
            common_subset_comparison(
                train_rows,
                validation_rows,
                test_rows,
                REFERENCE_FEATURES,
                include_market_mid=False,
            )
        ),
        "market_common_subset": (
            common_subset_comparison(
                train_rows,
                validation_rows,
                test_rows,
                MARKET_FEATURES,
                include_market_mid=True,
            )
        ),
    }


def main() -> None:
    rows = load_rows()

    market_times: dict[
        str,
        datetime,
    ] = {}

    for row in rows:
        condition_id = row["condition_id"].strip().lower()

        timestamp = parse_dt(row["prediction_timestamp"])

        previous = market_times.get(condition_id)

        if previous is None or timestamp < previous:
            market_times[condition_id] = timestamp

    split = chronological_market_split(market_times)

    split_lookup: dict[
        str,
        str,
    ] = {}

    for condition_id in split.train_markets:
        split_lookup[condition_id] = "train"

    for condition_id in split.validation_markets:
        split_lookup[condition_id] = "validation"

    for condition_id in split.test_markets:
        split_lookup[condition_id] = "test"

    train_rows = [
        row
        for row in rows
        if split_lookup[row["condition_id"].strip().lower()] == "train"
    ]

    validation_rows = [
        row
        for row in rows
        if split_lookup[row["condition_id"].strip().lower()] == "validation"
    ]

    test_rows = [
        row
        for row in rows
        if split_lookup[row["condition_id"].strip().lower()] == "test"
    ]

    train_rows_market = add_market_logit(train_rows)

    validation_rows_market = add_market_logit(validation_rows)

    test_rows_market = add_market_logit(test_rows)

    report = {
        "markets": {
            "train": len(split.train_markets),
            "validation": len(split.validation_markets),
            "test": len(split.test_markets),
        },
        "reference_track": (
            run_feature_track(
                train_rows,
                validation_rows,
                test_rows,
                REFERENCE_FEATURES,
            )
        ),
        "market_track": (
            run_feature_track(
                train_rows,
                validation_rows,
                test_rows,
                MARKET_FEATURES,
            )
        ),
        "incremental_market_model": (
            common_subset_comparison(
                train_rows_market,
                validation_rows_market,
                test_rows_market,
                INCREMENTAL_MARKET_FEATURES,
                include_market_mid=True,
            )
        ),
    }

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
