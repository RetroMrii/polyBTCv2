from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

BASELINE_FILE = ROOT / "data" / "normalized" / "p9_baseline_trades.csv"

DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p9_cashout_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p9_cashout_report.json"


POLICY_VERSION = "p9_cashout_v1"

CASHOUT_HORIZONS = (
    60,
    30,
)


OUTPUT_FIELDS = (
    "policy_version",
    "strategy_config",
    "split",
    "condition_id",
    "side",
    "entry_timestamp",
    "entry_horizon_seconds",
    "entry_price",
    "cashout_target_horizon_seconds",
    "exit_type",
    "exit_horizon_seconds",
    "exit_price",
    "label_yes",
    "realized_pnl_per_share",
)


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def load_baseline() -> list[dict[str, str]]:
    with BASELINE_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def load_exit_quotes() -> dict[
    tuple[str, int],
    dict[str, float | None],
]:
    quotes = {}

    with DATASET_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        for row in rows:
            horizon = int(row["target_horizon_seconds"])

            if horizon not in CASHOUT_HORIZONS:
                continue

            yes_mid = optional_float(row.get("yes_mid"))

            yes_spread = optional_float(row.get("yes_spread"))

            no_mid = optional_float(row.get("no_mid"))

            no_spread = optional_float(row.get("no_spread"))

            yes_bid = None
            no_bid = None

            if yes_mid is not None and yes_spread is not None:
                yes_bid = yes_mid - yes_spread / 2.0

            if no_mid is not None and no_spread is not None:
                no_bid = no_mid - no_spread / 2.0

            key = (
                row["condition_id"].strip().lower(),
                horizon,
            )

            if key in quotes:
                raise RuntimeError(f"duplicate P4 market/horizon row: {key}")

            quotes[key] = {
                "YES": yes_bid,
                "NO": no_bid,
            }

    return quotes


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


def build_cashout_trades(
    baseline: list[dict[str, str]],
    exit_quotes: dict,
) -> list[dict]:
    result = []

    for trade in baseline:
        condition_id = trade["condition_id"].strip().lower()

        side = trade["side"]

        entry_horizon = int(trade["entry_horizon_seconds"])

        entry_price = float(trade["entry_price"])

        label_yes = int(trade["label_yes"])

        for target_horizon in CASHOUT_HORIZONS:
            exit_type = "settlement"

            exit_horizon = None

            exit_price = settlement_value(
                side=side,
                label_yes=label_yes,
            )

            if entry_horizon > target_horizon:
                quote = exit_quotes.get(
                    (
                        condition_id,
                        target_horizon,
                    )
                )

                if quote is not None:
                    bid = quote.get(side)

                    if bid is not None:
                        exit_type = "cashout_bid"

                        exit_horizon = target_horizon

                        exit_price = float(bid)

            realized_pnl = exit_price - entry_price

            result.append(
                {
                    "policy_version": (POLICY_VERSION),
                    "strategy_config": (trade["strategy_config"]),
                    "split": (trade["split"]),
                    "condition_id": (condition_id),
                    "side": side,
                    "entry_timestamp": (trade["entry_timestamp"]),
                    "entry_horizon_seconds": (entry_horizon),
                    "entry_price": (entry_price),
                    "cashout_target_horizon_seconds": (target_horizon),
                    "exit_type": (exit_type),
                    "exit_horizon_seconds": (
                        exit_horizon if exit_horizon is not None else ""
                    ),
                    "exit_price": (exit_price),
                    "label_yes": (label_yes),
                    "realized_pnl_per_share": (realized_pnl),
                }
            )

    return result


def write_trades(
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
            "trades": 0,
            "mean_pnl_per_share": None,
            "total_pnl_per_share": 0.0,
            "cashout_count": 0,
            "settlement_count": 0,
            "positive_pnl_rate": None,
            "side_counts": {},
        }

    return {
        "trades": len(rows),
        "mean_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in rows) / len(rows)
        ),
        "total_pnl_per_share": (sum(row["realized_pnl_per_share"] for row in rows)),
        "cashout_count": sum(row["exit_type"] == "cashout_bid" for row in rows),
        "settlement_count": sum(row["exit_type"] == "settlement" for row in rows),
        "positive_pnl_rate": (
            sum(row["realized_pnl_per_share"] > 0.0 for row in rows) / len(rows)
        ),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
    }


def main() -> None:
    baseline = load_baseline()

    exit_quotes = load_exit_quotes()

    rows = build_cashout_trades(
        baseline,
        exit_quotes,
    )

    write_trades(rows)

    report = {
        "policy_version": (POLICY_VERSION),
        "cashout_horizons_seconds": (list(CASHOUT_HORIZONS)),
        "important_notes": [
            ("Entry stream is frozen from the P9 baseline."),
            ("Cashout occurs at the recorded executable bid."),
            (
                "If entry occurs at or after "
                "the target cashout horizon, "
                "the position is held to "
                "settlement."
            ),
            ("If the target bid is missing, the position is held to settlement."),
            (
                "No re-entry, stop loss, "
                "scale-in, reversal, or "
                "position sizing is applied."
            ),
        ],
        "strategy_configs": {},
    }

    configs = sorted({row["strategy_config"] for row in rows})

    for config in configs:
        report["strategy_configs"][config] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            report["strategy_configs"][config][split] = {}

            for horizon in CASHOUT_HORIZONS:
                selected = [
                    row
                    for row in rows
                    if (
                        row["strategy_config"] == config
                        and row["split"] == split
                        and row["cashout_target_horizon_seconds"] == horizon
                    )
                ]

                report["strategy_configs"][config][split][str(horizon)] = summarize(
                    selected
                )

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

    print(f"cashout-policy rows: {len(rows)}")


if __name__ == "__main__":
    main()
