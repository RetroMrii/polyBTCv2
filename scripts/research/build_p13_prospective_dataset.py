from __future__ import annotations

import bisect
import csv

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SNAPSHOT_FILE = ROOT / "data" / "raw" / "p12" / "btc_5m_market_snapshots_p12.csv"

LABEL_FILE = ROOT / "data" / "shadow" / "p12_market_resolutions.csv"

RTDS_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "rtds_1m_context_features.csv"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_supervised.csv"
)


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

MAX_RTDS_CONTEXT_AGE_SECONDS = 30.0


OUTPUT_FIELDS = (
    "condition_id",
    "target_horizon_seconds",
    "prediction_timestamp",
    "snapshot_observed_at",
    "snapshot_lag_seconds",
    "market_end_at",
    "reference_price",
    "strike",
    "relative_distance_from_strike",
    "reference_return_30s",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "normalized_yes_mid",
    "rtds_bar_start_at",
    "rtds_available_at",
    "rtds_context_age_seconds",
    "rtds_ohlc_close",
    "rtds_ohlc_return_1m",
    "label_yes",
    "label_version",
    "snapshot_complete",
    "reference_return_30s_complete",
    "rtds_context_complete",
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

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
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


def load_rtds_context() -> tuple[
    list[float],
    list[dict],
]:
    rows = []

    with RTDS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            return_1m = optional_float(row.get("rtds_ohlc_return_1m"))

            if return_1m is None:
                continue

            available_at = parse_timestamp(row["available_at"])

            rows.append(
                {
                    "timestamp": int(row["timestamp"]),
                    "bar_start_at": (parse_timestamp(row["bar_start_at"])),
                    "available_at": (available_at),
                    "available_epoch": (available_at.timestamp()),
                    "close": float(row["close"]),
                    "return_1m": (return_1m),
                }
            )

    rows.sort(key=lambda row: row["available_epoch"])

    epochs = [row["available_epoch"] for row in rows]

    return (
        epochs,
        rows,
    )


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

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            condition_id = market_id_from_row(row)

            if not condition_id:
                continue

            observed_at_raw = (row.get("observed_at") or "").strip()

            end_at_raw = (row.get("market_end_at") or "").strip()

            reference_price = optional_float(row.get("btc_price"))

            strike = optional_float(row.get("strike"))

            if (
                not observed_at_raw
                or not end_at_raw
                or reference_price is None
                or strike is None
                or reference_price <= 0.0
                or strike <= 0.0
            ):
                continue

            observed_at = parse_timestamp(observed_at_raw)

            market_end_at = parse_timestamp(end_at_raw)

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


def normalized_yes_mid(
    snapshot: dict,
) -> float | None:
    yes_bid = snapshot["yes_bid"]

    yes_ask = snapshot["yes_ask"]

    no_bid = snapshot["no_bid"]

    no_ask = snapshot["no_ask"]

    if yes_bid is None or yes_ask is None or no_bid is None or no_ask is None:
        return None

    yes_mid = (yes_bid + yes_ask) / 2.0

    no_mid = (no_bid + no_ask) / 2.0

    denominator = yes_mid + no_mid

    if denominator <= 0.0:
        return None

    return yes_mid / denominator


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


def reference_return_30s(
    rows: list[dict],
    epochs: list[float],
    current_snapshot: dict,
) -> tuple[
    float | None,
    float | None,
]:
    target = current_snapshot["observed_at"] - timedelta(seconds=30)

    anchor, lag = find_latest_snapshot(
        rows,
        epochs,
        target,
    )

    if anchor is None:
        return (
            None,
            None,
        )

    if lag is None or lag > MAX_HISTORY_ANCHOR_LAG_SECONDS:
        return (
            None,
            lag,
        )

    anchor_price = anchor["reference_price"]

    if anchor_price <= 0.0:
        return (
            None,
            lag,
        )

    value = current_snapshot["reference_price"] / anchor_price - 1.0

    return (
        value,
        lag,
    )


def find_rtds_context(
    epochs: list[float],
    rows: list[dict],
    prediction_timestamp: datetime,
) -> tuple[
    dict | None,
    float | None,
]:
    prediction_epoch = prediction_timestamp.timestamp()

    index = (
        bisect.bisect_right(
            epochs,
            prediction_epoch,
        )
        - 1
    )

    if index < 0:
        return (
            None,
            None,
        )

    context = rows[index]

    age_seconds = prediction_epoch - context["available_epoch"]

    if age_seconds < 0.0:
        raise RuntimeError("future RTDS context detected")

    if age_seconds > MAX_RTDS_CONTEXT_AGE_SECONDS:
        return (
            None,
            age_seconds,
        )

    return (
        context,
        age_seconds,
    )


def main() -> None:
    labels = load_labels()

    (
        rtds_epochs,
        rtds_rows,
    ) = load_rtds_context()

    snapshots_by_market = load_snapshots()

    output_rows = []

    stats = {
        "markets_seen": 0,
        "markets_with_valid_label": 0,
        "candidate_rows": 0,
        "missing_horizon_snapshot": 0,
        "stale_horizon_snapshot": 0,
        "missing_reference_return_30s": 0,
        "missing_rtds_context": 0,
        "complete_rows": 0,
    }

    by_horizon = {
        horizon: {
            "candidates": 0,
            "complete": 0,
            "missing_snapshot": 0,
            "stale_snapshot": 0,
            "missing_reference_return_30s": 0,
            "missing_rtds_context": 0,
        }
        for horizon in HORIZONS
    }

    prospective_markets = set()

    for (
        condition_id,
        market_rows,
    ) in snapshots_by_market.items():
        stats["markets_seen"] += 1

        label = labels.get(condition_id)

        if label is None:
            continue

        stats["markets_with_valid_label"] += 1

        market_end_at = market_rows[0]["market_end_at"]

        epochs = [row["observed_epoch"] for row in market_rows]

        for horizon in HORIZONS:
            prediction_timestamp = market_end_at - timedelta(seconds=horizon)

            stats["candidate_rows"] += 1

            by_horizon[horizon]["candidates"] += 1

            snapshot, snapshot_lag = find_latest_snapshot(
                market_rows,
                epochs,
                prediction_timestamp,
            )

            if snapshot is None:
                stats["missing_horizon_snapshot"] += 1

                by_horizon[horizon]["missing_snapshot"] += 1

                continue

            if snapshot_lag is None or snapshot_lag > MAX_HORIZON_LAG_SECONDS:
                stats["stale_horizon_snapshot"] += 1

                by_horizon[horizon]["stale_snapshot"] += 1

                continue

            (
                return_30s,
                return_anchor_lag,
            ) = reference_return_30s(
                market_rows,
                epochs,
                snapshot,
            )

            if return_30s is None:
                stats["missing_reference_return_30s"] += 1

                by_horizon[horizon]["missing_reference_return_30s"] += 1

            (
                rtds_context,
                rtds_age,
            ) = find_rtds_context(
                rtds_epochs,
                rtds_rows,
                prediction_timestamp,
            )

            if rtds_context is None:
                stats["missing_rtds_context"] += 1

                by_horizon[horizon]["missing_rtds_context"] += 1

                rtds_complete = False

                rtds_bar_start = ""
                rtds_available_at = ""
                rtds_close = ""
                rtds_return = ""

            else:
                rtds_complete = True

                rtds_bar_start = rtds_context["bar_start_at"].isoformat()

                rtds_available_at = rtds_context["available_at"].isoformat()

                rtds_close = rtds_context["close"]

                rtds_return = rtds_context["return_1m"]

            relative_distance = (
                snapshot["reference_price"] - snapshot["strike"]
            ) / snapshot["strike"]

            snapshot_complete = True

            reference_complete = return_30s is not None

            complete = snapshot_complete and reference_complete and rtds_complete

            if complete:
                stats["complete_rows"] += 1

                by_horizon[horizon]["complete"] += 1

                prospective_markets.add(condition_id)

            output_rows.append(
                {
                    "condition_id": (condition_id),
                    "target_horizon_seconds": (horizon),
                    "prediction_timestamp": (prediction_timestamp.isoformat()),
                    "snapshot_observed_at": (snapshot["observed_at"].isoformat()),
                    "snapshot_lag_seconds": (snapshot_lag),
                    "market_end_at": (market_end_at.isoformat()),
                    "reference_price": (snapshot["reference_price"]),
                    "strike": (snapshot["strike"]),
                    "relative_distance_from_strike": (relative_distance),
                    "reference_return_30s": ("" if return_30s is None else return_30s),
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
                    "normalized_yes_mid": (
                        ""
                        if normalized_yes_mid(snapshot) is None
                        else normalized_yes_mid(snapshot)
                    ),
                    "rtds_bar_start_at": (rtds_bar_start),
                    "rtds_available_at": (rtds_available_at),
                    "rtds_context_age_seconds": ("" if rtds_age is None else rtds_age),
                    "rtds_ohlc_close": (rtds_close),
                    "rtds_ohlc_return_1m": (rtds_return),
                    "label_yes": (label["label_yes"]),
                    "label_version": (label["label_version"]),
                    "snapshot_complete": (snapshot_complete),
                    "reference_return_30s_complete": (reference_complete),
                    "rtds_context_complete": (rtds_complete),
                }
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

    print("P13 prospective dataset build complete")

    print()
    print("RTDS CONTEXT")

    print(
        "usable_rtds_bars=",
        len(rtds_rows),
    )

    if rtds_rows:
        print(
            "first_rtds_available_at=",
            rtds_rows[0]["available_at"].isoformat(),
        )

        print(
            "last_rtds_available_at=",
            rtds_rows[-1]["available_at"].isoformat(),
        )

    print()
    print("DATASET")

    for (
        name,
        value,
    ) in stats.items():
        print(
            f"{name}=",
            value,
        )

    print(
        "complete_markets=",
        len(prospective_markets),
    )

    print()
    print("BY HORIZON")

    for horizon in HORIZONS:
        print(
            horizon,
            by_horizon[horizon],
        )

    print()
    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
