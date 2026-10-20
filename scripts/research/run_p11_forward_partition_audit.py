from __future__ import annotations

import csv
import json

from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

FROZEN_RESEARCH_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_ASSIGNMENTS = ROOT / "data" / "normalized" / "p11_market_partitions.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_forward_partition_audit.json"


REPORT_VERSION = "p11_forward_partition_audit_v1"


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.strip().replace(
            "Z",
            "+00:00",
        )
    )


def iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    return value.isoformat()


def build_market_ranges(
    rows: list[dict[str, str]],
) -> dict[str, dict]:
    grouped = defaultdict(list)

    for row in rows:
        condition_id = row["condition_id"].strip().lower()

        timestamp = parse_dt(row["prediction_timestamp"])

        grouped[condition_id].append(timestamp)

    output = {}

    for condition_id, timestamps in grouped.items():
        output[condition_id] = {
            "condition_id": condition_id,
            "first_prediction_timestamp": min(timestamps),
            "last_prediction_timestamp": max(timestamps),
            "row_count": len(timestamps),
        }

    return output


def main() -> None:
    p4_rows = load_csv(P4_FILE)

    research_rows = load_csv(FROZEN_RESEARCH_FILE)

    p4_markets = build_market_ranges(p4_rows)

    research_ids = {row["condition_id"].strip().lower() for row in research_rows}

    missing_research_markets = research_ids - set(p4_markets)

    if missing_research_markets:
        raise RuntimeError(
            "frozen research markets missing "
            "from refreshed P4: "
            f"{len(missing_research_markets)}"
        )

    research_ranges = [p4_markets[condition_id] for condition_id in research_ids]

    research_first = min(row["first_prediction_timestamp"] for row in research_ranges)

    research_last = max(row["last_prediction_timestamp"] for row in research_ranges)

    assignments = []

    for condition_id, market in sorted(
        p4_markets.items(),
        key=lambda item: (
            item[1]["first_prediction_timestamp"],
            item[0],
        ),
    ):
        first_ts = market["first_prediction_timestamp"]

        last_ts = market["last_prediction_timestamp"]

        if first_ts <= research_last:
            partition = "FROZEN_RESEARCH"

        else:
            partition = "STRICT_FORWARD"
        assignments.append(
            {
                "condition_id": (condition_id),
                "partition": (partition),
                "first_prediction_timestamp": (iso(first_ts)),
                "last_prediction_timestamp": (iso(last_ts)),
                "p4_row_count": (market["row_count"]),
            }
        )

    partition_counts = defaultdict(int)

    partition_rows = defaultdict(int)

    for row in assignments:
        partition_counts[row["partition"]] += 1

        partition_rows[row["partition"]] += int(row["p4_row_count"])

    strict_forward = [
        row for row in assignments if (row["partition"] == "STRICT_FORWARD")
    ]

    if strict_forward:
        forward_first = min(
            parse_dt(row["first_prediction_timestamp"]) for row in strict_forward
        )

        forward_last = max(
            parse_dt(row["last_prediction_timestamp"]) for row in strict_forward
        )
    else:
        forward_first = None
        forward_last = None

    overlap_ids = {row["condition_id"] for row in strict_forward} & research_ids

    if overlap_ids:
        raise RuntimeError("strict forward market overlaps frozen research markets")

    with OUTPUT_ASSIGNMENTS.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        fieldnames = [
            "condition_id",
            "partition",
            "first_prediction_timestamp",
            "last_prediction_timestamp",
            "p4_row_count",
        ]

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(assignments)

    report = {
        "report_version": (REPORT_VERSION),
        "p4_rows": len(p4_rows),
        "p4_markets": len(p4_markets),
        "frozen_research_market_ids": len(research_ids),
        "missing_research_markets": len(missing_research_markets),
        "research_period": {
            "first_prediction_timestamp": (iso(research_first)),
            "last_prediction_timestamp": (iso(research_last)),
        },
        "strict_forward_period": {
            "first_prediction_timestamp": (iso(forward_first)),
            "last_prediction_timestamp": (iso(forward_last)),
        },
        "partitions": {
            partition: {
                "markets": (partition_counts[partition]),
                "rows": (partition_rows[partition]),
            }
            for partition in (
                "FROZEN_RESEARCH",
                "STRICT_FORWARD",
            )
        },
        "strict_forward_markets": (len(strict_forward)),
        "strict_forward_overlap_with_research": (len(overlap_ids)),
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

    print("P11 forward partition audit complete")

    print(
        "P4 markets=",
        len(p4_markets),
    )

    print(
        "frozen research markets=",
        len(research_ids),
    )

    print(
        "research cutoff=",
        iso(research_last),
    )

    print()

    for partition in (
        "FROZEN_RESEARCH",
        "STRICT_FORWARD",
    ):
        print(
            partition,
            "markets=",
            partition_counts[partition],
            "rows=",
            partition_rows[partition],
        )

    print()

    print(
        "strict forward first=",
        iso(forward_first),
    )

    print(
        "strict forward last=",
        iso(forward_last),
    )

    print(
        "strict forward overlap=",
        len(overlap_ids),
    )

    print(f"Wrote {OUTPUT_ASSIGNMENTS}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
