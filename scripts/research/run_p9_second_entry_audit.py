from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p9_scalein_trades.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p9_second_entry_audit.json"


REPORT_VERSION = "p9_second_entry_audit_v1"


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


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


def extract_second_entries(
    rows: list[dict[str, str]],
) -> list[dict]:
    result = []

    for row in rows:
        if int(row["entry_count"]) < 2:
            continue

        second_price = optional_float(row["entry_2_price"])

        second_horizon = row["entry_2_horizon_seconds"].strip()

        if second_price is None or not second_horizon:
            raise RuntimeError("two-entry row missing second-entry data")

        side = row["side"]

        label_yes = int(row["label_yes"])

        settle = settlement_value(
            side=side,
            label_yes=label_yes,
        )

        pnl = settle - second_price

        result.append(
            {
                "strategy_config": (row["strategy_config"]),
                "split": (row["split"]),
                "condition_id": (row["condition_id"]),
                "side": side,
                "second_horizon_seconds": int(second_horizon),
                "second_entry_price": (second_price),
                "label_yes": (label_yes),
                "settlement_value": (settle),
                "second_entry_pnl_per_share": (pnl),
                "won": (settle == 1.0),
            }
        )

    return result


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "second_entries": 0,
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

        return sum(row["second_entry_pnl_per_share"] for row in selected) / len(
            selected
        )

    return {
        "second_entries": len(rows),
        "mean_entry_price": (
            sum(row["second_entry_price"] for row in rows) / len(rows)
        ),
        "mean_pnl_per_share": (
            sum(row["second_entry_pnl_per_share"] for row in rows) / len(rows)
        ),
        "win_rate": (sum(row["won"] for row in rows) / len(rows)),
        "side_counts": dict(sorted(Counter(row["side"] for row in rows).items())),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["second_horizon_seconds"]) for row in rows).items(),
                reverse=True,
            )
        ),
        "yes_mean_pnl": (mean_pnl(yes_rows)),
        "no_mean_pnl": (mean_pnl(no_rows)),
    }


def main() -> None:
    rows = load_rows()

    second_entries = extract_second_entries(rows)

    configs = sorted({row["strategy_config"] for row in rows})

    report = {
        "report_version": (REPORT_VERSION),
        "interpretation": (
            "Measures only the marginal "
            "second same-side share from "
            "the P9 scale-in policy."
        ),
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
                for row in second_entries
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

    print(f"second-entry rows: {len(second_entries)}")


if __name__ == "__main__":
    main()
