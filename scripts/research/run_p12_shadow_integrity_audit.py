from __future__ import annotations

import csv
import json

from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "shadow" / "p12_consensus_shadow_decisions.csv"

OUTPUT_REPORT = ROOT / "data" / "shadow" / "p12_shadow_integrity_report.json"


RESEARCH_CUTOFF = datetime.fromisoformat("2026-10-01T17:09:30+00:00")

ALLOWED_HORIZONS = {
    60,
    30,
}


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def main() -> None:
    rows = load_csv(INPUT_FILE)

    if not rows:
        raise RuntimeError("shadow decision file is empty")

    duplicate_keys = []
    seen_keys = set()

    trade_markets = Counter()

    before_or_at_cutoff = []
    invalid_horizons = []
    future_snapshot_rows = []
    invalid_model_probabilities = []
    invalid_market_probabilities = []
    trade_rule_violations = []
    missing_v2_trade_tick_size = []

    decision_counts = Counter()
    reason_counts = Counter()
    horizon_counts = Counter()
    side_counts = Counter()

    missing_reference_return = 0
    missing_market_probability = 0

    model_probabilities = []
    market_probabilities = []
    probability_gaps = []

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        condition_id = row["condition_id"].strip().lower()

        horizon = int(row["target_horizon_seconds"])

        prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

        snapshot_observed_at = parse_timestamp(row["snapshot_observed_at"])

        decision = row["decision"].strip()

        reason = row["reason"].strip()

        side = row["side"].strip()

        key = (
            condition_id,
            horizon,
        )

        if key in seen_keys:
            duplicate_keys.append(
                {
                    "row": row_number,
                    "condition_id": (condition_id),
                    "horizon": (horizon),
                }
            )

        seen_keys.add(key)

        if prediction_timestamp <= RESEARCH_CUTOFF:
            before_or_at_cutoff.append(row_number)

        if horizon not in ALLOWED_HORIZONS:
            invalid_horizons.append(row_number)

        if snapshot_observed_at > prediction_timestamp:
            future_snapshot_rows.append(row_number)

        model_probability = optional_float(row["model_probability"])

        market_probability = optional_float(row["market_probability"])

        probability_gap = optional_float(row["probability_gap"])

        reference_return_30s = optional_float(row["reference_return_30s"])

        if reference_return_30s is None:
            missing_reference_return += 1

        if market_probability is None:
            missing_market_probability += 1

        if model_probability is not None:
            model_probabilities.append(model_probability)

            if not (0.0 <= model_probability <= 1.0):
                invalid_model_probabilities.append(row_number)

        if market_probability is not None:
            market_probabilities.append(market_probability)

            if not (0.0 <= market_probability <= 1.0):
                invalid_market_probabilities.append(row_number)

        if probability_gap is not None:
            probability_gaps.append(probability_gap)

        decision_counts[decision] += 1

        reason_counts[reason] += 1

        horizon_counts[horizon] += 1

        if side:
            side_counts[side] += 1

        if decision == "TRADE":
            trade_markets[condition_id] += 1

            selected_ask = optional_float(row["selected_ask"])

            selected_depth = optional_float(row["selected_depth"])

            selected_book_age_ms = optional_float(row["selected_book_age_ms"])

            shadow_version = row["shadow_version"].strip()

            selected_tick_size = optional_float(row.get("selected_tick_size"))

            violations = []

            if shadow_version == "p12_consensus_shadow_v2" and (
                selected_tick_size is None or selected_tick_size <= 0.0
            ):
                violations.append("missing_or_invalid_selected_tick_size")

                missing_v2_trade_tick_size.append(row_number)

            if side not in {
                "YES",
                "NO",
            }:
                violations.append("missing_or_invalid_side")

            if probability_gap is None or probability_gap > 0.05:
                violations.append("invalid_probability_gap")

            if selected_ask is None:
                violations.append("missing_selected_ask")

            if selected_depth is None or selected_depth < 5.0:
                violations.append("invalid_selected_depth")

            if selected_book_age_ms is None or selected_book_age_ms > 500.0:
                violations.append("invalid_selected_book_age")

            if model_probability is None or market_probability is None:
                violations.append("missing_trade_probability")

            if side == "YES" and (
                model_probability is None
                or market_probability is None
                or model_probability <= 0.5
                or market_probability <= 0.5
            ):
                violations.append("yes_direction_not_confirmed")

            if side == "NO" and (
                model_probability is None
                or market_probability is None
                or model_probability >= 0.5
                or market_probability >= 0.5
            ):
                violations.append("no_direction_not_confirmed")

            if violations:
                trade_rule_violations.append(
                    {
                        "row": row_number,
                        "condition_id": (condition_id),
                        "violations": (violations),
                    }
                )

    multiple_trade_markets = {
        condition_id: count
        for (
            condition_id,
            count,
        ) in trade_markets.items()
        if count > 1
    }

    integrity_passed = all(
        (
            not duplicate_keys,
            not missing_v2_trade_tick_size,
            not before_or_at_cutoff,
            not invalid_horizons,
            not future_snapshot_rows,
            not invalid_model_probabilities,
            not invalid_market_probabilities,
            not multiple_trade_markets,
            not trade_rule_violations,
        )
    )

    report = {
        "rows": len(rows),
        "markets": len({row["condition_id"].strip().lower() for row in rows}),
        "decision_counts": dict(decision_counts),
        "reason_counts": dict(reason_counts),
        "horizon_counts": {
            str(key): value for key, value in sorted(horizon_counts.items())
        },
        "side_counts": dict(side_counts),
        "missing_reference_return_30s": (missing_reference_return),
        "missing_market_probability": (missing_market_probability),
        "duplicate_market_horizon_keys": (len(duplicate_keys)),
        "rows_at_or_before_research_cutoff": (len(before_or_at_cutoff)),
        "invalid_horizon_rows": len(invalid_horizons),
        "snapshot_after_prediction_rows": len(future_snapshot_rows),
        "invalid_model_probability_rows": len(invalid_model_probabilities),
        "missing_v2_trade_tick_size": len(missing_v2_trade_tick_size),
        "invalid_market_probability_rows": len(invalid_market_probabilities),
        "markets_with_multiple_trades": (multiple_trade_markets),
        "trade_rule_violations": (trade_rule_violations),
        "model_probability_range": (
            [
                min(model_probabilities),
                max(model_probabilities),
            ]
            if model_probabilities
            else None
        ),
        "market_probability_range": (
            [
                min(market_probabilities),
                max(market_probabilities),
            ]
            if market_probabilities
            else None
        ),
        "probability_gap_range": (
            [
                min(probability_gaps),
                max(probability_gaps),
            ]
            if probability_gaps
            else None
        ),
        "integrity_passed": (integrity_passed),
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

    print("P12 shadow integrity audit complete")

    print(
        "rows=",
        len(rows),
    )

    print(
        "markets=",
        report["markets"],
    )

    print(
        "decisions=",
        dict(decision_counts),
    )

    print(
        "reasons=",
        dict(reason_counts),
    )

    print(
        "horizons=",
        dict(sorted(horizon_counts.items())),
    )

    print(
        "sides=",
        dict(side_counts),
    )

    print()

    print(
        "missing_reference_return_30s=",
        missing_reference_return,
    )

    print(
        "missing_market_probability=",
        missing_market_probability,
    )

    print(
        "duplicate_keys=",
        len(duplicate_keys),
    )

    print(
        "pre_cutoff_rows=",
        len(before_or_at_cutoff),
    )

    print(
        "invalid_horizons=",
        len(invalid_horizons),
    )

    print(
        "future_snapshot_rows=",
        len(future_snapshot_rows),
    )

    print(
        "multiple_trade_markets=",
        len(multiple_trade_markets),
    )

    print(
        "trade_rule_violations=",
        len(trade_rule_violations),
    )

    print()

    print(
        "model_probability_range=",
        report["model_probability_range"],
    )

    print(
        "missing_v2_trade_tick_size=",
        len(missing_v2_trade_tick_size),
    )

    print(
        "market_probability_range=",
        report["market_probability_range"],
    )

    print(
        "probability_gap_range=",
        report["probability_gap_range"],
    )

    print()

    print(
        "INTEGRITY PASSED=",
        integrity_passed,
    )

    print()

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
