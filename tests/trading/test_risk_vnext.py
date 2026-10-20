from dataclasses import replace
from datetime import datetime, timezone

import pytest

from polybtc.risk.vnext import (
    PortfolioRiskState,
    RiskAction,
    RiskConfig,
    RiskRequest,
    VNextRiskGate,
)
from polybtc.strategy.vnext import (
    StrategyInput,
    VNextStrategy,
)


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def valid_strategy_decision():
    return VNextStrategy().evaluate(
        StrategyInput(
            condition_id="market-001",
            horizon_seconds=60,
            model_probability_yes=0.73,
            market_probability_yes=0.72,
            yes_ask=0.65,
            no_ask=0.36,
            yes_ask_size=10.0,
            no_ask_size=10.0,
            yes_book_age_ms=100.0,
            no_book_age_ms=100.0,
            reference_age_ms=100.0,
            tick_size=0.01,
            fee_per_share=0.01,
        )
    )


def valid_state():
    return PortfolioRiskState(
        state_complete=True,
        as_of_utc=NOW,
        daily_pnl_date_utc=NOW.date(),
        open_exposure_usd=0.0,
        open_capital_at_risk_usd=0.0,
        daily_realized_pnl_usd=0.0,
        entered_markets=frozenset(),
        pending_markets=frozenset(),
        kill_switch_active=False,
    )


def valid_request():
    return RiskRequest(
        decision=valid_strategy_decision(),
        state=valid_state(),
        requested_size=5.0,
        minimum_order_size=5.0,
        evaluated_at_utc=NOW,
    )


def test_approve_valid_shadow_entry():
    result = VNextRiskGate().evaluate(valid_request())

    assert result.action == RiskAction.APPROVE_SHADOW
    assert result.approved_size == 5
    assert result.maximum_execution_price == pytest.approx(0.66)
    assert result.reserved_notional_usd == pytest.approx(3.35)


def test_missing_state_rejected():
    request = valid_request()
    state = replace(request.state, state_complete=False)
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "portfolio_state_incomplete"


def test_previous_entry_rejected():
    request = valid_request()
    state = replace(
        request.state,
        entered_markets=frozenset({"market-001"}),
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "market_already_entered"


def test_pending_order_rejected():
    request = valid_request()
    state = replace(
        request.state,
        pending_markets=frozenset({"market-001"}),
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "market_order_pending"


def test_kill_switch():
    request = valid_request()
    state = replace(request.state, kill_switch_active=True)
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "kill_switch_active"


def test_daily_loss_limit():
    request = valid_request()
    state = replace(
        request.state,
        daily_realized_pnl_usd=-10.0,
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "daily_loss_limit_reached"


def test_exposure_limit():
    request = valid_request()
    state = replace(
        request.state,
        open_exposure_usd=23.0,
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "portfolio_exposure_limit"


def test_position_size_limit():
    request = replace(valid_request(), requested_size=6.0)
    result = VNextRiskGate().evaluate(request)
    assert result.reason == "position_size_limit"


def test_minimum_order_size():
    request = replace(valid_request(), minimum_order_size=6.0)
    result = VNextRiskGate().evaluate(request)
    assert result.reason == "below_minimum_order_size"


def test_invalid_daily_date():
    request = valid_request()
    state = replace(
        request.state,
        daily_pnl_date_utc=(datetime(2026, 10, 7).date()),
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "daily_pnl_date_mismatch"


def test_fail_closed_on_future_state():
    request = valid_request()
    state = replace(
        request.state,
        as_of_utc=NOW.replace(hour=16),
    )
    result = VNextRiskGate().evaluate(replace(request, state=state))
    assert result.reason == "state_from_future"


def test_approval_does_not_mutate_state():
    request = valid_request()
    original = request.state

    VNextRiskGate().evaluate(request)

    assert request.state == original
    assert not request.state.entered_markets
    assert not request.state.pending_markets


def test_reject_higher_execution_ceiling():
    with pytest.raises(ValueError):
        VNextRiskGate(RiskConfig(max_execution_price=0.80))


def test_reject_modified_ev():
    request = valid_request()
    decision = replace(
        request.decision,
        net_ev_per_share=0.20,
    )
    result = VNextRiskGate().evaluate(replace(request, decision=decision))
    assert result.reason == "expected_value_mismatch"


def test_reject_modified_strategy_version():
    request = valid_request()
    decision = replace(
        request.decision,
        strategy_version="unknown_strategy",
    )
    result = VNextRiskGate().evaluate(replace(request, decision=decision))
    assert result.reason == "unsupported_strategy_version"


def test_independent_order_value_limit():
    gate = VNextRiskGate(RiskConfig(max_order_value_usd=3.0))

    result = gate.evaluate(valid_request())

    assert result.action == RiskAction.REJECT
    assert result.reason == "order_value_limit"


def test_open_capital_at_risk_blocks_entry():
    request = valid_request()

    state = replace(
        request.state,
        open_exposure_usd=8.0,
        open_capital_at_risk_usd=8.0,
    )

    result = VNextRiskGate().evaluate(replace(request, state=state))

    assert result.action == RiskAction.REJECT
    assert result.reason == "daily_worst_case_loss_limit"


def test_realized_losses_reduce_budget():
    request = valid_request()

    state = replace(
        request.state,
        daily_realized_pnl_usd=-7.0,
    )

    result = VNextRiskGate().evaluate(replace(request, state=state))

    assert result.action == RiskAction.REJECT
    assert result.reason == "daily_worst_case_loss_limit"


def test_positive_pnl_does_not_increase_budget():
    request = valid_request()

    state = replace(
        request.state,
        open_exposure_usd=8.0,
        open_capital_at_risk_usd=8.0,
        daily_realized_pnl_usd=100.0,
    )

    result = VNextRiskGate().evaluate(replace(request, state=state))

    assert result.action == RiskAction.REJECT
    assert result.reason == "daily_worst_case_loss_limit"


def test_valid_entry_remains_approved():
    result = VNextRiskGate().evaluate(valid_request())

    assert result.action == RiskAction.APPROVE_SHADOW
    assert result.reserved_notional_usd == pytest.approx(3.35)


@pytest.mark.parametrize(
    "invalid_value",
    [-1.0, float("nan"), float("inf")],
)
def test_invalid_open_capital_at_risk(invalid_value):
    request = valid_request()

    state = replace(
        request.state,
        open_capital_at_risk_usd=invalid_value,
    )

    result = VNextRiskGate().evaluate(replace(request, state=state))

    assert result.action == RiskAction.REJECT
    assert result.reason == "invalid_portfolio_numbers"
