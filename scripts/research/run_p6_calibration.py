from __future__ import annotations

import csv
import json
import sys

from dataclasses import asdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.modeling.baselines import (
    fit_logistic_baseline,
    predict_logistic_probabilities,
)
from polybtc.modeling.calibration import (
    apply_isotonic_calibrator,
    apply_platt_calibrator,
    evaluate_calibration,
    expected_calibration_error,
    extreme_probability_counts,
    fit_isotonic_calibrator,
    fit_platt_calibrator,
    maximum_calibration_error,
    reliability_bins,
)
from polybtc.modeling.splits import (
    chronological_market_split,
)


DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p6_calibration_report.json"

OUTPUT_PREDICTIONS = ROOT / "data" / "normalized" / "p6_calibration_predictions.csv"


FEATURES = (
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
        raise RuntimeError("P4 supervised dataset is empty")

    return rows


def complete_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [row for row in rows if all(row[name].strip() for name in FEATURES)]


def feature_matrix(
    rows: list[dict[str, str]],
) -> list[list[float]]:
    return [[float(row[name]) for name in FEATURES] for row in rows]


def labels(
    rows: list[dict[str, str]],
) -> list[int]:
    return [int(row["label_yes"]) for row in rows]


def calibration_diagnostics(
    labels_: list[int],
    probabilities: list[float],
) -> dict:
    bins = reliability_bins(
        labels_,
        probabilities,
        bin_count=10,
    )

    return {
        "metrics": asdict(
            evaluate_calibration(
                labels_,
                probabilities,
            )
        ),
        "expected_calibration_error": (expected_calibration_error(bins)),
        "maximum_calibration_error": (maximum_calibration_error(bins)),
        "extreme_probabilities": (extreme_probability_counts(probabilities)),
        "reliability_bins": [asdict(item) for item in bins],
    }


def horizon_calibration_report(
    rows: list[dict[str, str]],
    raw_probabilities: list[float],
    platt_probabilities: list[float],
    isotonic_probabilities: list[float],
) -> dict:
    result = {}

    horizons = sorted(
        {int(row["target_horizon_seconds"]) for row in rows},
        reverse=True,
    )

    for horizon in horizons:
        indices = [
            index
            for index, row in enumerate(rows)
            if int(row["target_horizon_seconds"]) == horizon
        ]

        horizon_labels = [int(rows[index]["label_yes"]) for index in indices]

        horizon_raw = [raw_probabilities[index] for index in indices]

        horizon_platt = [platt_probabilities[index] for index in indices]

        horizon_isotonic = [isotonic_probabilities[index] for index in indices]

        result[str(horizon)] = {
            "rows": len(indices),
            "raw": calibration_diagnostics(
                horizon_labels,
                horizon_raw,
            ),
            "platt": calibration_diagnostics(
                horizon_labels,
                horizon_platt,
            ),
            "isotonic": calibration_diagnostics(
                horizon_labels,
                horizon_isotonic,
            ),
        }

    return result


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

    split_lookup: dict[str, str] = {}

    for condition_id in split.train_markets:
        split_lookup[condition_id] = "train"

    for condition_id in split.validation_markets:
        split_lookup[condition_id] = "validation"

    for condition_id in split.test_markets:
        split_lookup[condition_id] = "test"

    train_rows = complete_rows(
        [
            row
            for row in rows
            if split_lookup[row["condition_id"].strip().lower()] == "train"
        ]
    )

    validation_rows = complete_rows(
        [
            row
            for row in rows
            if split_lookup[row["condition_id"].strip().lower()] == "validation"
        ]
    )

    test_rows = complete_rows(
        [
            row
            for row in rows
            if split_lookup[row["condition_id"].strip().lower()] == "test"
        ]
    )

    base_model = fit_logistic_baseline(
        feature_matrix(train_rows),
        labels(train_rows),
        feature_names=FEATURES,
    )

    validation_raw = predict_logistic_probabilities(
        base_model,
        feature_matrix(validation_rows),
    )

    test_raw = predict_logistic_probabilities(
        base_model,
        feature_matrix(test_rows),
    )

    validation_labels = labels(validation_rows)

    test_labels = labels(test_rows)

    platt = fit_platt_calibrator(
        validation_raw,
        validation_labels,
    )

    isotonic = fit_isotonic_calibrator(
        validation_raw,
        validation_labels,
    )

    test_platt = apply_platt_calibrator(
        platt,
        test_raw,
    )

    test_isotonic = apply_isotonic_calibrator(
        isotonic,
        test_raw,
    )

    per_horizon = horizon_calibration_report(
        test_rows,
        test_raw,
        test_platt,
        test_isotonic,
    )

    report = {
        "features": list(FEATURES),
        "per_horizon_test": per_horizon,
        "markets": {
            "train": len(split.train_markets),
            "validation": len(split.validation_markets),
            "test": len(split.test_markets),
        },
        "rows": {
            "train": len(train_rows),
            "validation": len(validation_rows),
            "test": len(test_rows),
        },
        "validation_raw": asdict(
            evaluate_calibration(
                validation_labels,
                validation_raw,
            )
        ),
        "test": {
            "raw": calibration_diagnostics(
                test_labels,
                test_raw,
            ),
            "platt": calibration_diagnostics(
                test_labels,
                test_platt,
            ),
            "isotonic": calibration_diagnostics(
                test_labels,
                test_isotonic,
            ),
        },
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

    fieldnames = [
        "condition_id",
        "target_horizon_seconds",
        "prediction_timestamp",
        "label_yes",
        "raw_probability",
        "platt_probability",
        "isotonic_probability",
    ]

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for (
            row,
            raw_probability,
            platt_probability,
            isotonic_probability,
        ) in zip(
            test_rows,
            test_raw,
            test_platt,
            test_isotonic,
        ):
            writer.writerow(
                {
                    "condition_id": (row["condition_id"]),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "label_yes": (row["label_yes"]),
                    "raw_probability": (raw_probability),
                    "platt_probability": (platt_probability),
                    "isotonic_probability": (isotonic_probability),
                }
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
