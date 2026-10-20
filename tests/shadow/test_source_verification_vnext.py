import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.shadow import test_fee_provenance_vnext as fees
from tests.shadow import test_stream_driver_vnext as stream
from polybtc.shadow.orchestrator_vnext import VNextDecisionOrchestrator
from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.source_verification_vnext import (
    SnapshotSourceEvidence, VNextSourceVerificationAdapter,
)


def snapshots():
    return [replace(row, condition_id=fees.MARKET, yes_token_id="101", no_token_id="202")
            for row in stream.sample_rows()]


def evidence(row):
    # Synthetic attestations exercise the trust boundary; never production proof.
    return SnapshotSourceEvidence(
        evidence_id="fixture:" + row.snapshot_id, producer="test-acquisition",
        snapshot=row, captured_at_utc=row.observed_at,
        reference_endpoint="wss://ws-live-data.polymarket.com",
        reference_topic="crypto_prices_twap_sixty", reference_symbol="btc/usd",
        reference_window_seconds=60, strike_semantics_verified=True,
        metadata_endpoint="https://gamma-api.polymarket.com",
        metadata_condition_id=fees.MARKET,
        outcome_tokens=(("Up", "101"), ("Down", "202")),
        yes_book_endpoint="https://clob.polymarket.com/book",
        yes_book_condition_id=fees.MARKET, yes_book_asset_id="101",
        no_book_endpoint="https://clob.polymarket.com/book",
        no_book_condition_id=fees.MARKET, no_book_asset_id="202",
    )


def verifier(rows, overrides=None, trusted=True):
    records = {row.snapshot_id: evidence(row) for row in rows}
    records.update(overrides or {})
    return VNextSourceVerificationAdapter(
        trusted_producers=frozenset({"test-acquisition"}) if trusted else frozenset(),
        evidence=records,
    )


def verify(adapter, rows, **kwargs):
    return adapter.verify(
        prediction=rows[1], execution=rows[2], history=rows[:2],
        prediction_at=stream.TARGET, at=stream.NOW,
        fee_policy=kwargs.get("fee_policy", fees.policy()), fee_rate=0.07,
    )


def test_timestamps_and_collector_labels_are_not_verification():
    rows = [replace(row, source_name="polybtc_v1_1_telemetry",
                    collector_version="polybtc_vnext_local_v1") for row in snapshots()]
    result = verify(VNextSourceVerificationAdapter(), rows)
    assert result.sources == VerifiedSources(False, False, False, False)
    assert result.fee_descriptor_verified is True
    assert "fee_applicability_and_accounting_unverified" in result.reasons


def test_explicit_trusted_evidence_verifies_sources_independently():
    rows = snapshots()
    result = verify(verifier(rows), rows)
    assert result.sources == VerifiedSources(True, True, True, False)
    assert verify(verifier(rows, trusted=False), rows).sources == VerifiedSources(False, False, False, False)


@pytest.mark.parametrize("field,value,expected", [
    ("yes_book_asset_id", "202", (True, False, True, False)),
    ("no_book_condition_id", fees.OTHER, (True, True, False, False)),
    ("reference_symbol", "eth/usd", (False, True, True, False)),
    ("reference_window_seconds", 30, (False, True, True, False)),
    ("strike_semantics_verified", False, (False, True, True, False)),
    ("outcome_tokens", (), (True, False, False, False)),
    ("outcome_tokens", (("Up", "202"), ("Down", "101")), (True, False, False, False)),
])
def test_bad_upstream_evidence_rejects_only_relevant_claim(field, value, expected):
    rows = snapshots()
    ev = replace(evidence(rows[2]), **{field: value})
    result = verify(verifier(rows, {rows[2].snapshot_id: ev}), rows)
    assert result.sources == VerifiedSources(*expected)


@pytest.mark.parametrize("field,delta,expected", [
    ("yes_book_timestamp", -0.501, (True, False, True, False)),
    ("no_book_timestamp", 0.001, (True, True, False, False)),
    ("reference_timestamp", -3.001, (False, True, True, False)),
])
def test_freshness_uses_source_time_not_csv_time(field, delta, expected):
    rows = snapshots()
    rows[2] = replace(rows[2], **{field: stream.NOW + timedelta(seconds=delta)})
    assert verify(verifier(rows), rows).sources == VerifiedSources(*expected)


