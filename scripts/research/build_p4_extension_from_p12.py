from __future__ import annotations

import bisect
import csv
import json

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SNAPSHOT_FILE = ROOT / "data" / "raw" / "p12" / "btc_5m_market_snapshots_p12.csv"

LABEL_FILE = ROOT / "data" / "shadow" / "p12_market_resolutions.csv"

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_extension_pre_block1.csv"
)

REPORT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_extension_pre_block1_report.json"
)


BLOCK_1_START = datetime.fromisoformat("2026-10-03T20:45:00+00:00")

HORIZONS = (
    240,
    180,
    120,
    90,
    60,
    30,
)

MAX_HORIZON_LAG_SECONDS = 10.0
MAX_HISTORY_ANCHOR_LAG_SECONDS = 10.0


OUTPUT_FIELDS = (
    "condition_id",
    "market_end_at",
    "target_horizon_seconds",
    "prediction_timestamp",
    "snapshot_observed_at",
    "snapshot_lag_seconds",
    "reference_price",
    "strike",
    "distance_from_strike",
    "relative_distance_from_strike",
    "absolute_distance",
    "reference_return_30s",
    "reference_return_60s",
    "reference_return_120s",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "yes_mid",
    "no_mid",
    "normalized_yes_mid",
    "label_yes",
    "label_version",
    "eligible_reference_features",
    "eligible_book_features",
    "dataset_version",
    "feature_version",
)


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def market_id_from_row(
    row: dict[str, str],
) -> str:
    value = row.get("condition_id") or row.get("market_id") or ""

    return value.strip().lower()


def load_labels() -> dict[str, dict]:
    labels = {}

    with LABEL_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            condition_id = market_id_from_row(row)

            if not condition_id:
                continue

            status = row.get("status", "").strip().upper()

            if status and status != "VALID":
                continue

            raw_label = row.get("label_yes", "").strip()

            if raw_label not in {
                "0",
                "1",
            }:
                continue

            labels[condition_id] = {
                "label_yes": int(raw_label),
                "label_version": (
                    row.get(
                        "label_version",
                        "p3_v1",
                    ).strip()
                    or "p3_v1"
                ),
            }

    return labels


def load_snapshots() -> dict[
    str,
    list[dict],
]:
    by_market = defaultdict(list)

    with SNAPSHOT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        required = {
            "observed_at",
            "market_id",
            "btc_price",
            "strike",
            "market_end_at",
        }

        missing = required - set(reader.fieldnames or [])

        if missing:
            raise RuntimeError(f"snapshot schema missing: {sorted(missing)}")

        for row in reader:
            condition_id = market_id_from_row(row)

            if not condition_id:
                continue

            observed_raw = (row.get("observed_at") or "").strip()

            end_raw = (row.get("market_end_at") or "").strip()

            reference_price = optional_float(row.get("btc_price"))

            strike = optional_float(row.get("strike"))

            if (
                not observed_raw
                or not end_raw
                or reference_price is None
                or strike is None
                or reference_price <= 0.0
                or strike <= 0.0
            ):
                continue

            observed_at = parse_timestamp(observed_raw)

            market_end_at = parse_timestamp(end_raw)

            by_market[condition_id].append(
                {
                    "condition_id": (condition_id),
                    "observed_at": (observed_at),
                    "observed_epoch": (observed_at.timestamp()),
                    "market_end_at": (market_end_at),
                    "reference_price": (reference_price),
                    "strike": (strike),
                    "yes_bid": (optional_float(row.get("yes_bid"))),
                    "yes_ask": (optional_float(row.get("yes_ask"))),
                    "no_bid": (optional_float(row.get("no_bid"))),
                    "no_ask": (optional_float(row.get("no_ask"))),
                }
            )

    for rows in by_market.values():
        rows.sort(key=lambda row: row["observed_epoch"])

    return dict(by_market)


def find_latest_snapshot(
    rows: list[dict],
    epochs: list[float],
    target: datetime,
) -> tuple[
    dict | None,
    float | None,
]:
    target_epoch = target.timestamp()

    index = (
        bisect.bisect_right(
            epochs,
            target_epoch,
        )
        - 1
    )

    if index < 0:
        return (
            None,
            None,
        )

    snapshot = rows[index]

    lag_seconds = target_epoch - snapshot["observed_epoch"]

    return (
        snapshot,
        lag_seconds,
    )


