from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from polybtc.data.paper_policy_vnext import MAX_BOOK_AGE_MS, MAX_REFERENCE_AGE_MS
from polybtc.execution.model import calculate_taker_fee
from polybtc.shadow.ledger_vnext import VNextShadowLedger


class ShadowFillStatus(StrEnum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ShadowExecutionConfig:
    version: str = "shadow_executor_vnext_v1"
    slippage_ticks: int = 1
    max_execution_price: float = 0.70
    max_book_age_ms: float = MAX_BOOK_AGE_MS
    max_reference_age_ms: float = MAX_REFERENCE_AGE_MS


@dataclass(frozen=True, slots=True)
class ShadowExecutionQuote:
    condition_id: str
    observed_at_utc: datetime
    reference_observed_at_utc: datetime | None

    yes_ask: float | None
    no_ask: float | None

    yes_ask_size: float | None
    no_ask_size: float | None

    yes_tick_size: float | None
    no_tick_size: float | None

    minimum_order_size: float | None
    fee_rate: float | None


@dataclass(frozen=True, slots=True)
class ShadowExecutionResult:
    executor_version: str
    status: ShadowFillStatus
    condition_id: str
    side: str
    reason: str

    filled_size: float = 0.0
    observed_ask: float | None = None
    execution_price: float | None = None
    entry_fee: float | None = None
    total_cost: float | None = None


def _finite(
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return False

    return (
        math.isfinite(number)
        and (minimum is None or number >= minimum)
        and (maximum is None or number <= maximum)
    )


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware timestamp required")

    return value.astimezone(timezone.utc)


class VNextShadowExecutor:
    """
    Deterministic shadow-only execution.

    Consumes an existing pending ledger reservation.
    Does not place orders or fetch market data.
    """

    def __init__(
        self,
        config: ShadowExecutionConfig | None = None,
    ) -> None:
        self.config = config or ShadowExecutionConfig()
        c = self.config

        if c.max_execution_price != 0.70:
            raise ValueError("Fixed $0.70 ceiling required")

        if (
            isinstance(c.slippage_ticks, bool)
            or not isinstance(c.slippage_ticks, int)
            or c.slippage_ticks < 0
        ):
            raise ValueError("Invalid slippage ticks")

        if not _finite(c.max_book_age_ms, minimum=0) or not _finite(
            c.max_reference_age_ms, minimum=0
        ):
            raise ValueError("Invalid freshness limits")

    def execute(
        self,
        *,
        ledger: VNextShadowLedger,
        quote: ShadowExecutionQuote,
        at: datetime,
    ) -> ShadowExecutionResult:
        c = self.config
        now = _utc(at)

        if not isinstance(quote.condition_id, str):
            raise ValueError("Invalid market identifier")

        market_id = quote.condition_id.strip().lower()

        if not market_id:
            raise ValueError("Missing market identifier")

        # Locate the durable reservation.
        # The ledger remains authoritative for side and size.
        positions = [
            position
            for position in ledger.positions()
            if position.condition_id == market_id
        ]

        if len(positions) != 1:
            raise RuntimeError("Expected exactly one market reservation")

        position = positions[0]

        if position.status != "PENDING":
            raise RuntimeError("Execution requires a pending reservation")

        side = position.side

        if side not in ("YES", "NO"):
            raise RuntimeError("Invalid reserved side")

        def reject(reason: str) -> ShadowExecutionResult:
            ledger.reject_pending(
                condition_id=market_id,
                reason=reason,
                at=now,
            )

            return ShadowExecutionResult(
                executor_version=c.version,
                status=ShadowFillStatus.REJECTED,
                condition_id=market_id,
                side=side,
                reason=reason,
            )

        try:
            quote_time = _utc(quote.observed_at_utc)
        except ValueError:
            return reject("invalid_quote_timestamp")

        age_ms = (now - quote_time).total_seconds() * 1000

        if age_ms < 0:
            return reject("quote_from_future")

        if age_ms > c.max_book_age_ms:
            return reject("stale_execution_quote")

        if quote.reference_observed_at_utc is None:
            return reject("missing_reference_timestamp")

        try:
            reference_time = _utc(quote.reference_observed_at_utc)
        except ValueError:
            return reject("invalid_reference_timestamp")

        reference_age_ms = (now - reference_time).total_seconds() * 1000

        if reference_age_ms < 0:
            return reject("reference_from_future")

        if reference_age_ms > c.max_reference_age_ms:
            return reject("stale_execution_reference")

        if side == "YES":
            ask = quote.yes_ask
            depth = quote.yes_ask_size
            tick = quote.yes_tick_size
        else:
            ask = quote.no_ask
            depth = quote.no_ask_size
            tick = quote.no_tick_size

        if not _finite(ask, minimum=0, maximum=1):
            return reject("invalid_selected_ask")

        if ask == 0:
            return reject("invalid_selected_ask")

        if not _finite(depth, minimum=0):
            return reject("missing_or_invalid_depth")

        if not _finite(tick, minimum=0):
            return reject("invalid_tick_size")

        if tick == 0:
            return reject("invalid_tick_size")

        if not _finite(quote.minimum_order_size, minimum=0):
            return reject("missing_minimum_order_size")

        if quote.minimum_order_size == 0:
            return reject("invalid_minimum_order_size")

        if not _finite(quote.fee_rate, minimum=0):
            return reject("missing_or_invalid_fee_rate")

        # Reservation size is read from SQLite rather
        # than trusted from the caller's quote.
        # The v1 ledger exposes that via its positions
        # interface only for filled entries, so pending
        # size must be fetched through the added method
        # in Step 2 below.
        requested_size = ledger.pending_size(market_id)

        if requested_size < quote.minimum_order_size:
            return reject("below_minimum_order_size")

        if depth < requested_size:
            return reject("insufficient_execution_depth")

        execution_price = float(ask) + c.slippage_ticks * float(tick)

        if (
            not math.isfinite(execution_price)
            or execution_price > c.max_execution_price
            or execution_price > 1
        ):
            return reject("execution_price_ceiling")

        fee = calculate_taker_fee(
            filled_size=requested_size,
            execution_price=execution_price,
            fee_rate=float(quote.fee_rate),
        )

        total_cost = requested_size * execution_price + fee

        # record_fill verifies the original risk-approved
        # price, fee envelope, size, and reserved cost.
        # A changed quote that violates those constraints
        # must not be marked FILLED.
        try:
            ledger.record_fill(
                condition_id=market_id,
                execution_price=execution_price,
                filled_size=requested_size,
                entry_fee=fee,
                at=now,
            )
        except ValueError:
            return reject("fill_exceeds_approved_constraints")

        return ShadowExecutionResult(
            executor_version=c.version,
            status=ShadowFillStatus.FILLED,
            condition_id=market_id,
            side=side,
            reason="shadow_full_fill",
            filled_size=requested_size,
            observed_ask=float(ask),
            execution_price=execution_price,
            entry_fee=fee,
            total_cost=total_cost,
        )
