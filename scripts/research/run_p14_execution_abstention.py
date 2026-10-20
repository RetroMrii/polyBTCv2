from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from polybtc.execution.model import (
    ExecutionRequest,
    ExecutionSide,
    FillStatus,
    MarketExecutionState,
    execute_depth_constrained_crossing,
    settlement_pnl,
    calculate_taker_fee,
)

ROOT = Path(__file__).resolve().parents[2]
P13 = ROOT / "data" / "experiments" / "p13_model_improvement"
P14 = ROOT / "data" / "experiments" / "p14_market_relative"

PREDICTIONS = P13 / "p13_rtds_native_walkforward_predictions.csv"
SUPERVISED = P13 / "p13_prospective_supervised.csv"
SNAPSHOTS = ROOT / "data" / "raw" / "p12" / "btc_5m_market_snapshots_p12.csv"

OUTPUT_ROWS = P14 / "p14_execution_abstention_rows.csv"
OUTPUT_REPORT = P14 / "p14_execution_abstention_report.json"

HORIZON = 120
FEE_RATE = 0.07
MAX_ENTRY_PRICE = 0.70
MAX_BOOK_AGE_MS = 500.0
MAX_REFERENCE_AGE_MS = 5000.0
MAX_SNAPSHOT_LAG_SECONDS = 10.0
SLIPPAGE_TICKS = (0, 1, 2)

POLICIES = (
    "market_only",
    "agreement_only",
    "small_gap",
    "model_ev",
    "price_ceiling_070",
    "agreement_price_ceiling_070",
    "small_gap_price_ceiling_070",
)

FIELDS = [
    "condition_id",
    "target_horizon_seconds",
    "snapshot_observed_at",
]

NUMERIC_FIELDS = [
    "yes_ask",
    "no_ask",
    "yes_ask_size",
    "no_ask_size",
    "yes_book_age_ms",
    "no_book_age_ms",
    "yes_tick_size",
    "no_tick_size",
    "yes_min_order_size",
    "no_min_order_size",
    "reference_age_ms",
]


