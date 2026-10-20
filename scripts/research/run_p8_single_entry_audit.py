from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_single_entry_audit.json"

THRESHOLDS = (
    0.00,
    0.02,
    0.05,
    0.10,
    0.15,
)


def load_records() -> list[dict]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    result = []

    for row in rows:
        result.append(
            {
                "split": row["split"],
                "condition_id": (row["condition_id"].strip().lower()),
                "target_horizon_seconds": int(row["target_horizon_seconds"]),
                "selected_side": (row["selected_side"]),
                "selected_ask": float(row["selected_ask"]),
                "selected_edge": float(row["selected_edge"]),
                "realized_pnl_per_share": float(row["realized_pnl_per_share"]),
                "side_won": (row["side_won"].strip().lower() == "true"),
            }
        )

    return result


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

    for market_records in by_market.values():
        ordered = sorted(
            market_records,
            key=lambda item: -item["target_horizon_seconds"],
        )

        for record in ordered:
            if record["selected_edge"] >= threshold:
                selected.append(record)
                break

    return selected


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
            "total_realized_pnl_per_share": 0.0,
            "win_rate": None,
            "side_counts": {},
            "horizon_counts": {},
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
        "total_realized_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in records)
        ),
        "win_rate": (sum(1 for row in records if row["side_won"]) / len(records)),
        "side_counts": dict(
            sorted(Counter(row["selected_side"] for row in records).items())
        ),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["target_horizon_seconds"]) for row in records).items(),
                reverse=True,
            )
        ),
    }


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_single_entry_audit_v1"),
        "policy": (
            "At most one entry per market. "
            "Evaluate horizons chronologically "
            "from 240s to 30s and take the "
            "first row whose selected gross "
            "edge meets the threshold."
        ),
        "costs_excluded": [
            "fees",
            "slippage",
            "latency",
            "partial fills",
            "fill failure",
        ],
    }

    for split in (
        "validation",
        "development_holdout",
    ):
        split_rows = [row for row in rows if row["split"] == split]

        threshold_results = {}

        for threshold in THRESHOLDS:
            selected = first_qualifying_entries(
                split_rows,
                threshold,
            )

            threshold_results[f"{threshold:.2f}"] = summarize(selected)

        report[split] = {"thresholds": (threshold_results)}

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
