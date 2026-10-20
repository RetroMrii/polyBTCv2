from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.adapter_vnext import (
    VNextEvaluationAdapter,
)
from polybtc.shadow.orchestrator_vnext import (
    OrchestratorConfig,
    VNextDecisionOrchestrator,
)
from polybtc.shadow.runner_vnext import (
    VerifiedSources,
    VNextShadowRunner,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data/models/main/hgb3_expanded_v2.joblib"

TARGET = datetime(2026, 10, 8, 15, 4, tzinfo=timezone.utc)
END = TARGET + timedelta(seconds=60)
NOW = TARGET + timedelta(seconds=2)


def make_snapshot(
    *,
    snapshot_id,
    observed_at,
    ingested_at,
    reference_price=40010.0,
):
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        condition_id="adapter-market",
        observed_at=observed_at,
        ingested_at=ingested_at,
        source_name="verified_test_collector",
        reference_price=reference_price,
        reference_timestamp=observed_at,
        strike=40000.0,
        market_end_at=END,
        yes_bid=0.65,
        yes_ask=0.65,
        # Keep the fixture within the unchanged 5% model/market gap for v2.
        no_bid=0.06,
        no_ask=0.08,
        yes_ask_size=10,
        no_ask_size=10,
        yes_book_timestamp=observed_at,
        no_book_timestamp=observed_at,
        yes_tick_size=0.01,
        no_tick_size=0.01,
        yes_min_order_size=5,
        no_min_order_size=5,
    )


@pytest.fixture
def setup_adapter(tmp_path):
    prediction = make_snapshot(
        snapshot_id="prediction-001",
        observed_at=TARGET,
        ingested_at=TARGET,
    )

    execution = make_snapshot(
        snapshot_id="execution-001",
        observed_at=NOW,
        ingested_at=NOW,
    )

    anchor_at = TARGET - timedelta(seconds=30)
    anchor = make_snapshot(
        snapshot_id="anchor-001",
        observed_at=anchor_at,
        ingested_at=anchor_at,
        reference_price=40010.0 / 1.00012,
    )

    journal = VNextDecisionOrchestrator(
        journal_path=tmp_path / "journal.sqlite3",
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2,
        ),
    )

    selections = journal.process(
        snapshots=[anchor, prediction, execution],
        processing_at_utc=NOW,
    )

    assert len(selections) == 1
    assert selections[0].status == ("AWAITING_EXECUTION_ADAPTER")

    runner = VNextShadowRunner(
        model_path=MODEL,
        ledger_path=tmp_path / "trading.sqlite3",
    )

    adapter = VNextEvaluationAdapter(
        journal=journal,
        runner=runner,
    )

    return (
        adapter,
        journal,
        runner,
        prediction,
        execution,
        [anchor, prediction],
    )


def evaluate(
    setup_adapter,
    *,
    execution=True,
    verified=True,
):
    adapter, journal, runner, prediction, quote, history = setup_adapter

    sources = VerifiedSources(
        reference_source_verified=verified,
        yes_book_source_verified=verified,
        no_book_source_verified=verified,
        fee_policy_verified=verified,
    )

    return adapter.evaluate(
        condition_id="adapter-market",
        horizon_seconds=60,
        prediction_snapshot=prediction,
        execution_snapshot=quote if execution else None,
        history=history,
        at=NOW,
        sources=sources,
        fee_rate=0.07,
    )


def test_missing_execution_snapshot_abstains(setup_adapter):
    result = evaluate(
        setup_adapter,
        execution=False,
    )

    assert result.status == "ABSTAIN"
    assert result.reason == "missing_execution_snapshot"

    assert setup_adapter[1].decisions()[0]["status"] == ("ABSTAIN")


def test_unverified_sources_abstain(setup_adapter):
    result = evaluate(
        setup_adapter,
        verified=False,
    )

    assert result.status == "ABSTAIN"
    assert result.reason == ("unverified_input_provenance")


def test_delayed_shadow_execution_reconciles(setup_adapter):
    result = evaluate(setup_adapter)

    assert result.status == "SHADOW_FILLED"

    row = setup_adapter[1].decisions()[0]

    assert row["status"] == "SHADOW_FILLED"
    assert row["snapshot_id"] == "prediction-001"
    assert row["execution_price"] == pytest.approx(0.66)

    ledger = setup_adapter[2].ledger
    context = ledger.decision_context("adapter-market")

    assert context["snapshot_id"] == "prediction-001"
    assert datetime.fromisoformat(context["prediction_timestamp_utc"]) == TARGET


def test_duplicate_evaluation_is_rejected(setup_adapter):
    first = evaluate(setup_adapter)
    assert first.status == "SHADOW_FILLED"

    second = evaluate(setup_adapter)

    assert second.status == "UNRESOLVED"
    assert second.reason == "journal_not_awaiting"

    assert len(setup_adapter[2].ledger.positions()) == 1


def test_future_prediction_anchor_is_not_used(setup_adapter):
    adapter, journal, runner, prediction, execution, history = setup_adapter

    late_anchor = replace(
        history[0],
        ingested_at=TARGET + timedelta(seconds=1),
    )

    result = adapter.evaluate(
        condition_id="adapter-market",
        horizon_seconds=60,
        prediction_snapshot=prediction,
        execution_snapshot=execution,
        history=[late_anchor],
        at=NOW,
        sources=VerifiedSources(True, True, True, True),
        fee_rate=0.07,
    )

    assert result.status == "ABSTAIN"
    assert result.reason == "missing_reference_return_30s"

    assert runner.ledger.positions() == []
