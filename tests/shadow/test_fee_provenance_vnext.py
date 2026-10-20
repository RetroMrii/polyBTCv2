"""E8 offline evidence integration using the user-selected main v2 artifact."""
import json
import sqlite3
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.shadow import test_stream_driver_vnext as stream
from polybtc.data.fee_policy_cache_vnext import (
    CACHE_VERSION, CachedFeePolicy, FeeCacheError, VNextFeePolicyCache,
)
from polybtc.data.polymarket_fees import FEE_PROVIDER_VERSION, PolymarketFeePolicy
from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.shadow.orchestrator_vnext import VNextDecisionOrchestrator
from polybtc.shadow.runner_vnext import VerifiedSources


MARKET = "0x" + "a" * 64
OTHER = "0x" + "b" * 64
MODEL = Path(__file__).resolve().parents[2] / "data/models/main/hgb3_expanded_v2.joblib"


def policy(**changes):
    return replace(CachedFeePolicy(
        condition_id=MARKET, fee_rate=0.07, fee_exponent=1, fee_flag=True,
        source=f"https://clob.polymarket.com/clob-markets/{MARKET}",
        provider_version=FEE_PROVIDER_VERSION,
        retrieved_at_utc=stream.NOW - timedelta(seconds=5),
        cache_version=CACHE_VERSION,
    ), **changes)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "MODEL", MODEL)
    # Any accidental provider/network call during processing fails the test.
    monkeypatch.setattr(
        "polybtc.data.fee_policy_cache_vnext.fetch_market_fee_policy",
        Mock(side_effect=AssertionError("Decision processing must be offline")),
    )
    driver, journal, runner = stream.build_driver(tmp_path)
    rows = [replace(row, condition_id=MARKET) for row in stream.sample_rows()]
    return driver, journal, runner, rows


def attach_cache(driver, tmp_path, evidence):
    cache = VNextFeePolicyCache(tmp_path / "fees.sqlite3")
    with sqlite3.connect(cache.path) as conn:
        conn.execute(
            "INSERT INTO fee_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (evidence.condition_id, evidence.fee_rate, evidence.fee_exponent,
             int(evidence.fee_flag), evidence.source, evidence.provider_version,
             evidence.retrieved_at_utc.isoformat(), evidence.cache_version),
        )
    driver.fee_cache = cache
    return cache


def test_exact_evidence_survives_refresh_restart_and_is_immutable(setup, tmp_path, monkeypatch):
    driver, journal, runner, rows = setup
    evidence = policy()
    cache = attach_cache(driver, tmp_path, evidence)
    lookup = Mock(wraps=cache.get)
    monkeypatch.setattr(cache, "get", lookup)
    result = stream.run(driver, rows)[0]
    assert result.status == "SHADOW_FILLED"
    assert runner.ledger.positions()[0].execution_price == pytest.approx(0.66)
    lookup.assert_called_once_with(MARKET, at=stream.NOW)
    original = runner.ledger.decision_context(MARKET)
    assert {k: original[k] for k in evidence.provenance()} == evidence.provenance()
    assert json.loads(journal.decisions()[0]["fee_provenance_json"]) == evidence.provenance()

    # Exercise real cache refresh with a deterministic provider response.
    refreshed = replace(evidence, retrieved_at_utc=stream.NOW)
    monkeypatch.setattr(
        "polybtc.data.fee_policy_cache_vnext.fetch_market_fee_policy",
        lambda market: PolymarketFeePolicy(
            **{k: getattr(refreshed, k) for k in (
                "condition_id", "fee_rate", "fee_exponent", "fee_flag", "source",
                "provider_version", "retrieved_at_utc")},
            descriptor_verified=True, research_formula_compatible=True,
        ),
    )
    cache.refresh(MARKET, at=stream.NOW)
    assert VNextShadowLedger(runner.ledger.path).decision_context(MARKET) == original
    reopened = VNextDecisionOrchestrator(journal_path=journal.path, config=journal.config)
    assert json.loads(reopened.decisions()[0]["fee_provenance_json"]) == evidence.provenance()
    assert stream.run(driver, rows) == []
    assert len(runner.ledger.positions()) == 1
    with pytest.raises(FrozenInstanceError):
        evidence.fee_rate = 0.08
    for database, statement in (
        (journal.path, "UPDATE decisions SET fee_provenance_json=NULL"),
        (journal.path, "DELETE FROM decisions"),
        (runner.ledger.path, "UPDATE entry_decision_context SET context_json='{}'"),
    ):
        with sqlite3.connect(database) as conn, pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)


def test_fee_evidence_persists_for_abstention(setup, tmp_path):
    driver, journal, runner, rows = setup
    attach_cache(driver, tmp_path, policy())
    result = stream.run(driver, rows[:-1])[0]
    assert result.reason == "missing_execution_snapshot"
    assert runner.ledger.positions() == []
    assert json.loads(journal.decisions()[0]["fee_provenance_json"]) == policy().provenance()


