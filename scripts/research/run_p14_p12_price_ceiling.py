from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# P14-C: P12 price-ceiling counterfactual
#
# Read-only research.
# No P12 strategy changes.
# No model training.
# No bootstrap.
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

INPUT = ROOT / "data" / "shadow" / "p12_shadow_settled_trades.csv"

P12_REPORT = ROOT / "data" / "shadow" / "p12_shadow_performance_report.json"

OUTPUT_DIR = ROOT / "data" / "experiments" / "p14_market_relative"

OUTPUT_REPORT = OUTPUT_DIR / "p14_p12_price_ceiling_report.json"

OUTPUT_ROWS = OUTPUT_DIR / "p14_p12_price_ceiling_trades.csv"

PRICE_CEILING = 0.70

# Original P12 simulated execution-price cap.
P12_MAX_EXECUTION_PRICE = 0.99

SLIPPAGE_SCENARIOS = (0, 1, 2)

EXPECTED_TRADES = 117

NUMERIC_COLUMNS = [
    "target_horizon_seconds",
    "label_yes",
    "won",
    "selected_ask",
    "tick_size",
    "slippage_ticks",
    "execution_price",
    "filled_size",
    "fee",
    "settlement_value",
    "gross_cost",
    "net_pnl",
    "net_pnl_per_share",
]


