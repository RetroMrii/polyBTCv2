from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p9_scalein_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p9_scalein_report.json"


POLICY_VERSION = "p9_scalein_v1"

MAX_ENTRIES = 2


OUTPUT_FIELDS = (
    "policy_version",
    "strategy_config",
    "split",
    "condition_id",
    "side",
    "entry_count",
    "entry_1_horizon_seconds",
    "entry_1_price",
    "entry_2_horizon_seconds",
    "entry_2_price",
    "average_entry_price",
    "label_yes",
    "settlement_value",
    "total_realized_pnl",
    "realized_pnl_per_share",
)


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_rows() -> list[dict[str, str]]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def settlement_value(
    *,
    side: str,
    label_yes: int,
) -> float:
    if side == "YES":
        return float(label_yes)

    if side == "NO":
        return float(1 - label_yes)

    raise RuntimeError(f"unexpected side: {side}")


def build_positions(
    rows: list[dict[str, str]],
) -> list[dict]:
    grouped: dict[
        tuple[str, str, str],
        list[dict[str, str]],
    ] = {}

    for row in rows:
        if row["action"] != "TRADE":
            continue

        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"],
        )

        grouped.setdefault(
            key,
            [],
        ).append(row)

    result = []

    for (
        strategy_config,
        split,
        condition_id,
    ), market_rows in grouped.items():
        ordered = sorted(
            market_rows,
            key=lambda row: parse_dt(row["prediction_timestamp"]),
        )

        first = ordered[0]

        side = first["selected_side"]

        entries = [first]

        for candidate in ordered[1:]:
            if len(entries) >= MAX_ENTRIES:
                break

            if candidate["selected_side"] != side:
                continue

            entries.append(candidate)

        label_yes = int(first["label_yes"])

        settle = settlement_value(
            side=side,
            label_yes=label_yes,
        )

        prices = [float(entry["selected_price"]) for entry in entries]

        total_pnl = sum(settle - price for price in prices)

        pnl_per_share = total_pnl / len(prices)

        second = entries[1] if len(entries) > 1 else None

        result.append(
            {
                "policy_version": (POLICY_VERSION),
                "strategy_config": (strategy_config),
                "split": (split),
                "condition_id": (condition_id),
                "side": (side),
                "entry_count": (len(entries)),
                "entry_1_horizon_seconds": (first["target_horizon_seconds"]),
                "entry_1_price": (float(first["selected_price"])),
                "entry_2_horizon_seconds": (
                    second["target_horizon_seconds"] if second is not None else ""
                ),
                "entry_2_price": (
                    float(second["selected_price"]) if second is not None else ""
                ),
                "average_entry_price": (sum(prices) / len(prices)),
                "label_yes": (label_yes),
                "settlement_value": (settle),
                "total_realized_pnl": (total_pnl),
                "realized_pnl_per_share": (pnl_per_share),
            }
        )

    return result


def write_rows(
    rows: list[dict],
) -> None:
    with OUTPUT_TRADES.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(rows)


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "markets": 0,
            "shares": 0,
            "second_entry_markets": 0,
            "mean_entries_per_market": None,
            "mean_pnl_per_share": None,
            "mean_total_pnl_per_market": None,
            "side_counts": {},
        }

    total_shares = sum(row["entry_count"] for row in rows)

    total_pnl = sum(row["total_realized_pnl"] for row in rows)

    return {
        "markets": len(rows),
        "shares": (total_shares),
        "second_entry_markets": sum(row["entry_count"] == 2 for row in rows),
        "mean_entries_per_market": (total_shares / len(rows)),
        "mean_pnl_per_share": (total_pnl / total_shares),
        "mean_total_pnl_per_market": (total_pnl / len(rows)),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
    }


def main() -> None:
    rows = load_rows()

    positions = build_positions(rows)

    write_rows(positions)

    configs = sorted({row["strategy_config"] for row in positions})

    report = {
        "policy_version": (POLICY_VERSION),
        "policy": {
            "maximum_entries_per_market": (MAX_ENTRIES),
            "entry_size_shares": 1.0,
            "second_entry_requires_same_side": (True),
            "exit_policy": ("hold_to_settlement"),
            "reentry_after_exit": False,
            "reversal": False,
        },
        "important_notes": [
            ("First entry is the first chronological TRADE signal."),
            (
                "A second entry is allowed "
                "only on a later TRADE signal "
                "for the same side."
            ),
            ("Each entry represents one normalized share."),
            ("All shares are held to settlement."),
            (
                "Mean PnL per share is the "
                "primary exposure-normalized "
                "comparison with baseline."
            ),
        ],
        "strategy_configs": {},
    }

    for config in configs:
        report["strategy_configs"][config] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            selected = [
                row
                for row in positions
                if (row["strategy_config"] == config and row["split"] == split)
            ]

            report["strategy_configs"][config][split] = summarize(selected)

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT_TRADES}")

    print(f"Wrote {OUTPUT_REPORT}")

    print(f"position rows: {len(positions)}")


if __name__ == "__main__":
    main()
