from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum

from polybtc.strategy.vnext import Action, StrategyDecision


class RiskAction(StrEnum):
    APPROVE_SHADOW = "APPROVE_SHADOW"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class RiskConfig:
    version: str = "risk_vnext_v1"
    shares_per_entry: float = 5.0
    max_open_exposure_usd: float = 25.0
    max_order_value_usd: float = 7.0
    max_daily_realized_loss_usd: float = 10.0
    max_execution_price: float = 0.70
    max_entries_per_market: int = 1


@dataclass(frozen=True, slots=True)
class PortfolioRiskState:
    # Must be reconstructed from durable execution,
    # position, and settlement records.
    state_complete: bool
    as_of_utc: datetime
    daily_pnl_date_utc: date

    open_exposure_usd: float
    open_capital_at_risk_usd: float
    daily_realized_pnl_usd: float

    # Markets with an entry ever recorded, including
    # settled entries. Pending orders reserve a market.
    entered_markets: frozenset[str]
    pending_markets: frozenset[str]

    kill_switch_active: bool


@dataclass(frozen=True, slots=True)
class RiskRequest:
    decision: StrategyDecision
    state: PortfolioRiskState
    requested_size: float
    minimum_order_size: float | None
    evaluated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class RiskDecision:
    risk_version: str
    action: RiskAction
    reason: str
    condition_id: str

    approved_side: Action | None = None
    approved_size: float = 0.0
    maximum_execution_price: float | None = None
    reserved_notional_usd: float = 0.0


