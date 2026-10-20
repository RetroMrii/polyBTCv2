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
from polybtc.modeling.splits import (
    chronological_market_split,
)


DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

REPORT_FILE = ROOT / "data" / "normalized" / "p8_edge_audit.json"

PREDICTIONS_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"


FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


EDGE_BUCKETS = (
    (-1.0, 0.00),
    (0.00, 0.02),
    (0.02, 0.05),
    (0.05, 0.10),
    (0.10, 0.15),
    (0.15, 1.00),
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


def complete_model_rows(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if all(row[name].strip() for name in FEATURES) and row["label_yes"].strip()
    ]


def feature_matrix(
    rows: list[dict[str, str]],
) -> list[list[float]]:
    return [[float(row[name]) for name in FEATURES] for row in rows]


def labels(
    rows: list[dict[str, str]],
) -> list[int]:
    return [int(row["label_yes"]) for row in rows]


def optional_float(
    value: str,
) -> float | None:
    stripped = value.strip()

    if not stripped:
        return None

    return float(stripped)


def build_edge_records(
    split_name: str,
    rows: list[dict[str, str]],
    probabilities: list[float],
) -> list[dict]:
    records = []

    for row, probability_yes in zip(
        rows,
        probabilities,
    ):
        yes_mid = optional_float(row["yes_mid"])

        yes_spread = optional_float(row["yes_spread"])

        no_mid = optional_float(row["no_mid"])

        no_spread = optional_float(row["no_spread"])

        if yes_mid is None or yes_spread is None or no_mid is None or no_spread is None:
            continue

        yes_ask = yes_mid + yes_spread / 2.0

        no_ask = no_mid + no_spread / 2.0

        label_yes = int(row["label_yes"])

        probability_no = 1.0 - probability_yes

        yes_edge = probability_yes - yes_ask

        no_edge = probability_no - no_ask

        if yes_edge >= no_edge:
            selected_side = "YES"
            selected_edge = yes_edge
            selected_ask = yes_ask
            selected_probability = probability_yes
            realized_pnl = label_yes - yes_ask
            side_won = label_yes == 1
        else:
            selected_side = "NO"
            selected_edge = no_edge
            selected_ask = no_ask
            selected_probability = probability_no
            realized_pnl = (1 - label_yes) - no_ask
            side_won = label_yes == 0

        records.append(
            {
                "split": split_name,
                "condition_id": (row["condition_id"].strip().lower()),
                "target_horizon_seconds": int(row["target_horizon_seconds"]),
                "prediction_timestamp": (row["prediction_timestamp"]),
                "label_yes": label_yes,
                "probability_yes": (probability_yes),
                "yes_ask": yes_ask,
                "no_ask": no_ask,
                "yes_edge": yes_edge,
                "no_edge": no_edge,
                "selected_side": (selected_side),
                "selected_probability": (selected_probability),
                "selected_ask": (selected_ask),
                "selected_edge": (selected_edge),
                "realized_pnl_per_share": (realized_pnl),
                "side_won": (side_won),
            }
        )

    return records


def summarize_records(
    records: list[dict],
) -> dict:
    if not records:
        return {
            "rows": 0,
            "markets": 0,
            "mean_predicted_edge": None,
            "mean_realized_pnl_per_share": None,
            "win_rate": None,
        }

    markets = {record["condition_id"] for record in records}

    return {
        "rows": len(records),
        "markets": len(markets),
        "mean_predicted_edge": (
            sum(record["selected_edge"] for record in records) / len(records)
        ),
        "mean_realized_pnl_per_share": (
            sum(record["realized_pnl_per_share"] for record in records) / len(records)
        ),
        "win_rate": (sum(1 for record in records if record["side_won"]) / len(records)),
    }


def bucket_report(
    records: list[dict],
) -> list[dict]:
    result = []

    for index, (
        lower,
        upper,
    ) in enumerate(EDGE_BUCKETS):
        if index == 0:
            selected = [
                record
                for record in records
                if (lower <= record["selected_edge"] < upper)
            ]
        elif index == (len(EDGE_BUCKETS) - 1):
            selected = [
                record
                for record in records
                if (lower <= record["selected_edge"] <= upper)
            ]
        else:
            selected = [
                record
                for record in records
                if (lower <= record["selected_edge"] < upper)
            ]

        summary = summarize_records(selected)

        summary.update(
            {
                "lower_edge": lower,
                "upper_edge": upper,
            }
        )

        result.append(summary)

    return result


def threshold_report(
    records: list[dict],
) -> dict:
    thresholds = (
        0.00,
        0.02,
        0.05,
        0.10,
        0.15,
    )

    result = {}

    for threshold in thresholds:
        selected = [
            record for record in records if (record["selected_edge"] >= threshold)
        ]

        result[f"{threshold:.2f}"] = summarize_records(selected)

    return result


def horizon_report(
    records: list[dict],
) -> dict:
    result = {}

    horizons = sorted(
        {record["target_horizon_seconds"] for record in records},
        reverse=True,
    )

    for horizon in horizons:
        horizon_rows = [
            record
            for record in records
            if (record["target_horizon_seconds"] == horizon)
        ]

        result[str(horizon)] = {
            "all": summarize_records(horizon_rows),
            "positive_edge_only": (
                summarize_records(
                    [
                        record
                        for record in horizon_rows
                        if (record["selected_edge"] > 0.0)
                    ]
                )
            ),
        }

    return result


def side_report(
    records: list[dict],
) -> dict:
    return {
        side: summarize_records(
            [record for record in records if (record["selected_side"] == side)]
        )
        for side in (
            "YES",
            "NO",
        )
    }


def write_predictions(
    records: list[dict],
) -> None:
    fieldnames = [
        "split",
        "condition_id",
        "target_horizon_seconds",
        "prediction_timestamp",
        "label_yes",
        "probability_yes",
        "yes_ask",
        "no_ask",
        "yes_edge",
        "no_edge",
        "selected_side",
        "selected_probability",
        "selected_ask",
        "selected_edge",
        "realized_pnl_per_share",
        "side_won",
    ]

    with PREDICTIONS_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(records)


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

    train_markets = set(split.train_markets)

    validation_markets = set(split.validation_markets)

    test_markets = set(split.test_markets)

    train_rows = complete_model_rows(
        [row for row in rows if (row["condition_id"].strip().lower() in train_markets)]
    )

    validation_rows = complete_model_rows(
        [
            row
            for row in rows
            if (row["condition_id"].strip().lower() in validation_markets)
        ]
    )

    test_rows = complete_model_rows(
        [row for row in rows if (row["condition_id"].strip().lower() in test_markets)]
    )

    model = fit_logistic_baseline(
        feature_matrix(train_rows),
        labels(train_rows),
        feature_names=FEATURES,
    )

    validation_probabilities = predict_logistic_probabilities(
        model,
        feature_matrix(validation_rows),
    )

    test_probabilities = predict_logistic_probabilities(
        model,
        feature_matrix(test_rows),
    )

    validation_records = build_edge_records(
        "validation",
        validation_rows,
        validation_probabilities,
    )

    test_records = build_edge_records(
        "development_holdout",
        test_rows,
        test_probabilities,
    )

    all_records = validation_records + test_records

    report = {
        "version": "p8_edge_audit_v1",
        "model_features": list(FEATURES),
        "important_note": (
            "Current test period has already "
            "been inspected during P5-P7 and "
            "is treated as a development "
            "holdout, not an untouched final "
            "test set."
        ),
        "edge_definition": {
            "yes": ("probability_yes - yes_ask"),
            "no": ("(1 - probability_yes) - no_ask"),
            "selection": ("side with larger predicted gross edge"),
            "realized_yes_pnl": ("label_yes - yes_ask"),
            "realized_no_pnl": ("(1 - label_yes) - no_ask"),
            "costs_excluded": [
                "fees",
                "slippage",
                "latency",
                "partial fills",
                "fill failure",
            ],
        },
        "markets": {
            "train": len(train_markets),
            "validation": len(validation_markets),
            "development_holdout": len(test_markets),
        },
        "validation": {
            "all": summarize_records(validation_records),
            "edge_buckets": bucket_report(validation_records),
            "thresholds": threshold_report(validation_records),
            "horizons": horizon_report(validation_records),
            "sides": side_report(validation_records),
        },
        "development_holdout": {
            "all": summarize_records(test_records),
            "edge_buckets": bucket_report(test_records),
            "thresholds": threshold_report(test_records),
            "horizons": horizon_report(test_records),
            "sides": side_report(test_records),
        },
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    write_predictions(all_records)

    print(f"Wrote {REPORT_FILE}")

    print(f"Wrote {PREDICTIONS_FILE}")


if __name__ == "__main__":
    main()
