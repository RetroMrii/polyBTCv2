from __future__ import annotations

import bisect
import csv

from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_DATASET = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_enriched_supervised.csv"
)

RAW_SNAPSHOTS = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_continuous_reference_supervised.csv"
)


ANCHOR_SECONDS = 60.0

MAX_ANCHOR_LAG_SECONDS = 10.0


NEW_FIELDS = (
    "continuous_reference_anchor_target",
    "continuous_reference_anchor_observed_at",
    "continuous_reference_anchor_lag_seconds",
    "continuous_reference_anchor_price",
    "continuous_reference_return_60s",
    "continuous_reference_return_60s_complete",
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


def optional_timestamp(
    value: str | None,
) -> datetime | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    # ISO-8601 timestamp.
    if "T" in raw or "-" in raw or ":" in raw:
        return parse_timestamp(raw)

    # Numeric Unix timestamp.
    try:
        numeric = float(raw)
    except ValueError:
        raise RuntimeError(f"unsupported timestamp format: {raw!r}")

    absolute = abs(numeric)

    # Normalize common Unix timestamp units.
    if absolute >= 1e17:
        # nanoseconds
        numeric /= 1_000_000_000.0

    elif absolute >= 1e14:
        # microseconds
        numeric /= 1_000_000.0

    elif absolute >= 1e11:
        # milliseconds
        numeric /= 1_000.0

    return datetime.fromtimestamp(
        numeric,
        tz=timezone.utc,
    )


def optional_float(
    value: str | None,
) -> float | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    return float(raw)


def build_reference_timeline() -> tuple[
    list[float],
    list[dict],
]:
    points = []

    scanned = 0
    skipped_missing = 0
    skipped_invalid = 0
    skipped_future_source = 0
    reference_timestamp_iso = 0
    reference_timestamp_numeric = 0

    with RAW_SNAPSHOTS.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        required = {
            "observed_at",
            "btc_price",
        }

        missing = required - set(reader.fieldnames or [])

        if missing:
            raise RuntimeError(f"raw snapshot schema missing: {sorted(missing)}")

        has_reference_timestamp = "reference_timestamp" in (reader.fieldnames or [])

        for row in reader:
            scanned += 1

            observed_at_raw = row.get("observed_at")

            price_raw = row.get("btc_price")

            if not observed_at_raw or not price_raw:
                skipped_missing += 1
                continue

            try:
                observed_at = parse_timestamp(observed_at_raw)

                price = float(price_raw)
            except (
                ValueError,
                TypeError,
            ):
                skipped_invalid += 1
                continue

            if price <= 0.0:
                skipped_invalid += 1
                continue

            reference_timestamp = None

            if has_reference_timestamp:
                reference_timestamp_raw = (row.get("reference_timestamp") or "").strip()

                if reference_timestamp_raw:
                    if (
                        "T" in reference_timestamp_raw
                        or "-" in reference_timestamp_raw
                        or ":" in reference_timestamp_raw
                    ):
                        reference_timestamp_iso += 1
                    else:
                        reference_timestamp_numeric += 1

                reference_timestamp = optional_timestamp(reference_timestamp_raw)

                # A source timestamp later than the
                # local observation timestamp would
                # violate causal ordering.
                if (
                    reference_timestamp is not None
                    and reference_timestamp > observed_at
                ):
                    skipped_future_source += 1
                    continue

            points.append(
                {
                    "observed_at": (observed_at),
                    "observed_epoch": (observed_at.timestamp()),
                    "reference_timestamp": (reference_timestamp),
                    "price": (price),
                }
            )

    points.sort(
        key=lambda point: (
            point["observed_epoch"],
            point["price"],
        )
    )

    epochs = [point["observed_epoch"] for point in points]

    print("REFERENCE TIMELINE")
    print(
        "raw_rows_scanned=",
        scanned,
    )
    print(
        "usable_reference_points=",
        len(points),
    )
    print(
        "skipped_missing=",
        skipped_missing,
    )
    print(
        "skipped_invalid=",
        skipped_invalid,
    )
    print(
        "skipped_future_source=",
        skipped_future_source,
    )
    print(
        "reference_timestamp_iso=",
        reference_timestamp_iso,
    )
    print(
        "reference_timestamp_numeric=",
        reference_timestamp_numeric,
    )

    if points:
        print(
            "first_reference_point=",
            points[0]["observed_at"].isoformat(),
        )
        print(
            "last_reference_point=",
            points[-1]["observed_at"].isoformat(),
        )

    print()

    return (
        epochs,
        points,
    )


def main() -> None:
    (
        reference_epochs,
        reference_points,
    ) = build_reference_timeline()

    if not reference_points:
        raise RuntimeError("no usable reference timeline points")

    with INPUT_DATASET.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        input_fields = reader.fieldnames or []

        rows = list(reader)

    output_fields = input_fields + list(NEW_FIELDS)

    output_rows = []

    complete = 0
    missing_anchor = 0
    stale_anchor = 0
    invalid_current_price = 0
    future_anchor_violations = 0
    future_source_violations = 0

    anchor_lags = []

    by_horizon = {}

    for row in rows:
        horizon = int(row["target_horizon_seconds"])

        horizon_stats = by_horizon.setdefault(
            horizon,
            {
                "rows": 0,
                "complete": 0,
                "missing_anchor": 0,
                "stale_anchor": 0,
            },
        )

        horizon_stats["rows"] += 1

        prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

        current_price = optional_float(row.get("reference_price"))

        anchor_target = prediction_timestamp - timedelta(seconds=ANCHOR_SECONDS)

        anchor_target_epoch = anchor_target.timestamp()

        index = (
            bisect.bisect_right(
                reference_epochs,
                anchor_target_epoch,
            )
            - 1
        )

        enriched = dict(row)

        enriched.update(
            {
                "continuous_reference_anchor_target": (anchor_target.isoformat()),
                "continuous_reference_anchor_observed_at": "",
                "continuous_reference_anchor_lag_seconds": "",
                "continuous_reference_anchor_price": "",
                "continuous_reference_return_60s": "",
                "continuous_reference_return_60s_complete": (False),
            }
        )

        if current_price is None or current_price <= 0.0:
            invalid_current_price += 1

            output_rows.append(enriched)
            continue

        if index < 0:
            missing_anchor += 1

            horizon_stats["missing_anchor"] += 1

            output_rows.append(enriched)
            continue

        anchor = reference_points[index]

        anchor_observed_at = anchor["observed_at"]

        if anchor_observed_at > anchor_target:
            future_anchor_violations += 1

        anchor_source_timestamp = anchor["reference_timestamp"]

        if (
            anchor_source_timestamp is not None
            and anchor_source_timestamp > anchor_target
        ):
            future_source_violations += 1

            output_rows.append(enriched)
            continue

        anchor_lag_seconds = anchor_target_epoch - anchor["observed_epoch"]

        if anchor_lag_seconds < 0.0:
            future_anchor_violations += 1

            output_rows.append(enriched)
            continue

        if anchor_lag_seconds > MAX_ANCHOR_LAG_SECONDS:
            stale_anchor += 1

            horizon_stats["stale_anchor"] += 1

            output_rows.append(enriched)
            continue

        anchor_price = anchor["price"]

        if anchor_price <= 0.0:
            invalid_current_price += 1

            output_rows.append(enriched)
            continue

        return_60s = current_price / anchor_price - 1.0

        anchor_lags.append(anchor_lag_seconds)

        complete += 1

        horizon_stats["complete"] += 1

        enriched.update(
            {
                "continuous_reference_anchor_observed_at": (
                    anchor_observed_at.isoformat()
                ),
                "continuous_reference_anchor_lag_seconds": (anchor_lag_seconds),
                "continuous_reference_anchor_price": (anchor_price),
                "continuous_reference_return_60s": (return_60s),
                "continuous_reference_return_60s_complete": (True),
            }
        )

        output_rows.append(enriched)

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
            fieldnames=output_fields,
            extrasaction="raise",
        )

        writer.writeheader()

        writer.writerows(output_rows)

    print("P13 continuous reference feature build complete")
    print()
    print(
        "input_rows=",
        len(rows),
    )
    print(
        "complete=",
        complete,
    )
    print(
        "missing_anchor=",
        missing_anchor,
    )
    print(
        "stale_anchor=",
        stale_anchor,
    )
    print(
        "invalid_current_price=",
        invalid_current_price,
    )
    print(
        "future_anchor_violations=",
        future_anchor_violations,
    )
    print(
        "future_source_violations=",
        future_source_violations,
    )

    if anchor_lags:
        print(
            "anchor_lag_min_seconds=",
            min(anchor_lags),
        )
        print(
            "anchor_lag_max_seconds=",
            max(anchor_lags),
        )

    print()
    print("COVERAGE BY HORIZON")

    for horizon in sorted(
        by_horizon,
        reverse=True,
    ):
        stats = by_horizon[horizon]

        print(
            horizon,
            "rows=",
            stats["rows"],
            "complete=",
            stats["complete"],
            "missing_anchor=",
            stats["missing_anchor"],
            "stale_anchor=",
            stats["stale_anchor"],
        )

    print()
    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
