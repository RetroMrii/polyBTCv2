from __future__ import annotations

import csv
import hashlib

from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.schema import SnapshotRecord


def _parse_datetime(
    value: str | None,
) -> datetime | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _float_or_none(
    value: str | None,
) -> float | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    return float(raw)


def _int_or_none(
    value: str | None,
) -> int | None:
    if value is None:
        return None

    raw = value.strip()

    if not raw:
        return None

    return int(raw)


def _snapshot_id(
    condition_id: str,
    observed_at: datetime,
) -> str:
    raw = f"{condition_id.lower()}|{observed_at.isoformat()}"

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return f"snapshot:{digest}"


def import_v1_market_snapshots(
    path: Path,
) -> list[SnapshotRecord]:
    ingested_at = datetime.now(timezone.utc)

    snapshots: list[SnapshotRecord] = []

    with path.open(
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
            "seconds_to_expiry",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "yes_bid_size",
            "yes_ask_size",
            "no_bid_size",
            "no_ask_size",
            "yes_token_id",
            "no_token_id",
            "reference_timestamp",
            "reference_age_ms",
            "reference_latency_ms",
            "yes_book_timestamp",
            "yes_book_age_ms",
            "yes_book_latency_ms",
            "no_book_timestamp",
            "no_book_age_ms",
            "no_book_latency_ms",
            "yes_tick_size",
            "yes_min_order_size",
            "no_tick_size",
            "no_min_order_size",
            "snapshot_build_latency_ms",
            "market_end_at",
            "collector_version",
        }

        fieldnames = set(reader.fieldnames or [])

        missing = required - fieldnames

        if missing:
            raise ValueError(
                "snapshot telemetry missing columns: " + ", ".join(sorted(missing))
            )

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            condition_id = row["market_id"].strip().lower()

            observed_at = _parse_datetime(row["observed_at"])

            if observed_at is None:
                raise ValueError(f"row {row_number}: missing observed_at")

            snapshots.append(
                SnapshotRecord(
                    snapshot_id=_snapshot_id(
                        condition_id,
                        observed_at,
                    ),
                    condition_id=condition_id,
                    observed_at=observed_at,
                    source_name=("polybtc_v1_1_telemetry"),
                    ingested_at=ingested_at,
                    reference_price=_float_or_none(row["btc_price"]),
                    reference_timestamp=(
                        _parse_datetime(row["reference_timestamp"])
                        if not row["reference_timestamp"].strip().isdigit()
                        else datetime.fromtimestamp(
                            int(row["reference_timestamp"]) / 1000.0,
                            tz=timezone.utc,
                        )
                    ),
                    reference_age_ms=(_float_or_none(row["reference_age_ms"])),
                    reference_latency_ms=(_float_or_none(row["reference_latency_ms"])),
                    strike=_float_or_none(row["strike"]),
                    seconds_to_expiry=(_float_or_none(row["seconds_to_expiry"])),
                    market_end_at=_parse_datetime(row["market_end_at"]),
                    yes_bid=_float_or_none(row["yes_bid"]),
                    yes_ask=_float_or_none(row["yes_ask"]),
                    yes_bid_size=_float_or_none(row["yes_bid_size"]),
                    yes_ask_size=_float_or_none(row["yes_ask_size"]),
                    no_bid=_float_or_none(row["no_bid"]),
                    no_ask=_float_or_none(row["no_ask"]),
                    no_bid_size=_float_or_none(row["no_bid_size"]),
                    no_ask_size=_float_or_none(row["no_ask_size"]),
                    yes_book_timestamp=(
                        datetime.fromtimestamp(
                            int(row["yes_book_timestamp"]) / 1000.0,
                            tz=timezone.utc,
                        )
                    ),
                    yes_book_age_ms=(_float_or_none(row["yes_book_age_ms"])),
                    yes_book_latency_ms=(_float_or_none(row["yes_book_latency_ms"])),
                    no_book_timestamp=(
                        datetime.fromtimestamp(
                            int(row["no_book_timestamp"]) / 1000.0,
                            tz=timezone.utc,
                        )
                    ),
                    no_book_age_ms=(_float_or_none(row["no_book_age_ms"])),
                    no_book_latency_ms=(_float_or_none(row["no_book_latency_ms"])),
                    yes_tick_size=(_float_or_none(row["yes_tick_size"])),
                    yes_min_order_size=(_float_or_none(row["yes_min_order_size"])),
                    no_tick_size=(_float_or_none(row["no_tick_size"])),
                    no_min_order_size=(_float_or_none(row["no_min_order_size"])),
                    snapshot_build_latency_ms=(
                        _float_or_none(row["snapshot_build_latency_ms"])
                    ),
                    momentum_60s=_float_or_none(row.get("momentum_60s")),
                    volatility_60s=_float_or_none(row.get("volatility_60s")),
                    yes_token_id=(row["yes_token_id"].strip() or None),
                    no_token_id=(row["no_token_id"].strip() or None),
                    source_file=path.name,
                    source_row_number=row_number,
                    collector_version=(row["collector_version"].strip() or None),
                )
            )

    return snapshots
