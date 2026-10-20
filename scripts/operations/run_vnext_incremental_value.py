from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


VERSION = "vnext_incremental_value_v1"

WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)

HORIZONS = (240, 180, 120, 90, 60, 30)

MIN_HOLDOUT_MARKETS = 100


def read_only(path: Path) -> sqlite3.Connection:
    path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=15,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def valid_probability(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        probability = float(value)
    except (ValueError, TypeError, OverflowError):
        return None

    if not math.isfinite(probability):
        return None

    if not 0 <= probability <= 1:
        return None

    return probability


def load_paired_rows(state_dir: Path):
    decisions_path = state_dir / "decisions.sqlite3"
    resolutions_path = state_dir / "resolutions.sqlite3"

    with read_only(decisions_path) as db:
        decisions = [
            dict(row)
            for row in db.execute("""
                SELECT
                    condition_id,
                    horizon_seconds,
                    target_at_utc,
                    status,
                    reason,
                    model_probability_yes,
                    prediction_market_probability_yes
                FROM decisions
                ORDER BY target_at_utc, condition_id
            """)
        ]

    with read_only(resolutions_path) as db:
        resolutions = {
            str(row["condition_id"]).strip().lower(): dict(row)
            for row in db.execute("""
                SELECT
                    condition_id,
                    label_yes,
                    resolved_at_utc,
                    settlement_status
                FROM resolutions
                WHERE settlement_status IN ('VERIFIED', 'SETTLED')
            """)
        }

    exclusions = Counter()
    paired = []
    seen = set()

    for row in decisions:
        market = str(row["condition_id"]).strip().lower()
        horizon = int(row["horizon_seconds"])
        key = (market, horizon)

        if key in seen:
            raise ValueError(f"Duplicate decision for market/horizon: {key}")

        seen.add(key)

        if horizon not in HORIZONS:
            exclusions["unsupported_horizon"] += 1
            continue

        resolution = resolutions.get(market)

        if resolution is None:
            exclusions["missing_verified_resolution"] += 1
            continue

        label = resolution["label_yes"]

        if type(label) is not int or label not in (0, 1):
            raise ValueError(f"Invalid verified label for {market}")

        model = valid_probability(row["model_probability_yes"])
        baseline = valid_probability(row["prediction_market_probability_yes"])

        if model is None or baseline is None:
            exclusions["missing_or_invalid_paired_probability"] += 1
            continue

        target = datetime.fromisoformat(row["target_at_utc"])
        resolved = datetime.fromisoformat(resolution["resolved_at_utc"])

        if (
            target.tzinfo is None
            or resolved.tzinfo is None
            or target.utcoffset() is None
            or resolved.utcoffset() is None
        ):
            raise ValueError(f"Timezone-naive timestamps for {market}")

        if resolved <= target:
            raise ValueError(f"Resolution precedes prediction: {market}")

        paired.append(
            {
                "condition_id": market,
                "horizon_seconds": horizon,
                "target_at_utc": target.isoformat(),
                "label_yes": label,
                "model_probability_yes": model,
                "market_probability_yes": baseline,
            }
        )

    paired.sort(
        key=lambda r: (
            r["target_at_utc"],
            r["condition_id"],
            r["horizon_seconds"],
        )
    )

    coverage = {
        "journal_decisions": len(decisions),
        "verified_resolution_markets": len(resolutions),
        "paired_predictions": len(paired),
        "paired_markets": len({row["condition_id"] for row in paired}),
        "exclusions": dict(sorted(exclusions.items())),
    }

    return paired, coverage


def combined_probability(row, weight: float) -> float:
    return (1.0 - weight) * row["market_probability_yes"] + weight * row[
        "model_probability_yes"
    ]


def evaluate(rows, weight: float):
    if not rows:
        return None

    errors = []
    losses = []
    correct = 0

    for row in rows:
        p = combined_probability(row, weight)
        y = row["label_yes"]

        errors.append((p - y) ** 2)

        clipped = min(max(p, 1e-15), 1.0 - 1e-15)

        losses.append(-(y * math.log(clipped) + (1 - y) * math.log(1 - clipped)))

        prediction = int(p >= 0.5)
        correct += int(prediction == y)

    n = len(rows)

    return {
        "n": n,
        "unique_markets": len({row["condition_id"] for row in rows}),
        "accuracy": round(correct / n, 8),
        "brier": round(sum(errors) / n, 8),
        "log_loss": round(sum(losses) / n, 8),
    }


def evaluate_market_balanced(rows, weight):
    """
    Each market contributes equal weight, regardless
    of how many of its six horizons were captured.
    """
    by_market = defaultdict(list)

    for row in rows:
        by_market[row["condition_id"]].append(row)

    if not by_market:
        return None

    scores = [evaluate(market_rows, weight) for market_rows in by_market.values()]

    return {
        "markets": len(scores),
        "brier": sum(score["brier"] for score in scores) / len(scores),
        "log_loss": sum(score["log_loss"] for score in scores) / len(scores),
    }


BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 20261011


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None

    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return sorted_values[lower]

    part = position - lower

    return sorted_values[lower] * (1 - part) + sorted_values[upper] * part


def loss_difference(row, weight):
    """
    Paired candidate-minus-market losses.
    Negative means the candidate performs better.
    """
    y = row["label_yes"]
    baseline = row["market_probability_yes"]
    candidate = combined_probability(row, weight)

    brier_difference = (candidate - y) ** 2 - (baseline - y) ** 2

    def log_loss(p):
        p = min(max(p, 1e-15), 1.0 - 1e-15)
        return -(y * math.log(p) + (1 - y) * math.log(1 - p))

    return (
        brier_difference,
        log_loss(candidate) - log_loss(baseline),
    )


def cluster_bootstrap(
    rows,
    weight,
    *,
    resamples=BOOTSTRAP_RESAMPLES,
    seed=BOOTSTRAP_SEED,
):
    """
    Markets are the bootstrap units.

    First average each market's paired losses across
    its available horizons. Then resample entire
    markets with replacement.

    Primary estimand: equal weight per market.
    """
    if not 0 <= weight <= 1:
        raise ValueError("Weight must be between 0 and 1")

    if resamples < 1:
        raise ValueError("At least one resample is required")

    by_market = defaultdict(list)

    for row in rows:
        by_market[row["condition_id"]].append(row)

    markets = sorted(by_market)
    n_markets = len(markets)

    if n_markets < 2:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "markets": n_markets,
            "required_markets": 2,
        }

    # Each entry contains that market's mean paired
    # Brier difference and mean paired log-loss difference.
    market_differences = []

    for market in markets:
        losses = [loss_difference(row, weight) for row in by_market[market]]

        n = len(losses)

        market_differences.append(
            (
                sum(pair[0] for pair in losses) / n,
                sum(pair[1] for pair in losses) / n,
            )
        )

    observed = (
        sum(pair[0] for pair in market_differences) / n_markets,
        sum(pair[1] for pair in market_differences) / n_markets,
    )

    rng = random.Random(seed)
    brier_draws = []
    log_loss_draws = []

    for _ in range(resamples):
        indices = [rng.randrange(n_markets) for _ in range(n_markets)]

        brier_draws.append(sum(market_differences[i][0] for i in indices) / n_markets)

        log_loss_draws.append(
            sum(market_differences[i][1] for i in indices) / n_markets
        )

    brier_draws.sort()
    log_loss_draws.sort()

    def metric_result(value, draws):
        lower = percentile(draws, 0.025)
        upper = percentile(draws, 0.975)

        return {
            "difference": round(value, 8),
            "ci_95_lower": round(lower, 8),
            "ci_95_upper": round(upper, 8),
            "ci_excludes_zero": lower > 0 or upper < 0,
            "bootstrap_fraction_negative": round(
                sum(x < 0 for x in draws) / len(draws),
                6,
            ),
        }

    return {
        "status": "EVALUATED",
        "candidate_hgb3_weight": weight,
        "baseline_hgb3_weight": 0.0,
        "markets": n_markets,
        "prediction_rows": len(rows),
        "resamples": resamples,
        "seed": seed,
        "unit": "market",
        "estimand": "equal_market_weight",
        "difference_direction": ("candidate_minus_market; negative favors candidate"),
        "brier": metric_result(observed[0], brier_draws),
        "log_loss": metric_result(observed[1], log_loss_draws),
        "limitations": (
            "Exploratory percentile cluster bootstrap. "
            "Intervals assume sampled markets reasonably "
            "represent the target market population. "
            "They do not account for temporal dependence "
            "between markets or for choosing a candidate "
            "after inspecting these same observations."
        ),
    }


