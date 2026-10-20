from __future__ import annotations

import csv
import json
import sys

from collections import defaultdict
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
    execute_level1_crossing,
    settlement_pnl,
)


STRATEGY_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

SNAPSHOTS_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

P9_SCALEIN_FILE = ROOT / "data" / "normalized" / "p9_scalein_trades.csv"

OUTPUT_TRADES = ROOT / "data" / "normalized" / "p10_level2_fee_scenario_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p10_level2_fee_scenario_report.json"


BACKTEST_VERSION = "p10_level2_fee_scenario_v1"

REQUESTED_SIZE = 1.0

CRYPTO_TAKER_FEE_RATE = 0.07

STALENESS_THRESHOLDS_MS = (
    250.0,
    500.0,
    1000.0,
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
                    "split": split,
                    "condition_id": (condition_id),
                    "entry_number": (entry_number),
                    "side": side,
                    "prediction_timestamp": (row["prediction_timestamp"].strip()),
                    "target_horizon_seconds": int(row["target_horizon_seconds"]),
                    "strategy_selected_price": float(row["selected_price"]),
                    "label_yes": int(row["label_yes"]),
                }
            )

    return entries


def run_level1(
    entries: list[dict],
    p4_index: dict,
    snapshot_index: dict,
) -> list[dict]:
    results = []

    for entry in entries:
        p4_key = (
            entry["condition_id"],
            entry["prediction_timestamp"],
            entry["target_horizon_seconds"],
        )

        p4_row = p4_index.get(p4_key)

        if p4_row is None:
            raise RuntimeError(f"P4 lineage missing for {p4_key}")

        snapshot_observed_at = p4_row["snapshot_observed_at"].strip()

        snapshot_key = (
            entry["condition_id"],
            snapshot_observed_at,
        )

        snapshot = snapshot_index.get(snapshot_key)

        if snapshot is None:
            raise RuntimeError(f"raw snapshot missing for {snapshot_key}")

        yes_ask = optional_float(snapshot.get("yes_ask"))

        no_ask = optional_float(snapshot.get("no_ask"))

        side = ExecutionSide(entry["side"])

        prefix = "yes" if side == ExecutionSide.YES else "no"

        book_age_ms = optional_float(snapshot.get(f"{prefix}_book_age_ms"))

        book_latency_ms = optional_float(snapshot.get(f"{prefix}_book_latency_ms"))

        tick_size = optional_float(snapshot.get(f"{prefix}_tick_size"))

        ask_size = optional_float(snapshot.get(f"{prefix}_ask_size"))

        if (
            book_age_ms is None
            or book_latency_ms is None
            or tick_size is None
            or ask_size is None
        ):
            raise RuntimeError("missing P10 execution telemetry")

        execution = execute_level1_crossing(
            ExecutionRequest(
                side=side,
                requested_size=REQUESTED_SIZE,
            ),
            MarketExecutionState(
                yes_ask=yes_ask,
                no_ask=no_ask,
            ),
        )

        if execution.status != FillStatus.FILLED:
            raise RuntimeError(
                f"unexpected Level 1 execution rejection: {entry} {execution.reason}"
            )

        assert execution.execution_price is not None

        price_difference = execution.execution_price - entry["strategy_selected_price"]

        gross_pnl = settlement_pnl(
            side=side,
            label_yes=entry["label_yes"],
            execution_price=(execution.execution_price),
            filled_size=(execution.filled_size),
        )

        fee = calculate_taker_fee(
            filled_size=(execution.filled_size),
            execution_price=(execution.execution_price),
            fee_rate=(CRYPTO_TAKER_FEE_RATE),
        )

        net_pnl = gross_pnl - fee

        results.append(
            {
                "backtest_version": (BACKTEST_VERSION),
                "execution_level": 2,
                **entry,
                "snapshot_observed_at": (snapshot_observed_at),
                "requested_size": (execution.requested_size),
                "filled_size": (execution.filled_size),
                "execution_price": (execution.execution_price),
                "strategy_price_difference": (price_difference),
                "fill_status": (execution.status),
                "fill_reason": (execution.reason),
                "gross_realized_pnl": (gross_pnl),
                "taker_fee": (fee),
                "net_realized_pnl": (net_pnl),
                "book_age_ms": (book_age_ms),
                "book_latency_ms": (book_latency_ms),
                "tick_size": (tick_size),
                "ask_size": (ask_size),
            }
        )

    return results


def write_csv(
    rows: list[dict],
    path: Path,
) -> None:
    if not rows:
        raise RuntimeError("cannot write empty P10 output")

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


def build_market_totals(
    rows: list[dict],
) -> dict[
    tuple[str, str, str],
    dict,
]:
    grouped = {}

    for row in rows:
        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"],
        )

        if key not in grouped:
            grouped[key] = {
                "entries": 0,
                "pnl": 0.0,
            }

        grouped[key]["entries"] += 1

        grouped[key]["pnl"] += float(row["gross_realized_pnl"])

    return grouped


