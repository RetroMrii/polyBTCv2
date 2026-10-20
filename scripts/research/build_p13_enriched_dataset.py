from __future__ import annotations

import bisect
import csv

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

BTC_CONTEXT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "btc_1m_context_features.csv"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_enriched_supervised.csv"
)


BTC_FEATURE_FIELDS = (
    "btc_return_1m",
    "btc_return_3m",
    "btc_return_5m",
    "btc_realized_vol_5m",
    "btc_realized_vol_15m",
    "btc_range_5m",
    "btc_volume_zscore_30m",
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
    value: str | None,
) -> float | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    return float(raw)


def main() -> None:
    btc_rows = []

    with BTC_CONTEXT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            bar_start = parse_timestamp(row["observed_at"])

            bar_available_at = bar_start.timestamp() + 60.0

            btc_rows.append(
                {
                    "bar_start": (bar_start),
                    "bar_available_at": (bar_available_at),
                    "close": optional_float(row["close"]),
                    **{
                        field: optional_float(row[field])
                        for field in BTC_FEATURE_FIELDS
                    },
                }
            )

    btc_rows.sort(key=lambda row: row["bar_available_at"])

    btc_available_times = [row["bar_available_at"] for row in btc_rows]

    with P4_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        p4_fields = reader.fieldnames or []

        p4_rows = list(reader)

    output_fields = p4_fields + [
        "btc_context_bar_start",
        "btc_context_available_at",
        "btc_context_age_seconds",
        "btc_context_close",
        *BTC_FEATURE_FIELDS,
        "btc_context_complete",
    ]

    output_rows = []

    matched = 0
    unmatched = 0

    complete_context = 0
    incomplete_context = 0

    context_ages = []

    feature_missing_counts = {field: 0 for field in BTC_FEATURE_FIELDS}

    future_leakage_violations = 0

    for row in p4_rows:
        prediction_timestamp = parse_timestamp(row["prediction_timestamp"])

        prediction_epoch = prediction_timestamp.timestamp()

        index = (
            bisect.bisect_right(
                btc_available_times,
                prediction_epoch,
            )
            - 1
        )

        if index < 0:
            unmatched += 1

            enriched = dict(row)

            enriched.update(
                {
                    "btc_context_bar_start": "",
                    "btc_context_available_at": "",
                    "btc_context_age_seconds": "",
                    "btc_context_close": "",
                    **{field: "" for field in BTC_FEATURE_FIELDS},
                    "btc_context_complete": (False),
                }
            )

            output_rows.append(enriched)

            continue

        context = btc_rows[index]

        matched += 1

        available_at = datetime.fromtimestamp(
            context["bar_available_at"],
            tz=timezone.utc,
        )

        if available_at > prediction_timestamp:
            future_leakage_violations += 1

        context_age_seconds = prediction_epoch - context["bar_available_at"]

        context_ages.append(context_age_seconds)

        context_complete = all(
            context[field] is not None for field in BTC_FEATURE_FIELDS
        )

        if context_complete:
            complete_context += 1
        else:
            incomplete_context += 1

        for field in BTC_FEATURE_FIELDS:
            if context[field] is None:
                feature_missing_counts[field] += 1

        enriched = dict(row)

        enriched.update(
            {
                "btc_context_bar_start": (context["bar_start"].isoformat()),
                "btc_context_available_at": (available_at.isoformat()),
                "btc_context_age_seconds": (context_age_seconds),
                "btc_context_close": (context["close"]),
                **{
                    field: (context[field] if context[field] is not None else "")
                    for field in BTC_FEATURE_FIELDS
                },
                "btc_context_complete": (context_complete),
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

    print("P13 enriched dataset build complete")

    print(
        "p4_rows=",
        len(p4_rows),
    )

    print(
        "matched_context=",
        matched,
    )

    print(
        "unmatched_context=",
        unmatched,
    )

    print(
        "complete_context=",
        complete_context,
    )

    print(
        "incomplete_context=",
        incomplete_context,
    )

    print(
        "future_leakage_violations=",
        future_leakage_violations,
    )

    if context_ages:
        print(
            "context_age_min_seconds=",
            min(context_ages),
        )

        print(
            "context_age_max_seconds=",
            max(context_ages),
        )

    print()
    print("FEATURE MISSING COUNTS")

    for (
        field,
        count,
    ) in feature_missing_counts.items():
        print(
            field,
            count,
        )

    print()
    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