def reference_return(
    rows: list[dict],
    epochs: list[float],
    current_snapshot: dict,
    seconds: int,
) -> float | None:
    target = current_snapshot["observed_at"] - timedelta(seconds=seconds)

    anchor, lag = find_latest_snapshot(
        rows,
        epochs,
        target,
    )

    if anchor is None:
        return None

    if lag is None or lag > MAX_HISTORY_ANCHOR_LAG_SECONDS:
        return None

    anchor_price = anchor["reference_price"]

    if anchor_price <= 0.0:
        return None

    return current_snapshot["reference_price"] / anchor_price - 1.0


def market_probability_fields(
    snapshot: dict,
) -> tuple[
    float | None,
    float | None,
    float | None,
]:
    yes_bid = snapshot["yes_bid"]
    yes_ask = snapshot["yes_ask"]
    no_bid = snapshot["no_bid"]
    no_ask = snapshot["no_ask"]

    if yes_bid is None or yes_ask is None or no_bid is None or no_ask is None:
        return (
            None,
            None,
            None,
        )

    yes_mid = (yes_bid + yes_ask) / 2.0

    no_mid = (no_bid + no_ask) / 2.0

    denominator = yes_mid + no_mid

    if denominator <= 0.0:
        return (
            yes_mid,
            no_mid,
            None,
        )

    return (
        yes_mid,
        no_mid,
        yes_mid / denominator,
    )


