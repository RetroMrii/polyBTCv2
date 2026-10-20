from __future__ import annotations

import csv
import json
import sys

from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(
        0,
        str(SRC),
    )


from polybtc.execution.model import (
    ExecutionRequest,
    ExecutionSide,
    FillStatus,
    MarketExecutionState,
    calculate_taker_fee,
    execute_depth_constrained_crossing,
    settlement_pnl,
)

from polybtc.strategy.expected_value import (
    StrategyAction,
    StrategyParameters,
    evaluate_expected_value,
)

PREDICTIONS_FILE = ROOT / "data" / "normalized" / "p11_extension_frozen_predictions.csv"

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

SNAPSHOTS_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

OUTPUT_DECISIONS = (
    ROOT / "data" / "normalized" / "p11_extension_frozen_strategy_decisions.csv"
)

OUTPUT_TRADES = (
    ROOT / "data" / "normalized" / "p11_extension_frozen_execution_trades.csv"
)

OUTPUT_REPORT = (
    ROOT / "data" / "normalized" / "p11_extension_frozen_strategy_execution_report.json"
)


REPORT_VERSION = "p11_extension_frozen_strategy_execution_v1"

ESTIMATED_STRATEGY_COST_PER_SHARE = 0.0

CRYPTO_TAKER_FEE_RATE = 0.07

STALENESS_THRESHOLDS_MS = (
    250.0,
    500.0,
    1000.0,
)

SLIPPAGE_TICKS = (
    0,
    1,
    2,
)


STRATEGY_CONFIGS = {
    "ev_000_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.00,
    ),
    "ev_002_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.02,
    ),
    "ev_005_all_prices": StrategyParameters(
        minimum_net_ev_per_share=0.05,
    ),
    "ev_000_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.00,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
    "ev_002_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.02,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
    "ev_005_price_040_060": StrategyParameters(
        minimum_net_ev_per_share=0.05,
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    ),
}


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


def lineage_key(
    row: dict[str, str],
) -> tuple[str, str, int]:
    return (
        row["condition_id"].strip().lower(),
        row["prediction_timestamp"].strip(),
        int(row["target_horizon_seconds"]),
    )


def build_p4_index(
    rows: list[dict[str, str]],
) -> dict[
    tuple[str, str, int],
    dict[str, str],
]:
    index = {}

    for row in rows:
        key = lineage_key(row)

        if key in index:
            raise RuntimeError(f"duplicate P4 key: {key}")

        index[key] = row

    return index


def build_snapshot_index(
    rows: list[dict[str, str]],
) -> dict[
    tuple[str, str],
    dict[str, str],
]:
    index = {}

    for row in rows:
        key = (
            row["market_id"].strip().lower(),
            row["observed_at"].strip(),
        )

        if key in index:
            raise RuntimeError(f"duplicate raw snapshot key: {key}")

        index[key] = row

    return index


