from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class ExecutionSide(StrEnum):
    YES = "YES"
    NO = "NO"


class FillStatus(StrEnum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionRequest:
    side: ExecutionSide
    requested_size: float


@dataclass(
    frozen=True,
    slots=True,
)
class MarketExecutionState:
    yes_ask: float | None
    no_ask: float | None


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionResult:
    status: FillStatus
    side: ExecutionSide

    requested_size: float
    filled_size: float

    execution_price: float | None

    reason: str


def _valid_number(
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return (
        math.isfinite(number)
        and (minimum is None or number >= minimum)
        and (maximum is None or number <= maximum)
    )


def execute_level1_crossing(
    request: ExecutionRequest,
    market: MarketExecutionState,
) -> ExecutionResult:
    if (
        not _valid_number(request.requested_size, minimum=0)
        or request.requested_size == 0
    ):
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="invalid_requested_size",
        )

    if request.side == ExecutionSide.YES:
        ask = market.yes_ask

    elif request.side == ExecutionSide.NO:
        ask = market.no_ask

    else:
        raise ValueError(f"unsupported execution side: {request.side}")

    if ask is None:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="missing_ask",
        )

    if not _valid_number(ask, minimum=0, maximum=1):
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="invalid_ask",
        )

    return ExecutionResult(
        status=FillStatus.FILLED,
        side=request.side,
        requested_size=request.requested_size,
        filled_size=request.requested_size,
        execution_price=ask,
        reason="level1_cross_recorded_ask",
    )


def execute_depth_constrained_crossing(
    request: ExecutionRequest,
    market: MarketExecutionState,
    *,
    available_ask_size: float | None,
    minimum_order_size: float | None,
) -> ExecutionResult:
    if (
        not _valid_number(request.requested_size, minimum=0)
        or request.requested_size == 0
    ):
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="invalid_requested_size",
        )

    if minimum_order_size is None:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="missing_minimum_order_size",
        )

    if not _valid_number(minimum_order_size, minimum=0) or minimum_order_size == 0:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="invalid_minimum_order_size",
        )

    if request.requested_size < minimum_order_size:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="below_minimum_order_size",
        )

    if available_ask_size is None:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="missing_ask_size",
        )

    if not _valid_number(available_ask_size, minimum=0):
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="invalid_ask_size",
        )

    if available_ask_size < request.requested_size:
        return ExecutionResult(
            status=FillStatus.REJECTED,
            side=request.side,
            requested_size=request.requested_size,
            filled_size=0.0,
            execution_price=None,
            reason="insufficient_top_of_book_depth",
        )

    return execute_level1_crossing(
        request,
        market,
    )


def settlement_value_per_share(
    side: ExecutionSide,
    label_yes: int,
) -> float:
    if label_yes not in {0, 1}:
        raise ValueError(f"invalid label_yes: {label_yes}")

    if side == ExecutionSide.YES:
        return float(label_yes)

    if side == ExecutionSide.NO:
        return float(1 - label_yes)

    raise ValueError(f"unsupported execution side: {side}")


def settlement_pnl(
    *,
    side: ExecutionSide,
    label_yes: int,
    execution_price: float,
    filled_size: float,
) -> float:
    value = settlement_value_per_share(
        side,
        label_yes,
    )

    return (value - execution_price) * filled_size


def calculate_taker_fee(
    *,
    filled_size: float,
    execution_price: float,
    fee_rate: float,
) -> float:
    if filled_size < 0:
        raise ValueError("filled_size must be non-negative")

    if not 0.0 <= execution_price <= 1.0:
        raise ValueError("execution_price must be between 0 and 1")

    if fee_rate < 0:
        raise ValueError("fee_rate must be non-negative")

    raw_fee = filled_size * fee_rate * execution_price * (1.0 - execution_price)

    return round(
        raw_fee,
        5,
    )
