from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.strategy.vnext import (
    Action,
    StrategyInput,
    VNextStrategy,
)


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def make_decision(market: str):
    result = VNextStrategy().evaluate(
        StrategyInput(
            condition_id=market,
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
            fee_per_share=0.01,
        )
    )

    assert result.action == Action.BUY_YES
    return result


def attempt_reservation(
    database_path,
    market,
    barrier=None,
):
    ledger = VNextShadowLedger(database_path)

    if barrier is not None:
        barrier.wait(timeout=10)

    return ledger.reserve(
        decision=make_decision(market),
        risk_gate=VNextRiskGate(),
        requested_size=5,
        minimum_order_size=5,
        at=NOW,
    )


def test_concurrent_duplicate_market(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    VNextShadowLedger(path)

    workers = 8
    barrier = Barrier(workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                attempt_reservation,
                path,
                "market-duplicate",
                barrier,
            )
            for _ in range(workers)
        ]
        results = [future.result() for future in futures]

    assert sum(result.approved for result in results) == 1

    ledger = VNextShadowLedger(path)
    assert len(ledger.positions()) == 1


def test_concurrent_risk_budget(tmp_path):
    path = tmp_path / "risk-budget.sqlite3"
    VNextShadowLedger(path)

    workers = 8
    barrier = Barrier(workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                attempt_reservation,
                path,
                f"market-{index}",
                barrier,
            )
            for index in range(workers)
        ]
        results = [future.result() for future in futures]

    # Each approval reserves $3.35.
    # A $10 worst-case budget can contain at most two.
    assert sum(result.approved for result in results) == 2

    ledger = VNextShadowLedger(path)
    state = ledger.portfolio_state(at=NOW)

    assert state.open_capital_at_risk_usd == pytest.approx(6.70)

    assert len(state.pending_markets) == 2


def test_pending_survives_restart(tmp_path):
    path = tmp_path / "restart.sqlite3"
    ledger = VNextShadowLedger(path)

    assert attempt_reservation(path, "market-restart").approved

    reopened = VNextShadowLedger(path)

    pending = reopened.pending_reservations(
        at=NOW + timedelta(seconds=5),
        stale_after_seconds=30,
    )

    assert len(pending) == 1
    assert pending[0]["condition_id"] == "market-restart"
    assert pending[0]["stale"] is False


def test_stale_pending_remains_reserved(tmp_path):
    path = tmp_path / "stale.sqlite3"
    ledger = VNextShadowLedger(path)

    assert attempt_reservation(path, "market-stale").approved

    pending = ledger.pending_reservations(
        at=NOW + timedelta(seconds=40),
        stale_after_seconds=30,
    )

    assert pending[0]["stale"] is True

    state = ledger.portfolio_state(at=NOW + timedelta(seconds=40))

    assert "market-stale" in state.pending_markets

    assert state.open_exposure_usd == pytest.approx(3.35)


def test_explicit_rejection_of_stale_pending(tmp_path):
    path = tmp_path / "reject.sqlite3"
    ledger = VNextShadowLedger(path)

    assert attempt_reservation(path, "market-reject").approved

    ledger.reject_pending(
        condition_id="market-reject",
        reason="manual_reconciliation_no_fill",
        at=NOW + timedelta(seconds=40),
    )

    assert ledger.pending_reservations(at=NOW + timedelta(seconds=41)) == []

    assert ledger.portfolio_state(at=NOW + timedelta(seconds=41)).open_exposure_usd == 0


def test_future_dated_pending_fails_closed(tmp_path):
    path = tmp_path / "future.sqlite3"
    ledger = VNextShadowLedger(path)

    assert attempt_reservation(path, "market-future").approved

    with pytest.raises(RuntimeError):
        ledger.pending_reservations(at=NOW - timedelta(seconds=1))


def test_invalid_staleness_threshold(tmp_path):
    ledger = VNextShadowLedger(tmp_path / "invalid.sqlite3")

    with pytest.raises(ValueError):
        ledger.pending_reservations(
            at=NOW,
            stale_after_seconds=-1,
        )
