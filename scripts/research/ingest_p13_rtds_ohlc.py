from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "raw" / "p13" / "btc_1m_ohlc.csv"

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "rtds_1m_context_features.csv"
)


OUTPUT_FIELDS = (
    "timestamp",
    "bar_start_at",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "rtds_ohlc_return_1m",
    "previous_timestamp",
    "contiguous_previous_minute",
)


def main() -> None:
    rows = []

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        expected = {
            "Timestamp",
            "Open",
            "High",
            "Low",
            "Close",
        }

        if set(reader.fieldnames or []) != expected:
            raise RuntimeError(f"unexpected OHLC schema: {reader.fieldnames}")

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            try:
                timestamp = int(row["Timestamp"])

                open_price = float(row["Open"])

                high_price = float(row["High"])

                low_price = float(row["Low"])

                close_price = float(row["Close"])

            except (
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                raise RuntimeError(f"invalid row {row_number}: {row}") from exc

            if (
                min(
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                )
                <= 0.0
            ):
                raise RuntimeError(f"non-positive price at row {row_number}")

            if high_price < max(
                open_price,
                close_price,
                low_price,
            ):
                raise RuntimeError(f"invalid high at row {row_number}")

            if low_price > min(
                open_price,
                close_price,
                high_price,
            ):
                raise RuntimeError(f"invalid low at row {row_number}")

            rows.append(
                {
                    "timestamp": timestamp,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                }
            )

    rows.sort(key=lambda row: row["timestamp"])

    duplicate_timestamps = 0

    deduped = []

    seen = set()

    for row in rows:
        timestamp = row["timestamp"]

        if timestamp in seen:
            duplicate_timestamps += 1
            continue

        seen.add(timestamp)
        deduped.append(row)

    output_rows = []

    contiguous_pairs = 0
    gaps = 0

    previous = None

    for row in deduped:
        timestamp = row["timestamp"]

        bar_start = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )

        available_at = datetime.fromtimestamp(
            timestamp + 60,
            tz=timezone.utc,
        )

        previous_timestamp = ""
        contiguous = False
        return_1m = ""

        if previous is not None:
            previous_timestamp = previous["timestamp"]

            delta = timestamp - previous["timestamp"]

            if delta == 60:
                contiguous = True
                contiguous_pairs += 1

                return_1m = row["close"] / previous["close"] - 1.0

            else:
                gaps += 1

        output_rows.append(
            {
                "timestamp": timestamp,
                "bar_start_at": (bar_start.isoformat()),
                "available_at": (available_at.isoformat()),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "rtds_ohlc_return_1m": (return_1m),
                "previous_timestamp": (previous_timestamp),
                "contiguous_previous_minute": (contiguous),
            }
        )

        previous = row

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

    print("P13 RTDS OHLC ingest complete")

    print(
        "input_rows=",
        len(rows),
    )

    print(
        "output_rows=",
        len(output_rows),
    )

    print(
        "duplicate_timestamps=",
        duplicate_timestamps,
    )

    print(
        "contiguous_pairs=",
        contiguous_pairs,
    )

    print(
        "gaps=",
        gaps,
    )

    if output_rows:
        print(
            "first_bar=",
            output_rows[0]["bar_start_at"],
        )

        print(
            "last_bar=",
            output_rows[-1]["bar_start_at"],
        )

    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