def test_snapshot_tampering_and_unattested_history_block():
    rows = snapshots()
    adapter = verifier(rows)
    rows[2] = replace(rows[2], yes_ask=0.67)
    assert verify(adapter, rows).sources == VerifiedSources(False, False, False, False)
    rows = snapshots()
    adapter = verifier(rows, {rows[0].snapshot_id: None})
    assert verify(adapter, rows).sources == VerifiedSources(False, True, True, False)


def test_execution_token_swap_and_stale_fee_block():
    rows = snapshots()
    rows[2] = replace(rows[2], yes_token_id="202", no_token_id="101")
    result = verify(verifier(rows), rows, fee_policy=fees.policy(
        retrieved_at_utc=stream.NOW - timedelta(days=2)))
    assert result.sources == VerifiedSources(False, False, False, False)
    assert not result.fee_descriptor_verified


def test_driver_persists_checks_offline_and_cannot_override_them(tmp_path, monkeypatch):
    rows = snapshots()
    driver, journal, runner = stream.build_driver(tmp_path)
    driver.source_verifier = verifier(rows)
    cache = fees.attach_cache(driver, tmp_path, fees.policy())
    lookup = Mock(wraps=cache.get)
    monkeypatch.setattr(cache, "get", lookup)
    monkeypatch.setattr("polybtc.data.fee_policy_cache_vnext.fetch_market_fee_policy",
                        Mock(side_effect=AssertionError("Network in decision loop")))
    results = driver.process(
        snapshots=rows, at=stream.NOW, sources=VerifiedSources(True, True, True, True),
        fee_rate=0.07, kill_switch=True,
    )
    assert results[0].status == "ABSTAIN"
    assert runner.ledger.positions() == []
    lookup.assert_called_once_with(fees.MARKET, at=stream.NOW)
    row = journal.decisions()[0]
    stored = json.loads(row["source_verification_json"])
    assert stored["fee_descriptor_verified"] is True
    assert stored["fee_policy_verified"] is False
    assert stored["reference_source_verified"] is True
    assert stored["evidence_ids"] == ["fixture:anchor", "fixture:execution", "fixture:prediction"]
    assert json.loads(row["fee_provenance_json"]) == fees.policy().provenance()
    reopened = VNextDecisionOrchestrator(journal_path=journal.path, config=journal.config)
    assert reopened.decisions()[0]["source_verification_json"] == row["source_verification_json"]
    with sqlite3.connect(journal.path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decisions SET source_verification_json='{}'")


def test_cache_does_not_promote_fee_flag_on_legacy_path(tmp_path):
    driver, journal, runner = stream.build_driver(tmp_path)
    fees.attach_cache(driver, tmp_path, fees.policy())
    result = driver.process(
        snapshots=snapshots(), at=stream.NOW,
        sources=VerifiedSources(True, True, True, False), fee_rate=None,
        kill_switch=True,
    )[0]
    assert result.reason == "unverified_input_provenance"
    assert runner.ledger.positions() == []


def test_runtime_defaults_to_v2_and_closed_verification(tmp_path, monkeypatch):
    from scripts.operations import run_vnext_shadow
    csv = tmp_path / "input.csv"
    csv.write_text("observed_at\n", encoding="utf-8")
    assert run_vnext_shadow.DEFAULT_MODEL_PATH.name == "hgb3_expanded_v2.joblib"
    runtime = run_vnext_shadow.build_runtime(
        csv, tmp_path / "state", run_vnext_shadow.DEFAULT_MODEL_PATH,
    )
    assert runtime.config.kill_switch is True
    assert runtime.config.interval_seconds == 0.25
    assert runtime.sources == VerifiedSources(False, False, False, False)
    driver = runtime.service.driver
    assert driver.adapter.runner.model.model_version == "hgb3_expanded_v2"
    assert driver.adapter.runner.model.model_sha256 == "42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4"
    assert isinstance(driver.source_verifier, VNextSourceVerificationAdapter)


def test_explicit_refresh_cli_uses_cache_refresh_once(tmp_path, monkeypatch, capsys):
    from scripts.operations import refresh_vnext_fees
    refresh = Mock(return_value=fees.policy())
    monkeypatch.setattr(refresh_vnext_fees.VNextFeePolicyCache, "refresh", refresh)
    monkeypatch.setattr("sys.argv", ["refresh_vnext_fees", "--fee-cache", str(tmp_path / "fees.db"),
                                    "--condition-id", fees.MARKET, "--condition-id", fees.MARKET])
    refresh_vnext_fees.main()
    refresh.assert_called_once_with(fees.MARKET)
    assert json.loads(capsys.readouterr().out) == fees.policy().provenance()


def test_v4_migration_preserves_fee_evidence_without_source_backfill(tmp_path):
    driver, journal, runner = stream.build_driver(tmp_path)
    fees.attach_cache(driver, tmp_path, fees.policy())
    assert stream.run(driver, snapshots())[0].status == "SHADOW_FILLED"
    original = journal.decisions()[0]
    with sqlite3.connect(journal.path) as conn:
        conn.execute("DROP TRIGGER trg_source_verification_no_update")
        conn.execute("DROP TRIGGER trg_source_verification_no_delete")
        conn.execute("ALTER TABLE decisions DROP COLUMN source_verification_json")
        conn.execute("PRAGMA user_version=4")
    reopened = VNextDecisionOrchestrator(journal_path=journal.path, config=journal.config)
    assert reopened.decisions()[0] == original
    assert reopened.decisions()[0]["source_verification_json"] is None


def test_claim_rejects_verification_for_different_snapshot(tmp_path):
    driver, journal, runner = stream.build_driver(tmp_path)
    rows = snapshots()
    journal.process(snapshots=rows, processing_at_utc=stream.NOW)
    result = replace(verify(verifier(rows), rows), prediction_snapshot_id="wrong")
    assert journal.claim(condition_id=fees.MARKET, horizon_seconds=60,
                         at=stream.NOW, source_verification=result) is None
    assert journal.decisions()[0]["status"] == "AWAITING_EXECUTION_ADAPTER"


@pytest.mark.parametrize("source,limit", [("reference", 3000), ("yes_book", 500), ("no_book", 500)])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_diagnostic_freshness_boundary_preserves_gate(source, limit, offset):
    rows = snapshots()
    age = limit + offset
    rows[2] = replace(rows[2], **{source + "_timestamp": stream.NOW - timedelta(milliseconds=age)})
    result = verify(verifier(rows), rows)
    assert result.provenance()['reference_max_age_ms'] == 3000
    assert result.provenance()['book_max_age_ms'] == 500
    assert getattr(result.sources, source + "_source_verified") == (offset <= 0)
    failures = [d for d in result.diagnostics if d.role == "execution" and d.source == source]
    if offset <= 0:
        assert failures == []
    else:
        assert len(failures) == 1
        d = failures[0]
        assert d.reason == "stale_source"
        assert d.age_ms == pytest.approx(age)
        assert d.limit_ms == limit
        assert d.snapshot_id == rows[2].snapshot_id
        assert d.evaluated_at_utc == stream.NOW.isoformat()
        assert d.source_timestamp == getattr(rows[2], source + "_timestamp").isoformat()


def test_future_time_missing_evidence_and_tampering_are_distinct():
    rows = snapshots()
    rows[2] = replace(rows[2], yes_book_timestamp=stream.NOW + timedelta(milliseconds=1))
    result = verify(verifier(rows), rows)
    diagnostic = next(d for d in result.diagnostics if d.source == "yes_book")
    assert diagnostic.reason == "future_source_timestamp" and diagnostic.age_ms == -1
    rows = snapshots()
    missing = verify(verifier(rows, {rows[0].snapshot_id: None}), rows)
    assert any(d.role == "history" and d.reason == "missing_evidence" for d in missing.diagnostics)
    adapter = verifier(rows)
    rows[2] = replace(rows[2], yes_ask=0.67)
    tampered = verify(adapter, rows)
    assert any(d.reason == "snapshot_binding_mismatch" for d in tampered.diagnostics)


def test_fresh_at_collection_stale_at_evaluation_and_stale_history():
    rows = snapshots()
    rows[0] = replace(rows[0], reference_timestamp=rows[0].observed_at - timedelta(milliseconds=3001))
    rows[2] = replace(rows[2], observed_at=stream.NOW - timedelta(seconds=1),
                      ingested_at=stream.NOW - timedelta(milliseconds=900),
                      yes_book_timestamp=stream.NOW - timedelta(milliseconds=1100))
    result = verify(verifier(rows), rows)
    assert result.sources == VerifiedSources(False, False, True, False)
    book = next(d for d in result.diagnostics if d.source == "yes_book")
    assert book.age_ms == 1100 and book.reason == "stale_source"
    historical = next(d for d in result.diagnostics if d.role == "history")
    assert historical.age_ms == pytest.approx(3001)
    assert historical.evaluated_at_utc == rows[0].observed_at.isoformat()


def test_failure_diagnostics_persist_once_across_restart(tmp_path):
    rows = snapshots()
    rows[2] = replace(rows[2], no_book_timestamp=stream.NOW - timedelta(milliseconds=501))
    driver, journal, runner = stream.build_driver(tmp_path)
    driver.source_verifier = verifier(rows)
    fees.attach_cache(driver, tmp_path, fees.policy())
    stream.run(driver, rows)
    original = journal.decisions()[0]["source_verification_json"]
    payload = json.loads(original)
    assert payload["diagnostics_version"] == 1
    assert any(d["reason"] == "stale_source" and d["source"] == "no_book" for d in payload["diagnostics"])
    reopened = VNextDecisionOrchestrator(journal_path=journal.path, config=journal.config)
    assert reopened.decisions()[0]["source_verification_json"] == original
    stream.run(driver, rows)
    assert journal.decisions()[0]["source_verification_json"] == original
    assert runner.ledger.positions() == []


def test_only_consumed_anchor_is_verified_without_changing_feature_value():
    from polybtc.shadow.runner_vnext import _reference_return_30s, reference_anchor_30s
    rows = snapshots()
    unused = replace(rows[0], snapshot_id="unused", observed_at=rows[0].observed_at-timedelta(seconds=1),
                     reference_timestamp=rows[0].observed_at-timedelta(seconds=20), reference_price=1)
    history = [unused, *rows[:2]]
    adapter = verifier(rows)  # No evidence for unused row, whose price is not consumed.
    result = adapter.verify(prediction=rows[1], execution=rows[2], history=history,
                            prediction_at=stream.TARGET, at=stream.NOW,
                            fee_policy=fees.policy(), fee_rate=.07)
    assert result.sources.reference_source_verified
    assert result.reference_anchor_snapshot_id == rows[0].snapshot_id
    assert reference_anchor_30s(history, rows[1], decision_at=stream.TARGET) == rows[0]
    assert _reference_return_30s(history, rows[1], decision_at=stream.TARGET) == _reference_return_30s(rows[:2], rows[1], decision_at=stream.TARGET)
    assert "fixture:unused" not in result.evidence_ids


def test_selected_anchor_failure_does_not_fall_back_to_fresh_earlier_row():
    rows = snapshots()
    earlier = replace(rows[0], snapshot_id="earlier", observed_at=rows[0].observed_at-timedelta(seconds=1),
                      ingested_at=rows[0].observed_at-timedelta(seconds=1),
                      reference_timestamp=rows[0].observed_at-timedelta(seconds=1))
    rows[0] = replace(rows[0], reference_timestamp=rows[0].observed_at-timedelta(milliseconds=3001))
    result = verifier([*rows, earlier]).verify(prediction=rows[1], execution=rows[2],
        history=[earlier,*rows[:2]], prediction_at=stream.TARGET, at=stream.NOW,
        fee_policy=fees.policy(), fee_rate=.07)
    assert not result.sources.reference_source_verified
    assert result.reference_anchor_snapshot_id == rows[0].snapshot_id
    assert any(d.role == "history" and d.reason == "stale_source" for d in result.diagnostics)


def test_missing_consumed_anchor_is_not_verified():
    rows = snapshots()
    result = verifier(rows).verify(prediction=rows[1], execution=rows[2],history=[rows[1]],
        prediction_at=stream.TARGET,at=stream.NOW,fee_policy=fees.policy(),fee_rate=.07)
    assert not result.sources.reference_source_verified
    assert any(d.reason == "missing_reference_anchor" for d in result.diagnostics)
