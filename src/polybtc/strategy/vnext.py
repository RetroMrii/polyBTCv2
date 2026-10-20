from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    version: str = "strategy_vnext_v1"

    max_execution_price: float = 0.70
    max_probability_gap: float = 0.05
    min_net_ev_per_share: float = 0.0

    min_ask_depth: float = 5.0
    max_book_age_ms: float = 500.0
    max_reference_age_ms: float = 2000.0

    slippage_ticks: int = 1

    allowed_horizons: tuple[int, ...] = (240, 180, 120, 90, 60, 30)


@dataclass(frozen=True, slots=True)
class StrategyInput:
    condition_id: str
    horizon_seconds: int

    model_probability_yes: float | None
    market_probability_yes: float | None

    yes_ask: float | None
    no_ask: float | None

    yes_ask_size: float | None
    no_ask_size: float | None

    yes_book_age_ms: float | None
    no_book_age_ms: float | None
    reference_age_ms: float | None

    tick_size: float | None

    # Estimated acquisition fee in dollars PER SHARE.
    # Convert venue fee rules to this amount upstream.
    fee_per_share: float | None


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    strategy_version: str
    condition_id: str
    horizon_seconds: int

    action: Action
    reason: str

    model_probability_yes: float | None
    market_probability_yes: float | None

    selected_probability: float | None = None
    selected_ask: float | None = None
    execution_price: float | None = None
    fee_per_share: float | None = None
    net_ev_per_share: float | None = None


def valid_number(
    value: float | None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    if not math.isfinite(number):
        return False

    if minimum is not None and number < minimum:
        return False

    if maximum is not None and number > maximum:
        return False

    return True


class VNextStrategy:
    def __init__(
        self,
        config: StrategyConfig | None = None,
    ) -> None:
        self.config = config or StrategyConfig()
        c = self.config

        if c.max_execution_price != 0.70:
            raise ValueError("vNext v1 requires the fixed $0.70 ceiling")

        if not (
            0 <= c.max_probability_gap <= 1
            and 0 <= c.min_net_ev_per_share <= 1
            and c.min_ask_depth > 0
            and c.max_book_age_ms >= 0
            and c.max_reference_age_ms >= 0
        ):
            raise ValueError("Invalid strategy configuration")

        if (
            isinstance(c.slippage_ticks, bool)
            or not isinstance(c.slippage_ticks, int)
            or c.slippage_ticks < 0
        ):
            raise ValueError("Invalid slippage ticks")

    def evaluate(
        self,
        item: StrategyInput,
    ) -> StrategyDecision:
        c = self.config

        def abstain(reason: str) -> StrategyDecision:
            return StrategyDecision(
                strategy_version=c.version,
                condition_id=item.condition_id,
                horizon_seconds=item.horizon_seconds,
                action=Action.ABSTAIN,
                reason=reason,
                model_probability_yes=(item.model_probability_yes),
                market_probability_yes=(item.market_probability_yes),
            )

        if not item.condition_id.strip():
            return abstain("invalid_market_id")

        if item.horizon_seconds not in c.allowed_horizons:
            return abstain("unsupported_horizon")

        if not valid_number(item.reference_age_ms, minimum=0):
            return abstain("missing_reference_age")

        if item.reference_age_ms > c.max_reference_age_ms:
            return abstain("stale_reference")

        if not valid_number(item.model_probability_yes, 0, 1):
            return abstain("missing_model_probability")

        if not valid_number(item.market_probability_yes, 0, 1):
            return abstain("missing_market_probability")

        model_p = float(item.model_probability_yes)
        market_p = float(item.market_probability_yes)

        # No direction is chosen when the market
        # probability is exactly neutral.
        if market_p == 0.5:
            return abstain("market_direction_neutral")

        # Model and market must agree on the
        # direction of the selected outcome.
        if (model_p > 0.5) != (market_p > 0.5):
            return abstain("model_market_disagreement")

        if model_p == 0.5:
            return abstain("model_direction_neutral")

        if abs(model_p - market_p) > c.max_probability_gap:
            return abstain("probability_gap_too_large")

        if not valid_number(item.tick_size, minimum=0) or item.tick_size == 0:
            return abstain("invalid_tick_size")

        if not valid_number(item.fee_per_share, minimum=0):
            return abstain("missing_fee_estimate")

        if market_p > 0.5:
            action = Action.BUY_YES
            probability = market_p
            ask = item.yes_ask
            depth = item.yes_ask_size
            age = item.yes_book_age_ms
        else:
            action = Action.BUY_NO
            probability = 1.0 - market_p
            ask = item.no_ask
            depth = item.no_ask_size
            age = item.no_book_age_ms

        if not valid_number(ask, 0, 1) or ask == 0:
            return abstain("missing_or_invalid_ask")

        if not valid_number(age, minimum=0):
            return abstain("missing_book_age")

        if age > c.max_book_age_ms:
            return abstain("stale_book")

        if not valid_number(depth, minimum=0):
            return abstain("missing_ask_depth")

        if depth < c.min_ask_depth:
            return abstain("insufficient_depth")

        execution_price = float(ask) + c.slippage_ticks * float(item.tick_size)

        if execution_price > c.max_execution_price:
            return abstain("price_ceiling_exceeded")

        fee = float(item.fee_per_share)

        # Binary contract held to settlement:
        # expected payout = P(selected side) * $1.
        net_ev = probability - execution_price - fee

        if net_ev <= c.min_net_ev_per_share:
            return abstain("insufficient_net_ev")

        return StrategyDecision(
            strategy_version=c.version,
            condition_id=item.condition_id,
            horizon_seconds=item.horizon_seconds,
            action=action,
            reason="positive_net_ev",
            model_probability_yes=model_p,
            market_probability_yes=market_p,
            selected_probability=probability,
            selected_ask=float(ask),
            execution_price=execution_price,
            fee_per_share=fee,
            net_ev_per_share=net_ev,
        )
