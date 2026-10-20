from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.runner_vnext import (
    VerifiedSources,
    VNextShadowRunner,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data/models/main/hgb3_expanded_v2.joblib"

NOW = datetime(2026, 10, 8, 15, 4, 0, tzinfo=timezone.utc)


def snapshot(
    *,
    observed_at=NOW,
    ingested_at=NOW,
    reference_price=40010.0,
    snapshot_id="snapshot-current",
):
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        condition_id="integration-market",
        observed_at=observed_at,
        source_name="integration_test",
        ingested_at=ingested_at,
        reference_price=reference_price,
        reference_timestamp=observed_at,
        strike=40000.0,
        market_end_at=NOW + timedelta(seconds=60),
        yes_bid=0.65,
        yes_ask=0.65,
        # Keep the fixture within the unchanged 5% model/market gap for v2.
        no_bid=0.06,
        no_ask=0.08,
        yes_ask_size=10.0,
        no_ask_size=10.0,
        yes_book_timestamp=observed_at,
        no_book_timestamp=observed_at,
        yes_tick_size=0.01,
        no_tick_size=0.01,
        yes_min_order_size=5.0,
        no_min_order_size=5.0,
    )


def valid_history():
    anchor_time = NOW - timedelta(seconds=30)

    anchor_price = 40010.0 / 1.00012

    return [
        snapshot(
            observed_at=anchor_time,
            ingested_at=anchor_time,
            reference_price=anchor_price,
            snapshot_id="snapshot-anchor",
        )
    ]


def sources(verified=True):
    return VerifiedSources(
        reference_source_verified=verified,
        yes_book_source_verified=verified,
        no_book_source_verified=verified,
        fee_policy_verified=verified,
    )


@pytest.fixture
def runner(tmp_path):
    return VNextShadowRunner(
        model_path=MODEL,
        ledger_path=tmp_path / "runner.sqlite3",
    )


def evaluate(
    runner,
    *,
    current=None,
    history=None,
    verified=True,
    fee_rate=0.07,
):
    return runner.evaluate(
        snapshot=current or snapshot(),
        history=valid_history() if history is None else history,
        horizon_seconds=60,
        decision_at_utc=NOW,
        sources=sources(verified),
        fee_rate=fee_rate,
    )


def test_end_to_end_shadow_fill(runner):
    result = evaluate(runner)

    assert result.status == "SHADOW_FILLED"
    assert result.execution_price == pytest.approx(0.66)

    positions = runner.ledger.positions()

    assert len(positions) == 1
    assert positions[0].status == "FILLED"

    context = runner.ledger.decision_context("integration-market")

    assert context is not None
    assert context["model_version"] == "hgb3_expanded_v2"
    assert context["calibration_version"] == "identity_v1"

    assert context["features"]["reference_return_30s"] == pytest.approx(0.00012)

    assert context["model_probability_yes"] == (
        pytest.approx(0.9241447912394446, abs=1e-8)
    )


def test_unverified_provenance_abstains(runner):
    result = evaluate(runner, verified=False)

    assert result.status == "ABSTAIN"
    assert result.reason == "unverified_input_provenance"
    assert runner.ledger.positions() == []


def test_v2_preserves_probability_gap_gate(runner):
    # The old v1 fixture is now outside the fixed gap under the selected v2 model.
    result = evaluate(runner, current=replace(snapshot(), no_bid=0.10, no_ask=0.12))
    assert result.reason == "probability_gap_too_large"
    assert runner.ledger.positions() == []


def test_missing_history_abstains(runner):
    result = evaluate(runner, history=[])

    assert result.reason == "missing_reference_return_30s"
    assert runner.ledger.positions() == []


def test_future_ingested_history_not_used(runner):
    future_history = [
        replace(
            valid_history()[0],
            ingested_at=NOW + timedelta(seconds=1),
        )
    ]

    result = evaluate(
        runner,
        history=future_history,
    )

    assert result.reason == "missing_reference_return_30s"


