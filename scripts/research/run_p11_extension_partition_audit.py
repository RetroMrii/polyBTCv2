from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

ORIGINAL_PARTITIONS_FILE = ROOT / "data" / "normalized" / "p11_market_partitions.csv"

OUTPUT_PARTITIONS = ROOT / "data" / "normalized" / "p11_extension_market_partitions.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_extension_partition_audit.json"


REPORT_VERSION = "p11_extension_partition_v1"


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def main() -> None:
    p4_rows = load_csv(P4_FILE)

    original_partition_rows = load_csv(ORIGINAL_PARTITIONS_FILE)

    original_market_ids = {
        row["condition_id"].strip().lower() for row in original_partition_rows
    }

    current_market_ids = {row["condition_id"].strip().lower() for row in p4_rows}

    missing_original_markets = original_market_ids - current_market_ids

    if missing_original_markets:
        raise RuntimeError(
            "markets from the original P11 "
            "universe are missing from current P4: "
            f"{len(missing_original_markets)}"
        )

    extension_market_ids = current_market_ids - original_market_ids

    if not extension_market_ids:
        raise RuntimeError("no new extension markets found")

    rows_by_market = {}

    for row in p4_rows:
        condition_id = row["condition_id"].strip().lower()

        rows_by_market.setdefault(
            condition_id,
            [],
        ).append(row)

    output_rows = []

    for condition_id in sorted(current_market_ids):
        market_rows = rows_by_market[condition_id]

        first_prediction = min(row["prediction_timestamp"] for row in market_rows)

        last_prediction = max(row["prediction_timestamp"] for row in market_rows)

        if condition_id in extension_market_ids:
            partition = "P11_EXTENSION"
        else:
            partition = "ORIGINAL_P11_UNIVERSE"

        output_rows.append(
            {
                "partition_version": (REPORT_VERSION),
                "condition_id": (condition_id),
                "partition": (partition),
                "first_prediction_timestamp": (first_prediction),
                "last_prediction_timestamp": (last_prediction),
                "rows": len(market_rows),
            }
        )

    extension_rows = [
        row
        for row in p4_rows
        if (row["condition_id"].strip().lower() in extension_market_ids)
    ]

    extension_first = min(row["prediction_timestamp"] for row in extension_rows)

    extension_last = max(row["prediction_timestamp"] for row in extension_rows)

    row_status_counts = Counter(row["row_status"] for row in extension_rows)

    rows_by_horizon = Counter(
        int(row["target_horizon_seconds"]) for row in extension_rows
    )

    with OUTPUT_PARTITIONS.open(
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

    report = {
        "report_version": (REPORT_VERSION),
        "definition": (
            "P11_EXTENSION consists only of "
            "markets present in refreshed P4 "
            "that were absent from the original "
            "p11_market_partitions.csv universe."
        ),
        "current_p4": {
            "markets": len(current_market_ids),
            "rows": len(p4_rows),
        },
        "original_p11_universe": {
            "markets": len(original_market_ids),
        },
        "extension": {
            "markets": len(extension_market_ids),
            "rows": len(extension_rows),
            "first_prediction_timestamp": (extension_first),
            "last_prediction_timestamp": (extension_last),
            "row_status_counts": dict(row_status_counts),
            "rows_by_horizon": {
                str(key): value for key, value in sorted(rows_by_horizon.items())
            },
        },
        "overlap_checks": {
            "extension_vs_original_markets": (
                len(extension_market_ids & original_market_ids)
            ),
            "original_markets_missing_from_current_p4": (len(missing_original_markets)),
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

    print("P11 extension partition audit complete")

    print()

    print(
        "current P4 markets=",
        len(current_market_ids),
    )

    print(
        "original P11 universe markets=",
        len(original_market_ids),
    )

    print(
        "extension markets=",
        len(extension_market_ids),
    )

    print(
        "extension rows=",
        len(extension_rows),
    )

    print(
        "extension first=",
        extension_first,
    )

    print(
        "extension last=",
        extension_last,
    )

    print(
        "extension overlap with original=",
        len(extension_market_ids & original_market_ids),
    )

    print(
        "status=",
        dict(row_status_counts),
    )

    print(
        "rows_by_horizon=",
        dict(sorted(rows_by_horizon.items())),
    )

    print()

    print(f"Wrote {OUTPUT_PARTITIONS}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
