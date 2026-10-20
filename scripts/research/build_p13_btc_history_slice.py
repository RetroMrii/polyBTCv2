from __future__ import annotations

import csv

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = ROOT / "data" / "external" / "bitcoin_history" / "btcusd_1-min_data.csv"

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "btc_1m_research_slice.csv"
)


START = datetime(
    2026,
    9,
    15,
    tzinfo=timezone.utc,
)

END = datetime(
    2026,
    10,
    5,
    23,
    59,
    59,
    tzinfo=timezone.utc,
)

START_TS = int(START.timestamp())

END_TS = int(END.timestamp())


OUTPUT_FIELDS = (
    "timestamp",
    "observed_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


def main() -> None:
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    kept = 0
    scanned = 0

    first_timestamp = None
    last_timestamp = None

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as source:
        reader = csv.DictReader(source)

        expected = {
            "Timestamp",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        if set(reader.fieldnames or []) != expected:
            raise RuntimeError(f"unexpected BTC history schema: {reader.fieldnames}")

        with OUTPUT_FILE.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as destination:
            writer = csv.DictWriter(
                destination,
                fieldnames=OUTPUT_FIELDS,
            )

            writer.writeheader()

            for row in reader:
                scanned += 1

                timestamp = int(row["Timestamp"])

                if timestamp < START_TS:
                    continue

                if timestamp > END_TS:
                    break

                observed_at = datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )

                writer.writerow(
                    {
                        "timestamp": (timestamp),
                        "observed_at": (observed_at.isoformat()),
                        "open": (row["Open"]),
                        "high": (row["High"]),
                        "low": (row["Low"]),
                        "close": (row["Close"]),
                        "volume": (row["Volume"]),
                    }
                )

                kept += 1

                if first_timestamp is None:
                    first_timestamp = observed_at

                last_timestamp = observed_at

    print("P13 BTC history slice complete")

    print(
        "scanned_rows=",
        scanned,
    )

    print(
        "kept_rows=",
        kept,
    )

    print(
        "first_timestamp=",
        first_timestamp,
    )

    print(
        "last_timestamp=",
        last_timestamp,
    )

    print(
        "output=",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()