def test_stale_books_abstain(runner):
    current = replace(
        snapshot(),
        yes_book_timestamp=NOW - timedelta(seconds=2),
    )

    result = evaluate(runner, current=current)

    assert result.reason == "stale_market_books"


def test_missing_fee_rate_abstains(runner):
    result = evaluate(runner, fee_rate=None)

    assert result.reason == "missing_or_invalid_fee_rate"


def test_restart_prevents_second_entry(runner):
    first = evaluate(runner)
    assert first.status == "SHADOW_FILLED"

    reopened = VNextShadowRunner(
        model_path=MODEL,
        ledger_path=runner.ledger.path,
    )

    second = evaluate(reopened)

    assert second.status == "ABSTAIN"
    assert second.reason == "risk:market_already_reserved"
    assert len(reopened.ledger.positions()) == 1


def test_decision_context_and_events_persist(runner):
    result = evaluate(runner)

    assert result.status == "SHADOW_FILLED"

    events = runner.ledger.events("integration-market")

    assert [event["event_type"] for event in events] == [
        "ENTRY_RESERVED",
        "ENTRY_FILLED",
    ]

    context = runner.ledger.decision_context("integration-market")

    assert context["fee_policy_version"] == ("research_fee_formula_v1")
    assert context["strategy_action"] == "BUY_YES"


def test_elapsed_inference_time_cannot_preserve_fresh_book(runner):
    from unittest.mock import Mock
    runner.clock = lambda: NOW + timedelta(milliseconds=501)
    original = runner.strategy.evaluate
    runner.strategy.evaluate = Mock(wraps=original)
    result = runner.evaluate(snapshot=snapshot(),execution_snapshot=snapshot(),history=valid_history(),
        horizon_seconds=60,decision_at_utc=NOW,sources=sources(),fee_rate=.07)
    assert result.reason == "stale_market_books"
    runner.strategy.evaluate.assert_not_called()
    assert runner.ledger.positions() == []


def test_elapsed_reservation_time_is_rechecked_by_executor(runner):
    ticks = iter([NOW, NOW + timedelta(milliseconds=501)])
    runner.clock = lambda: next(ticks)
    result = evaluate(runner)
    assert result.reason == "execution:stale_execution_quote"
    assert runner.ledger.positions()[0].status == "REJECTED"


def test_clock_rollback_after_reservation_never_fills(runner):
    ticks = iter([NOW, NOW - timedelta(milliseconds=1)])
    runner.clock = lambda: next(ticks)
    with pytest.raises(RuntimeError, match="clock moved backwards"):
        evaluate(runner)
    assert runner.ledger.positions()[0].status == "PENDING"

@pytest.mark.parametrize('age,reason', [(2500, None), (3000, None), (3000.001, 'stale_reference'), (-1, 'future_source_timestamp')])
def test_runtime_reference_contract_reaches_strategy_and_executor(runner, age, reason):
    from polybtc.shadow.runner_vnext import MAX_REFERENCE_AGE_MS, MAX_BOOK_AGE_MS
    from polybtc.shadow.source_verification_vnext import MAX_REFERENCE_AGE_MS as verifier_limit
    assert runner.strategy.config.max_reference_age_ms == runner.executor.config.max_reference_age_ms == verifier_limit == MAX_REFERENCE_AGE_MS == 3000
    assert runner.strategy.config.max_book_age_ms == runner.executor.config.max_book_age_ms == MAX_BOOK_AGE_MS == 500
    row = replace(snapshot(), reference_timestamp=NOW - timedelta(milliseconds=age))
    result = evaluate(runner, current=row)
    if reason:
        # Future prediction observations are rejected before the execution gate.
        assert result.reason == ('noncausal_prediction_reference' if age < 0 else reason)
        assert not runner.ledger.positions()
    else:
        assert result.status == 'SHADOW_FILLED'


def test_extended_reference_allowance_does_not_extend_books(runner):
    row = replace(snapshot(), reference_timestamp=NOW-timedelta(milliseconds=2500),
                  yes_book_timestamp=NOW-timedelta(milliseconds=501))
    assert evaluate(runner, current=row).reason == 'stale_market_books'
    assert not runner.ledger.positions()