def build_strategy_decisions(
    prediction_rows: list[dict[str, str]],
    p4_index: dict,
    snapshot_index: dict,
) -> list[dict]:
    decisions = []

    for prediction in prediction_rows:
        key = lineage_key(prediction)

        p4_row = p4_index.get(key)

        if p4_row is None:
            raise RuntimeError(f"P4 lineage missing: {key}")

        observed_at = p4_row["snapshot_observed_at"].strip()

        snapshot = snapshot_index.get(
            (
                prediction["condition_id"].strip().lower(),
                observed_at,
            )
        )

        if snapshot is None:
            raise RuntimeError(f"raw snapshot missing for {key}")

        yes_ask = optional_float(snapshot.get("yes_ask"))

        no_ask = optional_float(snapshot.get("no_ask"))

        if yes_ask is None or no_ask is None:
            continue

        p_yes = float(prediction["raw_probability"])

        for (
            config_name,
            parameters,
        ) in STRATEGY_CONFIGS.items():
            decision = evaluate_expected_value(
                p_yes=p_yes,
                yes_ask=yes_ask,
                no_ask=no_ask,
                estimated_cost_per_share=(ESTIMATED_STRATEGY_COST_PER_SHARE),
                parameters=parameters,
            )

            decisions.append(
                {
                    "report_version": (REPORT_VERSION),
                    "strategy_config": (config_name),
                    "condition_id": (prediction["condition_id"].strip().lower()),
                    "prediction_timestamp": (
                        prediction["prediction_timestamp"].strip()
                    ),
                    "target_horizon_seconds": int(prediction["target_horizon_seconds"]),
                    "snapshot_observed_at": (observed_at),
                    "label_yes": int(prediction["label_yes"]),
                    "p_yes": (p_yes),
                    "p_no": (decision.p_no),
                    "yes_ask": (yes_ask),
                    "no_ask": (no_ask),
                    "yes_gross_ev_per_share": (decision.yes_gross_ev_per_share),
                    "no_gross_ev_per_share": (decision.no_gross_ev_per_share),
                    "action": (decision.action.value),
                    "selected_side": (
                        decision.side.value if decision.side is not None else ""
                    ),
                    "selected_price": (decision.selected_price),
                    "selected_gross_ev_per_share": (
                        decision.selected_gross_ev_per_share
                    ),
                    "selected_net_ev_per_share": (decision.selected_net_ev_per_share),
                    "reason": (decision.reason),
                }
            )

    return decisions


def build_candidate_entries(
    decisions: list[dict],
) -> list[dict]:
    grouped = defaultdict(list)

    for row in decisions:
        if row["action"] != StrategyAction.TRADE.value:
            continue

        key = (
            row["strategy_config"],
            row["condition_id"],
        )

        grouped[key].append(row)

    entries = []

    for (
        strategy_config,
        condition_id,
    ), market_rows in grouped.items():
        ordered = sorted(
            market_rows,
            key=lambda row: row["prediction_timestamp"],
        )

        first = ordered[0]

        side = first["selected_side"]

        selected = [first]

        for candidate in ordered[1:]:
            if len(selected) >= 2:
                break

            if candidate["selected_side"] == side:
                selected.append(candidate)

        for (
            entry_number,
            row,
        ) in enumerate(
            selected,
            start=1,
        ):
            entries.append(
                {
                    "strategy_config": (strategy_config),
                    "condition_id": (condition_id),
                    "entry_number": (entry_number),
                    "side": (side),
                    "prediction_timestamp": (row["prediction_timestamp"]),
                    "target_horizon_seconds": (row["target_horizon_seconds"]),
                    "snapshot_observed_at": (row["snapshot_observed_at"]),
                    "label_yes": (row["label_yes"]),
                    "p_yes": (row["p_yes"]),
                    "selected_price": (row["selected_price"]),
                    "selected_net_ev_per_share": (row["selected_net_ev_per_share"]),
                }
            )

    return entries


