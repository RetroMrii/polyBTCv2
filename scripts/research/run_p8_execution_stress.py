from __future__ import annotations

import csv
import json

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_execution_stress.json"


THRESHOLDS = (
    0.00,
    0.02,
    0.05,
)

ADVERSE_PRICE_MOVES = (
    0.00,
    0.01,
    0.02,
    0.03,
    0.05,
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
                "label_yes": int(row["label_yes"]),
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


def stressed_pnl(
    row: dict,
    adverse_move: float,
) -> float:
    entry_price = min(
        1.0,
        row["selected_ask"] + adverse_move,
    )

    if row["selected_side"] == "YES":
        payout = row["label_yes"]
    else:
        payout = 1 - row["label_yes"]

    return payout - entry_price


def summarize(
    records: list[dict],
    adverse_move: float,
) -> dict:
    if not records:
        return {
            "trades": 0,
            "mean_pnl": None,
            "yes_mean_pnl": None,
            "no_mean_pnl": None,
        }

    pnls = [
        stressed_pnl(
            row,
            adverse_move,
        )
        for row in records
    ]

    yes_rows = [row for row in records if row["selected_side"] == "YES"]

    no_rows = [row for row in records if row["selected_side"] == "NO"]

    def mean_for(
        selected: list[dict],
    ) -> float | None:
        if not selected:
            return None

        return sum(
            stressed_pnl(
                row,
                adverse_move,
            )
            for row in selected
        ) / len(selected)

    return {
        "trades": len(records),
        "mean_pnl": (sum(pnls) / len(pnls)),
        "yes_trades": len(yes_rows),
        "yes_mean_pnl": mean_for(yes_rows),
        "no_trades": len(no_rows),
        "no_mean_pnl": mean_for(no_rows),
    }


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_execution_stress_v1"),
        "interpretation": (
            "Adverse price move is added "
            "to observed executable ask. "
            "Spread is already included "
            "because entry uses ask."
        ),
        "thresholds": list(THRESHOLDS),
        "adverse_price_moves": list(ADVERSE_PRICE_MOVES),
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

            stresses = {}

            for move in ADVERSE_PRICE_MOVES:
                stresses[f"{move:.2f}"] = summarize(
                    selected,
                    move,
                )

            report[split][f"{threshold:.2f}"] = stresses

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