def load_inputs():
    predictions = pd.read_csv(PREDICTIONS)
    supervised = pd.read_csv(SUPERVISED)

    predictions = predictions[predictions["target_horizon_seconds"] == HORIZON].copy()

    predictions["condition_id"] = predictions["condition_id"].str.strip().str.lower()

    supervised["condition_id"] = supervised["condition_id"].str.strip().str.lower()

    if predictions.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate OOS prediction keys.")

    if supervised.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate supervised keys.")

    lineage = supervised[
        [
            "condition_id",
            "target_horizon_seconds",
            "prediction_timestamp",
            "snapshot_observed_at",
            "snapshot_lag_seconds",
            "normalized_yes_mid",
            "label_yes",
        ]
    ].copy()

    merged = predictions.merge(
        lineage,
        on=["condition_id", "target_horizon_seconds"],
        how="left",
        validate="one_to_one",
        suffixes=("_oos", "_source"),
        indicator=True,
    )

    if not (merged["_merge"] == "both").all():
        raise RuntimeError("Missing supervised lineage.")

    # Confirm the OOS prediction refers to the same
    # prediction time, settlement label and market price.
    oos_timestamps = pd.to_datetime(
        merged["prediction_timestamp_oos"],
        utc=True,
        errors="coerce",
    )

    source_timestamps = pd.to_datetime(
        merged["prediction_timestamp_source"],
        utc=True,
        errors="coerce",
    )

    if oos_timestamps.isna().any() or source_timestamps.isna().any():
        raise RuntimeError("Invalid prediction timestamp in lineage.")

    if not oos_timestamps.equals(source_timestamps):
        mismatches = oos_timestamps != source_timestamps

        print("Prediction timestamp mismatches:")
        print(
            merged.loc[
                mismatches,
                [
                    "condition_id",
                    "prediction_timestamp_oos",
                    "prediction_timestamp_source",
                ],
            ]
            .head(10)
            .to_string(index=False)
        )

        raise RuntimeError("Prediction timestamp mismatch.")

    if not (merged["label_yes_oos"] == merged["label_yes_source"]).all():
        raise RuntimeError("Settlement label mismatch.")

    source_mid = pd.to_numeric(merged["normalized_yes_mid_source"], errors="coerce")
    oos_mid = pd.to_numeric(merged["normalized_yes_mid_oos"], errors="coerce")

    if not np.allclose(
        source_mid.to_numpy(dtype=float),
        oos_mid.to_numpy(dtype=float),
        equal_nan=True,
        atol=1e-12,
        rtol=0,
    ):
        raise RuntimeError("Market probability lineage mismatch.")

    raw = pd.read_csv(SNAPSHOTS)

    raw["market_id"] = raw["market_id"].str.strip().str.lower()

    raw["observed_at"] = pd.to_datetime(raw["observed_at"], utc=True)

    merged["snapshot_observed_at"] = pd.to_datetime(
        merged["snapshot_observed_at"], utc=True
    )

    merged["prediction_timestamp"] = pd.to_datetime(
        merged["prediction_timestamp_oos"], utc=True
    )

    # Keep only raw records actually referenced by
    # the selected OOS prediction snapshots.
    ids = set(merged["condition_id"])
    raw = raw[raw["market_id"].isin(ids)].copy()

    raw = raw.rename(
        columns={"market_id": "condition_id", "observed_at": "snapshot_observed_at"}
    )

    if raw.duplicated(["condition_id", "snapshot_observed_at"]).any():
        raise RuntimeError("Ambiguous raw snapshot identities.")

    merged = merged.merge(
        raw,
        on=["condition_id", "snapshot_observed_at"],
        how="left",
        validate="many_to_one",
        indicator="raw_match",
        suffixes=("", "_raw"),
    )

    if not (merged["raw_match"] == "both").all():
        raise RuntimeError("Original raw snapshot not found.")

    if (merged["snapshot_observed_at"] > merged["prediction_timestamp"]).any():
        raise RuntimeError("Future snapshot detected.")

    lag = pd.to_numeric(
        merged["snapshot_lag_seconds"],
        errors="coerce",
    )

    if (lag.isna() | (lag < 0) | (lag > MAX_SNAPSHOT_LAG_SECONDS)).any():
        raise RuntimeError("Invalid snapshot freshness.")

    for field in NUMERIC_FIELDS:
        merged[field] = pd.to_numeric(merged[field], errors="coerce")

    merged["market_probability"] = source_mid.to_numpy()
    merged["model_probability"] = pd.to_numeric(merged["hgb3_native"], errors="coerce")

    merged["label_yes"] = merged["label_yes_source"].astype(int)

    if not merged["model_probability"].between(0, 1).all():
        raise RuntimeError("Invalid model probabilities.")

    return merged


def base_opportunity(row):
    market_p = row.market_probability

    if not np.isfinite(market_p):
        return None, "missing_market_probability"

    if not 0 <= market_p <= 1:
        return None, "invalid_market_probability"

    if market_p == 0.5:
        return None, "market_probability_tie"

    side = ExecutionSide.YES if market_p > 0.5 else ExecutionSide.NO

    prefix = "yes" if side == ExecutionSide.YES else "no"

    ask = getattr(row, f"{prefix}_ask")
    ask_size = getattr(row, f"{prefix}_ask_size")
    age = getattr(row, f"{prefix}_book_age_ms")
    tick = getattr(row, f"{prefix}_tick_size")
    minimum = getattr(row, f"{prefix}_min_order_size")

    reference_age = row.reference_age_ms

    if not np.isfinite(reference_age):
        return None, "missing_reference_age"

    if reference_age < 0 or reference_age > MAX_REFERENCE_AGE_MS:
        return None, "stale_reference"

    if not np.isfinite(age):
        return None, "missing_book_age"

    if age < 0 or age > MAX_BOOK_AGE_MS:
        return None, "stale_book"

    if not np.isfinite(tick) or tick <= 0:
        return None, "invalid_tick"

    if not np.isfinite(minimum) or minimum <= 0:
        return None, "invalid_minimum_size"

    if not np.isfinite(ask) or not 0 < ask < 1:
        return None, "missing_or_invalid_ask"

    if not np.isfinite(ask_size) or ask_size < 0:
        return None, "missing_or_invalid_depth"

    execution = execute_depth_constrained_crossing(
        ExecutionRequest(
            side=side,
            requested_size=float(minimum),
        ),
        MarketExecutionState(
            yes_ask=float(ask) if side == ExecutionSide.YES else None,
            no_ask=float(ask) if side == ExecutionSide.NO else None,
        ),
        available_ask_size=float(ask_size),
        minimum_order_size=float(minimum),
    )

    if execution.status != FillStatus.FILLED:
        return None, execution.reason

    return {
        "side": side,
        "size": execution.filled_size,
        "ask": float(execution.execution_price),
        "tick": float(tick),
    }, "eligible"


