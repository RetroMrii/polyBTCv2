from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.executor_vnext import (
    ShadowExecutionQuote,
    ShadowFillStatus,
    VNextShadowExecutor,
)
from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.strategy.vnext import (
    Action,
    StrategyInput,
    VNextStrategy,
)


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def prepared_ledger(tmp_path):
    ledger = VNextShadowLedger(tmp_path / "executor_test.sqlite3")

    decision = VNextStrategy().evaluate(
        StrategyInput(
            condition_id="exec-market",
            horizon_seconds=60,
            model_probability_yes=0.73,
            market_probability_yes=0.72,
            yes_ask=0.65,
            no_ask=0.36,
            yes_ask_size=10.0,
            no_ask_size=10.0,
            yes_book_age_ms=0,
            no_book_age_ms=0,
            reference_age_ms=0,
            tick_size=0.01,
            fee_per_share=0.02,
        )
    )

    assert decision.action == Action.BUY_YES

    reservation = ledger.reserve(
        decision=decision,
        risk_gate=VNextRiskGate(),
        requested_size=5,
        minimum_order_size=5,
        at=NOW,
    )

    assert reservation.approved

    return ledger


def sample_quote():
    return ShadowExecutionQuote(
        condition_id="exec-market",
        observed_at_utc=NOW,
        reference_observed_at_utc=NOW,
        yes_ask=0.65,
        no_ask=0.36,
        yes_ask_size=10,
        no_ask_size=10,
        yes_tick_size=0.01,
        no_tick_size=0.01,
        minimum_order_size=5,
        fee_rate=0.07,
    )


def test_successful_fill(prepared_ledger):
    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=sample_quote(),
        at=NOW,
    )

    assert result.status == ShadowFillStatus.FILLED
    assert result.execution_price == pytest.approx(0.66)
    assert result.filled_size == pytest.approx(5)

    assert prepared_ledger.positions()[0].status == "FILLED"


def test_execution_price_ceiling(prepared_ledger):
    quote = replace(sample_quote(), yes_ask=0.70)

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.status == ShadowFillStatus.REJECTED
    assert result.reason == "execution_price_ceiling"


def test_stale_quote(prepared_ledger):
    quote = replace(
        sample_quote(),
        observed_at_utc=NOW - timedelta(seconds=1),
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "stale_execution_quote"


def test_stale_reference(prepared_ledger):
    quote = replace(
        sample_quote(),
        reference_observed_at_utc=(NOW - timedelta(milliseconds=3001)),
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "stale_execution_reference"


def test_missing_reference_timestamp(prepared_ledger):
    quote = replace(
        sample_quote(),
        reference_observed_at_utc=None,
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "missing_reference_timestamp"


def test_insufficient_depth(prepared_ledger):
    quote = replace(
        sample_quote(),
        yes_ask_size=3,
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "insufficient_execution_depth"


def test_reject_fee_overrun(prepared_ledger):
    quote = replace(
        sample_quote(),
        fee_rate=10.0,
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "fill_exceeds_approved_constraints"


def test_reject_price_above_reservation(prepared_ledger):
    quote = replace(
        sample_quote(),
        yes_ask=0.66,
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "fill_exceeds_approved_constraints"


def test_no_duplicate_fill(prepared_ledger):
    executor = VNextShadowExecutor()

    executor.execute(
        ledger=prepared_ledger,
        quote=sample_quote(),
        at=NOW,
    )

    with pytest.raises(RuntimeError):
        executor.execute(
            ledger=prepared_ledger,
            quote=sample_quote(),
            at=NOW,
        )


def test_restart_preserves_fill(prepared_ledger):
    executor = VNextShadowExecutor()

    executor.execute(
        ledger=prepared_ledger,
        quote=sample_quote(),
        at=NOW,
    )

    reopened = VNextShadowLedger(prepared_ledger.path)

    assert reopened.positions()[0].status == "FILLED"
    assert reopened.portfolio_state(at=NOW).open_exposure_usd > 0


def test_missing_fee_rate_rejected(prepared_ledger):
    quote = replace(
        sample_quote(),
        fee_rate=None,
    )

    result = VNextShadowExecutor().execute(
        ledger=prepared_ledger,
        quote=quote,
        at=NOW,
    )

    assert result.reason == "missing_or_invalid_fee_rate"