def validate_against_p9(
    p10_rows: list[dict],
    p9_rows: list[dict[str, str]],
) -> dict:
    p10_totals = build_market_totals(p10_rows)

    p9_index = {}

    for row in p9_rows:
        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"].strip().lower(),
        )

        if key in p9_index:
            raise RuntimeError(f"duplicate P9 market key: {key}")

        p9_index[key] = row

    missing_p9 = 0
    entry_count_mismatches = 0
    pnl_mismatches = 0
    maximum_pnl_difference = 0.0

    for key, p10 in p10_totals.items():
        p9 = p9_index.get(key)

        if p9 is None:
            missing_p9 += 1
            continue

        p9_entry_count = int(p9["entry_count"])

        if p9_entry_count != p10["entries"]:
            entry_count_mismatches += 1

        p9_pnl = float(p9["total_realized_pnl"])

        difference = abs(p9_pnl - p10["pnl"])

        maximum_pnl_difference = max(
            maximum_pnl_difference,
            difference,
        )

        if difference > 1e-12:
            pnl_mismatches += 1

    extra_p9 = len(set(p9_index) - set(p10_totals))

    return {
        "p10_market_positions": len(p10_totals),
        "p9_market_positions": len(p9_index),
        "missing_p9_positions": (missing_p9),
        "extra_p9_positions": (extra_p9),
        "entry_count_mismatches": (entry_count_mismatches),
        "pnl_mismatches": (pnl_mismatches),
        "maximum_pnl_difference": (maximum_pnl_difference),
        "passed": (
            missing_p9 == 0
            and extra_p9 == 0
            and entry_count_mismatches == 0
            and pnl_mismatches == 0
        ),
    }


def summarize(
    rows: list[dict],
) -> dict:
    configs = sorted({row["strategy_config"] for row in rows})

    result = {}

    for config in configs:
        result[config] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            selected = [
                row
                for row in rows
                if (row["strategy_config"] == config and row["split"] == split)
            ]

            gross_pnl = sum(float(row["gross_realized_pnl"]) for row in selected)

            total_fees = sum(float(row["taker_fee"]) for row in selected)

            net_pnl = sum(float(row["net_realized_pnl"]) for row in selected)

            filled_size = sum(float(row["filled_size"]) for row in selected)

            markets = len({row["condition_id"] for row in selected})

            result[config][split] = {
                "entries": len(selected),
                "markets": markets,
                "filled_size": (filled_size),
                "gross_realized_pnl": (gross_pnl),
                "total_taker_fees": (total_fees),
                "net_realized_pnl": (net_pnl),
                "gross_pnl_per_share": (
                    gross_pnl / filled_size if filled_size else None
                ),
                "net_pnl_per_share": (net_pnl / filled_size if filled_size else None),
            }

    return result


def summarize_staleness_scenarios(
    rows: list[dict],
) -> dict:
    result = {}

    configs = sorted({row["strategy_config"] for row in rows})

    for threshold in STALENESS_THRESHOLDS_MS:
        scenario_name = f"max_book_age_{int(threshold)}ms"

        result[scenario_name] = {}

        for config in configs:
            result[scenario_name][config] = {}

            for split in (
                "validation",
                "development_holdout",
            ):
                selected = [
                    row
                    for row in rows
                    if (row["strategy_config"] == config and row["split"] == split)
                ]

                eligible = [
                    row for row in selected if (float(row["book_age_ms"]) <= threshold)
                ]

                rejected = len(selected) - len(eligible)

                gross_pnl = sum(float(row["gross_realized_pnl"]) for row in eligible)

                fees = sum(float(row["taker_fee"]) for row in eligible)

                net_pnl = sum(float(row["net_realized_pnl"]) for row in eligible)

                filled_size = sum(float(row["filled_size"]) for row in eligible)

                result[scenario_name][config][split] = {
                    "candidate_entries": (len(selected)),
                    "filled_entries": (len(eligible)),
                    "stale_rejections": (rejected),
                    "fill_rate": (len(eligible) / len(selected) if selected else None),
                    "gross_realized_pnl": (gross_pnl),
                    "total_taker_fees": (fees),
                    "net_realized_pnl": (net_pnl),
                    "net_pnl_per_filled_share": (
                        net_pnl / filled_size if filled_size else None
                    ),
                }

    return result


def main() -> None:
    strategy_rows = load_csv(STRATEGY_FILE)

    p4_rows = load_csv(P4_FILE)

    snapshot_rows = load_csv(SNAPSHOTS_FILE)

    p9_rows = load_csv(P9_SCALEIN_FILE)

    entries = build_candidate_entries(strategy_rows)

    p4_index = build_p4_index(p4_rows)

    snapshot_index = build_snapshot_index(snapshot_rows)

    results = run_level1(
        entries,
        p4_index,
        snapshot_index,
    )

    write_csv(
        results,
        OUTPUT_TRADES,
    )

    p9_validation = validate_against_p9(
        results,
        p9_rows,
    )

    report = {
        "backtest_version": (BACKTEST_VERSION),
        "execution_level": 2,
        "execution_model": ("cross_recorded_ask_plus_crypto_taker_fee"),
        "fee_scenario": ("assume_fee_enabled_for_all_candidate_entries"),
        "crypto_taker_fee_rate": (CRYPTO_TAKER_FEE_RATE),
        "requested_size_per_entry": (REQUESTED_SIZE),
        "fees": True,
        "additional_slippage": False,
        "latency_adjustment": False,
        "staleness_filter_scenarios": [
            250,
            500,
            1000,
        ],
        "staleness_scenarios": (summarize_staleness_scenarios(results)),
        "depth_constraint": False,
        "candidate_entries": len(entries),
        "filled_entries": len(results),
        "p9_reproduction": (p9_validation),
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

    print("P10 Level 2 fee scenario complete")

    print(
        "candidate_entries=",
        len(entries),
    )

    print(
        "filled_entries=",
        len(results),
    )

    print(
        "p9_reproduction=",
        p9_validation["passed"],
    )

    print(
        "pnl_mismatches=",
        p9_validation["pnl_mismatches"],
    )

    print(
        "max_pnl_difference=",
        p9_validation["maximum_pnl_difference"],
    )

    print(f"Wrote {OUTPUT_TRADES}")

    print(f"Wrote {OUTPUT_REPORT}")

    if not p9_validation["passed"]:
        raise RuntimeError(
            "P10 Level 2 gross economics do not reproduce P9 scale-in economics"
        )


if __name__ == "__main__":
    main()
