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


STRATEGY_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

SNAPSHOTS_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p10_combined_execution_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p10_combined_execution_report.json"


BACKTEST_VERSION = "p10_combined_execution_v1"

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


def build_candidate_entries(
    rows: list[dict[str, str]],
) -> list[dict]:
    grouped = defaultdict(list)

    for row in rows:
        if row["action"] != "TRADE":
            continue

        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"].strip().lower(),
        )

        grouped[key].append(row)

    entries = []

    for (
        strategy_config,
        split,
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

        for entry_number, row in enumerate(
            selected,
            start=1,
        ):
            entries.append(
                {
                    "strategy_config": (strategy_config),
                    "split": (split),
                    "condition_id": (condition_id),
                    "entry_number": (entry_number),
                    "side": (side),
                    "prediction_timestamp": (row["prediction_timestamp"].strip()),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "label_yes": int(row["label_yes"]),
                }
            )

    return entries


def build_p4_index(
    rows: list[dict[str, str]],
) -> dict[
    tuple[str, str, int],
    dict[str, str],
]:
    index = {}

    for row in rows:
        key = (
            row["condition_id"].strip().lower(),
            row["prediction_timestamp"].strip(),
            int(row["target_horizon_seconds"]),
        )

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


def summarize(
    rows: list[dict],
) -> dict:
    output = {}

    scenarios = sorted({row["scenario"] for row in rows})

    configs = sorted({row["strategy_config"] for row in rows})

    for scenario in scenarios:
        output[scenario] = {}

        for config in configs:
            output[scenario][config] = {}

            for split in (
                "validation",
                "development_holdout",
            ):
                selected = [
                    row
                    for row in rows
                    if (
                        row["scenario"] == scenario
                        and row["strategy_config"] == config
                        and row["split"] == split
                    )
                ]

                filled = [
                    row for row in selected if (row["fill_status"] == FillStatus.FILLED)
                ]

                rejected = [
                    row
                    for row in selected
                    if (row["fill_status"] == FillStatus.REJECTED)
                ]

                total_size = sum(float(row["filled_size"]) for row in filled)

                capital = sum(float(row["entry_notional"]) for row in filled)

                gross_pnl = sum(float(row["gross_realized_pnl"]) for row in filled)

                fees = sum(float(row["taker_fee"]) for row in filled)

                net_pnl = sum(float(row["net_realized_pnl"]) for row in filled)

                output[scenario][config][split] = {
                    "candidate_entries": (len(selected)),
                    "filled_entries": (len(filled)),
                    "rejected_entries": (len(rejected)),
                    "fill_rate": (len(filled) / len(selected) if selected else None),
                    "filled_shares": (total_size),
                    "entry_notional": (capital),
                    "gross_realized_pnl": (gross_pnl),
                    "total_taker_fees": (fees),
                    "net_realized_pnl": (net_pnl),
                    "net_pnl_per_share": (net_pnl / total_size if total_size else None),
                    "return_on_entry_notional": (
                        net_pnl / capital if capital else None
                    ),
                    "rejection_reasons": dict(
                        Counter(row["fill_reason"] for row in rejected)
                    ),
                }

    return output


def main() -> None:
    strategy_rows = load_csv(STRATEGY_FILE)

    p4_rows = load_csv(P4_FILE)

    snapshot_rows = load_csv(SNAPSHOTS_FILE)

    entries = build_candidate_entries(strategy_rows)

    p4_index = build_p4_index(p4_rows)

    snapshot_index = build_snapshot_index(snapshot_rows)

    results = []

    for entry in entries:
        p4_key = (
            entry["condition_id"],
            entry["prediction_timestamp"],
            entry["target_horizon_seconds"],
        )

        p4_row = p4_index.get(p4_key)

        if p4_row is None:
            raise RuntimeError(f"P4 lineage missing: {p4_key}")

        observed_at = p4_row["snapshot_observed_at"].strip()

        snapshot = snapshot_index.get(
            (
                entry["condition_id"],
                observed_at,
            )
        )

        if snapshot is None:
            raise RuntimeError("raw snapshot missing")

        prefix = "yes" if entry["side"] == "YES" else "no"

        ask = optional_float(snapshot.get(f"{prefix}_ask"))

        ask_size = optional_float(snapshot.get(f"{prefix}_ask_size"))

        minimum_order_size = optional_float(snapshot.get(f"{prefix}_min_order_size"))

        tick_size = optional_float(snapshot.get(f"{prefix}_tick_size"))

        book_age_ms = optional_float(snapshot.get(f"{prefix}_book_age_ms"))

        if (
            ask is None
            or ask_size is None
            or minimum_order_size is None
            or tick_size is None
            or book_age_ms is None
        ):
            raise RuntimeError("missing combined execution telemetry")

        side = ExecutionSide(entry["side"])

        for max_book_age_ms in STALENESS_THRESHOLDS_MS:
            for slippage_ticks in SLIPPAGE_TICKS:
                scenario_name = (
                    f"age_{int(max_book_age_ms)}ms_slip_{slippage_ticks}tick"
                )

                if book_age_ms > max_book_age_ms:
                    results.append(
                        {
                            "backtest_version": (BACKTEST_VERSION),
                            "execution_level": 4,
                            "scenario": (scenario_name),
                            "max_book_age_ms": (max_book_age_ms),
                            "slippage_ticks": (slippage_ticks),
                            **entry,
                            "snapshot_observed_at": (observed_at),
                            "book_age_ms": (book_age_ms),
                            "ask": (ask),
                            "ask_size": (ask_size),
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
                        label_yes=entry["label_yes"],
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
                        "backtest_version": (BACKTEST_VERSION),
                        "execution_level": 4,
                        "scenario": (scenario_name),
                        "max_book_age_ms": (max_book_age_ms),
                        "slippage_ticks": (slippage_ticks),
                        **entry,
                        "snapshot_observed_at": (observed_at),
                        "book_age_ms": (book_age_ms),
                        "ask": (ask),
                        "ask_size": (ask_size),
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

    expected_scenario_rows = (
        len(entries) * len(STALENESS_THRESHOLDS_MS) * len(SLIPPAGE_TICKS)
    )

    if len(results) != expected_scenario_rows:
        raise RuntimeError(
            "unexpected scenario row count: "
            f"expected={expected_scenario_rows} "
            f"actual={len(results)}"
        )

    if any("scenario" not in row for row in results):
        raise RuntimeError("combined backtest contains rows without scenario metadata")

    if not results:
        raise RuntimeError("combined backtest produced no rows")

    with OUTPUT_TRADES.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(results[0].keys()),
        )

        writer.writeheader()
        writer.writerows(results)

    report = {
        "backtest_version": (BACKTEST_VERSION),
        "execution_level": 4,
        "execution_model": (
            "recorded_ask_plus_fee_"
            "minimum_order_depth_"
            "staleness_filter_"
            "tick_slippage_stress"
        ),
        "size_policy": ("one_minimum_executable_order_per_normalized_p9_entry"),
        "fee_scenario": ("assume_fee_enabled_for_all_candidate_entries"),
        "crypto_taker_fee_rate": (CRYPTO_TAKER_FEE_RATE),
        "staleness_thresholds_ms": list(STALENESS_THRESHOLDS_MS),
        "slippage_ticks": list(SLIPPAGE_TICKS),
        "candidate_entries_per_scenario": (len(entries)),
        "scenario_count": (len(STALENESS_THRESHOLDS_MS) * len(SLIPPAGE_TICKS)),
        "scenario_rows": (len(results)),
        "results": summarize(results),
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

    print("P10 combined execution backtest complete")

    print(
        "candidate_entries_per_scenario=",
        len(entries),
    )

    print(
        "scenarios=",
        len(STALENESS_THRESHOLDS_MS) * len(SLIPPAGE_TICKS),
    )

    print(
        "scenario_rows=",
        len(results),
    )

    print(f"Wrote {OUTPUT_TRADES}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
