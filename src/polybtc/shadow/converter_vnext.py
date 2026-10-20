from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.csv_tail_vnext import TailRow

from polybtc.data.importers.v1_market_snapshots import (
    _parse_datetime,
    _float_or_none,
)


CONVERTER_VERSION = "vnext_csv_converter_v1"

REQUIRED_FIELDS = frozenset(
    {
        "observed_at",
        "market_id",
        "btc_price",
        "strike",
        "seconds_to_expiry",
        "market_end_at",
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
        "collector_version",
    }
)


def _timestamp(value: str | float | int | None) -> datetime | None:
    if isinstance(value,(int,float)):
        value=str(value)
    if value is None or not value.strip():
        return None

    raw = value.strip()

    try:
        numeric = float(raw)
    except ValueError:
        return _parse_datetime(raw)

    if not math.isfinite(numeric):
        raise ValueError("Nonfinite source timestamp")

    if numeric > 100_000_000_000:
        seconds = numeric / 1000.0
    elif numeric > 1_000_000_000:
        seconds = numeric
    else:
        raise ValueError("Ambiguous numeric source timestamp")

    return datetime.fromtimestamp(
        seconds,
        tz=timezone.utc,
    )


def _number(value: str | None) -> float | None:
    number = float(value) if isinstance(value,(int,float)) else _float_or_none(value)

    if number is not None and not math.isfinite(number):
        raise ValueError("Nonfinite telemetry value")

    return number


def convert_v1_tail_row(
    row: TailRow,
    *,
    source_file: str | None,
) -> SnapshotRecord:
    """
    Convert one complete production v1.1 CSV row.

    Stable snapshot identity: tail row_id.
    Receipt timestamp: assigned by VNextCollectorBridge.
    Source timestamps: preserved from telemetry.

    No source time is substituted for a missing
    timestamp.
    """
    values = row.values

    missing = REQUIRED_FIELDS - set(values)

    if missing:
        raise ValueError(
            "Missing production telemetry columns: " + ", ".join(sorted(missing))
        )

    market = values["market_id"].strip().lower()

    if not market:
        raise ValueError("Missing market_id")

    observed = _parse_datetime(values["observed_at"])
    expiry = _parse_datetime(values["market_end_at"])

    if observed is None:
        raise ValueError("Missing observed_at")

    if expiry is None:
        raise ValueError("Missing market_end_at")

    return SnapshotRecord(
        snapshot_id=row.row_id,
        condition_id=market,
        observed_at=observed,
        source_name="polybtc_v1_1_telemetry",
        # Temporary value only. The bridge replaces
        # it with a persisted first-receipt timestamp.
        ingested_at=observed,
        reference_price=_number(values["btc_price"]),
        reference_timestamp=_timestamp(values["reference_timestamp"]),
        reference_age_ms=_number(values["reference_age_ms"]),
        reference_latency_ms=_number(values["reference_latency_ms"]),
        strike=_number(values["strike"]),
        seconds_to_expiry=_number(values["seconds_to_expiry"]),
        market_end_at=expiry,
        yes_bid=_number(values["yes_bid"]),
        yes_ask=_number(values["yes_ask"]),
        no_bid=_number(values["no_bid"]),
        no_ask=_number(values["no_ask"]),
        yes_bid_size=_number(values["yes_bid_size"]),
        yes_ask_size=_number(values["yes_ask_size"]),
        no_bid_size=_number(values["no_bid_size"]),
        no_ask_size=_number(values["no_ask_size"]),
        yes_token_id=(values["yes_token_id"].strip() or None),
        no_token_id=(values["no_token_id"].strip() or None),
        yes_book_timestamp=_timestamp(values["yes_book_timestamp"]),
        yes_book_age_ms=_number(values["yes_book_age_ms"]),
        yes_book_latency_ms=_number(values["yes_book_latency_ms"]),
        no_book_timestamp=_timestamp(values["no_book_timestamp"]),
        no_book_age_ms=_number(values["no_book_age_ms"]),
        no_book_latency_ms=_number(values["no_book_latency_ms"]),
        yes_tick_size=_number(values["yes_tick_size"]),
        yes_min_order_size=_number(values["yes_min_order_size"]),
        no_tick_size=_number(values["no_tick_size"]),
        no_min_order_size=_number(values["no_min_order_size"]),
        snapshot_build_latency_ms=_number(values["snapshot_build_latency_ms"]),
        momentum_60s=_number(values.get("momentum_60s")),
        volatility_60s=_number(values.get("volatility_60s")),
        source_file=Path(source_file).name if source_file else None,
        # Byte-offset identity is provided by row_id.
        # CSV physical row numbers change across
        # rotation and cannot be inferred reliably.
        source_row_number=None,
        collector_version=(values["collector_version"].strip() or None),
    )
