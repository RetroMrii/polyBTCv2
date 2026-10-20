from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "experiments"

INPUT = BASE / "p13_model_improvement" / "p13_rtds_native_walkforward_predictions.csv"

OUTPUT = BASE / "p14_market_relative" / "p14_agreement_diagnostics.json"

# Descriptive bands fixed before examining this report.
GAP_BINS = [-1.01, -0.20, -0.10, -0.05, 0.00, 0.05, 0.10, 0.20, 1.01]


def summarize(frame):
    if frame.empty:
        return {"rows": 0, "markets": 0}

    y = frame["label_yes"].to_numpy(dtype=int)
    market = frame["market"].to_numpy(dtype=float)
    model = frame["model"].to_numpy(dtype=float)

    return {
        "rows": int(len(frame)),
        "markets": int(frame["condition_id"].nunique()),
        "yes_rate": float(y.mean()),
        "mean_market_probability": float(market.mean()),
        "mean_model_probability": float(model.mean()),
        "market_brier": float(np.mean((market - y) ** 2)),
        "model_brier": float(np.mean((model - y) ** 2)),
        "model_minus_market_brier": float(
            np.mean((model - y) ** 2 - (market - y) ** 2)
        ),
        "market_direction_accuracy": float(np.mean((market >= 0.5) == y)),
        "model_direction_accuracy": float(np.mean((model >= 0.5) == y)),
    }


def main():
    df = pd.read_csv(INPUT)

    required = [
        "condition_id",
        "fold",
        "target_horizon_seconds",
        "label_yes",
        "normalized_yes_mid",
        "hgb3_native",
    ]

    missing = sorted(set(required) - set(df.columns))
    if missing:
        raise RuntimeError(f"Missing columns: {missing}")

    df["market"] = pd.to_numeric(df["normalized_yes_mid"], errors="coerce")
    df["model"] = pd.to_numeric(df["hgb3_native"], errors="coerce")
    df["label_yes"] = pd.to_numeric(df["label_yes"], errors="coerce")

    df = df.loc[
        df["market"].between(0, 1)
        & df["model"].between(0, 1)
        & df["label_yes"].isin([0, 1])
    ].copy()

    if df.duplicated(["condition_id", "target_horizon_seconds"]).any():
        raise RuntimeError("Duplicate prediction keys.")

    df["gap"] = df["model"] - df["market"]

    df["relationship"] = np.where(
        (df["model"] >= 0.5) == (df["market"] >= 0.5),
        "AGREEMENT",
        "DISAGREEMENT",
    )

    df["gap_band"] = pd.cut(
        df["gap"],
        bins=GAP_BINS,
        include_lowest=True,
    ).astype(str)

    report = {
        "experiment": "p14_market_relative_diagnostics_v1",
        "status": "exploratory",
        "probability_source": "chronological_oos_hgb3_native",
        "interpretation": (
            "Descriptive conditional forecast comparison. "
            "Not evidence of executable trading profitability."
        ),
        "overall": summarize(df),
        "by_relationship": {},
        "by_gap_band": {},
        "by_horizon": {},
        "by_fold": {},
    }

    for name, group in df.groupby("relationship"):
        report["by_relationship"][name] = summarize(group)

    for name, group in df.groupby("gap_band", observed=True):
        report["by_gap_band"][str(name)] = summarize(group)

    for horizon, group in df.groupby("target_horizon_seconds"):
        report["by_horizon"][str(int(horizon))] = {
            "overall": summarize(group),
            "agreement": summarize(group[group["relationship"] == "AGREEMENT"]),
            "disagreement": summarize(group[group["relationship"] == "DISAGREEMENT"]),
        }

    for fold, group in df.groupby("fold"):
        report["by_fold"][str(int(fold))] = {
            "overall": summarize(group),
            "agreement": summarize(group[group["relationship"] == "AGREEMENT"]),
            "disagreement": summarize(group[group["relationship"] == "DISAGREEMENT"]),
        }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("P14-A MARKET-RELATIVE DIAGNOSTICS")
    print("\nOVERALL")
    print(json.dumps(report["overall"], indent=2))

    print("\nRELATIONSHIPS")
    print(json.dumps(report["by_relationship"], indent=2))

    print("\nGAP BANDS")
    print(json.dumps(report["by_gap_band"], indent=2))

    print("\nHORIZONS")
    print(json.dumps(report["by_horizon"], indent=2))

    print("\nFOLDS")
    print(json.dumps(report["by_fold"], indent=2))

    print("\nreport=", OUTPUT)


if __name__ == "__main__":
    main()
