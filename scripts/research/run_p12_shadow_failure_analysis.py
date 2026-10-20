from __future__ import annotations

import csv
import json

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]

DECISIONS_FILE = ROOT / "data" / "shadow" / "p12_consensus_shadow_decisions.csv"

RESOLUTIONS_FILE = ROOT / "data" / "shadow" / "p12_market_resolutions.csv"

OUTPUT_REPORT = ROOT / "data" / "shadow" / "p12_shadow_failure_analysis.json"

OUTPUT_TRADES = ROOT / "data" / "shadow" / "p12_shadow_trade_diagnostics.csv"


REPORT_VERSION = "p12_shadow_failure_analysis_v1"


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


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def stats(
    values: list[float],
) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }

    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def main() -> None:
    decisions = load_csv(DECISIONS_FILE)

    resolutions = load_csv(RESOLUTIONS_FILE)

    resolution_index = {}

    for row in resolutions:
        condition_id = row["condition_id"].strip().lower()

        if condition_id in resolution_index:
            raise RuntimeError(f"duplicate resolution: {condition_id}")

        resolution_index[condition_id] = row

    trade_rows = [row for row in decisions if row["decision"].strip() == "TRADE"]

    diagnostics = []

    for row in trade_rows:
        condition_id = row["condition_id"].strip().lower()

        resolution = resolution_index.get(condition_id)

        if resolution is None:
            continue

        if resolution["validation_status"].strip() != "VALID":
            continue

        label_yes = int(resolution["label_yes"])

        side = row["side"].strip()

        won = label_yes == 1 if side == "YES" else label_yes == 0

        selected_ask = float(row["selected_ask"])

        model_probability = float(row["model_probability"])

        market_probability = float(row["market_probability"])

        probability_gap = float(row["probability_gap"])

        relative_distance = optional_float(row.get("relative_distance_from_strike"))

        reference_price = optional_float(row.get("reference_price"))

        strike = optional_float(row.get("strike"))

        reference_return_30s = optional_float(row.get("reference_return_30s"))

        book_age = optional_float(row.get("selected_book_age_ms"))

        depth = optional_float(row.get("selected_depth"))

        timestamp = parse_timestamp(row["prediction_timestamp"])

        filled_size = 5.0

        # Zero-slippage gross economics before fees.
        gross_pnl_per_share = 1.0 - selected_ask if won else -selected_ask

        # Exact P10/P12 fee accounting:
        # calculate fee on the whole fill and
        # round to 5 decimals before converting
        # back to per-share economics.
        raw_fee = filled_size * 0.07 * selected_ask * (1.0 - selected_ask)

        fee = round(
            raw_fee,
            5,
        )

        fee_per_share = fee / filled_size

        net_pnl_per_share = gross_pnl_per_share - fee_per_share

        diagnostics.append(
            {
                "condition_id": (condition_id),
                "prediction_timestamp": (row["prediction_timestamp"]),
                "date_utc": (timestamp.date().isoformat()),
                "hour_utc": (timestamp.hour),
                "horizon_seconds": int(row["target_horizon_seconds"]),
                "side": (side),
                "label_yes": (label_yes),
                "won": int(won),
                "selected_ask": (selected_ask),
                "model_probability": (model_probability),
                "market_probability": (market_probability),
                "probability_gap": (probability_gap),
                "relative_distance_from_strike": (relative_distance),
                "reference_price": (reference_price),
                "strike": (strike),
                "reference_return_30s": (reference_return_30s),
                "selected_depth": (depth),
                "selected_book_age_ms": (book_age),
                "gross_pnl_per_share_0tick": (gross_pnl_per_share),
                "fee_per_share_0tick": (fee_per_share),
                "net_pnl_per_share_0tick": (net_pnl_per_share),
            }
        )

    if not diagnostics:
        raise RuntimeError("no resolved P12 TRADE rows")

    diagnostics.sort(key=lambda row: row["prediction_timestamp"])

    with OUTPUT_TRADES.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(diagnostics[0].keys()),
        )

        writer.writeheader()
        writer.writerows(diagnostics)

    wins = [row for row in diagnostics if row["won"] == 1]

    losses = [row for row in diagnostics if row["won"] == 0]

    def summarize_group(
        rows: list[dict],
    ) -> dict:
        if not rows:
            return {
                "entries": 0,
            }

        pnl_values = [row["net_pnl_per_share_0tick"] for row in rows]

        won_count = sum(row["won"] for row in rows)

        return {
            "entries": len(rows),
            "wins": won_count,
            "losses": (len(rows) - won_count),
            "win_rate": (won_count / len(rows)),
            "net_pnl_per_share": (sum(pnl_values) / len(pnl_values)),
            "total_net_pnl_per_share_units": (sum(pnl_values)),
            "selected_ask": stats([row["selected_ask"] for row in rows]),
            "model_probability": stats([row["model_probability"] for row in rows]),
            "market_probability": stats([row["market_probability"] for row in rows]),
            "probability_gap": stats([row["probability_gap"] for row in rows]),
            "relative_distance_from_strike": stats(
                [
                    row["relative_distance_from_strike"]
                    for row in rows
                    if (row["relative_distance_from_strike"] is not None)
                ]
            ),
            "reference_return_30s": stats(
                [
                    row["reference_return_30s"]
                    for row in rows
                    if (row["reference_return_30s"] is not None)
                ]
            ),
            "selected_depth": stats(
                [
                    row["selected_depth"]
                    for row in rows
                    if (row["selected_depth"] is not None)
                ]
            ),
            "selected_book_age_ms": stats(
                [
                    row["selected_book_age_ms"]
                    for row in rows
                    if (row["selected_book_age_ms"] is not None)
                ]
            ),
        }

    by_side = {}

    for side in (
        "YES",
        "NO",
    ):
        by_side[side] = summarize_group(
            [row for row in diagnostics if row["side"] == side]
        )

    by_horizon = {}

    for horizon in (
        60,
        30,
    ):
        by_horizon[str(horizon)] = summarize_group(
            [row for row in diagnostics if (row["horizon_seconds"] == horizon)]
        )

    by_date = {}

    dates = sorted({row["date_utc"] for row in diagnostics})

    for date in dates:
        by_date[date] = summarize_group(
            [row for row in diagnostics if row["date_utc"] == date]
        )

    loss_side_counts = Counter(row["side"] for row in losses)

    loss_horizon_counts = Counter(row["horizon_seconds"] for row in losses)

    average_win = (
        mean([row["net_pnl_per_share_0tick"] for row in wins]) if wins else None
    )

    average_loss = (
        mean([row["net_pnl_per_share_0tick"] for row in losses]) if losses else None
    )

    expected_contribution = mean(
        [row["net_pnl_per_share_0tick"] for row in diagnostics]
    )

    report = {
        "report_version": (REPORT_VERSION),
        "methodology": {
            "strategy_changes": ("NONE"),
            "parameter_search": (False),
            "scope": ("prospective P12 shadow TRADE rows only"),
            "execution_scenario": ("0 tick diagnostic economics"),
        },
        "overall": summarize_group(diagnostics),
        "payoff_decomposition": {
            "wins": len(wins),
            "losses": len(losses),
            "average_net_win_per_share": (average_win),
            "average_net_loss_per_share": (average_loss),
            "mean_net_pnl_per_trade_share": (expected_contribution),
        },
        "losses": {
            "count": len(losses),
            "by_side": dict(loss_side_counts),
            "by_horizon": {
                str(key): value for key, value in sorted(loss_horizon_counts.items())
            },
            "rows": (losses),
        },
        "by_side": (by_side),
        "by_horizon": (by_horizon),
        "by_date": (by_date),
        "important_notes": [
            ("This report is diagnostic only."),
            (
                "No strategy thresholds or model "
                "parameters are selected from these "
                "results."
            ),
            ("The current prospective sample remains small."),
            (
                "Observed YES/NO differences must "
                "not be converted into a side filter "
                "without a separately registered "
                "future experiment."
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

    print("P12 shadow failure analysis complete")

    print()
    print(
        "trades=",
        len(diagnostics),
    )
    print(
        "wins=",
        len(wins),
    )
    print(
        "losses=",
        len(losses),
    )

    print()
    print(
        "average net win/share=",
        average_win,
    )
    print(
        "average net loss/share=",
        average_loss,
    )
    print(
        "mean net pnl/trade/share=",
        expected_contribution,
    )

    print()
    print(
        "losses by side=",
        dict(loss_side_counts),
    )
    print(
        "losses by horizon=",
        dict(sorted(loss_horizon_counts.items())),
    )

    print()
    print("BY SIDE")

    for side in (
        "YES",
        "NO",
    ):
        print(
            side,
            by_side[side],
        )

    print()
    print("BY HORIZON")

    for horizon in (
        "60",
        "30",
    ):
        print(
            horizon,
            by_horizon[horizon],
        )

    print()
    print("LOSING TRADES")

    for row in losses:
        print(row)

    print()
    print(f"Wrote {OUTPUT_TRADES}")
    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
