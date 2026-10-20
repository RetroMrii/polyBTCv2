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
from polybtc.shadow.stream_driver_vnext import (
    VNextSnapshotStreamDriver,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "data/models/main/hgb3_expanded_v2.joblib"

TARGET = datetime(2026, 10, 8, 15, 4, tzinfo=timezone.utc)
END = TARGET + timedelta(seconds=60)
NOW = TARGET + timedelta(seconds=2)


def snapshot(
    snapshot_id,
    observed_at,
    reference_price=40010.0,
):
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        condition_id="stream-market",
        observed_at=observed_at,
        ingested_at=observed_at,
        source_name="stream_test",
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


def sample_rows(include_execution=True):
    anchor = snapshot(
        "anchor",
        TARGET - timedelta(seconds=30),
        40010.0 / 1.00012,
    )
    prediction = snapshot(
        "prediction",
        TARGET,
    )
    execution = snapshot(
        "execution",
        NOW,
    )

    return (
        [anchor, prediction, execution] if include_execution else [anchor, prediction]
    )


def build_driver(tmp_path):
    journal = VNextDecisionOrchestrator(
        journal_path=tmp_path / "journal.sqlite3",
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2.0,
        ),
    )

    runner = VNextShadowRunner(
        model_path=MODEL,
        ledger_path=tmp_path / "trades.sqlite3",
    )

    adapter = VNextEvaluationAdapter(
        journal=journal,
        runner=runner,
    )

    driver = VNextSnapshotStreamDriver(
        journal=journal,
        adapter=adapter,
    )

    return driver, journal, runner


def run(
    driver,
    rows,
    *,
    at=NOW,
    verified=True,
):
    return driver.process(
        snapshots=rows,
        at=at,
        sources=VerifiedSources(
            reference_source_verified=verified,
            yes_book_source_verified=verified,
            no_book_source_verified=verified,
            fee_policy_verified=verified,
        ),
        fee_rate=0.07,
    )


def test_driver_reconciles_shadow_fill(tmp_path):
    driver, journal, runner = build_driver(tmp_path)

    results = run(driver, sample_rows())

    assert len(results) == 1
    assert results[0].status == "SHADOW_FILLED"
    assert results[0].prediction_snapshot_id == "prediction"
    assert results[0].execution_snapshot_id == "execution"

    assert journal.decisions()[0]["status"] == "SHADOW_FILLED"
    assert len(runner.ledger.positions()) == 1


def test_missing_execution_quote_abstains(tmp_path):
    driver, journal, runner = build_driver(tmp_path)

    results = run(
        driver,
        sample_rows(include_execution=False),
    )

    assert len(results) == 1
    assert results[0].status == "ABSTAIN"
    assert results[0].reason == "missing_execution_snapshot"
    assert runner.ledger.positions() == []


def test_unverified_sources_abstain(tmp_path):
    driver, journal, runner = build_driver(tmp_path)

    results = run(
        driver,
        sample_rows(),
        verified=False,
    )

    assert results[0].status == "ABSTAIN"
    assert results[0].reason == ("unverified_input_provenance")
    assert runner.ledger.positions() == []


def test_no_early_horizon_finalization(tmp_path):
    driver, journal, runner = build_driver(tmp_path)

    results = run(
        driver,
        sample_rows(),
        at=TARGET + timedelta(seconds=1),
    )

    assert results == []
    assert journal.decisions() == []


def test_restart_does_not_duplicate_fill(tmp_path):
    driver, journal, runner = build_driver(tmp_path)
    rows = sample_rows()

    first = run(driver, rows)
    assert first[0].status == "SHADOW_FILLED"

    reopened, new_journal, new_runner = build_driver(tmp_path)

    second = run(reopened, rows)

    assert second == []
    assert len(new_journal.decisions()) == 1
    assert len(new_runner.ledger.positions()) == 1


def test_stale_execution_observation_abstains(tmp_path):
    driver, journal, runner = build_driver(tmp_path)

    rows = sample_rows()
    results = run(
        driver,
        rows,
        at=NOW + timedelta(seconds=3),
    )

    assert results[0].status == "ABSTAIN"
    assert results[0].reason == "missing_execution_snapshot"
    assert runner.ledger.positions() == []
