from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

BASELINE_FILE = ROOT / "data" / "normalized" / "p9_baseline_trades.csv"

DATASET_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p9_stoploss_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p9_stoploss_report.json"


POLICY_VERSION = "p9_stoploss_v1"

STOP_LOSSES = (
    0.10,
    0.20,
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


def load_quotes() -> dict[
    str,
    dict[int, dict[str, float | None]],
]:
    markets: dict[
        str,
        dict[int, dict[str, float | None]],
    ] = {}

    with DATASET_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        for row in rows:
            condition_id = row["condition_id"].strip().lower()

            horizon = int(row["target_horizon_seconds"])

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

            market = markets.setdefault(
                condition_id,
                {},
            )

            if horizon in market:
                raise RuntimeError(f"duplicate market/horizon {condition_id} {horizon}")

            market[horizon] = {
                "YES": yes_bid,
                "NO": no_bid,
            }

    return markets


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


def simulate_stop(
    *,
    trade: dict[str, str],
    market_quotes: dict[
        int,
        dict[str, float | None],
    ],
    stop_loss: float,
) -> dict:
    side = trade["side"]

    entry_price = float(trade["entry_price"])

    entry_horizon = int(trade["entry_horizon_seconds"])

    label_yes = int(trade["label_yes"])

    later_horizons = sorted(
        (horizon for horizon in market_quotes if horizon < entry_horizon),
        reverse=True,
    )

    exit_type = "settlement"
    exit_horizon = None

    exit_price = settlement_value(
        side=side,
        label_yes=label_yes,
    )

    for horizon in later_horizons:
        quote = market_quotes[horizon]

        bid = quote.get(side)

        if bid is None:
            continue

        mark_to_market_pnl = float(bid) - entry_price

        if mark_to_market_pnl <= -stop_loss:
            exit_type = "stop_bid"
            exit_horizon = horizon
            exit_price = float(bid)

            break

    realized_pnl = exit_price - entry_price

    return {
        "policy_version": (POLICY_VERSION),
        "strategy_config": (trade["strategy_config"]),
        "split": (trade["split"]),
        "condition_id": (trade["condition_id"]),
        "side": side,
        "entry_timestamp": (trade["entry_timestamp"]),
        "entry_horizon_seconds": (entry_horizon),
        "entry_price": (entry_price),
        "stop_loss_per_share": (stop_loss),
        "exit_type": (exit_type),
        "exit_horizon_seconds": (exit_horizon if exit_horizon is not None else ""),
        "exit_price": (exit_price),
        "label_yes": (label_yes),
        "realized_pnl_per_share": (realized_pnl),
    }


def build_rows(
    baseline: list[dict[str, str]],
    quotes: dict,
) -> list[dict]:
    result = []

    for trade in baseline:
        condition_id = trade["condition_id"].strip().lower()

        market_quotes = quotes.get(
            condition_id,
            {},
        )

        for stop_loss in STOP_LOSSES:
            result.append(
                simulate_stop(
                    trade=trade,
                    market_quotes=market_quotes,
                    stop_loss=stop_loss,
                )
            )

    return result


OUTPUT_FIELDS = (
    "policy_version",
    "strategy_config",
    "split",
    "condition_id",
    "side",
    "entry_timestamp",
    "entry_horizon_seconds",
    "entry_price",
    "stop_loss_per_share",
    "exit_type",
    "exit_horizon_seconds",
    "exit_price",
    "label_yes",
    "realized_pnl_per_share",
)


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
            "trades": 0,
            "mean_pnl_per_share": None,
            "stop_count": 0,
            "settlement_count": 0,
            "positive_pnl_rate": None,
            "side_counts": {},
        }

    return {
        "trades": len(rows),
        "mean_pnl_per_share": (
            sum(row["realized_pnl_per_share"] for row in rows) / len(rows)
        ),
        "stop_count": sum(row["exit_type"] == "stop_bid" for row in rows),
        "settlement_count": sum(row["exit_type"] == "settlement" for row in rows),
        "positive_pnl_rate": (
            sum(row["realized_pnl_per_share"] > 0.0 for row in rows) / len(rows)
        ),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
    }


def main() -> None:
    baseline = load_baseline()

    quotes = load_quotes()

    rows = build_rows(
        baseline,
        quotes,
    )

    write_rows(rows)

    report = {
        "policy_version": (POLICY_VERSION),
        "stop_losses_per_share": list(STOP_LOSSES),
        "important_notes": [
            ("Entry stream is frozen from the P9 hold baseline."),
            ("Stop evaluation uses later recorded horizons only."),
            ("Stops execute against the recorded executable bid."),
            ("If no stop triggers, position is held to settlement."),
            ("No cashout, re-entry, scale-in, reversal, or sizing is applied."),
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

            for stop_loss in STOP_LOSSES:
                selected = [
                    row
                    for row in rows
                    if (
                        row["strategy_config"] == config
                        and row["split"] == split
                        and abs(row["stop_loss_per_share"] - stop_loss) < 1e-12
                    )
                ]

                report["strategy_configs"][config][split][f"{stop_loss:.2f}"] = (
                    summarize(selected)
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

    print(f"stop-policy rows: {len(rows)}")


if __name__ == "__main__":
    main()
