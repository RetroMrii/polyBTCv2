from __future__ import annotations

import csv
import json
import random

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_candidate_audit.json"


THRESHOLDS = (
    0.00,
    0.02,
    0.05,
)

MIN_ENTRY_PRICE = 0.40
MAX_ENTRY_PRICE = 0.60

BOOTSTRAP_SAMPLES = 10000
RANDOM_SEED = 42


def load_records() -> list[dict]:
    with INPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    result = []

    for row in rows:
        result.append(
            {
                "split": row["split"],
                "condition_id": (row["condition_id"].strip().lower()),
                "target_horizon_seconds": int(row["target_horizon_seconds"]),
                "selected_side": (row["selected_side"].strip()),
                "selected_ask": float(row["selected_ask"]),
                "selected_edge": float(row["selected_edge"]),
                "realized_pnl_per_share": float(row["realized_pnl_per_share"]),
            }
        )

    return result


def first_entries(
    rows: list[dict],
    threshold: float,
) -> list[dict]:
    grouped: dict[
        str,
        list[dict],
    ] = {}

    for row in rows:
        grouped.setdefault(
            row["condition_id"],
            [],
        ).append(row)

    selected = []

    for market_rows in grouped.values():
        ordered = sorted(
            market_rows,
            key=lambda row: -row["target_horizon_seconds"],
        )

        for row in ordered:
            if row["selected_edge"] >= threshold:
                selected.append(row)
                break

    return selected


def candidate_rows(
    rows: list[dict],
) -> list[dict]:
    return [
        row
        for row in rows
        if (MIN_ENTRY_PRICE <= row["selected_ask"] < MAX_ENTRY_PRICE)
    ]


def percentile(
    values: list[float],
    q: float,
) -> float:
    ordered = sorted(values)

    position = (len(ordered) - 1) * q

    lower = int(position)

    upper = min(
        lower + 1,
        len(ordered) - 1,
    )

    fraction = position - lower

    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap(
    rows: list[dict],
) -> dict:
    if not rows:
        return {
            "trades": 0,
            "mean_pnl": None,
            "ci_95_lower": None,
            "ci_95_upper": None,
            "probability_mean_positive": None,
        }

    pnls = [row["realized_pnl_per_share"] for row in rows]

    rng = random.Random(RANDOM_SEED)

    means = []

    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [pnls[rng.randrange(len(pnls))] for _ in range(len(pnls))]

        means.append(sum(sample) / len(sample))

    return {
        "trades": len(rows),
        "mean_pnl": (sum(pnls) / len(pnls)),
        "ci_95_lower": percentile(
            means,
            0.025,
        ),
        "ci_95_upper": percentile(
            means,
            0.975,
        ),
        "probability_mean_positive": (sum(value > 0.0 for value in means) / len(means)),
    }


def summarize(
    rows: list[dict],
) -> dict:
    yes_rows = [row for row in rows if row["selected_side"] == "YES"]

    no_rows = [row for row in rows if row["selected_side"] == "NO"]

    return {
        "all": bootstrap(rows),
        "yes": bootstrap(yes_rows),
        "no": bootstrap(no_rows),
        "mean_entry_price": (
            sum(row["selected_ask"] for row in rows) / len(rows) if rows else None
        ),
        "mean_predicted_edge": (
            sum(row["selected_edge"] for row in rows) / len(rows) if rows else None
        ),
        "horizon_counts": dict(
            sorted(
                Counter(str(row["target_horizon_seconds"]) for row in rows).items(),
                reverse=True,
            )
        ),
    }


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_candidate_audit_v1"),
        "candidate_definition": {
            "entry_price_lower": (MIN_ENTRY_PRICE),
            "entry_price_upper": (MAX_ENTRY_PRICE),
            "selection": ("first chronological threshold crossing per market"),
            "important_note": (
                "The 0.40-0.60 price range "
                "was identified exploratorily "
                "during P8 and is not an "
                "untouched validated rule."
            ),
        },
    }

    for split in (
        "validation",
        "development_holdout",
    ):
        split_rows = [row for row in rows if row["split"] == split]

        report[split] = {}

        for threshold in THRESHOLDS:
            entries = first_entries(
                split_rows,
                threshold,
            )

            candidate = candidate_rows(entries)

            report[split][f"{threshold:.2f}"] = summarize(candidate)

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


if __name__ == "__main__":
    main()
