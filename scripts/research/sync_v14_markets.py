from __future__ import annotations

import csv
import sys

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.data.polymarket_metadata import (
    fetch_market_metadata,
)


SNAPSHOTS_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

MARKETS_FILE = ROOT / "data" / "normalized" / "markets.csv"


MARKET_FIELDS = [
    "condition_id",
    "question",
    "market_end_at",
    "source_name",
    "ingested_at",
    "market_slug",
    "yes_token_id",
    "no_token_id",
    "market_start_at",
    "strike",
    "closed",
    "resolved",
    "resolved_at",
    "winning_outcome",
    "winning_token_id",
    "label_yes",
    "resolution_source",
    "resolution_source_version",
    "resolution_retrieved_at",
    "source_record_id",
]


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()

    return value or None


def load_existing_markets() -> list[dict[str, str]]:
    with MARKETS_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    condition_ids = [row["condition_id"].strip().lower() for row in rows]

    if len(condition_ids) != len(set(condition_ids)):
        raise RuntimeError("duplicate condition_ids already exist in markets.csv")

    return rows


def load_telemetry_markets() -> dict[str, dict[str, str]]:
    markets: dict[str, dict[str, str]] = {}

    with SNAPSHOTS_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        for row_number, row in enumerate(
            rows,
            start=2,
        ):
            condition_id = row["market_id"].strip().lower()

            if not condition_id:
                raise RuntimeError(f"missing market_id at snapshot row {row_number}")

            candidate = {
                "condition_id": condition_id,
                "question": (_nonempty(row.get("question")) or ""),
                "market_end_at": (_nonempty(row.get("market_end_at")) or ""),
                "strike": (_nonempty(row.get("strike")) or ""),
                "yes_token_id": (_nonempty(row.get("yes_token_id")) or ""),
                "no_token_id": (_nonempty(row.get("no_token_id")) or ""),
            }

            existing = markets.get(condition_id)

            if existing is None:
                markets[condition_id] = candidate
                continue

            for field in (
                "question",
                "market_end_at",
                "strike",
                "yes_token_id",
                "no_token_id",
            ):
                old = existing[field]
                new = candidate[field]

                if old and new and old != new:
                    raise RuntimeError(
                        f"inconsistent {field} for {condition_id}: {old!r} != {new!r}"
                    )

                if not old and new:
                    existing[field] = new

    return markets


def main() -> None:
    existing_rows = load_existing_markets()

    telemetry_markets = load_telemetry_markets()

    existing_ids = {row["condition_id"].strip().lower() for row in existing_rows}

    missing_ids = sorted(set(telemetry_markets) - existing_ids)

    print(f"existing_markets={len(existing_rows)}")
    print(f"telemetry_markets={len(telemetry_markets)}")
    print(f"missing_markets={len(missing_ids)}")

    if not missing_ids:
        print("No new canonical markets to add.")
        return

    now = datetime.now(timezone.utc)

    new_rows: list[dict[str, str]] = []

    for index, condition_id in enumerate(
        missing_ids,
        start=1,
    ):
        raw = telemetry_markets[condition_id]

        metadata = fetch_market_metadata(condition_id)

        if metadata is None:
            raise RuntimeError(f"Gamma metadata missing for {condition_id}")

        metadata_condition_id = metadata.condition_id.strip().lower()

        if metadata_condition_id != condition_id:
            raise RuntimeError(f"Gamma condition_id mismatch for {condition_id}")

        telemetry_yes_token = raw["yes_token_id"] or None
        telemetry_no_token = raw["no_token_id"] or None

        if (
            telemetry_yes_token is not None
            and metadata.yes_token_id is not None
            and telemetry_yes_token != metadata.yes_token_id
        ):
            raise RuntimeError(f"YES token mismatch for {condition_id}")

        if (
            telemetry_no_token is not None
            and metadata.no_token_id is not None
            and telemetry_no_token != metadata.no_token_id
        ):
            raise RuntimeError(f"NO token mismatch for {condition_id}")

        question = raw["question"] or metadata.question or ""

        market_end_at = raw["market_end_at"]

        if not question:
            raise RuntimeError(f"question missing for {condition_id}")

        if not market_end_at:
            raise RuntimeError(f"market_end_at missing for {condition_id}")

        new_row = {
            "condition_id": condition_id,
            "question": question,
            "market_end_at": market_end_at,
            "source_name": ("v1.1_market_snapshot_v1.4"),
            "ingested_at": now.isoformat(),
            "market_slug": (metadata.slug or ""),
            "yes_token_id": (metadata.yes_token_id or telemetry_yes_token or ""),
            "no_token_id": (metadata.no_token_id or telemetry_no_token or ""),
            "market_start_at": "",
            "strike": raw["strike"],
            "closed": ("" if metadata.closed is None else str(metadata.closed)),
            "resolved": "",
            "resolved_at": "",
            "winning_outcome": "",
            "winning_token_id": "",
            "label_yes": "",
            "resolution_source": (metadata.resolution_source or ""),
            "resolution_source_version": "",
            "resolution_retrieved_at": "",
            "source_record_id": (SNAPSHOTS_FILE.name),
        }

        new_rows.append(new_row)

        print(
            f"[{index}/{len(missing_ids)}] "
            f"{condition_id[:14]}... "
            f"closed={metadata.closed}"
        )

    all_rows = existing_rows + new_rows

    temp_file = MARKETS_FILE.with_suffix(".csv.tmp")

    with temp_file.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=MARKET_FIELDS,
            extrasaction="raise",
        )

        writer.writeheader()

        writer.writerows(all_rows)

    temp_file.replace(MARKETS_FILE)

    final_ids = {row["condition_id"].strip().lower() for row in all_rows}

    if len(final_ids) != len(all_rows):
        raise RuntimeError("duplicate condition_ids after market sync")

    print()
    print(f"added_markets={len(new_rows)}")
    print(f"final_markets={len(all_rows)}")


if __name__ == "__main__":
    main()
