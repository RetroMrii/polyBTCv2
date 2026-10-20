from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path

from polybtc.strategy.consensus import (
    ConsensusConfig,
    ConsensusDecision,
    ConsensusInput,
    evaluate_consensus,
)


ROOT = Path(__file__).resolve().parents[2]

RESIDUAL_FILE = ROOT / "data" / "normalized" / "p115_residual_dataset.csv"

RAW_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p12_historical_consensus_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p12_historical_consensus_report.json"


REPORT_VERSION = "p12_historical_consensus_v1"

ALLOWED_HORIZONS = {
    60,
    30,
}

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


def raw_key(
    condition_id: str,
    observed_at: str,
) -> tuple[str, str]:
    return (
        condition_id.strip().lower(),
        observed_at.strip(),
    )


def main() -> None:
    residual_rows = load_csv(RESIDUAL_FILE)

    raw_rows = load_csv(RAW_FILE)

    raw_index = {}

    for row in raw_rows:
        key = raw_key(
            row["market_id"],
            row["observed_at"],
        )

        if key in raw_index:
            raise RuntimeError(f"duplicate raw snapshot key: {key}")

        raw_index[key] = row

    config = ConsensusConfig(
        allowed_horizons_seconds=(
            60,
            30,
        ),
        max_probability_gap=0.05,
        max_book_age_ms=500.0,
        minimum_depth=5.0,
    )

    eligible_rows = []

    missing_raw = 0

    for row in residual_rows:
        horizon = int(row["target_horizon_seconds"])

        if horizon not in ALLOWED_HORIZONS:
            continue

        key = raw_key(
            row["condition_id"],
            row["snapshot_observed_at"],
        )

        raw = raw_index.get(key)

        if raw is None:
            missing_raw += 1
            continue

        eligible_rows.append(
            (
                row,
                raw,
            )
        )

    eligible_rows.sort(
        key=lambda item: (
            item[0]["prediction_timestamp"],
            -int(item[0]["target_horizon_seconds"]),
            item[0]["condition_id"],
        )
    )

    traded_markets = set()

    reason_counts = Counter()

    trade_rows = []

    candidate_rows = 0
    shadow_entries = 0

    by_split_entries = Counter()
    by_horizon_entries = Counter()
    by_side_entries = Counter()

    for row, raw in eligible_rows:
        condition_id = row["condition_id"].strip().lower()

        horizon = int(row["target_horizon_seconds"])

        model_probability = float(row["model_probability"])

        market_probability = optional_float(row["market_probability"])

        candidate_rows += 1

        if condition_id in traded_markets:
            reason_counts["market_already_has_shadow_entry"] += 1
            continue

        consensus = evaluate_consensus(
            candidate=ConsensusInput(
                condition_id=(condition_id),
                target_horizon_seconds=(horizon),
                model_probability=(model_probability),
                market_probability=(market_probability),
                yes_ask=optional_float(row["yes_ask"]),
                no_ask=optional_float(row["no_ask"]),
                yes_top_depth=optional_float(row["yes_top_depth"]),
                no_top_depth=optional_float(row["no_top_depth"]),
                yes_book_age_ms=optional_float(row["yes_book_age_ms"]),
                no_book_age_ms=optional_float(row["no_book_age_ms"]),
            ),
            config=config,
        )

        reason_counts[consensus.reason] += 1

        if consensus.decision != ConsensusDecision.TRADE:
            continue

        if consensus.side is None or consensus.selected_ask is None:
            raise RuntimeError("TRADE result missing side/ask")

        side = consensus.side.value

        if side == "YES":
            tick_size = optional_float(raw.get("yes_tick_size"))
        else:
            tick_size = optional_float(raw.get("no_tick_size"))

        if tick_size is None:
            raise RuntimeError(f"trade candidate missing tick size: {condition_id}")

        label_yes = int(row["label_yes"])

        outcome_won = label_yes == 1 if side == "YES" else label_yes == 0

        traded_markets.add(condition_id)

        shadow_entries += 1

        by_split_entries[row["source_split"]] += 1

        by_horizon_entries[horizon] += 1

        by_side_entries[side] += 1

        for slippage_ticks in SLIPPAGE_TICKS:
            execution_price = consensus.selected_ask + (slippage_ticks * tick_size)

            execution_price = min(
                execution_price,
                0.99,
            )

            filled_size = 5.0

            fee = calculate_taker_fee(
                filled_size=filled_size,
                execution_price=execution_price,
                fee_rate=FEE_RATE,
            )

            settlement_value = filled_size if outcome_won else 0.0

            gross_cost = filled_size * execution_price

            net_pnl = settlement_value - gross_cost - fee

            net_pnl_per_share = net_pnl / filled_size

            trade_rows.append(
                {
                    "report_version": (REPORT_VERSION),
                    "source_split": (row["source_split"]),
                    "condition_id": (condition_id),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "snapshot_observed_at": (row["snapshot_observed_at"]),
                    "target_horizon_seconds": (horizon),
                    "side": (side),
                    "label_yes": (label_yes),
                    "won": int(outcome_won),
                    "model_probability": (model_probability),
                    "market_probability": (market_probability),
                    "probability_gap": (consensus.probability_gap),
                    "selected_ask": (consensus.selected_ask),
                    "selected_depth": (consensus.selected_depth),
                    "selected_book_age_ms": (consensus.selected_book_age_ms),
                    "tick_size": (tick_size),
                    "slippage_ticks": (slippage_ticks),
                    "execution_price": (execution_price),
                    "filled_size": (filled_size),
                    "fee": (fee),
                    "net_pnl": (net_pnl),
                    "net_pnl_per_share": (net_pnl_per_share),
                }
            )

    if not trade_rows:
        raise RuntimeError("historical consensus backtest produced no trades")

    with OUTPUT_TRADES.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(trade_rows[0].keys()),
        )

        writer.writeheader()
        writer.writerows(trade_rows)

    scenario_reports = {}

    for slippage_ticks in SLIPPAGE_TICKS:
        selected = [
            row for row in trade_rows if int(row["slippage_ticks"]) == slippage_ticks
        ]

        wins = sum(int(row["won"]) for row in selected)

        total_pnl = sum(float(row["net_pnl"]) for row in selected)

        total_cost = sum(
            float(row["filled_size"]) * float(row["execution_price"])
            + float(row["fee"])
            for row in selected
        )

        total_shares = sum(float(row["filled_size"]) for row in selected)

        by_split = {}

        for split in (
            "ORIGINAL_FORWARD",
            "FORWARD_EXTENSION",
        ):
            split_rows = [row for row in selected if (row["source_split"] == split)]

            if split_rows:
                split_pnl = sum(float(row["net_pnl"]) for row in split_rows)

                split_shares = sum(float(row["filled_size"]) for row in split_rows)

                by_split[split] = {
                    "entries": len(split_rows),
                    "net_pnl": (split_pnl),
                    "net_pnl_per_share": (split_pnl / split_shares),
                }

        scenario_reports[f"slip_{slippage_ticks}tick"] = {
            "entries": len(selected),
            "wins": wins,
            "losses": (len(selected) - wins),
            "win_rate": (wins / len(selected)),
            "net_pnl": (total_pnl),
            "net_pnl_per_share": (total_pnl / total_shares),
            "roi": (total_pnl / total_cost if total_cost else None),
            "by_source_split": (by_split),
        }

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "prediction_source": (
                "P11/P11-extension walk-forward out-of-sample probabilities"
            ),
            "policy": ("P12 consensus policy v1"),
            "allowed_horizons_seconds": [
                60,
                30,
            ],
            "max_probability_gap": (0.05),
            "max_book_age_ms": (500.0),
            "minimum_depth": (5.0),
            "maximum_entries_per_market": (1),
            "filled_size": (5.0),
            "fee_rate": (FEE_RATE),
            "slippage_ticks": list(SLIPPAGE_TICKS),
        },
        "candidate_rows": (candidate_rows),
        "markets_with_entry": (shadow_entries),
        "entry_counts": {
            "by_source_split": dict(by_split_entries),
            "by_horizon": {
                str(key): value for key, value in sorted(by_horizon_entries.items())
            },
            "by_side": dict(by_side_entries),
        },
        "reason_counts": dict(reason_counts),
        "missing_raw_lineage": (missing_raw),
        "scenarios": (scenario_reports),
        "important_notes": [
            (
                "This is a historical diagnostic "
                "backtest, not untouched validation "
                "of the P12 consensus policy."
            ),
            ("The P12 policy was designed after inspection of this research period."),
            (
                "Predictions are nevertheless "
                "walk-forward out-of-sample rather "
                "than predictions from the final "
                "P12 model trained on these markets."
            ),
            ("No parameters are selected or changed from this report."),
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

    print("P12 historical consensus backtest complete")

    print()

    print(
        "candidate rows=",
        candidate_rows,
    )

    print(
        "markets with entry=",
        shadow_entries,
    )

    print(
        "entries by split=",
        dict(by_split_entries),
    )

    print(
        "entries by horizon=",
        dict(sorted(by_horizon_entries.items())),
    )

    print(
        "entries by side=",
        dict(by_side_entries),
    )

    print()

    print("REASONS")

    for reason, count in reason_counts.most_common():
        print(
            reason,
            count,
        )

    print()

    print("ECONOMIC SCENARIOS")

    for name in (
        "slip_0tick",
        "slip_1tick",
        "slip_2tick",
    ):
        result = scenario_reports[name]

        print()
        print(
            name,
            "entries=",
            result["entries"],
            "win_rate=",
            round(
                result["win_rate"],
                4,
            ),
            "net/share=",
            round(
                result["net_pnl_per_share"],
                6,
            ),
            "ROI=",
            round(
                result["roi"],
                6,
            ),
        )

        for split, split_result in result["by_source_split"].items():
            print(
                " ",
                split,
                "entries=",
                split_result["entries"],
                "net/share=",
                round(
                    split_result["net_pnl_per_share"],
                    6,
                ),
            )

    print()

    print(f"Wrote {OUTPUT_TRADES}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