def load_data() -> pd.DataFrame:
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    if not P12_REPORT.exists():
        raise FileNotFoundError(P12_REPORT)

    df = pd.read_csv(INPUT)

    required = {
        "condition_id",
        "prediction_timestamp",
        "side",
        *NUMERIC_COLUMNS,
    }

    missing = required - set(df.columns)

    if missing:
        raise RuntimeError(f"Missing columns: {sorted(missing)}")

    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    if df[NUMERIC_COLUMNS].isna().any().any():
        raise RuntimeError("Missing or invalid numeric values.")

    df["condition_id"] = df["condition_id"].astype(str).str.strip().str.lower()

    df["side"] = df["side"].astype(str).str.strip().str.upper()

    df["prediction_timestamp"] = pd.to_datetime(
        df["prediction_timestamp"],
        utc=True,
        errors="coerce",
    )

    if df["prediction_timestamp"].isna().any():
        raise RuntimeError("Invalid prediction timestamps.")

    if not df["side"].isin(["YES", "NO"]).all():
        raise RuntimeError("Unexpected execution side.")

    if not df["label_yes"].isin([0, 1]).all():
        raise RuntimeError("Invalid settlement labels.")

    if not df["won"].isin([0, 1]).all():
        raise RuntimeError("Invalid win indicators.")

    if not df["slippage_ticks"].isin(SLIPPAGE_SCENARIOS).all():
        raise RuntimeError("Unexpected slippage scenario.")

    if not df["execution_price"].between(0, 1).all():
        raise RuntimeError("Execution price outside [0, 1].")

    if not df["selected_ask"].between(0, 1).all():
        raise RuntimeError("Recorded ask outside [0, 1].")

    if (df["filled_size"] <= 0).any():
        raise RuntimeError("Invalid filled size.")

    if (df["tick_size"] <= 0).any():
        raise RuntimeError("Invalid tick size.")

    if (df["fee"] < 0).any():
        raise RuntimeError("Negative taker fee.")

    # --------------------------------------------------------
    # Settlement identity
    # --------------------------------------------------------

    expected_won = np.where(
        df["side"].eq("YES"),
        df["label_yes"].eq(1),
        df["label_yes"].eq(0),
    )

    if not np.array_equal(
        df["won"].to_numpy(dtype=int),
        expected_won.astype(int),
    ):
        raise RuntimeError("Win indicator contradicts settlement label.")

    expected_settlement = df["won"] * df["filled_size"]

    if not np.allclose(
        df["settlement_value"],
        expected_settlement,
        atol=1e-8,
        rtol=0,
    ):
        raise RuntimeError("Settlement value mismatch.")

    expected_gross_cost = df["execution_price"] * df["filled_size"]

    if not np.allclose(
        df["gross_cost"],
        expected_gross_cost,
        atol=1e-8,
        rtol=0,
    ):
        raise RuntimeError("Gross entry cost mismatch.")

    expected_net_pnl = df["settlement_value"] - df["gross_cost"] - df["fee"]

    if not np.allclose(
        df["net_pnl"],
        expected_net_pnl,
        atol=1e-8,
        rtol=0,
    ):
        raise RuntimeError("Recorded settlement PnL mismatch.")

    expected_per_share = df["net_pnl"] / df["filled_size"]

    if not np.allclose(
        df["net_pnl_per_share"],
        expected_per_share,
        atol=1e-8,
        rtol=0,
    ):
        raise RuntimeError("Recorded net PnL per share mismatch.")

    # --------------------------------------------------------
    # Unique market/scenario records
    # --------------------------------------------------------

    if df.duplicated(["condition_id", "slippage_ticks"]).any():
        raise RuntimeError("Duplicate market/slippage combination.")

    markets = df["condition_id"].nunique()

    if markets != EXPECTED_TRADES:
        raise RuntimeError(
            f"Expected {EXPECTED_TRADES} trades, "
            f"found {markets}. "
            "Review the refreshed P12 sample."
        )

    counts = df.groupby("slippage_ticks")["condition_id"].nunique()

    for slip in SLIPPAGE_SCENARIOS:
        if counts.get(slip, 0) != markets:
            raise RuntimeError(f"Incomplete slippage scenario: {slip}")

    # All three slippage rows must represent
    # the same original shadow trade.
    immutable_columns = [
        "prediction_timestamp",
        "target_horizon_seconds",
        "side",
        "label_yes",
        "won",
        "selected_ask",
        "filled_size",
        "tick_size",
    ]

    for column in immutable_columns:
        distinct = df.groupby("condition_id")[column].nunique()

        if (distinct != 1).any():
            raise RuntimeError(f"Cross-scenario inconsistency: {column}")

    # --------------------------------------------------------
    # Reproduce original P12 execution-price convention
    # --------------------------------------------------------

    expected_price = np.minimum(
        P12_MAX_EXECUTION_PRICE,
        df["selected_ask"] + df["slippage_ticks"] * df["tick_size"],
    )

    mismatches = ~np.isclose(
        df["execution_price"].to_numpy(dtype=float),
        expected_price,
        atol=1e-9,
        rtol=0,
    )

    if mismatches.any():
        diagnostic = df.loc[
            mismatches,
            [
                "condition_id",
                "selected_ask",
                "tick_size",
                "slippage_ticks",
                "execution_price",
            ],
        ].copy()

        diagnostic["expected_price"] = expected_price[mismatches]

        print(
            "\nEXECUTION PRICE MISMATCHES:",
            int(mismatches.sum()),
        )

        print(diagnostic.head(15).to_string(index=False))

        raise RuntimeError("Execution prices do not reproduce P12's $0.99 cap.")

    return df


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "average_entry_price": None,
            "average_fee_per_share": None,
            "break_even_win_rate": None,
            "filled_shares": 0.0,
            "gross_entry_cost": 0.0,
            "total_fees": 0.0,
            "all_in_cost": 0.0,
            "net_pnl": 0.0,
            "net_pnl_per_share": None,
            "roi": None,
        }

    shares = float(df["filled_size"].sum())

    gross_cost = float(df["gross_cost"].sum())

    fees = float(df["fee"].sum())

    all_in_cost = gross_cost + fees

    net_pnl = float(df["net_pnl"].sum())

    wins = int(df["won"].sum())

    return {
        "trades": int(len(df)),
        "wins": wins,
        "losses": int(len(df) - wins),
        "win_rate": float(df["won"].mean()),
        "average_entry_price": (gross_cost / shares),
        "average_fee_per_share": (fees / shares),
        "break_even_win_rate": (all_in_cost / shares),
        "filled_shares": shares,
        "gross_entry_cost": gross_cost,
        "total_fees": fees,
        "all_in_cost": all_in_cost,
        "net_pnl": net_pnl,
        "net_pnl_per_share": (net_pnl / shares),
        # P12 ROI is calculated against the
        # full entry cost INCLUDING fees.
        "roi": (net_pnl / all_in_cost if all_in_cost > 0 else None),
    }


def breakdown(df: pd.DataFrame) -> dict:
    result = {
        "overall": summarize(df),
        "by_side": {},
        "by_horizon": {},
        "by_period": {},
    }

    for side in ("YES", "NO"):
        result["by_side"][side] = summarize(df[df["side"] == side])

    for horizon, group in df.groupby("target_horizon_seconds"):
        result["by_horizon"][str(int(horizon))] = summarize(group)

    if not df.empty:
        periods = df.copy()

        periods["date_utc"] = periods["prediction_timestamp"].dt.strftime("%Y-%m-%d")

        for date, group in periods.groupby("date_utc"):
            result["by_period"][date] = summarize(group)

    return result