def uncertainty_report(rows):
    horizon_240 = [row for row in rows if row["horizon_seconds"] == 240]

    return {
        "method": "paired_market_cluster_bootstrap",
        "overall": {
            "hgb3_only": cluster_bootstrap(rows, 1.0),
            "blend_10pct": cluster_bootstrap(rows, 0.1),
            "blend_25pct": cluster_bootstrap(rows, 0.25),
            "blend_50pct": cluster_bootstrap(rows, 0.5),
        },
        "horizon_240": {
            "hgb3_only": cluster_bootstrap(horizon_240, 1.0),
            "blend_25pct": cluster_bootstrap(horizon_240, 0.25),
        },
        "multiple_comparison_warning": (
            "The 240-second horizon and blend weights "
            "were examined after inspecting historical "
            "performance. These intervals are exploratory "
            "and must not be interpreted as untouched "
            "confirmatory evidence."
        ),
    }


def weight_sweep(rows):
    return [
        {
            "hgb3_weight": weight,
            "metrics": evaluate(rows, weight),
            "market_balanced": evaluate_market_balanced(rows, weight),
        }
        for weight in WEIGHTS
    ]


def chronological_holdout(rows):
    market_times = {}

    for row in rows:
        market = row["condition_id"]
        timestamp = row["target_at_utc"]

        if market not in market_times or timestamp < market_times[market]:
            market_times[market] = timestamp

    ordered_markets = sorted(
        market_times,
        key=lambda market: (
            market_times[market],
            market,
        ),
    )

    if len(ordered_markets) < MIN_HOLDOUT_MARKETS:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "required_markets": MIN_HOLDOUT_MARKETS,
            "available_markets": len(ordered_markets),
        }

    split_index = int(len(ordered_markets) * 0.7)

    development_ids = set(ordered_markets[:split_index])
    holdout_ids = set(ordered_markets[split_index:])

    if development_ids & holdout_ids:
        raise RuntimeError("Market overlap in split")

    development = [row for row in rows if row["condition_id"] in development_ids]

    holdout = [row for row in rows if row["condition_id"] in holdout_ids]

    # Weight selection only uses earlier markets.
    # Tie-breaking prefers less HGB3 weight.
    selected_weight = min(
        WEIGHTS,
        key=lambda weight: (
            evaluate_market_balanced(development, weight)["brier"],
            weight,
        ),
    )

    return {
        "status": "EVALUATED",
        "development_markets": len(development_ids),
        "holdout_markets": len(holdout_ids),
        "selected_weight": selected_weight,
        "selection_metric": "market_balanced_brier",
        "development_results": weight_sweep(development),
        "holdout_results": {
            "market_only": evaluate(holdout, 0.0),
            "hgb3_only": evaluate(holdout, 1.0),
            "combined": evaluate(holdout, selected_weight),
            "selected_combination_weight": selected_weight,
        },
        "note": (
            "Holdout is chronological and market-disjoint. "
            "Do not reuse it to tune future weights."
        ),
    }


def build_report(rows, coverage):
    per_horizon = {}

    for horizon in HORIZONS:
        subset = [row for row in rows if row["horizon_seconds"] == horizon]

        per_horizon[str(horizon)] = {
            "market_only": evaluate(subset, 0.0),
            "hgb3_only": evaluate(subset, 1.0),
            "equal_weight": evaluate(subset, 0.5),
        }

    return {
        "report_version": VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "overall": {
            "market_only": evaluate(rows, 0.0),
            "hgb3_only": evaluate(rows, 1.0),
            "equal_weight": evaluate(rows, 0.5),
        },
        "weight_sweep": weight_sweep(rows),
        "by_horizon": per_horizon,
        "uncertainty": uncertainty_report(rows),
        "chronological_holdout": chronological_holdout(rows),
        "interpretation": (
            "Research-only predictive comparison. "
            "The weight sweep is descriptive, not an "
            "unbiased out-of-sample model-selection result. "
            "Markets, not individual horizons, are the "
            "primary independent units. "
            "No profitability claims."
        ),
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/shadow/vnext_local_live"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/vnext_incremental_value.json"),
    )

    args = parser.parse_args()

    rows, coverage = load_paired_rows(args.state_dir)

    report = build_report(rows, coverage)

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