def build_execution_results(
    entries: list[dict],
    snapshot_index: dict,
) -> list[dict]:
    results = []

    for entry in entries:
        snapshot = snapshot_index.get(
            (
                entry["condition_id"],
                entry["snapshot_observed_at"],
            )
        )

        if snapshot is None:
            raise RuntimeError("candidate entry raw snapshot missing")

        prefix = "yes" if entry["side"] == "YES" else "no"

        ask = optional_float(snapshot.get(f"{prefix}_ask"))

        ask_size = optional_float(snapshot.get(f"{prefix}_ask_size"))

        book_age_ms = optional_float(snapshot.get(f"{prefix}_book_age_ms"))

        tick_size = optional_float(snapshot.get(f"{prefix}_tick_size"))

        minimum_order_size = optional_float(snapshot.get(f"{prefix}_min_order_size"))

        side = ExecutionSide(entry["side"])

        for max_book_age_ms in STALENESS_THRESHOLDS_MS:
            for slippage_ticks in SLIPPAGE_TICKS:
                scenario = f"age_{int(max_book_age_ms)}ms_slip_{slippage_ticks}tick"

                missing_fields = []

                if ask is None:
                    missing_fields.append("ask")

                if ask_size is None:
                    missing_fields.append("ask_size")

                if book_age_ms is None:
                    missing_fields.append("book_age_ms")

                if tick_size is None:
                    missing_fields.append("tick_size")

                if minimum_order_size is None:
                    missing_fields.append("minimum_order_size")

                if missing_fields:
                    results.append(
                        {
                            "report_version": (REPORT_VERSION),
                            "scenario": (scenario),
                            "max_book_age_ms": (max_book_age_ms),
                            "slippage_ticks": (slippage_ticks),
                            **entry,
                            "ask": (ask),
                            "ask_size": (ask_size),
                            "book_age_ms": (book_age_ms),
                            "tick_size": (tick_size),
                            "minimum_order_size": (minimum_order_size),
                            "requested_size": 0.0,
                            "filled_size": 0.0,
                            "execution_price": None,
                            "fill_status": (FillStatus.REJECTED),
                            "fill_reason": (
                                "missing_execution_telemetry:"
                                + ",".join(missing_fields)
                            ),
                            "entry_notional": 0.0,
                            "gross_realized_pnl": 0.0,
                            "taker_fee": 0.0,
                            "net_realized_pnl": 0.0,
                        }
                    )

                    continue

                assert book_age_ms is not None

                assert minimum_order_size is not None

                assert tick_size is not None

                if book_age_ms > max_book_age_ms:
                    results.append(
                        {
                            "report_version": (REPORT_VERSION),
                            "scenario": (scenario),
                            "max_book_age_ms": (max_book_age_ms),
                            "slippage_ticks": (slippage_ticks),
                            **entry,
                            "ask": (ask),
                            "ask_size": (ask_size),
                            "book_age_ms": (book_age_ms),
                            "tick_size": (tick_size),
                            "minimum_order_size": (minimum_order_size),
                            "requested_size": (minimum_order_size),
                            "filled_size": 0.0,
                            "execution_price": None,
                            "fill_status": (FillStatus.REJECTED),
                            "fill_reason": ("stale_book"),
                            "entry_notional": 0.0,
                            "gross_realized_pnl": 0.0,
                            "taker_fee": 0.0,
                            "net_realized_pnl": 0.0,
                        }
                    )

                    continue

                execution = execute_depth_constrained_crossing(
                    ExecutionRequest(
                        side=side,
                        requested_size=(minimum_order_size),
                    ),
                    MarketExecutionState(
                        yes_ask=(ask if side == ExecutionSide.YES else None),
                        no_ask=(ask if side == ExecutionSide.NO else None),
                    ),
                    available_ask_size=(ask_size),
                    minimum_order_size=(minimum_order_size),
                )

                if execution.status == FillStatus.FILLED:
                    assert execution.execution_price is not None

                    stressed_price = min(
                        1.0,
                        execution.execution_price + (slippage_ticks * tick_size),
                    )

                    gross_pnl = settlement_pnl(
                        side=side,
                        label_yes=int(entry["label_yes"]),
                        execution_price=(stressed_price),
                        filled_size=(execution.filled_size),
                    )

                    fee = calculate_taker_fee(
                        filled_size=(execution.filled_size),
                        execution_price=(stressed_price),
                        fee_rate=(CRYPTO_TAKER_FEE_RATE),
                    )

                    net_pnl = gross_pnl - fee

                    entry_notional = stressed_price * execution.filled_size

                else:
                    stressed_price = None
                    gross_pnl = 0.0
                    fee = 0.0
                    net_pnl = 0.0
                    entry_notional = 0.0

                results.append(
                    {
                        "report_version": (REPORT_VERSION),
                        "scenario": (scenario),
                        "max_book_age_ms": (max_book_age_ms),
                        "slippage_ticks": (slippage_ticks),
                        **entry,
                        "ask": (ask),
                        "ask_size": (ask_size),
                        "book_age_ms": (book_age_ms),
                        "tick_size": (tick_size),
                        "minimum_order_size": (minimum_order_size),
                        "requested_size": (execution.requested_size),
                        "filled_size": (execution.filled_size),
                        "execution_price": (stressed_price),
                        "fill_status": (execution.status),
                        "fill_reason": (execution.reason),
                        "entry_notional": (entry_notional),
                        "gross_realized_pnl": (gross_pnl),
                        "taker_fee": (fee),
                        "net_realized_pnl": (net_pnl),
                    }
                )

    return results


