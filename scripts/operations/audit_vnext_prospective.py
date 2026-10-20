from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


HORIZONS = (240, 180, 120, 90, 60, 30)
VERSION = "vnext_prospective_integrity_v1"


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")

    return value.astimezone(timezone.utc)


def probability(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    return result if math.isfinite(result) and 0 <= result <= 1 else None


def read_db(path):
    path = Path(path).resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    db = sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=15,
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def load_data(state_dir):
    with read_db(state_dir / "decisions.sqlite3") as db:
        decisions = [
            dict(row)
            for row in db.execute("""
                SELECT
                    condition_id,
                    horizon_seconds,
                    target_at_utc,
                    processed_at_utc,
                    completed_at_utc,
                    status,
                    reason,
                    snapshot_id,
                    snapshot_observed_at_utc,
                    snapshot_ingested_at_utc,
                    horizon_gap_seconds,
                    model_probability_yes,
                    market_probability_yes,
                    prediction_market_probability_yes
                FROM decisions
                ORDER BY target_at_utc, condition_id
            """)
        ]

    with read_db(state_dir / "resolutions.sqlite3") as db:
        resolutions = [
            dict(row)
            for row in db.execute("""
                SELECT
                    condition_id,
                    label_yes,
                    resolved_at_utc,
                    settlement_status
                FROM resolutions
            """)
        ]

    return decisions, resolutions


def audit(decisions, resolutions, since, now=None):
    since = utc(since)
    now = utc(now or datetime.now(timezone.utc))

    rows = [row for row in decisions if utc(row["target_at_utc"]) >= since]

    counts = Counter()
    reasons = Counter()
    statuses = Counter()
    violations = []
    by_market = defaultdict(list)
    by_horizon = defaultdict(Counter)
    seen = set()

    resolution_map = {}

    for resolution in resolutions:
        market = resolution["condition_id"].strip().lower()

        if market in resolution_map:
            violations.append(f"duplicate_resolution:{market}")

        resolution_map[market] = resolution

        if type(resolution["label_yes"]) is not int or (
            resolution["label_yes"] not in (0, 1)
        ):
            violations.append(f"invalid_resolution_label:{market}")

    for row in rows:
        market = row["condition_id"].strip().lower()
        horizon = row["horizon_seconds"]
        key = (market, horizon)

        by_market[market].append(row)
        by_horizon[horizon]["decisions"] += 1

        reasons[row["reason"]] += 1
        statuses[row["status"]] += 1

        if key in seen:
            violations.append(f"duplicate_decision:{key}")

        seen.add(key)

        if horizon not in HORIZONS:
            violations.append(f"unsupported_horizon:{key}")

        target = utc(row["target_at_utc"])
        processed = utc(row["processed_at_utc"])

        if processed < target:
            violations.append(f"processed_before_target:{key}")

        if target > now:
            violations.append(f"future_target:{key}")

        if row["status"] == "PROCESSING":
            counts["unresolved_processing_claims"] += 1

        if row["status"] == "AWAITING_EXECUTION_ADAPTER":
            counts["awaiting_adapter"] += 1

        if row["status"] == "SHADOW_FILLED":
            counts["shadow_filled_decisions"] += 1

        snapshot_id = row["snapshot_id"]

        observed_raw = row["snapshot_observed_at_utc"]
        ingested_raw = row["snapshot_ingested_at_utc"]

        if snapshot_id:
            counts["selected_snapshots"] += 1

            if not observed_raw or not ingested_raw:
                violations.append(f"incomplete_snapshot_timestamps:{key}")
            else:
                observed = utc(observed_raw)
                ingested = utc(ingested_raw)

                if observed > target:
                    violations.append(f"observed_after_target:{key}")

                # Late arrival is a legitimate rejection,
                # not necessarily an invariant failure.
                if ingested > target:
                    counts["snapshots_ingested_after_target"] += 1

                    if row["reason"] not in (
                        "snapshot_arrived_after_target",
                        "prediction_snapshot_not_causal",
                    ):
                        violations.append(f"noncausal_snapshot_accepted:{key}")

                if ingested < observed:
                    counts["ingested_before_observed"] += 1

                if observed <= target and ingested <= target:
                    counts["causally_available_snapshots"] += 1
                    by_horizon[horizon]["causal_snapshots"] += 1

        model_raw = row["model_probability_yes"]
        market_raw = row["prediction_market_probability_yes"]

        model_p = probability(model_raw)
        market_p = probability(market_raw)

        if model_raw is not None and model_p is None:
            violations.append(f"invalid_model_probability:{key}")

        if market_raw is not None and market_p is None:
            violations.append(f"invalid_market_probability:{key}")

        if model_p is not None:
            counts["model_predictions"] += 1
            by_horizon[horizon]["model_predictions"] += 1

        if market_p is not None:
            counts["market_baselines"] += 1
            by_horizon[horizon]["market_baselines"] += 1

        if model_p is not None and market_p is not None:
            counts["paired_predictions"] += 1
            by_horizon[horizon]["paired_predictions"] += 1

            if (
                not snapshot_id
                or not observed_raw
                or not ingested_raw
                or utc(observed_raw) > target
                or utc(ingested_raw) > target
            ):
                violations.append(f"paired_prediction_not_causal:{key}")

            if row["status"] not in ("ABSTAIN", "SHADOW_FILLED"):
                violations.append(f"paired_prediction_nonterminal:{key}")

        elif model_p is not None:
            counts["model_without_market_baseline"] += 1

    resolved_markets = set()
    paired_markets = set()
    resolved_paired_markets = set()
    resolved_paired_rows = 0

    for market, market_rows in by_market.items():
        resolution = resolution_map.get(market)

        valid_resolution = (
            resolution is not None
            and type(resolution["label_yes"]) is int
            and resolution["label_yes"] in (0, 1)
            and resolution["settlement_status"] in ("VERIFIED", "SETTLED")
        )

        if valid_resolution:
            resolved_markets.add(market)

        market_has_pair = False

        for row in market_rows:
            if (
                probability(row["model_probability_yes"]) is not None
                and probability(row["prediction_market_probability_yes"]) is not None
            ):
                market_has_pair = True

                if valid_resolution:
                    resolved_paired_rows += 1
                    resolved_paired_markets.add(market)

        if market_has_pair:
            paired_markets.add(market)

        # Only require all six horizons when all six
        # targets fall within the audit window and
        # enough time has elapsed to finalize them.
        earliest = min(utc(r["target_at_utc"]) for r in market_rows)

        expiry = earliest + timedelta(seconds=240)

        if (
            max(r["horizon_seconds"] for r in market_rows) == 240
            and earliest >= since
            and expiry <= now
        ):
            missing = set(HORIZONS) - {r["horizon_seconds"] for r in market_rows}

            if missing:
                counts["markets_missing_scheduled_decisions"] += 1

    counts["audited_decisions"] = len(rows)
    counts["audited_markets"] = len(by_market)
    counts["verified_audited_markets"] = len(resolved_markets)
    counts["paired_markets"] = len(paired_markets)
    counts["resolved_paired_markets"] = len(resolved_paired_markets)
    counts["resolved_paired_predictions"] = resolved_paired_rows

    counts["nonpaired_decisions"] = len(rows) - counts["paired_predictions"]

    coverage = counts["paired_predictions"] / len(rows) if rows else None

    return {
        "audit_version": VERSION,
        "since_utc": since.isoformat(),
        "audited_at_utc": now.isoformat(),
        "coverage": {
            **dict(sorted(counts.items())),
            "paired_decision_coverage": (
                round(coverage, 6) if coverage is not None else None
            ),
        },
        "decision_statuses": dict(sorted(statuses.items())),
        "abstention_reasons": dict(sorted(reasons.items())),
        "by_horizon": {str(h): dict(sorted(by_horizon[h].items())) for h in HORIZONS},
        "integrity_violations": violations[:100],
        "integrity_violation_count": len(violations),
        "notes": [
            "Post-cutoff audit only; earlier journal rows excluded.",
            "Late snapshot ingestion is tracked separately.",
            "Missing predictions can be legitimate abstentions.",
            "Paired rows from one market are correlated.",
            "No trading performance inference is made.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/shadow/vnext_local_live"),
    )
    parser.add_argument(
        "--since",
        default="2026-10-09T18:27:00+00:00",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/vnext_prospective_integrity.json"),
    )

    args = parser.parse_args()

    decisions, resolutions = load_data(args.state_dir)

    result = audit(
        decisions,
        resolutions,
        since=args.since,
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
