from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_temporal_audit.json"


THRESHOLDS = (
    0.00,
    0.02,
    0.05,
)


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_records() -> list[dict]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    records = []

    for row in rows:
        records.append(
            {
                "split": row["split"],
                "condition_id": (row["condition_id"].strip().lower()),
                "prediction_timestamp": parse_dt(row["prediction_timestamp"]),
                "target_horizon_seconds": int(row["target_horizon_seconds"]),
                "selected_side": (row["selected_side"].strip()),
                "selected_ask": float(row["selected_ask"]),
                "selected_edge": float(row["selected_edge"]),
                "realized_pnl_per_share": float(row["realized_pnl_per_share"]),
                "side_won": (row["side_won"].strip().lower() == "true"),
            }
        )

    return records


def first_qualifying_entries(
    records: list[dict],
    threshold: float,
) -> list[dict]:
    by_market: dict[
        str,
        list[dict],
    ] = {}

    for record in records:
        by_market.setdefault(
            record["condition_id"],
            [],
        ).append(record)

    selected = []

    for market_rows in by_market.values():
        ordered = sorted(
            market_rows,
            key=lambda item: (
                -item["target_horizon_seconds"],
                item["prediction_timestamp"],
            ),
        )

        for record in ordered:
            if record["selected_edge"] >= threshold:
                selected.append(record)
                break

    return sorted(
        selected,
        key=lambda item: item["prediction_timestamp"],
    )


def side_summary(
    records: list[dict],
    side: str,
) -> dict:
    selected = [row for row in records if row["selected_side"] == side]

    if not selected:
        return {
            "trades": 0,
            "mean_realized_pnl_per_share": None,
            "win_rate": None,
        }

    return {
        "trades": len(selected),
        "mean_realized_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in selected) / len(selected)
        ),
        "win_rate": (sum(row["side_won"] for row in selected) / len(selected)),
    }


def summarize(
    records: list[dict],
) -> dict:
    if not records:
        return {
            "trades": 0,
            "markets": 0,
            "mean_predicted_edge": None,
            "mean_entry_price": None,
            "mean_realized_pnl_per_share": None,
            "win_rate": None,
            "side_counts": {},
            "horizon_counts": {},
            "yes": side_summary(
                [],
                "YES",
            ),
            "no": side_summary(
                [],
                "NO",
            ),
        }

    return {
        "trades": len(records),
        "markets": len({row["condition_id"] for row in records}),
        "mean_predicted_edge": (
            sum(row["selected_edge"] for row in records) / len(records)
        ),
        "mean_entry_price": (
            sum(row["selected_ask"] for row in records) / len(records)
        ),
        "mean_realized_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in records) / len(records)
        ),
        "win_rate": (sum(row["side_won"] for row in records) / len(records)),
        "side_counts": dict(
            sorted(Counter(row["selected_side"] for row in records).items())
        ),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["target_horizon_seconds"]) for row in records).items(),
                reverse=True,
            )
        ),
        "yes": side_summary(
            records,
            "YES",
        ),
        "no": side_summary(
            records,
            "NO",
        ),
    }


def split_into_thirds(
    records: list[dict],
) -> dict[
    str,
    list[dict],
]:
    ordered = sorted(
        records,
        key=lambda item: item["prediction_timestamp"],
    )

    count = len(ordered)

    first_cut = count // 3

    second_cut = 2 * count // 3

    return {
        "early": (ordered[:first_cut]),
        "middle": (ordered[first_cut:second_cut]),
        "late": (ordered[second_cut:]),
    }


def temporal_report(
    records: list[dict],
    threshold: float,
) -> dict:
    selected = first_qualifying_entries(
        records,
        threshold,
    )

    thirds = split_into_thirds(selected)

    result = {
        "all": summarize(selected),
        "thirds": {},
    }

    for name, block in thirds.items():
        if block:
            start_at = block[0]["prediction_timestamp"].isoformat()

            end_at = block[-1]["prediction_timestamp"].isoformat()
        else:
            start_at = None
            end_at = None

        result["thirds"][name] = {
            "start_at": (start_at),
            "end_at": (end_at),
            "summary": summarize(block),
        }

    return result


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_temporal_audit_v1"),
        "policy": (
            "At most one entry per market. "
            "Take the first chronological "
            "horizon whose selected gross "
            "edge meets the threshold."
        ),
        "thresholds": list(THRESHOLDS),
    }

    for split in (
        "validation",
        "development_holdout",
    ):
        split_rows = [row for row in rows if row["split"] == split]

        report[split] = {}

        for threshold in THRESHOLDS:
            report[split][f"{threshold:.2f}"] = temporal_report(
                split_rows,
                threshold,
            )

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