def validate_p12_baseline(
    df: pd.DataFrame,
) -> None:
    reference = json.loads(P12_REPORT.read_text(encoding="utf-8"))

    if int(reference["trade_markets"]) != EXPECTED_TRADES:
        raise RuntimeError(
            "P12 performance report is not synchronized with 117 trades."
        )

    for slip in SLIPPAGE_SCENARIOS:
        subset = df[df["slippage_ticks"] == slip]

        actual = summarize(subset)

        original = reference["scenarios"][f"slip_{slip}tick"]

        if actual["trades"] != original["entries"]:
            raise RuntimeError(f"Trade-count mismatch at {slip} ticks.")

        if not np.isclose(
            actual["net_pnl"],
            original["net_pnl"],
            atol=1e-7,
            rtol=0,
        ):
            raise RuntimeError(f"Net PnL mismatch at {slip} ticks.")

        if not np.isclose(
            actual["net_pnl_per_share"],
            original["net_pnl_per_share"],
            atol=1e-7,
            rtol=0,
        ):
            raise RuntimeError(f"PnL/share mismatch at {slip} ticks.")

        if not np.isclose(
            actual["roi"],
            original["roi"],
            atol=1e-7,
            rtol=0,
        ):
            print("\nP12 ROI INTEGRITY DIAGNOSTIC")

            print("scenario=", slip)
            print("actual_roi=", actual["roi"])
            print("reference_roi=", original["roi"])
            print(
                "gross_cost=",
                actual["gross_entry_cost"],
            )
            print(
                "fees=",
                actual["total_fees"],
            )
            print(
                "all_in_cost=",
                actual["all_in_cost"],
            )

            raise RuntimeError(f"P12 ROI mismatch at {slip} ticks.")

    print("P12 BASELINE VALIDATION PASSED")


def main() -> None:
    df = load_data()

    validate_p12_baseline(df)

    # --------------------------------------------------------
    # Counterfactual: fixed $0.70 maximum execution price
    # --------------------------------------------------------

    df["passes_ceiling"] = df["execution_price"] <= PRICE_CEILING + 1e-12

    df["counterfactual_decision"] = np.where(
        df["passes_ceiling"],
        "KEEP",
        "REJECT_PRICE_CEILING",
    )

    report = {
        "experiment": "p14_p12_price_ceiling_v1",
        "status": "exploratory_counterfactual",
        "source": str(INPUT.relative_to(ROOT)),
        "original_trades": EXPECTED_TRADES,
        "price_ceiling": PRICE_CEILING,
        "price_ceiling_basis": ("recorded_slippage_adjusted_execution_price"),
        "p12_execution_price_cap": (P12_MAX_EXECUTION_PRICE),
        "roi_denominator": ("gross_entry_cost_plus_taker_fees"),
        "scenarios": {},
        "notes": [
            "P12 baseline remains unchanged.",
            "All results reuse original P12 settlements.",
            "Ceiling is a fixed strategy-design decision.",
            "No new or later trades are simulated.",
            "Different slippage scenarios may retain different trades.",
            "This is not untouched prospective validation.",
            "No bootstrap or threshold optimization.",
        ],
    }

    for slip in SLIPPAGE_SCENARIOS:
        subset = df[df["slippage_ticks"] == slip].copy()

        kept = subset[subset["passes_ceiling"]].copy()

        excluded = subset[~subset["passes_ceiling"]].copy()

        # Accounting decomposition.
        reconstructed = kept["net_pnl"].sum() + excluded["net_pnl"].sum()

        if not np.isclose(
            reconstructed,
            subset["net_pnl"].sum(),
            atol=1e-8,
            rtol=0,
        ):
            raise RuntimeError(f"PnL decomposition failure: {slip}")

        report["scenarios"][str(slip)] = {
            "original": breakdown(subset),
            "ceiling_070": breakdown(kept),
            "excluded": breakdown(excluded),
            "pnl_change": float(kept["net_pnl"].sum() - subset["net_pnl"].sum()),
        }

    # --------------------------------------------------------
    # Output protection
    # --------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_REPORT.exists() or OUTPUT_ROWS.exists():
        raise FileExistsError(
            "P14-C outputs already exist. Archive them before rerunning."
        )

    df.to_csv(
        OUTPUT_ROWS,
        index=False,
    )

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\nP14-C COMPLETE")
    print(
        "original_trade_markets=",
        EXPECTED_TRADES,
    )
    print(
        "price_ceiling=",
        PRICE_CEILING,
    )

    for slip in SLIPPAGE_SCENARIOS:
        scenario = report["scenarios"][str(slip)]

        print(f"\nSLIPPAGE {slip} TICKS")

        for name in (
            "original",
            "ceiling_070",
            "excluded",
        ):
            print(
                name,
                scenario[name]["overall"],
            )

        print("\nCEILING BY SIDE")

        for side, values in scenario["ceiling_070"]["by_side"].items():
            print(side, values)

        print(
            "\nPNL CHANGE=",
            scenario["pnl_change"],
        )

    print("\nOUTPUTS")
    print(OUTPUT_REPORT)
    print(OUTPUT_ROWS)


if __name__ == "__main__":
    main()
