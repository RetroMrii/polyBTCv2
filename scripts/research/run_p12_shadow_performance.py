from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

DECISIONS_FILE = ROOT / "data" / "shadow" / "p12_consensus_shadow_decisions.csv"

RESOLUTIONS_FILE = ROOT / "data" / "shadow" / "p12_market_resolutions.csv"

OUTPUT_SETTLED = ROOT / "data" / "shadow" / "p12_shadow_settled_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "shadow" / "p12_shadow_performance_report.json"


REPORT_VERSION = "p12_shadow_performance_v1"

FEE_RATE = 0.07

SLIPPAGE_TICKS = (
    0,
    1,
    2,
)


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def calculate_taker_fee(
    *,
    filled_size: float,
    execution_price: float,
    fee_rate: float,
) -> float:
    raw_fee = filled_size * fee_rate * execution_price * (1.0 - execution_price)

    return round(
        raw_fee,
        5,
    )


def main() -> None:
    decisions = load_csv(DECISIONS_FILE)

    resolutions = load_csv(RESOLUTIONS_FILE)

    resolution_index = {}

    for row in resolutions:
        condition_id = row["condition_id"].strip().lower()

        if condition_id in resolution_index:
            raise RuntimeError(f"duplicate P12 resolution: {condition_id}")

        resolution_index[condition_id] = row

    decision_counts = Counter(row["decision"].strip() for row in decisions)

    reason_counts = Counter(row["reason"].strip() for row in decisions)

    trade_rows = [row for row in decisions if (row["decision"].strip() == "TRADE")]

    settled_rows = []

    unresolved_trade_markets = []

    for row in trade_rows:
        condition_id = row["condition_id"].strip().lower()

        resolution = resolution_index.get(condition_id)

        if resolution is None:
            unresolved_trade_markets.append(condition_id)
            continue

        if resolution["validation_status"].strip() != "VALID":
            unresolved_trade_markets.append(condition_id)
            continue

        raw_label = resolution["label_yes"].strip()

        if raw_label not in {
            "0",
            "1",
        }:
            raise RuntimeError(
                f"VALID P12 resolution missing binary label: {condition_id}"
            )

        label_yes = int(raw_label)

        side = row["side"].strip()

        if side not in {
            "YES",
            "NO",
        }:
            raise RuntimeError(f"TRADE row has invalid side: {condition_id}")

        selected_ask = optional_float(row["selected_ask"])

        if selected_ask is None:
            raise RuntimeError(f"TRADE row missing selected_ask: {condition_id}")

        if side == "YES":
            won = label_yes == 1
        else:
            won = label_yes == 0

        # P12 paper sizing remains one
        # minimum-size 5-share order.
        filled_size = 5.0

        tick_size = optional_float(row.get("selected_tick_size"))

        tick_size_source = "shadow_telemetry"

        if tick_size is None:
            # Legacy p12_consensus_shadow_v1
            # rows predate selected_tick_size.
            tick_size = 0.01

            tick_size_source = "legacy_assumed_0.01"

        if tick_size <= 0.0:
            raise RuntimeError(
                f"invalid selected tick size: {condition_id} {tick_size}"
            )
        for slippage_ticks in SLIPPAGE_TICKS:
            execution_price = selected_ask + (slippage_ticks * tick_size)

            execution_price = min(
                execution_price,
                0.99,
            )

            fee = calculate_taker_fee(
                filled_size=(filled_size),
                execution_price=(execution_price),
                fee_rate=(FEE_RATE),
            )

            settlement_value = filled_size if won else 0.0

            gross_cost = filled_size * execution_price

            net_pnl = settlement_value - gross_cost - fee

            settled_rows.append(
                {
                    "report_version": (REPORT_VERSION),
                    "condition_id": (condition_id),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "target_horizon_seconds": (int(row["target_horizon_seconds"])),
                    "side": (side),
                    "label_yes": (label_yes),
                    "won": int(won),
                    "model_probability": (row["model_probability"]),
                    "market_probability": (row["market_probability"]),
                    "probability_gap": (row["probability_gap"]),
                    "selected_ask": (selected_ask),
                    "selected_depth": (row["selected_depth"]),
                    "selected_book_age_ms": (row["selected_book_age_ms"]),
                    "tick_size": (tick_size),
                    "tick_size_source": (tick_size_source),
                    "slippage_ticks": (slippage_ticks),
                    "execution_price": (execution_price),
                    "filled_size": (filled_size),
                    "fee": (fee),
                    "settlement_value": (settlement_value),
                    "gross_cost": (gross_cost),
                    "net_pnl": (net_pnl),
                    "net_pnl_per_share": (net_pnl / filled_size),
                }
            )

    OUTPUT_SETTLED.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if settled_rows:
        with OUTPUT_SETTLED.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(settled_rows[0].keys()),
            )

            writer.writeheader()
            writer.writerows(settled_rows)

    scenarios = {}

    for slippage_ticks in SLIPPAGE_TICKS:
        rows = [
            row
            for row in settled_rows
            if (int(row["slippage_ticks"]) == slippage_ticks)
        ]

        if not rows:
            scenarios[f"slip_{slippage_ticks}tick"] = {
                "entries": 0,
            }
            continue

        wins = sum(int(row["won"]) for row in rows)

        total_pnl = sum(float(row["net_pnl"]) for row in rows)

        total_shares = sum(float(row["filled_size"]) for row in rows)

        total_cost = sum(float(row["gross_cost"]) + float(row["fee"]) for row in rows)

        by_side = {}

        for side in (
            "YES",
            "NO",
        ):
            side_rows = [row for row in rows if (row["side"] == side)]

            if not side_rows:
                continue

            side_pnl = sum(float(row["net_pnl"]) for row in side_rows)

            side_shares = sum(float(row["filled_size"]) for row in side_rows)

            by_side[side] = {
                "entries": len(side_rows),
                "net_pnl": (side_pnl),
                "net_pnl_per_share": (side_pnl / side_shares),
            }

        scenarios[f"slip_{slippage_ticks}tick"] = {
            "entries": len(rows),
            "wins": (wins),
            "losses": (len(rows) - wins),
            "win_rate": (wins / len(rows)),
            "net_pnl": (total_pnl),
            "net_pnl_per_share": (total_pnl / total_shares),
            "roi": (total_pnl / total_cost if total_cost else None),
            "by_side": (by_side),
        }

    resolved_trade_market_ids = {row["condition_id"] for row in settled_rows}

    report = {
        "report_version": (REPORT_VERSION),
        "shadow_decisions": len(decisions),
        "decision_counts": dict(decision_counts),
        "reason_counts": dict(reason_counts),
        "trade_markets": len(trade_rows),
        "resolved_trade_markets": len(resolved_trade_market_ids),
        "unresolved_trade_markets": (unresolved_trade_markets),
        "scenarios": (scenarios),
        "important_notes": [
            (
                "Shadow schema v2 persists the "
                "contemporaneous selected-side tick "
                "size. Legacy v1 trades fall back "
                "to the historical 0.01 assumption."
            ),
            ("Only VALID P12 resolution labels are used for settlement."),
            ("Current sample size is too small for profitability conclusions."),
            (
                "Tick size is temporarily fixed at "
                "0.01 because the P12 shadow decision "
                "schema does not yet persist the "
                "selected-side tick size."
            ),
        ],
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

    print("P12 shadow performance evaluation complete")

    print()

    print(
        "shadow decisions=",
        len(decisions),
    )

    print(
        "trade markets=",
        len(trade_rows),
    )

    print(
        "resolved trade markets=",
        len(resolved_trade_market_ids),
    )

    print(
        "unresolved trade markets=",
        len(unresolved_trade_markets),
    )

    print()

    for name in (
        "slip_0tick",
        "slip_1tick",
        "slip_2tick",
    ):
        result = scenarios[name]

        print(
            name,
            result,
        )

    print()

    print(f"Wrote {OUTPUT_SETTLED}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