def summarize_strategy(
    decisions: list[dict],
    entries: list[dict],
) -> dict:
    report = {}

    for config in STRATEGY_CONFIGS:
        config_decisions = [
            row for row in decisions if (row["strategy_config"] == config)
        ]

        config_entries = [row for row in entries if (row["strategy_config"] == config)]

        trade_signals = [
            row
            for row in config_decisions
            if (row["action"] == StrategyAction.TRADE.value)
        ]

        report[config] = {
            "decision_rows": len(config_decisions),
            "trade_signals": len(trade_signals),
            "trade_signal_rate": (
                len(trade_signals) / len(config_decisions) if config_decisions else None
            ),
            "candidate_entries_after_p9": (len(config_entries)),
            "candidate_markets": len({row["condition_id"] for row in config_entries}),
            "first_entries": sum(row["entry_number"] == 1 for row in config_entries),
            "second_entries": sum(row["entry_number"] == 2 for row in config_entries),
        }

    return report


def summarize_execution(
    rows: list[dict],
) -> dict:
    report = {}

    scenarios = sorted({row["scenario"] for row in rows})

    for scenario in scenarios:
        report[scenario] = {}

        for config in STRATEGY_CONFIGS:
            selected = [
                row
                for row in rows
                if (row["scenario"] == scenario and row["strategy_config"] == config)
            ]

            filled = [
                row for row in selected if (row["fill_status"] == FillStatus.FILLED)
            ]

            rejected = [
                row for row in selected if (row["fill_status"] == FillStatus.REJECTED)
            ]

            filled_shares = sum(float(row["filled_size"]) for row in filled)

            capital = sum(float(row["entry_notional"]) for row in filled)

            gross_pnl = sum(float(row["gross_realized_pnl"]) for row in filled)

            fees = sum(float(row["taker_fee"]) for row in filled)

            net_pnl = sum(float(row["net_realized_pnl"]) for row in filled)

            report[scenario][config] = {
                "candidate_entries": (len(selected)),
                "filled_entries": (len(filled)),
                "rejected_entries": (len(rejected)),
                "fill_rate": (len(filled) / len(selected) if selected else None),
                "filled_shares": (filled_shares),
                "entry_notional": (capital),
                "gross_realized_pnl": (gross_pnl),
                "total_taker_fees": (fees),
                "net_realized_pnl": (net_pnl),
                "net_pnl_per_share": (
                    net_pnl / filled_shares if filled_shares else None
                ),
                "return_on_entry_notional": (net_pnl / capital if capital else None),
                "rejection_reasons": dict(
                    Counter(row["fill_reason"] for row in rejected)
                ),
            }

    return report


def write_csv(
    rows: list[dict],
    path: Path,
) -> None:
    if not rows:
        raise RuntimeError(f"cannot write empty file: {path}")

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )

        writer.writeheader()

        writer.writerows(rows)