def policy_accepts(policy, row, execution_price, fee_per_share):
    market_yes = row.market_probability >= 0.5
    model_yes = row.model_probability >= 0.5

    gap = abs(row.model_probability - row.market_probability)

    model_side_probability = (
        row.model_probability if market_yes else 1.0 - row.model_probability
    )

    if policy == "price_ceiling_070":
        return execution_price <= MAX_ENTRY_PRICE

    if policy == "agreement_price_ceiling_070":
        return market_yes == model_yes and execution_price <= MAX_ENTRY_PRICE

    if policy == "small_gap_price_ceiling_070":
        return gap <= 0.05 and execution_price <= MAX_ENTRY_PRICE

    if policy == "market_only":
        return True

    if policy == "agreement_only":
        return market_yes == model_yes

    if policy == "small_gap":
        return gap <= 0.05

    if policy == "model_ev":
        return (model_side_probability - execution_price - fee_per_share) > 0.0

    raise RuntimeError(f"Unknown policy: {policy}")


def simulate(df):
    rows = []

    for row in df.itertuples(index=False):
        entry, eligibility_reason = base_opportunity(row)

        for slip in SLIPPAGE_TICKS:
            for policy in POLICIES:
                record = {
                    "condition_id": row.condition_id,
                    "fold": int(row.fold),
                    "prediction_timestamp": row.prediction_timestamp.isoformat(),
                    "market_end_at": row.market_end_at,
                    "horizon": HORIZON,
                    "policy": policy,
                    "slippage_ticks": slip,
                    "market_probability": row.market_probability,
                    "model_probability": row.model_probability,
                    "label_yes": int(row.label_yes),
                    "common_eligible": entry is not None,
                    "eligibility_reason": eligibility_reason,
                    "decision": "SKIP",
                    "side": "",
                    "filled_size": 0.0,
                    "execution_price": np.nan,
                    "entry_notional": 0.0,
                    "gross_pnl": 0.0,
                    "fee": 0.0,
                    "net_pnl": 0.0,
                }

                if entry is None:
                    record["decision"] = "INELIGIBLE"
                    rows.append(record)
                    continue

                stressed_price = min(
                    1.0,
                    entry["ask"] + slip * entry["tick"],
                )

                fee = calculate_taker_fee(
                    filled_size=entry["size"],
                    execution_price=stressed_price,
                    fee_rate=FEE_RATE,
                )

                fee_per_share = fee / entry["size"]

                if not policy_accepts(policy, row, stressed_price, fee_per_share):
                    record["decision"] = "FILTERED"
                    rows.append(record)
                    continue

                pnl = settlement_pnl(
                    side=entry["side"],
                    label_yes=int(row.label_yes),
                    execution_price=stressed_price,
                    filled_size=entry["size"],
                )

                record.update(
                    {
                        "decision": "FILLED",
                        "side": entry["side"].value,
                        "filled_size": entry["size"],
                        "execution_price": stressed_price,
                        "entry_notional": stressed_price * entry["size"],
                        "gross_pnl": pnl,
                        "fee": fee,
                        "net_pnl": pnl - fee,
                    }
                )

                rows.append(record)

    return pd.DataFrame(rows)


