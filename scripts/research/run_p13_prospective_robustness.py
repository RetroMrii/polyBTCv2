from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]

HISTORICAL_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_enriched_supervised.csv"
)

PROSPECTIVE_DATASET_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_supervised.csv"
)

PREDICTIONS_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_validation_predictions.csv"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_robustness_report.json"
)


BOOTSTRAP_SAMPLES = 10000
RANDOM_SEED = 1337


def optional_float(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return float(value)


def summarize(values):
    array = np.asarray(
        values,
        dtype=float,
    )

    return {
        "count": int(len(array)),
        "mean": float(np.mean(array)),
        "std": float(
            np.std(
                array,
                ddof=1,
            )
        )
        if len(array) > 1
        else 0.0,
        "min": float(np.min(array)),
        "p01": float(np.quantile(array, 0.01)),
        "p05": float(np.quantile(array, 0.05)),
        "p25": float(np.quantile(array, 0.25)),
        "median": float(np.quantile(array, 0.50)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "max": float(np.max(array)),
    }


def load_feature_distribution():
    historical = []

    with HISTORICAL_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            value = optional_float(row.get("btc_return_1m"))

            if value is not None:
                historical.append(value)

    prospective = []

    with PROSPECTIVE_DATASET_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            value = optional_float(row.get("rtds_ohlc_return_1m"))

            if value is not None:
                prospective.append(value)

    if not historical:
        raise RuntimeError("no historical btc_return_1m values")

    if not prospective:
        raise RuntimeError("no prospective RTDS return values")

    historical_array = np.asarray(
        historical,
        dtype=float,
    )

    prospective_array = np.asarray(
        prospective,
        dtype=float,
    )

    hist_mean = float(np.mean(historical_array))

    hist_std = float(
        np.std(
            historical_array,
            ddof=1,
        )
    )

    prospective_mean = float(np.mean(prospective_array))

    prospective_std = float(
        np.std(
            prospective_array,
            ddof=1,
        )
    )

    return {
        "historical_bitstamp": (summarize(historical_array)),
        "prospective_rtds": (summarize(prospective_array)),
        "prospective_mean_shift_in_historical_std": (
            (prospective_mean - hist_mean) / hist_std
        ),
        "prospective_std_ratio_vs_historical": (prospective_std / hist_std),
    }


def load_predictions():
    rows = []

    with PREDICTIONS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            rows.append(
                {
                    "condition_id": (row["condition_id"].strip().lower()),
                    "horizon": int(float(row["target_horizon_seconds"])),
                    "label": int(row["label_yes"]),
                    "a": float(row["A_BASELINE_probability"]),
                    "b": float(row["B_RTDS_MINUTE_probability"]),
                }
            )

    return rows


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def logloss(y, p):
    epsilon = 1e-15

    p = np.clip(
        p,
        epsilon,
        1.0 - epsilon,
    )

    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def paired_metrics(rows):
    y = np.asarray(
        [row["label"] for row in rows],
        dtype=float,
    )

    a = np.asarray(
        [row["a"] for row in rows],
        dtype=float,
    )

    b = np.asarray(
        [row["b"] for row in rows],
        dtype=float,
    )

    return {
        "rows": len(rows),
        "brier_A": brier(y, a),
        "brier_B": brier(y, b),
        "brier_B_minus_A": (brier(y, b) - brier(y, a)),
        "log_loss_A": logloss(y, a),
        "log_loss_B": logloss(y, b),
        "log_loss_B_minus_A": (logloss(y, b) - logloss(y, a)),
    }


def market_bootstrap(rows):
    by_market = defaultdict(list)

    for row in rows:
        by_market[row["condition_id"]].append(row)

    markets = sorted(by_market.keys())

    rng = np.random.default_rng(RANDOM_SEED)

    brier_deltas = []
    logloss_deltas = []

    for _ in range(BOOTSTRAP_SAMPLES):
        sampled_markets = rng.choice(
            markets,
            size=len(markets),
            replace=True,
        )

        sample_rows = []

        for market in sampled_markets:
            sample_rows.extend(by_market[market])

        metrics = paired_metrics(sample_rows)

        brier_deltas.append(metrics["brier_B_minus_A"])

        logloss_deltas.append(metrics["log_loss_B_minus_A"])

    brier_array = np.asarray(
        brier_deltas,
        dtype=float,
    )

    logloss_array = np.asarray(
        logloss_deltas,
        dtype=float,
    )

    return {
        "markets": len(markets),
        "bootstrap_samples": (BOOTSTRAP_SAMPLES),
        "brier_delta": {
            "mean": float(np.mean(brier_array)),
            "ci95_low": float(
                np.quantile(
                    brier_array,
                    0.025,
                )
            ),
            "ci95_high": float(
                np.quantile(
                    brier_array,
                    0.975,
                )
            ),
            "probability_B_better": float(np.mean(brier_array < 0.0)),
        },
        "log_loss_delta": {
            "mean": float(np.mean(logloss_array)),
            "ci95_low": float(
                np.quantile(
                    logloss_array,
                    0.025,
                )
            ),
            "ci95_high": float(
                np.quantile(
                    logloss_array,
                    0.975,
                )
            ),
            "probability_B_better": float(np.mean(logloss_array < 0.0)),
        },
    }


def main():
    distribution = load_feature_distribution()

    rows = load_predictions()

    if not rows:
        raise RuntimeError("no prospective predictions")

    overall = paired_metrics(rows)

    bootstrap = market_bootstrap(rows)

    horizons = sorted(
        {row["horizon"] for row in rows},
        reverse=True,
    )

    by_horizon = {}

    for horizon in horizons:
        horizon_rows = [row for row in rows if row["horizon"] == horizon]

        by_horizon[str(horizon)] = {
            "metrics": paired_metrics(horizon_rows),
            "market_bootstrap": (market_bootstrap(horizon_rows)),
        }

    report = {
        "report_version": ("p13_prospective_robustness_v1"),
        "feature_distribution_shift": (distribution),
        "overall": overall,
        "overall_market_bootstrap": (bootstrap),
        "by_horizon": by_horizon,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P13 prospective robustness audit complete")

    print()

    print("FEATURE DISTRIBUTIONS")

    print(
        "historical_bitstamp=",
        distribution["historical_bitstamp"],
    )

    print(
        "prospective_rtds=",
        distribution["prospective_rtds"],
    )

    print(
        "mean_shift_in_historical_std=",
        distribution["prospective_mean_shift_in_historical_std"],
    )

    print(
        "std_ratio=",
        distribution["prospective_std_ratio_vs_historical"],
    )

    print()

    print("OVERALL")

    print(overall)

    print()

    print("MARKET-CLUSTER BOOTSTRAP")

    print(bootstrap)

    print()

    print("BY HORIZON")

    for horizon in horizons:
        result = by_horizon[str(horizon)]

        print()
        print(
            "horizon",
            horizon,
        )

        print(
            "metrics=",
            result["metrics"],
        )

        print(
            "bootstrap=",
            result["market_bootstrap"],
        )

    print()

    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
