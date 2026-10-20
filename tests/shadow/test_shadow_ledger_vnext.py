from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.ledger_vnext import (
    VNextShadowLedger,
)
from polybtc.strategy.vnext import (
    Action,
    StrategyInput,
    VNextStrategy,
)


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def make_decision(market="market-001"):
    item = StrategyInput(
        condition_id=market,
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

    decision = VNextStrategy().evaluate(item)
    assert decision.action == Action.BUY_YES
    return decision


@pytest.fixture
def ledger(tmp_path):
    return VNextShadowLedger(tmp_path / "shadow_vnext.sqlite3")


def reserve(
    ledger,
    market="market-001",
    at=NOW,
    kill_switch=False,
):
    return ledger.reserve(
        decision=make_decision(market),
        risk_gate=VNextRiskGate(),
        requested_size=5.0,
        minimum_order_size=5.0,
        at=at,
        kill_switch=kill_switch,
    )


def fill(ledger, market="market-001", at=NOW):
    ledger.record_fill(
        condition_id=market,
        execution_price=0.66,
        filled_size=5.0,
        entry_fee=0.05,
        at=at,
    )


def test_reservation_is_persistent(ledger):
    result = reserve(ledger)

    assert result.approved
    assert result.reservation_id is not None

    reopened = VNextShadowLedger(ledger.path)

    state = reopened.portfolio_state(at=NOW)

    assert "market-001" in state.pending_markets
    assert state.open_exposure_usd == pytest.approx(3.35)


def test_duplicate_market_rejected(ledger):
    assert reserve(ledger).approved

    second = reserve(ledger)

    assert not second.approved
    assert second.reason == "market_already_reserved"

    assert len(ledger.positions()) == 1


def test_fill_and_reconstruct_state(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    reopened = VNextShadowLedger(ledger.path)
    state = reopened.portfolio_state(at=NOW)

    assert "market-001" in state.entered_markets
    assert "market-001" not in state.pending_markets

    assert state.open_exposure_usd == pytest.approx(3.35)

    assert state.open_capital_at_risk_usd == pytest.approx(3.35)

    assert reopened.positions()[0].status == "FILLED"


def test_fill_above_approved_price_rejected(ledger):
    assert reserve(ledger).approved

    with pytest.raises(ValueError):
        ledger.record_fill(
            condition_id="market-001",
            execution_price=0.70,
            filled_size=5.0,
            entry_fee=0.05,
            at=NOW,
        )

    assert ledger.positions()[0].status == "PENDING"


def test_fee_overrun_rejected(ledger):
    assert reserve(ledger).approved

    with pytest.raises(ValueError):
        ledger.record_fill(
            condition_id="market-001",
            execution_price=0.66,
            filled_size=5.0,
            entry_fee=0.06,
            at=NOW,
        )

    assert ledger.positions()[0].status == "PENDING"


def test_full_fill_required(ledger):
    assert reserve(ledger).approved

    with pytest.raises(ValueError):
        ledger.record_fill(
            condition_id="market-001",
            execution_price=0.66,
            filled_size=2.0,
            entry_fee=0.02,
            at=NOW,
        )


def test_yes_win_settlement(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    settled_at = NOW + timedelta(minutes=5)

    pnl = ledger.settle(
        condition_id="market-001",
        label_yes=1,
        at=settled_at,
    )

    assert pnl == pytest.approx(1.65)

    state = ledger.portfolio_state(at=settled_at)

    assert state.open_exposure_usd == pytest.approx(0.0)
    assert state.daily_realized_pnl_usd == pytest.approx(1.65)


def test_yes_loss_settlement(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    pnl = ledger.settle(
        condition_id="market-001",
        label_yes=0,
        at=NOW + timedelta(minutes=5),
    )

    assert pnl == pytest.approx(-3.35)


def test_settlement_is_idempotent(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    first = ledger.settle(
        condition_id="market-001",
        label_yes=1,
        at=NOW + timedelta(minutes=5),
    )

    second = ledger.settle(
        condition_id="market-001",
        label_yes=1,
        at=NOW + timedelta(minutes=6),
    )

    assert first == second

    with pytest.raises(RuntimeError):
        ledger.settle(
            condition_id="market-001",
            label_yes=0,
            at=NOW + timedelta(minutes=6),
        )


def test_rejection_releases_exposure(ledger):
    assert reserve(ledger).approved

    ledger.reject_pending(
        condition_id="market-001",
        reason="insufficient_executable_depth",
        at=NOW,
    )

    state = ledger.portfolio_state(at=NOW)

    assert state.open_exposure_usd == 0.0
    assert not state.pending_markets

    # Conservative one-reservation-per-market policy.
    assert not reserve(ledger).approved


def test_kill_switch_denies_reservation(ledger):
    result = reserve(
        ledger,
        kill_switch=True,
    )

    assert not result.approved
    assert result.reason == "kill_switch_active"

    assert ledger.positions() == []


def test_risk_budget_is_reconstructed(ledger):
    assert reserve(ledger, "market-a").approved
    fill(ledger, "market-a")

    assert reserve(
        ledger,
        "market-b",
        at=NOW + timedelta(seconds=1),
    ).approved

    # Third entry would bring total capital at risk
    # above the fixed $10 daily risk budget.
    third = reserve(
        ledger,
        "market-c",
        at=NOW + timedelta(seconds=2),
    )

    assert not third.approved
    assert third.reason == ("daily_worst_case_loss_limit")


def test_different_day_pnl(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    tomorrow = NOW + timedelta(days=1)

    ledger.settle(
        condition_id="market-001",
        label_yes=0,
        at=tomorrow,
    )

    tomorrow_state = ledger.portfolio_state(at=tomorrow)

    assert tomorrow_state.daily_realized_pnl_usd == (pytest.approx(-3.35))


def test_unknown_market_cannot_fill(ledger):
    with pytest.raises(RuntimeError):
        fill(ledger, "does-not-exist")


def test_risk_rejects_invalid_strategy(ledger):
    decision = replace(
        make_decision(),
        strategy_version="unsupported",
    )

    result = ledger.reserve(
        decision=decision,
        risk_gate=VNextRiskGate(),
        requested_size=5.0,
        minimum_order_size=5.0,
        at=NOW,
    )

    assert not result.approved
    assert result.reason == ("unsupported_strategy_version")


def test_settled_market_cannot_reenter(ledger):
    assert reserve(ledger).approved
    fill(ledger)

    ledger.settle(
        condition_id="market-001",
        label_yes=1,
        at=NOW + timedelta(minutes=5),
    )

    result = reserve(
        ledger,
        at=NOW + timedelta(minutes=6),
    )

    assert not result.approved
    assert result.reason == "market_already_reserved"
