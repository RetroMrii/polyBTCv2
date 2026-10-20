from __future__ import annotations

import csv
import json

from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXECUTION_FILE = ROOT / "data" / "normalized" / "p11_walk_forward_execution_trades.csv"

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_regime_robustness_report.json"


REPORT_VERSION = "p11_regime_robustness_v1"

FOCUS_SCENARIO = "age_500ms_slip_1tick"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def optional_float(value: object) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(
        value.strip().replace(
            "Z",
            "+00:00",
        )
    )


def lineage_key(
    row: dict[str, str],
) -> tuple[str, str, int]:
    return (
        row["condition_id"].strip().lower(),
        row["prediction_timestamp"].strip(),
        int(row["target_horizon_seconds"]),
    )


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "candidate_entries": 0,
            "filled_entries": 0,
            "filled_shares": 0.0,
            "net_realized_pnl": 0.0,
            "net_pnl_per_share": None,
            "return_on_entry_notional": None,
        }

    filled = [row for row in rows if row["fill_status"] == "FILLED"]

    filled_shares = sum(float(row["filled_size"]) for row in filled)

    pnl = sum(float(row["net_realized_pnl"]) for row in filled)

    notional = sum(float(row["entry_notional"]) for row in filled)

    return {
        "candidate_entries": len(rows),
        "filled_entries": len(filled),
        "filled_shares": filled_shares,
        "net_realized_pnl": pnl,
        "net_pnl_per_share": (pnl / filled_shares if filled_shares else None),
        "return_on_entry_notional": (pnl / notional if notional else None),
    }


def quantile_thresholds(
    values: list[float],
) -> tuple[float, float]:
    ordered = sorted(values)

    if not ordered:
        raise RuntimeError("cannot calculate quantiles from empty data")

    low_index = int(0.33 * (len(ordered) - 1))

    high_index = int(0.67 * (len(ordered) - 1))

    return (
        ordered[low_index],
        ordered[high_index],
    )


def bucket(
    value: float | None,
    low: float,
    high: float,
) -> str:
    if value is None:
        return "MISSING"

    if value <= low:
        return "LOW"

    if value <= high:
        return "MEDIUM"

    return "HIGH"


def main() -> None:
    execution_rows = load_csv(EXECUTION_FILE)

    p4_rows = load_csv(P4_FILE)

    execution_rows = [
        row for row in execution_rows if (row["scenario"] == FOCUS_SCENARIO)
    ]

    if not execution_rows:
        raise RuntimeError("focus execution scenario not found")

    p4_index = {lineage_key(row): row for row in p4_rows}

    enriched = []

    for row in execution_rows:
        key = lineage_key(row)

        p4 = p4_index.get(key)

        if p4 is None:
            raise RuntimeError(f"missing P4 lineage: {key}")

        side = row["side"]

        spread = (
            optional_float(p4.get("yes_spread"))
            if side == "YES"
            else optional_float(p4.get("no_spread"))
        )

        depth = (
            optional_float(p4.get("yes_top_depth"))
            if side == "YES"
            else optional_float(p4.get("no_top_depth"))
        )

        volatility = optional_float(p4.get("realized_volatility_60s"))

        if volatility is None:
            volatility = optional_float(p4.get("volatility_60s"))

        enriched_row = dict(row)

        enriched_row["regime_spread"] = spread

        enriched_row["regime_depth"] = depth

        enriched_row["regime_volatility"] = volatility

        enriched.append(enriched_row)

    spreads = [
        row["regime_spread"] for row in enriched if row["regime_spread"] is not None
    ]

    depths = [
        row["regime_depth"] for row in enriched if row["regime_depth"] is not None
    ]

    volatilities = [
        row["regime_volatility"]
        for row in enriched
        if row["regime_volatility"] is not None
    ]

    spread_low, spread_high = quantile_thresholds(spreads)

    depth_low, depth_high = quantile_thresholds(depths)

    vol_low, vol_high = quantile_thresholds(volatilities)

    grouped = defaultdict(list)

    for row in enriched:
        timestamp = parse_dt(row["prediction_timestamp"])

        hour_block = (timestamp.hour // 6) * 6

        dimensions = {
            "horizon": str(row["target_horizon_seconds"]),
            "volatility": bucket(
                row["regime_volatility"],
                vol_low,
                vol_high,
            ),
            "spread": bucket(
                row["regime_spread"],
                spread_low,
                spread_high,
            ),
            "depth": bucket(
                row["regime_depth"],
                depth_low,
                depth_high,
            ),
            "utc_time_block": (f"{hour_block:02d}-{hour_block + 5:02d}"),
        }

        for (
            dimension,
            value,
        ) in dimensions.items():
            grouped[
                (
                    row["strategy_config"],
                    dimension,
                    value,
                )
            ].append(row)

    configs = sorted({row["strategy_config"] for row in enriched})

    report = {
        "report_version": (REPORT_VERSION),
        "scenario": (FOCUS_SCENARIO),
        "quantile_thresholds": {
            "spread": {
                "low_medium": (spread_low),
                "medium_high": (spread_high),
            },
            "depth": {
                "low_medium": (depth_low),
                "medium_high": (depth_high),
            },
            "volatility": {
                "low_medium": (vol_low),
                "medium_high": (vol_high),
            },
        },
        "important_note": (
            "Regime buckets are descriptive "
            "only and must not be used to "
            "select new trading filters from "
            "this forward dataset."
        ),
        "configs": {},
    }

    for config in configs:
        report["configs"][config] = {}

        for dimension in (
            "horizon",
            "volatility",
            "spread",
            "depth",
            "utc_time_block",
        ):
            dimension_report = {}

            keys = sorted(
                {
                    value
                    for (
                        candidate_config,
                        candidate_dimension,
                        value,
                    ) in grouped
                    if (candidate_config == config and candidate_dimension == dimension)
                }
            )

            for value in keys:
                dimension_report[value] = summarize(
                    grouped[
                        (
                            config,
                            dimension,
                            value,
                        )
                    ]
                )

            report["configs"][config][dimension] = dimension_report

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P11 regime robustness complete")

    print(
        "scenario=",
        FOCUS_SCENARIO,
    )

    for config in configs:
        print()
        print(config)

        print("  HORIZON")

        for (
            value,
            metrics,
        ) in report["configs"][config]["horizon"].items():
            print(
                "   ",
                value,
                "entries=",
                metrics["filled_entries"],
                "net/share=",
                (
                    round(
                        metrics["net_pnl_per_share"],
                        6,
                    )
                    if metrics["net_pnl_per_share"] is not None
                    else None
                ),
            )

        print("  VOLATILITY")

        for (
            value,
            metrics,
        ) in report["configs"][config]["volatility"].items():
            print(
                "   ",
                value,
                "entries=",
                metrics["filled_entries"],
                "net/share=",
                (
                    round(
                        metrics["net_pnl_per_share"],
                        6,
                    )
                    if metrics["net_pnl_per_share"] is not None
                    else None
                ),
            )

    print()

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