def main() -> None:
    prediction_rows = load_csv(PREDICTIONS_FILE)

    p4_rows = load_csv(P4_FILE)

    snapshot_rows = load_csv(SNAPSHOTS_FILE)

    p4_index = build_p4_index(p4_rows)

    snapshot_index = build_snapshot_index(snapshot_rows)

    decisions = build_strategy_decisions(
        prediction_rows,
        p4_index,
        snapshot_index,
    )

    entries = build_candidate_entries(decisions)

    execution_rows = build_execution_results(
        entries,
        snapshot_index,
    )

    expected_execution_rows = (
        len(entries) * len(STALENESS_THRESHOLDS_MS) * len(SLIPPAGE_TICKS)
    )

    if len(execution_rows) != expected_execution_rows:
        raise RuntimeError(
            "unexpected execution row "
            "count: "
            f"expected="
            f"{expected_execution_rows} "
            f"actual="
            f"{len(execution_rows)}"
        )

    write_csv(
        decisions,
        OUTPUT_DECISIONS,
    )

    write_csv(
        execution_rows,
        OUTPUT_TRADES,
    )

    strategy_report = summarize_strategy(
        decisions,
        entries,
    )

    execution_report = summarize_execution(execution_rows)

    source_market_count = len(
        {row["condition_id"].strip().lower() for row in prediction_rows}
    )

    report = {
        "report_version": (REPORT_VERSION),
        "evaluation_type": ("p11_extension_frozen_stack"),
        "prediction_model": ("frozen_p5_logistic_raw_probability"),
        "calibration": ("none"),
        "strategy_version": ("p85_strategy_v1"),
        "position_policy": {
            "maximum_entries_per_market": 2,
            "second_entry_requires_same_side": (True),
            "exit_policy": ("hold_to_settlement"),
        },
        "execution_model": {
            "recorded_ask": True,
            "assume_fee_enabled": True,
            "crypto_taker_fee_rate": (CRYPTO_TAKER_FEE_RATE),
            "minimum_order_size": ("recorded_market_minimum"),
            "top_of_book_depth_constraint": (True),
            "book_age_thresholds_ms": list(STALENESS_THRESHOLDS_MS),
            "adverse_slippage_ticks": list(SLIPPAGE_TICKS),
        },
        "source": {
            "prediction_rows": len(prediction_rows),
            "prediction_markets": (source_market_count),
            "strategy_decision_rows": (len(decisions)),
            "candidate_entries": (len(entries)),
            "execution_scenario_rows": (len(execution_rows)),
        },
        "important_notes": [
            (
                "All model, calibration, "
                "strategy, position-policy, "
                "and execution parameters "
                "are frozen from P5-P10."
            ),
            ("No strategy configuration is selected using this strict-forward period."),
            (
                "The 0.40-0.60 entry-price "
                "variants remain exploratory "
                "and data-discovered."
            ),
            (
                "Tick slippage is a "
                "deterministic adverse stress "
                "scenario, not an empirically "
                "measured fill distribution."
            ),
            ("Return on entry notional is turnover return, not portfolio return."),
        ],
        "strategy": (strategy_report),
        "execution": (execution_report),
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

    print("P11 extension frozen strategy + execution evaluation complete")

    print()

    print(
        "prediction rows=",
        len(prediction_rows),
    )

    print(
        "prediction markets=",
        source_market_count,
    )

    print(
        "strategy decision rows=",
        len(decisions),
    )

    print(
        "candidate entries=",
        len(entries),
    )

    print(
        "execution scenario rows=",
        len(execution_rows),
    )

    print()

    print("STRATEGY COUNTS")

    for config in STRATEGY_CONFIGS:
        row = strategy_report[config]

        print(
            config,
            "signals=",
            row["trade_signals"],
            "entries=",
            row["candidate_entries_after_p9"],
            "markets=",
            row["candidate_markets"],
            "second_entries=",
            row["second_entries"],
        )

    print()

    print("EXECUTION RESULTS")

    for scenario in sorted(execution_report):
        print()
        print(f"=== {scenario} ===")

        for config in STRATEGY_CONFIGS:
            row = execution_report[scenario][config]

            print(
                config,
                "fill=",
                (
                    round(
                        row["fill_rate"],
                        4,
                    )
                    if row["fill_rate"] is not None
                    else None
                ),
                "net/share=",
                (
                    round(
                        row["net_pnl_per_share"],
                        6,
                    )
                    if row["net_pnl_per_share"] is not None
                    else None
                ),
                "ROI=",
                (
                    round(
                        row["return_on_entry_notional"],
                        6,
                    )
                    if row["return_on_entry_notional"] is not None
                    else None
                ),
                "reject=",
                row["rejection_reasons"],
            )

    print()

    print(f"Wrote {OUTPUT_DECISIONS}")

    print(f"Wrote {OUTPUT_TRADES}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
