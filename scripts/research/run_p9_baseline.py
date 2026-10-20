from __future__ import annotations

import csv
import json
import sys

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(
        0,
        str(SRC),
    )


from polybtc.position.policies import (
    BASELINE_HOLD_POLICY,
)


INPUT_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p9_baseline_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p9_baseline_report.json"


POLICY_VERSION = "p9_baseline_v1"


OUTPUT_FIELDS = (
    "policy_version",
    "policy_id",
    "strategy_config",
    "split",
    "condition_id",
    "entry_timestamp",
    "entry_horizon_seconds",
    "side",
    "entry_price",
    "predicted_net_ev_per_share",
    "label_yes",
    "settlement_value",
    "realized_pnl_per_share",
    "won",
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


def build_trades(
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

    trades = []

    for (
        strategy_config,
        split,
        condition_id,
    ), market_rows in grouped.items():
        ordered = sorted(
            market_rows,
            key=lambda row: parse_dt(row["prediction_timestamp"]),
        )

        entry = ordered[0]

        side = entry["selected_side"]

        entry_price = float(entry["selected_price"])

        label_yes = int(entry["label_yes"])

        if side == "YES":
            settlement_value = float(label_yes)

        elif side == "NO":
            settlement_value = float(1 - label_yes)

        else:
            raise RuntimeError(f"unexpected side: {side}")

        realized_pnl = settlement_value - entry_price

        trades.append(
            {
                "policy_version": (POLICY_VERSION),
                "policy_id": (BASELINE_HOLD_POLICY.policy_id.value),
                "strategy_config": (strategy_config),
                "split": split,
                "condition_id": (condition_id),
                "entry_timestamp": (entry["prediction_timestamp"]),
                "entry_horizon_seconds": (entry["target_horizon_seconds"]),
                "side": side,
                "entry_price": (entry_price),
                "predicted_net_ev_per_share": float(entry["selected_net_ev_per_share"]),
                "label_yes": (label_yes),
                "settlement_value": (settlement_value),
                "realized_pnl_per_share": (realized_pnl),
                "won": (settlement_value == 1.0),
            }
        )

    return sorted(
        trades,
        key=lambda row: (
            row["strategy_config"],
            row["split"],
            row["entry_timestamp"],
        ),
    )


def write_trades(
    trades: list[dict],
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
        writer.writerows(trades)


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "trades": 0,
            "markets": 0,
            "mean_pnl_per_share": None,
            "total_pnl_per_share": 0.0,
            "win_rate": None,
            "mean_entry_price": None,
            "side_counts": {},
            "horizon_counts": {},
        }

    return {
        "trades": len(rows),
        "markets": len({row["condition_id"] for row in rows}),
        "mean_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in rows) / len(rows)
        ),
        "total_pnl_per_share": (sum(row["realized_pnl_per_share"] for row in rows)),
        "win_rate": (sum(row["won"] for row in rows) / len(rows)),
        "mean_entry_price": (sum(row["entry_price"] for row in rows) / len(rows)),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["entry_horizon_seconds"]) for row in rows).items(),
                reverse=True,
            )
        ),
    }


def build_report(
    trades: list[dict],
) -> dict:
    strategy_configs = sorted({row["strategy_config"] for row in trades})

    report = {
        "policy_version": (POLICY_VERSION),
        "policy_id": (BASELINE_HOLD_POLICY.policy_id.value),
        "position_size_shares": (1.0),
        "policy": {
            "maximum_entries_per_market": 1,
            "exit_policy": ("hold_to_settlement"),
            "reentry_policy": ("none"),
            "scale_in": False,
            "scale_out": False,
            "reversal": False,
        },
        "important_notes": [
            ("This is the P9 control position policy."),
            ("The first chronological TRADE signal is used."),
            ("All later strategy signals for that market are ignored."),
            (
                "No cashout, stop loss, "
                "re-entry, scale-in, scale-out, "
                "or reversal is applied."
            ),
            ("PnL is settlement-value minus recorded executable entry ask."),
        ],
        "strategy_configs": {},
    }

    for config in strategy_configs:
        report["strategy_configs"][config] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            selected = [
                row
                for row in trades
                if (row["strategy_config"] == config and row["split"] == split)
            ]

            report["strategy_configs"][config][split] = summarize(selected)

    return report


def main() -> None:
    rows = load_rows()

    trades = build_trades(rows)

    write_trades(trades)

    report = build_report(trades)

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

    print(f"baseline trades: {len(trades)}")


if __name__ == "__main__":
    main()
