from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p85_strategy_decisions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p9_reversal_audit.json"


REPORT_VERSION = "p9_reversal_audit_v1"


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
    side: str,
    label_yes: int,
) -> float:
    if side == "YES":
        return float(label_yes)

    if side == "NO":
        return float(1 - label_yes)

    raise RuntimeError(f"unexpected side: {side}")


def build_flips(
    rows: list[dict[str, str]],
) -> list[dict]:
    grouped = {}

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

        original_side = first["selected_side"]

        flip = None

        for row in ordered[1:]:
            if row["selected_side"] != original_side:
                flip = row
                break

        if flip is None:
            continue

        flip_side = flip["selected_side"]

        flip_price = float(flip["selected_price"])

        label_yes = int(flip["label_yes"])

        flip_settle = settlement_value(
            flip_side,
            label_yes,
        )

        original_settle = settlement_value(
            original_side,
            label_yes,
        )

        result.append(
            {
                "strategy_config": (strategy_config),
                "split": split,
                "condition_id": (condition_id),
                "original_side": (original_side),
                "flip_side": (flip_side),
                "flip_horizon_seconds": int(flip["target_horizon_seconds"]),
                "flip_price": (flip_price),
                "label_yes": (label_yes),
                "flip_side_pnl_per_share": (flip_settle - flip_price),
                "flip_side_won": (flip_settle == 1.0),
                "original_side_won": (original_settle == 1.0),
            }
        )

    return result


def summarize(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "flips": 0,
            "mean_flip_pnl_per_share": None,
            "flip_win_rate": None,
            "original_side_win_rate": None,
            "horizon_counts": {},
            "direction_counts": {},
        }

    return {
        "flips": len(rows),
        "mean_flip_pnl_per_share": (
            sum(row["flip_side_pnl_per_share"] for row in rows) / len(rows)
        ),
        "flip_win_rate": (sum(row["flip_side_won"] for row in rows) / len(rows)),
        "original_side_win_rate": (
            sum(row["original_side_won"] for row in rows) / len(rows)
        ),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["flip_horizon_seconds"]) for row in rows).items(),
                reverse=True,
            )
        ),
        "direction_counts": dict(
            sorted(
                Counter(
                    (row["original_side"] + "->" + row["flip_side"]) for row in rows
                ).items()
            )
        ),
    }


def main() -> None:
    rows = load_rows()

    flips = build_flips(rows)

    configs = sorted({row["strategy_config"] for row in rows})

    report = {
        "report_version": (REPORT_VERSION),
        "interpretation": (
            "Audits the first opposite-side "
            "TRADE signal after the initial "
            "entry. This does not yet simulate "
            "closing or reversing a position."
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
                for row in flips
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

    print(f"flip rows: {len(flips)}")


if __name__ == "__main__":
    main()
