from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

RESOLUTIONS_FILE = ROOT / "data" / "normalized" / "market_resolutions.csv"

RESOLUTION_REPORT = ROOT / "data" / "normalized" / "p3_resolution_report.json"

REDEEM_REPORT = ROOT / "data" / "normalized" / "p3_redeem_crosscheck_report.json"


def main() -> None:
    with RESOLUTIONS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    condition_ids = [row["condition_id"].strip().lower() for row in rows]

    errors: list[str] = []

    if len(rows) != 295:
        errors.append(f"expected 295 labels, found {len(rows)}")

    if len(condition_ids) != len(set(condition_ids)):
        errors.append("duplicate condition_id detected")

    for row in rows:
        condition_id = row["condition_id"]

        if row["validation_status"] != "VALID":
            errors.append(f"{condition_id}: status={row['validation_status']}")

        if row["label_yes"] not in {"0", "1"}:
            errors.append(f"{condition_id}: invalid label_yes={row['label_yes']!r}")

        outcome = row["winning_outcome"]

        if row["label_yes"] == "1" and outcome != "YES":
            errors.append(f"{condition_id}: label_yes=1 but outcome != YES")

        if row["label_yes"] == "0" and outcome != "NO":
            errors.append(f"{condition_id}: label_yes=0 but outcome != NO")

        if not row["winning_token_id"].strip():
            errors.append(f"{condition_id}: missing winning_token_id")

        if not row["resolved_at"].strip():
            errors.append(f"{condition_id}: missing resolved_at")

        if row["label_version"] != "p3_v1":
            errors.append(
                f"{condition_id}: unexpected label_version={row['label_version']!r}"
            )

    resolution_report = json.loads(RESOLUTION_REPORT.read_text(encoding="utf-8"))

    if resolution_report["problem_markets"] != 0:
        errors.append("p3_resolution_report has problem_markets > 0")

    redeem_report = json.loads(REDEEM_REPORT.read_text(encoding="utf-8"))

    if redeem_report["outcome_mismatches"] != 0:
        errors.append("redeem crosscheck contains mismatches")

    if errors:
        print("P3 VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("P3 VALIDATION PASSED")
    print(f"labels: {len(rows)}")
    print(f"unique_condition_ids: {len(set(condition_ids))}")
    print(f"redeem_matches: {redeem_report['outcome_matches']}")
    print(f"redeem_mismatches: {redeem_report['outcome_mismatches']}")


if __name__ == "__main__":
    main()
