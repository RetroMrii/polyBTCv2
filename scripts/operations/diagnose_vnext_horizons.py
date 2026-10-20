from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


VERSION = "vnext_horizon_diagnostics_v1"
HORIZONS = (240, 180, 120, 90, 60, 30)
WINDOW_SECONDS = 20.0


def timestamp(value):
    if not value:
        return None

    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"Timezone-naive timestamp: {value}")

    return dt.astimezone(timezone.utc)


def open_readonly(path):
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


def load_decisions(path, since):
    with open_readonly(path) as db:
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT
                    condition_id,
                    horizon_seconds,
                    target_at_utc,
                    processed_at_utc,
                    status,
                    reason,
                    snapshot_id,
                    snapshot_observed_at_utc,
                    snapshot_ingested_at_utc,
                    model_probability_yes,
                    prediction_market_probability_yes
                FROM decisions
                WHERE target_at_utc >= ?
                ORDER BY target_at_utc, condition_id
            """,
                (since.isoformat(timespec="microseconds"),),
            )
        ]


def find_csv_neighbors(path, decisions):
    """
    Find nearest locally observed CSV snapshots
    on either side of each scheduled horizon.

    The CSV does NOT establish when the shadow
    service ingested those observations.
    """
    targets_by_market = defaultdict(list)

    for decision in decisions:
        market = decision["condition_id"].strip().lower()
        targets_by_market[market].append(decision)

        decision["_before"] = None
        decision["_after"] = None

    seen_markets = Counter()
    valid_rows = Counter()

    with Path(path).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        required = {"market_id", "observed_at"}
        missing = required - set(reader.fieldnames or [])

        if missing:
            raise ValueError(f"Missing CSV columns: {sorted(missing)}")

        for row in reader:
            market = (row.get("market_id") or "").strip().lower()

            if market not in targets_by_market:
                continue

            seen_markets[market] += 1

            try:
                observed = timestamp(row.get("observed_at"))
            except (ValueError, TypeError, OverflowError):
                valid_rows["invalid_observed_at"] += 1
                continue

            if observed is None:
                valid_rows["missing_observed_at"] += 1
                continue

            valid_rows["valid"] += 1

            for decision in targets_by_market[market]:
                target = timestamp(decision["target_at_utc"])
                delta = (observed - target).total_seconds()

                if not -WINDOW_SECONDS <= delta <= WINDOW_SECONDS:
                    continue

                key = "_before" if delta <= 0 else "_after"
                previous = decision[key]

                # Choose closest to target.
                if previous is None or abs(delta) < abs(previous["delta_seconds"]):
                    decision[key] = {
                        "observed_at": observed.isoformat(),
                        "delta_seconds": round(delta, 6),
                    }

    return {
        "markets_with_csv_rows": len(seen_markets),
        "matching_csv_rows": sum(seen_markets.values()),
        "csv_timestamp_checks": dict(valid_rows),
    }


def summarize(decisions):
    by_horizon = defaultdict(Counter)
    by_reason = defaultdict(Counter)
    examples = []

    for row in decisions:
        horizon = int(row["horizon_seconds"])
        reason = row["reason"]
        target = timestamp(row["target_at_utc"])
        processed = timestamp(row["processed_at_utc"])

        selected_observed = timestamp(row["snapshot_observed_at_utc"])
        selected_ingested = timestamp(row["snapshot_ingested_at_utc"])

        before = row["_before"]
        after = row["_after"]

        h = by_horizon[horizon]
        r = by_reason[reason]

        h["decisions"] += 1
        r["decisions"] += 1

        if row["model_probability_yes"] is not None:
            h["model_predictions"] += 1

        if (
            row["model_probability_yes"] is not None
            and row["prediction_market_probability_yes"] is not None
        ):
            h["paired_predictions"] += 1

        if before:
            h["csv_snapshot_before_target"] += 1
            r["csv_snapshot_before_target"] += 1

            gap = abs(before["delta_seconds"])

            if gap <= 2:
                h["csv_pre_target_within_2s"] += 1
                r["csv_pre_target_within_2s"] += 1

            if gap <= 10:
                h["csv_pre_target_within_10s"] += 1
                r["csv_pre_target_within_10s"] += 1

        else:
            h["no_pre_target_csv_within_20s"] += 1
            r["no_pre_target_csv_within_20s"] += 1

        if after:
            h["csv_snapshot_after_target"] += 1
            r["csv_snapshot_after_target"] += 1

        if selected_ingested:
            ingestion_delay = (selected_ingested - target).total_seconds()

            if ingestion_delay > 0:
                h["selected_ingested_late"] += 1
                r["selected_ingested_late"] += 1

        else:
            ingestion_delay = None

        processing_delay = (processed - target).total_seconds()

        if processing_delay > 5:
            h["processed_over_5s_after_target"] += 1
            r["processed_over_5s_after_target"] += 1

        if reason in (
            "stale_horizon",
            "snapshot_arrived_after_target",
            "missing_horizon",
        ):
            examples.append(
                {
                    "market": row["condition_id"],
                    "horizon": horizon,
                    "reason": reason,
                    "target": target.isoformat(),
                    "processing_delay_seconds": round(processing_delay, 3),
                    "csv_before": before,
                    "csv_after": after,
                    "selected_observed_at": (
                        selected_observed.isoformat() if selected_observed else None
                    ),
                    "selected_ingestion_delay_seconds": (
                        round(ingestion_delay, 3)
                        if ingestion_delay is not None
                        else None
                    ),
                }
            )

    return {
        "decision_count": len(decisions),
        "by_horizon": {str(h): dict(sorted(by_horizon[h].items())) for h in HORIZONS},
        "by_reason": {
            reason: dict(sorted(counts.items()))
            for reason, counts in sorted(by_reason.items())
        },
        "rejection_examples": examples[:40],
        "total_rejections_examined": len(examples),
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("data/shadow/vnext_local_live"),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/live/vnext_market_snapshots.csv"),
    )
    parser.add_argument(
        "--since",
        default="2026-10-09T18:27:00+00:00",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/vnext_horizon_diagnostics.json"),
    )

    args = parser.parse_args()
    since = timestamp(args.since)

    decisions = load_decisions(
        args.state_dir / "decisions.sqlite3",
        since,
    )

    csv_coverage = find_csv_neighbors(
        args.csv,
        decisions,
    )

    report = {
        "version": VERSION,
        "since_utc": since.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "csv_coverage": csv_coverage,
        **summarize(decisions),
        "limitations": [
            "CSV observed_at is not shadow ingestion time.",
            "Only snapshots within +/-20s are examined.",
            "Absent CSV observations may reflect file rotation.",
            "Reason codes retain existing orchestrator semantics.",
            "No journal, collector, or trading-state writes.",
        ],
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