def main() -> None:
    labels = load_labels()

    snapshots_by_market = load_snapshots()

    stats = {
        "markets_seen": 0,
        "markets_valid_label": 0,
        "markets_excluded_block1_or_later": 0,
        "markets_included_pre_block1": 0,
        "candidate_rows": 0,
        "rows_written": 0,
        "missing_snapshot": 0,
        "stale_snapshot": 0,
        "rows_missing_reference_30s": 0,
        "rows_with_book": 0,
    }

    by_horizon = {
        horizon: {
            "candidate": 0,
            "written": 0,
            "missing_snapshot": 0,
            "stale_snapshot": 0,
        }
        for horizon in HORIZONS
    }

    output_rows = []

    included_markets = set()
    excluded_markets = set()

    earliest_end = None
    latest_end = None

    for (
        condition_id,
        market_rows,
    ) in snapshots_by_market.items():
        stats["markets_seen"] += 1

        label = labels.get(condition_id)

        if label is None:
            continue

        stats["markets_valid_label"] += 1

        market_end_at = market_rows[0]["market_end_at"]

        # Critical isolation rule:
        # Any market ending at or after Block 1 start
        # is completely excluded from development.
        if market_end_at >= BLOCK_1_START:
            stats["markets_excluded_block1_or_later"] += 1

            excluded_markets.add(condition_id)

            continue

        stats["markets_included_pre_block1"] += 1

        included_markets.add(condition_id)

        if earliest_end is None or market_end_at < earliest_end:
            earliest_end = market_end_at

        if latest_end is None or market_end_at > latest_end:
            latest_end = market_end_at

        epochs = [row["observed_epoch"] for row in market_rows]

        for horizon in HORIZONS:
            stats["candidate_rows"] += 1

            by_horizon[horizon]["candidate"] += 1

            prediction_timestamp = market_end_at - timedelta(seconds=horizon)

            snapshot, lag = find_latest_snapshot(
                market_rows,
                epochs,
                prediction_timestamp,
            )

            if snapshot is None:
                stats["missing_snapshot"] += 1

                by_horizon[horizon]["missing_snapshot"] += 1

                continue

            if lag is None or lag > MAX_HORIZON_LAG_SECONDS:
                stats["stale_snapshot"] += 1

                by_horizon[horizon]["stale_snapshot"] += 1

                continue

            reference_price = snapshot["reference_price"]

            strike = snapshot["strike"]

            distance = reference_price - strike

            relative_distance = distance / strike

            return_30s = reference_return(
                market_rows,
                epochs,
                snapshot,
                30,
            )

            return_60s = reference_return(
                market_rows,
                epochs,
                snapshot,
                60,
            )

            return_120s = reference_return(
                market_rows,
                epochs,
                snapshot,
                120,
            )

            if return_30s is None:
                stats["rows_missing_reference_30s"] += 1

            (
                yes_mid,
                no_mid,
                normalized_yes_mid,
            ) = market_probability_fields(snapshot)

            eligible_book = normalized_yes_mid is not None

            if eligible_book:
                stats["rows_with_book"] += 1

            output_rows.append(
                {
                    "condition_id": (condition_id),
                    "market_end_at": (market_end_at.isoformat()),
                    "target_horizon_seconds": (horizon),
                    "prediction_timestamp": (prediction_timestamp.isoformat()),
                    "snapshot_observed_at": (snapshot["observed_at"].isoformat()),
                    "snapshot_lag_seconds": (lag),
                    "reference_price": (reference_price),
                    "strike": (strike),
                    "distance_from_strike": (distance),
                    "relative_distance_from_strike": (relative_distance),
                    "absolute_distance": (abs(distance)),
                    "reference_return_30s": ("" if return_30s is None else return_30s),
                    "reference_return_60s": ("" if return_60s is None else return_60s),
                    "reference_return_120s": (
                        "" if return_120s is None else return_120s
                    ),
                    "yes_bid": (
                        "" if snapshot["yes_bid"] is None else snapshot["yes_bid"]
                    ),
                    "yes_ask": (
                        "" if snapshot["yes_ask"] is None else snapshot["yes_ask"]
                    ),
                    "no_bid": (
                        "" if snapshot["no_bid"] is None else snapshot["no_bid"]
                    ),
                    "no_ask": (
                        "" if snapshot["no_ask"] is None else snapshot["no_ask"]
                    ),
                    "yes_mid": ("" if yes_mid is None else yes_mid),
                    "no_mid": ("" if no_mid is None else no_mid),
                    "normalized_yes_mid": (
                        "" if normalized_yes_mid is None else normalized_yes_mid
                    ),
                    "label_yes": (label["label_yes"]),
                    "label_version": (label["label_version"]),
                    "eligible_reference_features": (return_30s is not None),
                    "eligible_book_features": (eligible_book),
                    "dataset_version": ("p4_extension_pre_block1_v1"),
                    "feature_version": ("p4_semantics_v1"),
                }
            )

            stats["rows_written"] += 1

            by_horizon[horizon]["written"] += 1

    # Hard safety assertions.
    if included_markets & excluded_markets:
        raise RuntimeError("market isolation failure")

    for row in output_rows:
        market_end_at = parse_timestamp(row["market_end_at"])

        if market_end_at >= BLOCK_1_START:
            raise RuntimeError(
                "BLOCK 1 LEAKAGE DETECTED: "
                f"{row['condition_id']} "
                f"{market_end_at.isoformat()}"
            )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(output_rows)

    report = {
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "dataset_version": ("p4_extension_pre_block1_v1"),
        "feature_version": ("p4_semantics_v1"),
        "block1_start_exclusive": (BLOCK_1_START.isoformat()),
        "isolation_rule": ("include only markets with market_end_at < block1_start"),
        "block1_consumed": False,
        "block2_consumed": False,
        "stats": stats,
        "by_horizon": by_horizon,
        "included_market_count": (len(included_markets)),
        "excluded_block1_or_later_market_count": (len(excluded_markets)),
        "earliest_included_market_end": (
            None if earliest_end is None else earliest_end.isoformat()
        ),
        "latest_included_market_end": (
            None if latest_end is None else latest_end.isoformat()
        ),
        "output": str(OUTPUT_FILE),
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P4 pre-Block-1 extension build complete")

    print()

    print(
        "BLOCK 1 START=",
        BLOCK_1_START.isoformat(),
    )

    print("inclusion rule: market_end_at < BLOCK_1_START")

    print()

    for key, value in stats.items():
        print(
            f"{key}=",
            value,
        )

    print()

    print(
        "included_markets=",
        len(included_markets),
    )

    print(
        "excluded_block1_or_later_markets=",
        len(excluded_markets),
    )

    print(
        "earliest_market_end=",
        (None if earliest_end is None else earliest_end.isoformat()),
    )

    print(
        "latest_market_end=",
        (None if latest_end is None else latest_end.isoformat()),
    )

    print()

    print("BY HORIZON")

    for horizon in HORIZONS:
        print(
            horizon,
            by_horizon[horizon],
        )

    print()

    print("BLOCK 1 CONSUMED=False")

    print("BLOCK 2 CONSUMED=False")

    print()

    print(
        "output=",
        OUTPUT_FILE,
    )

    print(
        "report=",
        REPORT_FILE,
    )


if __name__ == "__main__":
    main()
