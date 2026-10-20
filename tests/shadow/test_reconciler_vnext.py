from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.ledger_vnext import (
    DecisionContext,
    VNextShadowLedger,
)
from polybtc.shadow.orchestrator_vnext import (
    OrchestratorConfig,
    VNextDecisionOrchestrator,
)
from polybtc.shadow.reconciler_vnext import (
    VNextClaimReconciler,
)
from polybtc.strategy.vnext import (
    Action,
    StrategyInput,
    VNextStrategy,
)


TARGET = datetime(2026, 10, 8, 15, 4, tzinfo=timezone.utc)

PROCESS_AT = TARGET + timedelta(seconds=2)
END = TARGET + timedelta(seconds=60)


@pytest.fixture
def prepared(tmp_path):
    journal = VNextDecisionOrchestrator(
        journal_path=tmp_path / "journal.sqlite3",
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2,
        ),
    )

    snapshot = SnapshotRecord(
        snapshot_id="reconcile-snapshot",
        condition_id="reconcile-market",
        observed_at=TARGET,
        ingested_at=TARGET,
        source_name="reconciliation_test",
        market_end_at=END,
    )

    journal.process(
        snapshots=[snapshot],
        processing_at_utc=PROCESS_AT,
    )

    token = journal.claim(
        condition_id="reconcile-market",
        horizon_seconds=60,
        at=PROCESS_AT,
    )

    assert token is not None

    ledger = VNextShadowLedger(tmp_path / "trades.sqlite3")

    reconciler = VNextClaimReconciler(
        journal=journal,
        ledger=ledger,
    )

    return journal, ledger, reconciler, token


def make_decision():
    decision = VNextStrategy().evaluate(
        StrategyInput(
            condition_id="reconcile-market",
            horizon_seconds=60,
            model_probability_yes=0.73,
            market_probability_yes=0.72,
            yes_ask=0.65,
            no_ask=0.36,
            yes_ask_size=10,
            no_ask_size=10,
            yes_book_age_ms=100,
            no_book_age_ms=100,
            reference_age_ms=100,
            tick_size=0.01,
            fee_per_share=0.01,
        )
    )

    assert decision.action == Action.BUY_YES
    return decision


def reserve(ledger, *, snapshot_id="reconcile-snapshot"):
    decision = make_decision()

    context = DecisionContext(
        decision_id="reconcile-decision-001",
        model_version="hgb3_expanded_v1",
        calibration_version="identity_v1",
        model_sha256="a" * 64,
        prediction_timestamp_utc=TARGET,
        features={
            "relative_distance_from_strike": 0.00025,
            "target_horizon_seconds": 60.0,
            "reference_return_30s": 0.00012,
        },
        model_probability_yes=0.73,
        market_probability_yes=0.72,
        observed_ask=0.65,
        selected_tick_size=0.01,
        selected_ask_depth=10,
        quote_observed_at_utc=TARGET,
        reference_source_at_utc=TARGET,
        reference_timestamp_provenance="source_verified",
        quote_timestamp_provenance="source_verified",
        fee_policy_version="research_fee_formula_v1",
        fee_rate=0.07,
        estimated_fee_per_share=0.01,
        estimated_net_ev_per_share=0.05,
        strategy_action="BUY_YES",
        snapshot_id=snapshot_id,
    )

    result = ledger.reserve(
        decision=decision,
        risk_gate=VNextRiskGate(),
        requested_size=5,
        minimum_order_size=5,
        at=PROCESS_AT,
        decision_context=context,
    )

    assert result.approved


def reconcile(prepared, token=None):
    journal, ledger, reconciler, claim = prepared

    return reconciler.reconcile(
        condition_id="reconcile-market",
        horizon_seconds=60,
        claim_token=claim if token is None else token,
        at=PROCESS_AT + timedelta(seconds=1),
    )


def test_no_entry_remains_unresolved(prepared):
    result = reconcile(prepared)

    assert result.status == "UNRESOLVED"
    assert result.reason == "no_trading_ledger_entry"
    assert prepared[0].decisions()[0]["status"] == "PROCESSING"


def test_pending_reservation_remains_unresolved(prepared):
    reserve(prepared[1])

    result = reconcile(prepared)

    assert result.reason == "pending_execution"
    assert prepared[0].decisions()[0]["status"] == "PROCESSING"


def test_fill_reconciles(prepared):
    reserve(prepared[1])

    prepared[1].record_fill(
        condition_id="reconcile-market",
        execution_price=0.66,
        filled_size=5,
        entry_fee=0.05,
        at=PROCESS_AT,
    )

    result = reconcile(prepared)

    assert result.status == "SHADOW_FILLED"

    row = prepared[0].decisions()[0]
    assert row["status"] == "SHADOW_FILLED"
    assert row["execution_price"] == pytest.approx(0.66)


def test_rejection_reconciles_to_abstention(prepared):
    reserve(prepared[1])

    prepared[1].reject_pending(
        condition_id="reconcile-market",
        reason="insufficient_execution_depth",
        at=PROCESS_AT,
    )

    result = reconcile(prepared)

    assert result.status == "ABSTAIN"
    assert result.reason == "execution_rejected"


def test_wrong_token_cannot_reconcile(prepared):
    reserve(prepared[1])

    result = reconcile(prepared, token="wrong-token")

    assert result.reason == "claim_ownership_mismatch"
    assert prepared[0].decisions()[0]["status"] == "PROCESSING"


def test_mismatched_snapshot_fails_closed(prepared):
    reserve(
        prepared[1],
        snapshot_id="different-snapshot",
    )

    with pytest.raises(RuntimeError, match="snapshot"):
        reconcile(prepared)

    assert prepared[0].decisions()[0]["status"] == "PROCESSING"


def test_reconciliation_is_idempotent(prepared):
    reserve(prepared[1])

    prepared[1].record_fill(
        condition_id="reconcile-market",
        execution_price=0.66,
        filled_size=5,
        entry_fee=0.05,
        at=PROCESS_AT,
    )

    assert reconcile(prepared).status == "SHADOW_FILLED"

    second = reconcile(prepared)

    assert second.status == "UNRESOLVED"
    assert second.reason == "decision_not_processing"


def test_restart_reconciles_existing_fill(prepared):
    journal, ledger, _, token = prepared

    reserve(ledger)

    ledger.record_fill(
        condition_id="reconcile-market",
        execution_price=0.66,
        filled_size=5,
        entry_fee=0.05,
        at=PROCESS_AT,
    )

    reopened_journal = VNextDecisionOrchestrator(
        journal_path=journal.path,
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2,
        ),
    )

    reopened_ledger = VNextShadowLedger(ledger.path)

    recovered = VNextClaimReconciler(
        journal=reopened_journal,
        ledger=reopened_ledger,
    )

    result = recovered.reconcile(
        condition_id="reconcile-market",
        horizon_seconds=60,
        claim_token=token,
        at=PROCESS_AT + timedelta(seconds=1),
    )

    assert result.status == "SHADOW_FILLED"
