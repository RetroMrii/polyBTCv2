from __future__ import annotations

import csv
import json

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p11_frozen_execution_trades.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p11_temporal_robustness_report.json"

REPORT_VERSION = "p11_temporal_robustness_v1"

FOCUS_SCENARIO = "age_500ms_slip_1tick"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def summarize(rows: list[dict[str, str]]) -> dict:
    filled = [row for row in rows if row["fill_status"] == "FILLED"]

    filled_shares = sum(float(row["filled_size"]) for row in filled)

    net_pnl = sum(float(row["net_realized_pnl"]) for row in filled)

    notional = sum(float(row["entry_notional"]) for row in filled)

    markets = {row["condition_id"] for row in rows}

    wins = sum(float(row["net_realized_pnl"]) > 0.0 for row in filled)

    return {
        "candidate_entries": len(rows),
        "filled_entries": len(filled),
        "markets": len(markets),
        "filled_shares": filled_shares,
        "net_realized_pnl": net_pnl,
        "net_pnl_per_share": (net_pnl / filled_shares if filled_shares else None),
        "return_on_entry_notional": (net_pnl / notional if notional else None),
        "entry_win_rate": (wins / len(filled) if filled else None),
    }


def main() -> None:
    rows = load_csv(INPUT_FILE)

    rows = [row for row in rows if row["scenario"] == FOCUS_SCENARIO]

    if not rows:
        raise RuntimeError(f"scenario not found: {FOCUS_SCENARIO}")

    by_day = defaultdict(list)
    by_six_hour = defaultdict(list)
    by_config = defaultdict(list)

    for row in rows:
        ts = parse_dt(row["prediction_timestamp"])

        day_key = ts.date().isoformat()

        six_hour_start = (ts.hour // 6) * 6

        six_hour_key = f"{day_key}T{six_hour_start:02d}:00Z"

        config = row["strategy_config"]

        by_day[(config, day_key)].append(row)

        by_six_hour[(config, six_hour_key)].append(row)

        by_config[config].append(row)

    configs = sorted(by_config)

    report = {
        "report_version": REPORT_VERSION,
        "scenario": FOCUS_SCENARIO,
        "important_note": (
            "This is descriptive robustness analysis "
            "only. No thresholds or configurations "
            "are selected using these windows."
        ),
        "configs": {},
    }

    for config in configs:
        daily = {}

        six_hour = {}

        for (
            candidate_config,
            key,
        ), selected in sorted(by_day.items()):
            if candidate_config != config:
                continue

            daily[key] = summarize(selected)

        for (
            candidate_config,
            key,
        ), selected in sorted(by_six_hour.items()):
            if candidate_config != config:
                continue

            six_hour[key] = summarize(selected)

        report["configs"][config] = {
            "overall": summarize(by_config[config]),
            "daily": daily,
            "six_hour_windows": six_hour,
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

    print("P11 temporal robustness complete")

    print(
        "scenario=",
        FOCUS_SCENARIO,
    )

    for config in configs:
        print()
        print(config)

        for (
            day,
            metrics,
        ) in report["configs"][config]["daily"].items():
            value = metrics["net_pnl_per_share"]

            print(
                day,
                "entries=",
                metrics["filled_entries"],
                "net/share=",
                (round(value, 6) if value is not None else None),
            )

    print()
    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
