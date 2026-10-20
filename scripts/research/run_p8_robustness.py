from __future__ import annotations

import csv
import json
import random

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "normalized" / "p8_edge_predictions.csv"

OUTPUT_FILE = ROOT / "data" / "normalized" / "p8_robustness.json"


THRESHOLDS = (
    0.00,
    0.02,
    0.05,
    0.10,
    0.15,
)

COSTS_PER_SHARE = (
    0.000,
    0.005,
    0.010,
    0.020,
    0.030,
    0.050,
)

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


def percentile(
    values: list[float],
    q: float,
) -> float:
    ordered = sorted(values)

    index = (len(ordered) - 1) * q

    lower = int(index)
    upper = min(
        lower + 1,
        len(ordered) - 1,
    )

    fraction = index - lower

    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_pnl(
    records: list[dict],
) -> dict:
    if not records:
        return {
            "trades": 0,
            "mean_gross_pnl": None,
            "ci_95_lower": None,
            "ci_95_upper": None,
            "probability_mean_positive": None,
        }

    pnl = [row["realized_pnl_per_share"] for row in records]

    rng = random.Random(RANDOM_SEED)

    bootstrap_means = []

    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [pnl[rng.randrange(len(pnl))] for _ in range(len(pnl))]

        bootstrap_means.append(sum(sample) / len(sample))

    return {
        "trades": len(records),
        "mean_gross_pnl": (sum(pnl) / len(pnl)),
        "ci_95_lower": percentile(
            bootstrap_means,
            0.025,
        ),
        "ci_95_upper": percentile(
            bootstrap_means,
            0.975,
        ),
        "probability_mean_positive": (
            sum(value > 0.0 for value in bootstrap_means) / len(bootstrap_means)
        ),
    }


def cost_report(
    records: list[dict],
) -> dict:
    if not records:
        return {}

    gross_mean = sum(row["realized_pnl_per_share"] for row in records) / len(records)

    return {f"{cost:.3f}": (gross_mean - cost) for cost in COSTS_PER_SHARE}


def main() -> None:
    rows = load_records()

    report = {
        "version": ("p8_robustness_v1"),
        "bootstrap_samples": (BOOTSTRAP_SAMPLES),
        "random_seed": (RANDOM_SEED),
        "cost_interpretation": (
            "Generic all-in cost per share "
            "subtracted from gross settlement "
            "PnL. This is a sensitivity test, "
            "not an empirical execution-cost "
            "estimate."
        ),
    }

    for split in (
        "validation",
        "development_holdout",
    ):
        split_rows = [row for row in rows if row["split"] == split]

        results = {}

        for threshold in THRESHOLDS:
            selected = first_entries(
                split_rows,
                threshold,
            )

            results[f"{threshold:.2f}"] = {
                "bootstrap": (bootstrap_pnl(selected)),
                "net_pnl_by_cost": (cost_report(selected)),
            }

        report[split] = results

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