def summarize(group):
    filled = group[group["decision"] == "FILLED"].copy()
    capital = filled["entry_notional"].sum()
    shares = filled["filled_size"].sum()
    net = filled["net_pnl"].sum()

    ordered = filled.sort_values(["prediction_timestamp", "condition_id"])

    equity = np.r_[0.0, ordered["net_pnl"].cumsum().to_numpy()]
    drawdown = equity - np.maximum.accumulate(equity)

    return {
        "opportunities": int(len(group)),
        "common_eligible": int(group["common_eligible"].sum()),
        "ineligible": int((group["decision"] == "INELIGIBLE").sum()),
        "filtered": int((group["decision"] == "FILTERED").sum()),
        "trades": int(len(filled)),
        "trade_markets": int(filled["condition_id"].nunique()),
        "entry_notional": float(capital),
        "filled_shares": float(shares),
        "gross_pnl": float(filled["gross_pnl"].sum()),
        "fees": float(filled["fee"].sum()),
        "net_pnl": float(net),
        "net_per_share": float(net / shares) if shares else None,
        "roi_on_entry_notional": (float(net / capital) if capital else None),
        "win_rate": (float((filled["net_pnl"] > 0).mean()) if len(filled) else None),
        "max_cumulative_pnl_drawdown": float(-drawdown.min()),
    }


def main():
    df = load_inputs()
    results = simulate(df)

    expected = len(df) * len(SLIPPAGE_TICKS) * len(POLICIES)
    if len(results) != expected:
        raise RuntimeError("Unexpected result count.")

    if (
        results.loc[results["decision"] == "FILLED"]
        .duplicated(["policy", "slippage_ticks", "condition_id"])
        .any()
    ):
        raise RuntimeError("Multiple entries per market.")

    report = {
        "experiment": "p14_execution_abstention_v1",
        "status": "exploratory",
        "horizon": HORIZON,
        "fee_rate_assumption": FEE_RATE,
        "max_entry_price": MAX_ENTRY_PRICE,
        "price_ceiling_basis": "stressed_selected_side_execution_price",
        "price_ceiling_status": "fixed_strategy_design_choice",
        "max_book_age_ms": MAX_BOOK_AGE_MS,
        "max_reference_age_ms": MAX_REFERENCE_AGE_MS,
        "slippage_ticks": list(SLIPPAGE_TICKS),
        "source_oos_markets": int(df["condition_id"].nunique()),
        "source_oos_rows": int(len(df)),
        "policies": list(POLICIES),
        "overall": {},
        "by_fold": {},
        "eligibility_reasons": {},
        "notes": [
            "One fixed 120s horizon per market.",
            "Exact original snapshot lineage is required.",
            "All policies use identical base eligibility.",
            "Market-only is a participation benchmark, not an EV-optimal strategy.",
            "No strategy thresholds were trained on this evaluation.",
            "Fee and slippage assumptions are simulated.",
            "Cumulative PnL drawdown is not portfolio drawdown.",
            "Prior research has already examined this period.",
        ],
    }

    base = results[
        (results["policy"] == "market_only") & (results["slippage_ticks"] == 0)
    ]

    report["eligibility_reasons"] = {
        str(k): int(v) for k, v in base["eligibility_reason"].value_counts().items()
    }

    for slip in SLIPPAGE_TICKS:
        report["overall"][str(slip)] = {}
        report["by_fold"][str(slip)] = {}

        for policy in POLICIES:
            subset = results[
                (results["slippage_ticks"] == slip) & (results["policy"] == policy)
            ]

            report["overall"][str(slip)][policy] = summarize(subset)

            report["by_fold"][str(slip)][policy] = {
                str(int(fold)): summarize(group)
                for fold, group in subset.groupby("fold")
            }

    P14.mkdir(parents=True, exist_ok=True)

    if OUTPUT_ROWS.exists() or OUTPUT_REPORT.exists():
        raise FileExistsError(
            "P14 execution results already exist. Archive them before rerunning."
        )

    results.to_csv(OUTPUT_ROWS, index=False)
    OUTPUT_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("P14-B2 COMPLETE")
    print("source_markets=", report["source_oos_markets"])
    print("eligibility_reasons=", report["eligibility_reasons"])

    for slip in SLIPPAGE_TICKS:
        print(f"\nSLIPPAGE {slip} TICKS")
        for policy, values in report["overall"][str(slip)].items():
            print(policy, values)

    print("\nOUTPUTS")
    print(OUTPUT_ROWS)
    print(OUTPUT_REPORT)


if __name__ == "__main__":
    main()
