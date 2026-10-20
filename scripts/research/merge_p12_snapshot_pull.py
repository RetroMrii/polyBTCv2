from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EXISTING_FILE = ROOT / "data" / "raw" / "p12" / "btc_5m_market_snapshots_p12.csv"

INCOMING_FILE = (
    ROOT / "data" / "raw" / "p12" / "incoming" / "btc_5m_market_snapshots.csv"
)

OUTPUT_TEMP = ROOT / "data" / "raw" / "p12" / "btc_5m_market_snapshots_p12.tmp.csv"


def row_key(
    row: dict[str, str],
) -> tuple[str, str]:
    return (
        row["observed_at"].strip(),
        row["market_id"].strip().lower(),
    )


def read_rows(
    path: Path,
) -> tuple[
    list[str],
    list[dict[str, str]],
]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        fields = reader.fieldnames

        if not fields:
            raise RuntimeError(f"missing header: {path}")

        rows = list(reader)

    return (
        list(fields),
        rows,
    )


def main() -> None:
    incoming_fields, incoming_rows = read_rows(INCOMING_FILE)

    if EXISTING_FILE.exists():
        existing_fields, existing_rows = read_rows(EXISTING_FILE)

        if existing_fields != incoming_fields:
            raise RuntimeError(
                "P12 snapshot schemas differ\n"
                f"existing={existing_fields}\n"
                f"incoming={incoming_fields}"
            )

    else:
        existing_fields = incoming_fields
        existing_rows = []

    existing_keys = {row_key(row) for row in existing_rows}

    added_rows = []

    duplicate_incoming = 0

    seen_incoming = set()

    for row in incoming_rows:
        key = row_key(row)

        if key in seen_incoming:
            duplicate_incoming += 1
            continue

        seen_incoming.add(key)

        if key in existing_keys:
            continue

        existing_keys.add(key)
        added_rows.append(row)

    combined = existing_rows + added_rows

    combined.sort(
        key=lambda row: (
            row["observed_at"],
            row["market_id"],
        )
    )

    with OUTPUT_TEMP.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=existing_fields,
        )

        writer.writeheader()
        writer.writerows(combined)

    OUTPUT_TEMP.replace(EXISTING_FILE)

    print("P12 snapshot merge complete")

    print(
        "existing_rows_before=",
        len(existing_rows),
    )

    print(
        "incoming_rows=",
        len(incoming_rows),
    )

    print(
        "new_rows_added=",
        len(added_rows),
    )

    print(
        "duplicate_rows_inside_incoming=",
        duplicate_incoming,
    )

    print(
        "combined_rows=",
        len(combined),
    )

    print(
        "output=",
        EXISTING_FILE,
    )


if __name__ == "__main__":
    main()
