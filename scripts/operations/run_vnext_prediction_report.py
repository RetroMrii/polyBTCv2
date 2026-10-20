from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPORT_VERSION = "vnext_prospective_prediction_report_v2"
HORIZONS = (240, 180, 120, 90, 60, 30)


def read_rows(path: Path, query: str) -> list[dict]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return [dict(row) for row in db.execute(query)]


def probability(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def metrics(rows: list[dict], key: str) -> dict | None:
    pairs = [(probability(row.get(key)), row["label_yes"]) for row in rows]
    pairs = [(p, y) for p, y in pairs if p is not None]
    if not pairs:
        return None
    epsilon = 1e-15
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    log_loss = -sum(
        y * math.log(max(epsilon, min(1 - epsilon, p)))
        + (1 - y) * math.log(max(epsilon, min(1 - epsilon, 1 - p)))
        for p, y in pairs
    ) / len(pairs)
    return {
        "n": len(pairs),
        "unique_markets": len(
            {
                row["condition_id"]
                for row in rows
                if probability(row.get(key)) is not None
            }
        ),
        "brier": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "mean_predicted_yes": round(sum(p for p, _ in pairs) / len(pairs), 6),
        "actual_yes_rate": round(sum(y for _, y in pairs) / len(pairs), 6),
    }


def calibrate(rows: list[dict], key: str, bins: int = 10) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        p = probability(row.get(key))
        if p is not None:
            groups[min(int(p * bins), bins - 1)].append((p, row["label_yes"]))
    return [
        {
            "range": f"[{i / bins:.1f}, {(i + 1) / bins:.1f}{']' if i == bins - 1 else ')'}",
            "n": len(group),
            "avg_probability": round(sum(p for p, _ in group) / len(group), 6),
            "yes_frequency": round(sum(y for _, y in group) / len(group), 6),
        }
        for i, group in sorted(groups.items())
    ]


def build_report(decisions: list[dict], resolutions: list[dict]) -> dict:
    labels = {}
    for record in resolutions:
        market = str(record["condition_id"]).strip().lower()
        if (
            not market
            or record["settlement_status"] not in ("VERIFIED", "SETTLED")
            or type(record["label_yes"]) is not int
            or record["label_yes"] not in (0, 1)
        ):
            raise ValueError(f"Invalid registered resolution for {market!r}")
        if market in labels:
            raise ValueError(f"Duplicate resolution for {market}")
        labels[market] = record

    seen = set()
    eligible = []
    reason_counts = Counter()
    total = len(decisions)
    model_predictions = 0
    baseline_predictions = 0
    for record in decisions:
        market = str(record["condition_id"]).strip().lower()
        horizon = record["horizon_seconds"]
        key = (market, horizon)
        if not market or key in seen:
            raise ValueError(f"Invalid/duplicate journal decision {key}")
        seen.add(key)
        reason_counts[str(record["reason"])] += 1
        p = probability(record["model_probability_yes"])
        q = probability(record["prediction_market_probability_yes"])
        if record["model_probability_yes"] is not None and p is None:
            raise ValueError(f"Invalid model probability: {key}")
        if record["prediction_market_probability_yes"] is not None and q is None:
            raise ValueError(f"Invalid prediction-time market probability: {key}")
        if p is not None:
            model_predictions += 1
        if q is not None:
            baseline_predictions += 1
        label = labels.get(market)
        if label is None:
            continue
        # Check that the recorded decision precedes resolution.
        if datetime.fromisoformat(record["target_at_utc"]) >= datetime.fromisoformat(
            label["resolved_at_utc"]
        ):
            raise ValueError(f"Decision at/after resolution: {key}")
        eligible.append(
            {**record, "condition_id": market, "label_yes": label["label_yes"]}
        )

    modeled = [
        row for row in eligible if probability(row["model_probability_yes"]) is not None
    ]
    paired = [
        row
        for row in modeled
        if probability(row["prediction_market_probability_yes"]) is not None
    ]
    by_horizon = {}
    for horizon in HORIZONS:
        subset = [row for row in eligible if row["horizon_seconds"] == horizon]
        comparable = [
            row
            for row in subset
            if probability(row["model_probability_yes"]) is not None
            and probability(row["prediction_market_probability_yes"]) is not None
        ]
        by_horizon[str(horizon)] = {
            "resolved_decisions": len(subset),
            "model": metrics(subset, "model_probability_yes"),
            "market": metrics(subset, "prediction_market_probability_yes"),
            "paired_n": len(comparable),
            "paired_model": metrics(comparable, "model_probability_yes"),
            "paired_market": metrics(comparable, "prediction_market_probability_yes"),
        }

    return {
        "report_version": REPORT_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "coverage": {
            "journal_decisions": total,
            "journal_unique_markets": len(
                {row["condition_id"].strip().lower() for row in decisions}
            ),
            "verified_resolution_markets": len(labels),
            "resolved_decisions": len(eligible),
            "model_predictions_all": model_predictions,
            "market_probabilities_all": baseline_predictions,
            "resolved_model_predictions": len(modeled),
            "resolved_model_markets": len({row["condition_id"] for row in modeled}),
            "resolved_paired_comparisons": len(paired),
        },
        "journal_reasons": dict(sorted(reason_counts.items())),
        "model_all_resolved": metrics(eligible, "model_probability_yes"),
        "market_all_resolved": metrics(eligible, "prediction_market_probability_yes"),
        "paired_model": metrics(paired, "model_probability_yes"),
        "paired_market": metrics(paired, "prediction_market_probability_yes"),
        "calibration_model": calibrate(modeled, "model_probability_yes"),
        "by_horizon": by_horizon,
        "interpretation": "Diagnostic only. Rows within the same market are correlated. Compare paired metrics only. No inference about profitability or statistical significance.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only prospective HGB3 probability evaluation"
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("data/shadow/vnext_local_live")
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    decisions = read_rows(
        args.state_dir / "decisions.sqlite3",
        """
        SELECT condition_id, horizon_seconds, target_at_utc, status, reason,
               model_probability_yes, market_probability_yes, prediction_market_probability_yes
        FROM decisions
        ORDER BY target_at_utc, condition_id, horizon_seconds
    """,
    )
    resolutions = read_rows(
        args.state_dir / "resolutions.sqlite3",
        """
        SELECT condition_id, label_yes, resolved_at_utc, settlement_status
        FROM resolutions
    """,
    )
    report = build_report(decisions, resolutions)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(content, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
