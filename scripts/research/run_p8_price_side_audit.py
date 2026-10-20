from __future__ import annotations

import csv
import json

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_price_side_audit.json"


THRESHOLDS = (
    0.00,
    0.02,
    0.05,
)

PRICE_BUCKETS = (
    (0.00, 0.20),
    (0.20, 0.40),
    (0.40, 0.60),
    (0.60, 0.80),
    (0.80, 1.01),
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
                "selected_side": (row["selected_side"].strip()),
                "selected_ask": float(row["selected_ask"]),
                "selected_edge": float(row["selected_edge"]),
                "realized_pnl_per_share": float(row["realized_pnl_per_share"]),
                "side_won": (row["side_won"].strip().lower() == "true"),
            }
        )

    return result


def first_entries(
    rows: list[dict],
    threshold: float,
) -> list[dict]:
    grouped: dict[
        str,
        list[dict],
    ] = {}

    for row in rows:
        grouped.setdefault(
            row["condition_id"],
            [],
        ).append(row)

    selected = []

    for market_rows in grouped.values():
        ordered = sorted(
            market_rows,
            key=lambda row: -row["target_horizon_seconds"],
        )

        for row in ordered:
            if row["selected_edge"] >= threshold:
                selected.append(row)
                break

    return selected


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "trades": 0,
            "mean_entry_price": None,
            "mean_predicted_edge": None,
            "mean_realized_pnl_per_share": None,
            "win_rate": None,
        }

    return {
        "trades": len(rows),
        "mean_entry_price": (sum(row["selected_ask"] for row in rows) / len(rows)),
        "mean_predicted_edge": (sum(row["selected_edge"] for row in rows) / len(rows)),
        "mean_realized_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in rows) / len(rows)
        ),
        "win_rate": (sum(row["side_won"] for row in rows) / len(rows)),
    }


def price_bucket_report(
    rows: list[dict],
) -> list[dict]:
    result = []

    for lower, upper in PRICE_BUCKETS:
        selected = [row for row in rows if (lower <= row["selected_ask"] < upper)]

        summary = summarize(selected)

        summary.update(
            {
                "lower_price": lower,
                "upper_price": upper,
            }
        )

        result.append(summary)

    return result


def side_report(
    rows: list[dict],
) -> dict:
    result = {}

    for side in (
        "YES",
        "NO",
    ):
        side_rows = [row for row in rows if (row["selected_side"] == side)]

        result[side] = {
            "all": summarize(side_rows),
            "price_buckets": (price_bucket_report(side_rows)),
        }

    return result


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_price_side_audit_v1"),
        "policy": (
            "At most one entry per market. Use first chronological threshold crossing."
        ),
    }

    for split in (
        "validation",
        "development_holdout",
    ):
        split_rows = [row for row in rows if row["split"] == split]

        report[split] = {}

        for threshold in THRESHOLDS:
            selected = first_entries(
                split_rows,
                threshold,
            )

            report[split][f"{threshold:.2f}"] = {
                "all": summarize(selected),
                "sides": side_report(selected),
            }

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
