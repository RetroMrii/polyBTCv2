from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from polybtc.data.schema import FillRecord, OrderRecord, OrderSide, Outcome
from polybtc.data.validation import (
    validate_condition_id,
    validate_nonnegative,
    validate_probability,
)

EXIT_EVENTS = {
    "CASHOUT",
    "STOPLOSS",
    "TIME_EXIT",
    "TRAIL_EXIT",
    "PROTECT_EXIT",
    "RECONCILED_EXIT",
    "SETTLE",
}

_ORDER_ID_RE = re.compile(r"(?:order_id|exit_order_id)=(0x[0-9a-fA-F]{64})")


@dataclass(frozen=True, slots=True)
class V1TradeAudit:
    source_row_number: int
    timestamp: datetime
    mode: str
    market_id: str
    side: str
    outcome: str
    price: float | None
    size: float | None
    simulated: bool
    reason: str
    pnl: float | None


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive timestamp: {value!r}")
    return dt.astimezone(timezone.utc)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    return None if value == "" else float(value)


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _synthetic_id(
    prefix: str,
    market_id: str,
    ts: datetime,
    row_number: int,
) -> str:
    raw = (
        f"{prefix}|{market_id}|{ts.isoformat()}|{row_number}"
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:24]}"


def _extract_order_id(reason: str) -> str | None:
    match = _ORDER_ID_RE.search(reason)
    return match.group(1) if match else None


def _outcome(value: str) -> Outcome:
    normalized = value.strip().upper()
    if normalized == "YES":
        return Outcome.YES
    if normalized == "NO":
        return Outcome.NO
    raise ValueError(f"unexpected v1 trade outcome: {value!r}")


def load_v1_trade_audit(
    path: str | Path,
) -> list[V1TradeAudit]:
    rows: list[V1TradeAudit] = []

    with Path(path).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row_number, row in enumerate(reader, start=2):
            timestamp = _parse_dt(row["timestamp"])
            market_id = row["market_id"].strip()
            validate_condition_id(market_id)

            price = _float_or_none(row.get("price"))
            size = _float_or_none(row.get("size"))
            pnl = _float_or_none(row.get("pnl"))

            validate_probability(price, "price")
            validate_nonnegative(size, "size")

            rows.append(
                V1TradeAudit(
                    source_row_number=row_number,
                    timestamp=timestamp,
                    mode=row["mode"].strip(),
                    market_id=market_id,
                    side=row["side"].strip(),
                    outcome=row["outcome"].strip().upper(),
                    price=price,
                    size=size,
                    simulated=_bool(row["simulated"]),
                    reason=row["reason"].strip(),
                    pnl=pnl,
                )
            )

    return rows


def reconstruct_orders(
    rows: Iterable[V1TradeAudit],
    *,
    ingested_at: datetime | None = None,
) -> list[OrderRecord]:
    ingestion_time = (
        ingested_at or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)

    orders: list[OrderRecord] = []

    for row in rows:
        if row.side not in {
            "ORDER_POSTED",
            "EXIT_ORDER_POSTED",
        }:
            continue

        if row.price is None or row.size is None:
            continue

        real_order_id = _extract_order_id(row.reason)
        order_id = real_order_id or _synthetic_id(
            "v1_order",
            row.market_id,
            row.timestamp,
            row.source_row_number,
        )

        orders.append(
            OrderRecord(
                order_id=order_id,
                condition_id=row.market_id,
                token_id="UNKNOWN",
                outcome=_outcome(row.outcome),
                side=(
                    OrderSide.BUY
                    if row.side == "ORDER_POSTED"
                    else OrderSide.SELL
                ),
                submitted_at=row.timestamp,
                limit_price=row.price,
                requested_size=row.size,
                source_name="polybtc_v1_1_trades",
                ingested_at=ingestion_time,
                status="RECONSTRUCTED_FROM_V1_EVENT",
                source_record_id=str(row.source_row_number),
            )
        )

    return orders


def reconstruct_fills(
    rows: Iterable[V1TradeAudit],
    *,
    ingested_at: datetime | None = None,
) -> list[FillRecord]:
    ingestion_time = (
        ingested_at or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)

    fills: list[FillRecord] = []

    for row in rows:
        if row.side == "BUY":
            exchange_side = OrderSide.BUY
        elif row.side in EXIT_EVENTS:
            exchange_side = OrderSide.SELL
        else:
            continue

        if row.price is None or row.size is None:
            continue

        fill_id = _synthetic_id(
            "v1_fill",
            row.market_id,
            row.timestamp,
            row.source_row_number,
        )

        fills.append(
            FillRecord(
                fill_id=fill_id,
                condition_id=row.market_id,
                side=exchange_side,
                filled_at=row.timestamp,
                price=row.price,
                size=row.size,
                source_name="polybtc_v1_1_trades",
                ingested_at=ingestion_time,
                order_id=_extract_order_id(row.reason),
                outcome=_outcome(row.outcome),
                source_record_id=str(row.source_row_number),
                reconciliation_status="RECONSTRUCTED_FROM_V1_EVENT",
            )
        )

    return fills
