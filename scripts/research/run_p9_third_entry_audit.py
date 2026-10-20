from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p9_third_entry_audit.json"


REPORT_VERSION = "p9_third_entry_audit_v1"


def parse_dt(
    value: str,
) -> datetime:
    return datetime.fromisoformat(value.strip())


def load_rows() -> list[dict[str, str]]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def settlement_value(
    *,
    side: str,
    label_yes: int,
) -> float:
    if side == "YES":
        return float(label_yes)

    if side == "NO":
        return float(1 - label_yes)

    raise RuntimeError(f"unexpected side: {side}")


def extract_third_entries(
    rows: list[dict[str, str]],
) -> list[dict]:
    grouped: dict[
        tuple[str, str, str],
        list[dict[str, str]],
    ] = {}

    for row in rows:
        if row["action"] != "TRADE":
            continue

        key = (
            row["strategy_config"],
            row["split"],
            row["condition_id"],
        )

        grouped.setdefault(
            key,
            [],
        ).append(row)

    result = []

    for (
        strategy_config,
        split,
        condition_id,
    ), market_rows in grouped.items():
        ordered = sorted(
            market_rows,
            key=lambda row: parse_dt(row["prediction_timestamp"]),
        )

        first = ordered[0]

        side = first["selected_side"]

        same_side_entries = [row for row in ordered if (row["selected_side"] == side)]

        if len(same_side_entries) < 3:
            continue

        third = same_side_entries[2]

        third_price = float(third["selected_price"])

        third_horizon = int(third["target_horizon_seconds"])

        label_yes = int(third["label_yes"])

        settle = settlement_value(
            side=side,
            label_yes=label_yes,
        )

        pnl = settle - third_price

        result.append(
            {
                "strategy_config": (strategy_config),
                "split": (split),
                "condition_id": (condition_id),
                "side": (side),
                "third_horizon_seconds": (third_horizon),
                "third_entry_price": (third_price),
                "label_yes": (label_yes),
                "settlement_value": (settle),
                "third_entry_pnl_per_share": (pnl),
                "won": (settle == 1.0),
            }
        )

    return result


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "third_entries": 0,
            "mean_entry_price": None,
            "mean_pnl_per_share": None,
            "win_rate": None,
            "side_counts": {},
            "horizon_counts": {},
            "yes_mean_pnl": None,
            "no_mean_pnl": None,
        }

    yes_rows = [row for row in rows if row["side"] == "YES"]

    no_rows = [row for row in rows if row["side"] == "NO"]

    def mean_pnl(
        selected: list[dict],
    ) -> float | None:
        if not selected:
            return None

        return sum(row["third_entry_pnl_per_share"] for row in selected) / len(selected)

    return {
        "third_entries": len(rows),
        "mean_entry_price": (sum(row["third_entry_price"] for row in rows) / len(rows)),
        "mean_pnl_per_share": (
            sum(row["third_entry_pnl_per_share"] for row in rows) / len(rows)
        ),
        "win_rate": (sum(row["won"] for row in rows) / len(rows)),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["third_horizon_seconds"]) for row in rows).items(),
                reverse=True,
            )
        ),
        "yes_mean_pnl": (mean_pnl(yes_rows)),
        "no_mean_pnl": (mean_pnl(no_rows)),
    }


def main() -> None:
    rows = load_rows()

    third_entries = extract_third_entries(rows)

    configs = sorted({row["strategy_config"] for row in rows})

    report = {
        "report_version": (REPORT_VERSION),
        "interpretation": ("Measures only the marginal third same-side share."),
        "strategy_configs": {},
    }

    for config in configs:
        report["strategy_configs"][config] = {}

        for split in (
            "validation",
            "development_holdout",
        ):
            selected = [
                row
                for row in third_entries
                if (row["strategy_config"] == config and row["split"] == split)
            ]

            report["strategy_configs"][config][split] = summarize(selected)

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {OUTPUT_FILE}")

    print(f"third-entry rows: {len(third_entries)}")


if __name__ == "__main__":
    main()
