from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

REPORT_FILE = ROOT / "data" / "normalized" / "p4_dataset_report.json"


EXPECTED_DATASET_VERSION = "p4_v1"
EXPECTED_FEATURE_VERSION = "snapshot_history_v1"
EXPECTED_LABEL_VERSION = "p3_v1"

MAX_HORIZON_LAG_SECONDS = 10.0

EXPECTED_HORIZONS = {
    240,
    180,
    120,
    90,
    60,
    30,
}


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


def main() -> None:
    with DATASET_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise RuntimeError("P4 dataset is empty")

    keys: set[tuple[str, int]] = set()

    markets: set[str] = set()

    row_status_counts: Counter[str] = Counter()

    reference_eligible = 0
    book_eligible = 0

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        condition_id = row["condition_id"].strip().lower()

        if not condition_id.startswith("0x"):
            raise RuntimeError(f"invalid condition_id at row {row_number}")

        horizon = int(row["target_horizon_seconds"])

        if horizon not in EXPECTED_HORIZONS:
            raise RuntimeError(f"unexpected horizon at row {row_number}: {horizon}")

        key = (
            condition_id,
            horizon,
        )

        if key in keys:
            raise RuntimeError(f"duplicate market/horizon key: {key}")

        keys.add(key)
        markets.add(condition_id)

        if row["dataset_version"] != EXPECTED_DATASET_VERSION:
            raise RuntimeError(f"unexpected dataset_version at row {row_number}")

        if row["feature_version"] != EXPECTED_FEATURE_VERSION:
            raise RuntimeError(f"unexpected feature_version at row {row_number}")

        if row["label_version"] != EXPECTED_LABEL_VERSION:
            raise RuntimeError(f"unexpected label_version at row {row_number}")

        if row["label_yes"] not in {
            "0",
            "1",
        }:
            raise RuntimeError(f"invalid label at row {row_number}")

        prediction_timestamp = _parse_dt(row["prediction_timestamp"])

        observed_at = _parse_dt(row["snapshot_observed_at"])

        lag_seconds = (prediction_timestamp - observed_at).total_seconds()

        if lag_seconds < 0:
            raise RuntimeError(f"future leakage at row {row_number}: {lag_seconds}")

        if lag_seconds > MAX_HORIZON_LAG_SECONDS:
            raise RuntimeError(f"stale horizon at row {row_number}: {lag_seconds}")

        actual_seconds = float(row["actual_seconds_to_expiry"])

        horizon_gap = float(row["horizon_gap_seconds"])

        if actual_seconds < horizon:
            raise RuntimeError(
                f"snapshot occurs after target horizon at row {row_number}"
            )

        expected_gap = actual_seconds - horizon

        if abs(expected_gap - horizon_gap) > 1e-6:
            raise RuntimeError(f"horizon gap mismatch at row {row_number}")

        if abs(horizon_gap - lag_seconds) > 1e-6:
            raise RuntimeError(f"timestamp/horizon gap mismatch at row {row_number}")

        for field in (
            "reference_price",
            "strike",
            "distance_from_strike",
            "absolute_distance_from_strike",
            "relative_distance_from_strike",
        ):
            if not row[field].strip():
                raise RuntimeError(
                    f"required reference feature {field} missing at row {row_number}"
                )

        eligible_reference = row["eligible_reference_features"].strip() == "True"

        eligible_book = row["eligible_book_features"].strip() == "True"

        if not eligible_reference:
            raise RuntimeError(
                f"reference-ineligible row unexpectedly present at row {row_number}"
            )

        reference_eligible += 1

        book_fields = (
            "yes_mid",
            "no_mid",
            "yes_spread",
            "no_spread",
            "yes_top_depth",
            "no_top_depth",
            "yes_book_imbalance",
            "no_book_imbalance",
            "normalized_yes_mid",
        )

        book_complete = all(row[field].strip() for field in book_fields)

        if eligible_book != book_complete:
            raise RuntimeError(f"book eligibility mismatch at row {row_number}")

        if eligible_book:
            book_eligible += 1

        expected_status = "COMPLETE" if book_complete else "MISSING_BOOK"

        if row["row_status"] != expected_status:
            raise RuntimeError(f"row_status mismatch at row {row_number}")

        row_status_counts[row["row_status"]] += 1

    report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))

    if report["dataset_rows"] != len(rows):
        raise RuntimeError("report dataset row count mismatch")

    if report["markets"] != len(markets):
        raise RuntimeError("report market count mismatch")

    if report["eligible_reference_rows"] != reference_eligible:
        raise RuntimeError("report reference eligibility mismatch")

    if report["eligible_book_rows"] != book_eligible:
        raise RuntimeError("report book eligibility mismatch")

    if report["row_status_counts"] != dict(sorted(row_status_counts.items())):
        raise RuntimeError("report row status counts mismatch")

    print(f"rows={len(rows)}")
    print(f"markets={len(markets)}")
    print(f"unique_keys={len(keys)}")
    print(f"reference_eligible={reference_eligible}")
    print(f"book_eligible={book_eligible}")
    print("P4 validation PASSED")


if __name__ == "__main__":
    main()
