from __future__ import annotations

import csv
import json
import math

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

ORIGINAL_PARTITIONS_FILE = ROOT / "data" / "normalized" / "p11_market_partitions.csv"

EXTENSION_PARTITIONS_FILE = (
    ROOT / "data" / "normalized" / "p11_extension_market_partitions.csv"
)

RESIDUAL_DATASET_FILE = ROOT / "data" / "normalized" / "p115_residual_dataset.csv"

OUTPUT_PREDICTIONS = (
    ROOT / "data" / "normalized" / "p115_market_anchored_walk_forward_predictions.csv"
)

OUTPUT_REPORT = (
    ROOT / "data" / "normalized" / "p115_market_anchored_walk_forward_report.json"
)


REPORT_VERSION = "p115_market_anchored_walk_forward_v1"

EPSILON = 1e-6


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def normalize_condition_id(
    value: str,
) -> str:
    return value.strip().lower()


def utc_date(
    timestamp: str,
) -> str:
    return (
        datetime.fromisoformat(
            timestamp.replace(
                "Z",
                "+00:00",
            )
        )
        .date()
        .isoformat()
    )


def market_logit(
    probability: float,
) -> float:
    p = min(
        max(
            probability,
            EPSILON,
        ),
        1.0 - EPSILON,
    )

    return math.log(p / (1.0 - p))


def brier_score(
    labels: list[int],
    probabilities: list[float],
) -> float:
    return sum(
        (probability - label) ** 2
        for label, probability in zip(
            labels,
            probabilities,
        )
    ) / len(labels)


def log_loss(
    labels: list[int],
    probabilities: list[float],
) -> float:
    total = 0.0

    for label, probability in zip(
        labels,
        probabilities,
    ):
        p = min(
            max(
                probability,
                1e-15,
            ),
            1.0 - 1e-15,
        )

        total -= label * math.log(p) + (1 - label) * math.log(1.0 - p)

    return total / len(labels)


def accuracy(
    labels: list[int],
    probabilities: list[float],
) -> float:
    correct = sum(
        (1 if probability >= 0.5 else 0) == label
        for label, probability in zip(
            labels,
            probabilities,
        )
    )

    return correct / len(labels)


def metrics(
    labels: list[int],
    probabilities: list[float],
) -> dict:
    return {
        "rows": len(labels),
        "accuracy": accuracy(
            labels,
            probabilities,
        ),
        "brier_score": brier_score(
            labels,
            probabilities,
        ),
        "log_loss": log_loss(
            labels,
            probabilities,
        ),
    }