@pytest.mark.parametrize("changes", [
    {"condition_id": OTHER}, {"source": "unknown"}, {"provider_version": "unknown"},
    {"cache_version": "unknown"}, {"fee_rate": float("nan")},
    {"fee_exponent": 2}, {"fee_flag": False},
    {"retrieved_at_utc": stream.NOW + timedelta(seconds=1)},
    {"retrieved_at_utc": stream.NOW - timedelta(days=2)},
    {"retrieved_at_utc": stream.NOW.replace(tzinfo=None)},
])
def test_invalid_evidence_blocks_adapter_and_runner(setup, changes):
    driver, journal, runner, rows = setup
    bad = policy(**changes)
    journal.process(snapshots=rows, processing_at_utc=stream.NOW)
    result = driver.adapter.evaluate(
        condition_id=MARKET, horizon_seconds=60, prediction_snapshot=rows[1],
        execution_snapshot=rows[2], history=rows[:2], at=stream.NOW,
        sources=VerifiedSources(True, True, True, True), fee_rate=0.07,
        fee_policy=bad, require_fee_provenance=True,
    )
    assert result.reason == "invalid_fee_provenance"
    direct = runner.evaluate(
        snapshot=rows[1], execution_snapshot=rows[2], history=rows[:2],
        horizon_seconds=60, decision_at_utc=stream.NOW,
        sources=VerifiedSources(True, True, True, True), fee_rate=0.07,
        fee_policy=bad, require_fee_provenance=True,
    )
    assert direct.reason == "invalid_fee_provenance"
    assert runner.ledger.positions() == []


@pytest.mark.parametrize("missing,rate", [(True, 0.07), (False, 0.08)])
def test_required_missing_or_rate_mismatched_evidence_blocks(setup, missing, rate):
    driver, journal, runner, rows = setup
    journal.process(snapshots=rows, processing_at_utc=stream.NOW)
    result = driver.adapter.evaluate(
        condition_id=MARKET, horizon_seconds=60, prediction_snapshot=rows[1],
        execution_snapshot=rows[2], history=rows[:2], at=stream.NOW,
        sources=VerifiedSources(True, True, True, True), fee_rate=rate,
        fee_policy=None if missing else policy(), require_fee_provenance=True,
    )
    assert result.reason == ("missing_fee_provenance" if missing else "invalid_fee_provenance")
    assert runner.ledger.positions() == []


@pytest.mark.parametrize("failure", ["missing", "expired", "conflict"])
def test_cache_failure_never_falls_back_to_caller_rate(setup, tmp_path, failure):
    driver, journal, runner, rows = setup
    cache = attach_cache(driver, tmp_path, policy())
    if failure == "missing":
        with sqlite3.connect(cache.path) as conn:
            conn.execute("DELETE FROM fee_policies")
    elif failure == "expired":
        with sqlite3.connect(cache.path) as conn:
            conn.execute("UPDATE fee_policies SET retrieved_at_utc=?", (
                (stream.NOW - timedelta(days=2)).isoformat(),))
    else:
        cache.get = Mock(side_effect=FeeCacheError("Conflicting evidence"))
    result = stream.run(driver, rows)[0]
    assert result.status == "ABSTAIN"
    assert runner.ledger.positions() == []
    assert journal.decisions()[0]["fee_provenance_json"] is None


def test_legacy_calls_remain_unknown_and_do_not_gain_evidence(setup):
    driver, journal, runner, rows = setup
    assert stream.run(driver, rows)[0].status == "SHADOW_FILLED"
    assert journal.decisions()[0]["fee_provenance_json"] is None
    assert runner.ledger.decision_context(MARKET).get("fee_policy_source") is None
    with sqlite3.connect(journal.path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decisions SET fee_provenance_json='{}'")


def test_v3_journal_upgrade_preserves_legacy_decision(setup):
    driver, journal, runner, rows = setup
    assert stream.run(driver, rows)[0].status == "SHADOW_FILLED"
    original = journal.decisions()[0]
    with sqlite3.connect(journal.path) as conn:
        conn.execute("DROP TRIGGER trg_fee_provenance_no_update")
        conn.execute("DROP TRIGGER trg_fee_provenance_no_delete")
        conn.execute("ALTER TABLE decisions DROP COLUMN fee_provenance_json")
        conn.execute("PRAGMA user_version=3")
    reopened = VNextDecisionOrchestrator(journal_path=journal.path, config=journal.config)
    assert reopened.decisions()[0] == original
    with sqlite3.connect(journal.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5


def test_evidence_does_not_enable_sources_or_bypass_kill_switch(setup, tmp_path):
    driver, journal, runner, rows = setup
    attach_cache(driver, tmp_path, policy())
    result = driver.process(
        snapshots=rows, at=stream.NOW,
        sources=VerifiedSources(False, False, False, False),
        fee_rate=None, kill_switch=True,
    )[0]
    assert result.reason == "unverified_input_provenance"
    assert runner.ledger.positions() == []
    assert json.loads(journal.decisions()[0]["fee_provenance_json"]) == policy().provenance()