def finite(
    value: object,
    minimum: float | None = None,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return False

    return math.isfinite(number) and (minimum is None or number >= minimum)


def utc_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def canonical_market_id(value: str) -> str:
    return value.strip().lower()


class VNextRiskGate:
    def __init__(
        self,
        config: RiskConfig | None = None,
    ) -> None:
        self.config = config or RiskConfig()
        c = self.config

        if c.max_execution_price != 0.70:
            raise ValueError("vNext requires the fixed $0.70 price ceiling")

        for name in (
            "shares_per_entry",
            "max_open_exposure_usd",
            "max_order_value_usd",
            "max_daily_realized_loss_usd",
        ):
            if not finite(getattr(c, name), minimum=0):
                raise ValueError(f"Invalid {name}")

        if (
            c.shares_per_entry <= 0
            or c.max_open_exposure_usd <= 0
            or c.max_order_value_usd <= 0
            or c.max_daily_realized_loss_usd <= 0
        ):
            raise ValueError("Risk limits must be positive")

        if c.max_entries_per_market != 1:
            raise ValueError("vNext supports exactly one entry per market")

    def evaluate(self, request: RiskRequest) -> RiskDecision:
        c = self.config
        d = request.decision
        s = request.state

        market_id = canonical_market_id(d.condition_id)

        def reject(reason: str) -> RiskDecision:
            return RiskDecision(
                risk_version=c.version,
                action=RiskAction.REJECT,
                reason=reason,
                condition_id=market_id,
            )

        # Fail closed if the durable state is missing
        # or cannot be trusted.
        if not s.state_complete:
            return reject("portfolio_state_incomplete")

        if not utc_datetime(request.evaluated_at_utc):
            return reject("invalid_evaluation_timestamp")

        if not utc_datetime(s.as_of_utc):
            return reject("invalid_state_timestamp")

        now = request.evaluated_at_utc.astimezone(timezone.utc)
        state_time = s.as_of_utc.astimezone(timezone.utc)

        if state_time > now:
            return reject("state_from_future")

        if s.daily_pnl_date_utc != now.date():
            return reject("daily_pnl_date_mismatch")

        if (
            not finite(s.open_exposure_usd, 0)
            or not finite(s.open_capital_at_risk_usd, 0)
            or not finite(s.daily_realized_pnl_usd)
        ):
            return reject("invalid_portfolio_numbers")

        if not isinstance(s.kill_switch_active, bool):
            return reject("invalid_kill_switch_state")

        if s.kill_switch_active:
            return reject("kill_switch_active")

        if not market_id:
            return reject("invalid_market_id")

        if not isinstance(s.entered_markets, frozenset) or not isinstance(
            s.pending_markets, frozenset
        ):
            return reject("invalid_market_state")

        if any(
            not isinstance(value, str)
            or not value.strip()
            or value != canonical_market_id(value)
            for value in s.entered_markets | s.pending_markets
        ):
            return reject("invalid_market_state")

        if market_id in s.pending_markets:
            return reject("market_order_pending")

        if market_id in s.entered_markets:
            return reject("market_already_entered")

        if s.daily_realized_pnl_usd <= -c.max_daily_realized_loss_usd:
            return reject("daily_loss_limit_reached")

        if d.action not in (Action.BUY_YES, Action.BUY_NO):
            return reject("strategy_did_not_approve")

        if d.reason != "positive_net_ev":
            return reject("invalid_strategy_approval")

        if d.strategy_version != "strategy_vnext_v1":
            return reject("unsupported_strategy_version")

        if not finite(request.requested_size, 0):
            return reject("invalid_requested_size")

        if request.requested_size <= 0:
            return reject("invalid_requested_size")

        if request.requested_size > c.shares_per_entry:
            return reject("position_size_limit")

        if not finite(request.minimum_order_size, 0):
            return reject("missing_minimum_order_size")

        if (
            request.minimum_order_size <= 0
            or request.requested_size < request.minimum_order_size
        ):
            return reject("below_minimum_order_size")

        if not finite(d.execution_price, 0):
            return reject("missing_execution_price")

        if d.execution_price <= 0 or d.execution_price > c.max_execution_price:
            return reject("execution_price_limit")

        if not finite(d.fee_per_share, 0):
            return reject("invalid_fee_estimate")

        if not finite(d.net_ev_per_share) or d.net_ev_per_share <= 0:
            return reject("nonpositive_expected_value")

        if not finite(d.selected_probability, 0):
            return reject("missing_selected_probability")

        if d.selected_probability > 1:
            return reject("invalid_selected_probability")

        if not finite(d.selected_ask, 0):
            return reject("missing_selected_ask")

        if d.selected_ask <= 0 or d.selected_ask > d.execution_price:
            return reject("invalid_selected_ask")

        expected_ev = d.selected_probability - d.execution_price - d.fee_per_share

        if not math.isclose(
            expected_ev,
            d.net_ev_per_share,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            return reject("expected_value_mismatch")

        # Reserve projected cash cost, including fees.
        # Approval is not a fill; state changes later.
        reserved = request.requested_size * (d.execution_price + d.fee_per_share)

        # Independent maximum cost of one entry.
        # Cost includes modeled slippage and entry fees.
        if reserved > c.max_order_value_usd + 1e-9:
            return reject("order_value_limit")

        # Existing portfolio-wide exposure control.
        if s.open_exposure_usd + reserved > c.max_open_exposure_usd + 1e-9:
            return reject("portfolio_exposure_limit")

        # Conservative hold-to-settlement loss budget.
        # Positive realized PnL does not replenish budget.
        realized_losses = max(
            0.0,
            -s.daily_realized_pnl_usd,
        )

        projected_daily_capital_at_risk = (
            realized_losses + s.open_capital_at_risk_usd + reserved
        )

        if projected_daily_capital_at_risk > c.max_daily_realized_loss_usd + 1e-9:
            return reject("daily_worst_case_loss_limit")

        return RiskDecision(
            risk_version=c.version,
            action=RiskAction.APPROVE_SHADOW,
            reason="shadow_risk_approved",
            condition_id=market_id,
            approved_side=d.action,
            approved_size=request.requested_size,
            maximum_execution_price=d.execution_price,
            reserved_notional_usd=reserved,
        )