def make_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "logistic",
                LogisticRegression(
                    max_iter=1000,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def prediction_key(
    condition_id: str,
    prediction_timestamp: str,
    target_horizon_seconds: int,
) -> tuple[str, str, int]:
    return (
        normalize_condition_id(condition_id),
        prediction_timestamp.strip(),
        int(target_horizon_seconds),
    )


def main() -> None:
    p4_rows = load_csv(P4_FILE)

    original_partitions = load_csv(ORIGINAL_PARTITIONS_FILE)

    extension_partitions = load_csv(EXTENSION_PARTITIONS_FILE)

    residual_rows = load_csv(RESIDUAL_DATASET_FILE)

    frozen_market_ids = {
        normalize_condition_id(row["condition_id"])
        for row in original_partitions
        if (row["partition"].strip() == "FROZEN_RESEARCH")
    }

    original_forward_market_dates = {}

    for row in original_partitions:
        if row["partition"].strip() != "STRICT_FORWARD":
            continue

        condition_id = normalize_condition_id(row["condition_id"])

        original_forward_market_dates[condition_id] = utc_date(
            row["first_prediction_timestamp"]
        )

    extension_market_dates = {}

    for row in extension_partitions:
        if row["partition"].strip() != "P11_EXTENSION":
            continue

        condition_id = normalize_condition_id(row["condition_id"])

        extension_market_dates[condition_id] = utc_date(
            row["first_prediction_timestamp"]
        )

    overlap = set(original_forward_market_dates) & set(extension_market_dates)

    if overlap:
        raise RuntimeError("original forward and extension market sets overlap")

    test_market_dates = {
        **original_forward_market_dates,
        **extension_market_dates,
    }

    if frozen_market_ids & set(test_market_dates):
        raise RuntimeError("frozen research markets overlap with forward markets")

    btc_prediction_index = {}

    for row in residual_rows:
        key = prediction_key(
            row["condition_id"],
            row["prediction_timestamp"],
            int(row["target_horizon_seconds"]),
        )

        if key in btc_prediction_index:
            raise RuntimeError(f"duplicate residual prediction key: {key}")

        btc_prediction_index[key] = float(row["model_probability"])

    usable_rows_by_market = defaultdict(list)

    excluded_missing_book = 0
    excluded_missing_feature = 0

    for row in p4_rows:
        condition_id = normalize_condition_id(row["condition_id"])

        if (
            condition_id not in frozen_market_ids
            and condition_id not in test_market_dates
        ):
            continue

        market_probability = optional_float(row.get("normalized_yes_mid"))

        relative_distance = optional_float(row.get("relative_distance_from_strike"))

        reference_return_30s = optional_float(row.get("reference_return_30s"))

        if market_probability is None:
            excluded_missing_book += 1
            continue

        if relative_distance is None or reference_return_30s is None:
            excluded_missing_feature += 1
            continue

        horizon = int(row["target_horizon_seconds"])

        usable_rows_by_market[condition_id].append(
            {
                "condition_id": (condition_id),
                "prediction_timestamp": (row["prediction_timestamp"].strip()),
                "target_horizon_seconds": (horizon),
                "label_yes": int(row["label_yes"]),
                "market_probability": (market_probability),
                "market_logit": (market_logit(market_probability)),
                "relative_distance_from_strike": (relative_distance),
                "reference_return_30s": (reference_return_30s),
            }
        )

    training_market_ids = set(frozen_market_ids)

    fold_dates = sorted(set(test_market_dates.values()))

    output_rows = []
    fold_reports = []

    missing_btc_predictions = 0

    for fold_date in fold_dates:
        test_market_ids = {
            condition_id
            for (
                condition_id,
                market_date,
            ) in test_market_dates.items()
            if market_date == fold_date
        }

        training_rows = [
            row
            for condition_id in training_market_ids
            for row in usable_rows_by_market.get(condition_id, [])
        ]

        test_rows = [
            row
            for condition_id in test_market_ids
            for row in usable_rows_by_market.get(condition_id, [])
        ]

        if not training_rows:
            raise RuntimeError(f"no training rows for fold {fold_date}")

        if not test_rows:
            raise RuntimeError(f"no test rows for fold {fold_date}")

        market_only_x_train = np.array(
            [[row["market_logit"]] for row in training_rows],
            dtype=float,
        )

        market_plus_btc_x_train = np.array(
            [
                [
                    row["market_logit"],
                    row["relative_distance_from_strike"],
                    row["target_horizon_seconds"],
                    row["reference_return_30s"],
                ]
                for row in training_rows
            ],
            dtype=float,
        )

        y_train = np.array(
            [row["label_yes"] for row in training_rows],
            dtype=int,
        )

        market_only_model = make_pipeline()

        market_plus_btc_model = make_pipeline()

        market_only_model.fit(
            market_only_x_train,
            y_train,
        )

        market_plus_btc_model.fit(
            market_plus_btc_x_train,
            y_train,
        )

        labels = []
        raw_market_probabilities = []
        market_only_probabilities = []
        market_plus_btc_probabilities = []
        btc_only_probabilities = []

        fold_output_rows = []

        for row in sorted(
            test_rows,
            key=lambda item: (
                item["prediction_timestamp"],
                item["condition_id"],
                item["target_horizon_seconds"],
            ),
        ):
            market_only_x = np.array(
                [[row["market_logit"]]],
                dtype=float,
            )

            market_plus_btc_x = np.array(
                [
                    [
                        row["market_logit"],
                        row["relative_distance_from_strike"],
                        row["target_horizon_seconds"],
                        row["reference_return_30s"],
                    ]
                ],
                dtype=float,
            )

            market_only_probability = float(
                market_only_model.predict_proba(market_only_x)[0, 1]
            )

            market_plus_btc_probability = float(
                market_plus_btc_model.predict_proba(market_plus_btc_x)[0, 1]
            )

            key = prediction_key(
                row["condition_id"],
                row["prediction_timestamp"],
                row["target_horizon_seconds"],
            )

            btc_only_probability = btc_prediction_index.get(key)

            if btc_only_probability is None:
                missing_btc_predictions += 1
                continue

            label = row["label_yes"]

            labels.append(label)

            raw_market_probabilities.append(row["market_probability"])

            market_only_probabilities.append(market_only_probability)

            market_plus_btc_probabilities.append(market_plus_btc_probability)

            btc_only_probabilities.append(btc_only_probability)

            fold_output_rows.append(
                {
                    "report_version": (REPORT_VERSION),
                    "fold_date": (fold_date),
                    "condition_id": (row["condition_id"]),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "label_yes": (label),
                    "raw_market_probability": (row["market_probability"]),
                    "market_only_probability": (market_only_probability),
                    "market_plus_btc_probability": (market_plus_btc_probability),
                    "btc_only_walk_forward_probability": (btc_only_probability),
                }
            )

        if not labels:
            raise RuntimeError(f"no common comparison rows for fold {fold_date}")

        raw_market_metrics = metrics(
            labels,
            raw_market_probabilities,
        )

        market_only_metrics = metrics(
            labels,
            market_only_probabilities,
        )

        market_plus_btc_metrics = metrics(
            labels,
            market_plus_btc_probabilities,
        )

        btc_only_metrics = metrics(
            labels,
            btc_only_probabilities,
        )

        fold_reports.append(
            {
                "fold_date": (fold_date),
                "train_markets": len(training_market_ids),
                "test_markets": len(test_market_ids),
                "train_rows": len(training_rows),
                "test_rows_common": len(labels),
                "raw_market": (raw_market_metrics),
                "market_only_logistic": (market_only_metrics),
                "market_plus_btc": (market_plus_btc_metrics),
                "btc_only_walk_forward": (btc_only_metrics),
                "market_plus_btc_minus_market_only_brier": (
                    market_plus_btc_metrics["brier_score"]
                    - market_only_metrics["brier_score"]
                ),
                "market_plus_btc_minus_market_only_log_loss": (
                    market_plus_btc_metrics["log_loss"]
                    - market_only_metrics["log_loss"]
                ),
            }
        )

        output_rows.extend(fold_output_rows)

        training_market_ids.update(test_market_ids)

    if not output_rows:
        raise RuntimeError("no P11.5 anchored predictions produced")

    output_rows.sort(
        key=lambda row: (
            row["prediction_timestamp"],
            row["condition_id"],
            row["target_horizon_seconds"],
        )
    )

    with OUTPUT_PREDICTIONS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(output_rows[0].keys()),
        )

        writer.writeheader()
        writer.writerows(output_rows)

    all_labels = [int(row["label_yes"]) for row in output_rows]

    all_raw_market = [float(row["raw_market_probability"]) for row in output_rows]

    all_market_only = [float(row["market_only_probability"]) for row in output_rows]

    all_market_plus_btc = [
        float(row["market_plus_btc_probability"]) for row in output_rows
    ]

    all_btc_only = [
        float(row["btc_only_walk_forward_probability"]) for row in output_rows
    ]

    overall_raw_market = metrics(
        all_labels,
        all_raw_market,
    )

    overall_market_only = metrics(
        all_labels,
        all_market_only,
    )

    overall_market_plus_btc = metrics(
        all_labels,
        all_market_plus_btc,
    )

    overall_btc_only = metrics(
        all_labels,
        all_btc_only,
    )

    report = {
        "report_version": (REPORT_VERSION),
        "design": {
            "initial_training_partition": ("FROZEN_RESEARCH"),
            "forward_partitions": [
                "STRICT_FORWARD",
                "P11_EXTENSION",
            ],
            "walk_forward_unit": (
                "UTC calendar day by market first_prediction_timestamp"
            ),
            "market_only_features": [
                "market_logit",
            ],
            "market_plus_btc_features": [
                "market_logit",
                "relative_distance_from_strike",
                "target_horizon_seconds",
                "reference_return_30s",
            ],
            "model": (
                "StandardScaler + LogisticRegression(max_iter=1000, solver=lbfgs)"
            ),
        },
        "rows": len(output_rows),
        "markets": len({row["condition_id"] for row in output_rows}),
        "folds": len(fold_reports),
        "excluded_missing_book": (excluded_missing_book),
        "excluded_missing_feature": (excluded_missing_feature),
        "missing_btc_predictions": (missing_btc_predictions),
        "overall": {
            "raw_market": (overall_raw_market),
            "market_only_logistic": (overall_market_only),
            "market_plus_btc": (overall_market_plus_btc),
            "btc_only_walk_forward": (overall_btc_only),
            "market_plus_btc_minus_market_only_brier": (
                overall_market_plus_btc["brier_score"]
                - overall_market_only["brier_score"]
            ),
            "market_plus_btc_minus_market_only_log_loss": (
                overall_market_plus_btc["log_loss"] - overall_market_only["log_loss"]
            ),
            "market_plus_btc_minus_raw_market_brier": (
                overall_market_plus_btc["brier_score"]
                - overall_raw_market["brier_score"]
            ),
            "market_plus_btc_minus_raw_market_log_loss": (
                overall_market_plus_btc["log_loss"] - overall_raw_market["log_loss"]
            ),
        },
        "folds_detail": (fold_reports),
        "important_notes": [
            ("All comparisons use identical forward rows."),
            ("No market appears in training before its test fold."),
            (
                "The market-only logistic comparator "
                "separates simple market recalibration "
                "from incremental BTC-feature value."
            ),
            (
                "A negative market_plus_btc minus "
                "market_only metric indicates improvement."
            ),
            (
                "All data through 2026-10-01 is "
                "research data and is not untouched "
                "validation for any strategy selected "
                "from P11.5."
            ),
        ],
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

    print("P11.5 market-anchored walk-forward evaluation complete")

    print()

    print(
        "folds=",
        len(fold_reports),
    )

    print(
        "prediction rows=",
        len(output_rows),
    )

    print(
        "markets=",
        report["markets"],
    )

    print(
        "missing BTC predictions=",
        missing_btc_predictions,
    )

    print()

    for fold in fold_reports:
        print(
            fold["fold_date"],
            "train_markets=",
            fold["train_markets"],
            "test_markets=",
            fold["test_markets"],
            "rows=",
            fold["test_rows_common"],
        )

        print(
            "  raw market Brier=",
            round(
                fold["raw_market"]["brier_score"],
                6,
            ),
            "market-only=",
            round(
                fold["market_only_logistic"]["brier_score"],
                6,
            ),
            "market+BTC=",
            round(
                fold["market_plus_btc"]["brier_score"],
                6,
            ),
            "BTC-only=",
            round(
                fold["btc_only_walk_forward"]["brier_score"],
                6,
            ),
        )

        print(
            "  market+BTC - market-only Brier=",
            round(
                fold["market_plus_btc_minus_market_only_brier"],
                6,
            ),
            "logloss=",
            round(
                fold["market_plus_btc_minus_market_only_log_loss"],
                6,
            ),
        )

    print()

    print("OVERALL")

    for name in (
        "raw_market",
        "market_only_logistic",
        "market_plus_btc",
        "btc_only_walk_forward",
    ):
        result = report["overall"][name]

        print(
            name,
            "Brier=",
            round(
                result["brier_score"],
                6,
            ),
            "logloss=",
            round(
                result["log_loss"],
                6,
            ),
            "accuracy=",
            round(
                result["accuracy"],
                6,
            ),
        )

    print()

    print(
        "market+BTC - market-only Brier=",
        round(
            report["overall"]["market_plus_btc_minus_market_only_brier"],
            6,
        ),
    )

    print(
        "market+BTC - market-only logloss=",
        round(
            report["overall"]["market_plus_btc_minus_market_only_log_loss"],
            6,
        ),
    )

    print(
        "market+BTC - raw market Brier=",
        round(
            report["overall"]["market_plus_btc_minus_raw_market_brier"],
            6,
        ),
    )

    print(
        "market+BTC - raw market logloss=",
        round(
            report["overall"]["market_plus_btc_minus_raw_market_log_loss"],
            6,
        ),
    )

    print()

    print(f"Wrote {OUTPUT_PREDICTIONS}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
