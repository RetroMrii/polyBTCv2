"""Synthetic fixtures only. Tests never access project trading sources."""

import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data import freshness, now, read_db
from app.main import create_app
from app.services import Monitor


@pytest.fixture
def sources(tmp_path):
    settings = Settings(
        **{
            k: tmp_path / (k + (".csv" if k == "telemetry" else ".json" if k == "report" else ".sqlite3"))
            for k in ("telemetry", "decisions", "trades", "resolutions", "report")
        }
    )
    at = now()
    with closing(sqlite3.connect(settings.decisions)) as db, db:
        db.execute(
            "CREATE TABLE decisions (id INTEGER PRIMARY KEY, condition_id TEXT, horizon_seconds INTEGER, target_at_utc TEXT, processed_at_utc TEXT, status TEXT, reason TEXT, model_probability_yes REAL, prediction_market_probability_yes REAL, market_probability_yes REAL, execution_price REAL)"
        )
        db.executemany(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    1,
                    "test-market",
                    240,
                    at.isoformat(),
                    at.isoformat(),
                    "ABSTAIN",
                    "unverified_input_provenance",
                    0.8,
                    0.55,
                    0.95,
                    None,
                ),
                (
                    2,
                    "test-market",
                    180,
                    at.isoformat(),
                    at.isoformat(),
                    "ABSTAIN",
                    "missing_horizon",
                    None,
                    None,
                    0.9,
                    None,
                ),
                (
                    3,
                    "other-market",
                    30,
                    at.isoformat(),
                    at.isoformat(),
                    "ABSTAIN",
                    "stale_reference",
                    1.3,
                    None,
                    None,
                    None,
                ),
            ],
        )
    with closing(sqlite3.connect(settings.resolutions)) as db, db:
        db.execute(
            "CREATE TABLE resolutions (condition_id TEXT PRIMARY KEY, label_yes INTEGER, resolved_at_utc TEXT, evidence_source TEXT, evidence_id TEXT, settlement_status TEXT, settled_at_utc TEXT)"
        )
        db.execute(
            "INSERT INTO resolutions VALUES (?,?,?,?,?,?,?)",
            (
                "test-market",
                1,
                (at + timedelta(minutes=5)).isoformat(),
                "synthetic-test-evidence",
                "fixture-only",
                "VERIFIED",
                None,
            ),
        )
    with closing(sqlite3.connect(settings.trades)) as db, db:
        db.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE entry_decision_context (entry_id INTEGER, context_json TEXT)")
        db.execute("CREATE TABLE entry_events (event_id INTEGER PRIMARY KEY, entry_id INTEGER)")
    fields = [
        "market_id",
        "observed_at",
        "market_end_at",
        "btc_price",
        "strike",
        "yes_bid",
        "yes_ask",
        "no_bid",
        "no_ask",
        "reference_timestamp",
        "reference_age_ms",
        "yes_book_timestamp",
        "yes_book_age_ms",
        "no_book_timestamp",
        "no_book_age_ms",
    ]
    row = dict(
        zip(
            fields,
            [
                "test-market",
                at.isoformat(),
                (at + timedelta(minutes=3)).isoformat(),
                "100",
                "99",
                ".5",
                ".6",
                ".3",
                ".4",
                at.isoformat(),
                "0",
                (at + timedelta(milliseconds=100)).isoformat(),
                "-100",
                at.isoformat(),
                "0",
            ],
        )
    )
    with settings.telemetry.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)
    return settings


def test_prediction_baseline_is_not_execution_quote(sources):
    rows = Monitor(sources).decisions().rows
    prediction = next(r for r in rows if r.id == 1)
    assert prediction.prediction_market_probability_yes == 0.55
    assert prediction.market_probability_yes == 0.95
    assert prediction.probability_difference == pytest.approx(0.25)
    assert prediction.model_probability_no == pytest.approx(0.2)
    assert prediction.reason_info.category == "Execution authorization"
    assert prediction.verified_outcome == 1
    missing = next(r for r in rows if r.id == 2)
    assert missing.prediction_market_probability_yes is None
    assert missing.probability_difference is None


def test_invalid_probability_is_excluded(sources):
    row = next(r for r in Monitor(sources).decisions().rows if r.id == 3)
    assert row.model_probability_yes is None
    assert row.validation_warnings


def test_telemetry_formula_and_future_ages(sources):
    market = Monitor(sources).telemetry().current
    assert market.active
    assert market.market_probability_yes == pytest.approx(0.55 / 0.9)
    assert market.yes_book_age_ms == -100
    assert any("future-dated" in warning for warning in market.warnings)
    assert market.distance == 1


def test_expired_market_not_presented_as_active(sources):
    text = sources.telemetry.read_text()
    monitor = Monitor(sources)
    expiry = monitor.telemetry().current.market_end_at
    sources.telemetry.write_text(text.replace(expiry, (now() - timedelta(minutes=10)).isoformat()))
    assert not Monitor(sources).telemetry().current.active


def test_incomplete_csv_append_ignored(sources):
    with sources.telemetry.open("a") as f:
        f.write("partial-write,no-newline")
    telemetry = Monitor(sources).telemetry()
    assert len(telemetry.rows) == 1
    assert telemetry.current.market_id == "test-market"


def test_missing_sources_and_empty_portfolio(sources):
    monitor = Monitor(sources)
    portfolio = monitor.portfolio()
    assert portfolio.realized_pnl == 0
    assert portfolio.exposure == 0
    assert portfolio.win_rate is None
    assert "No hypothetical fills" in portfolio.detail
    assert monitor.performance().report is None
    sources.telemetry.unlink()
    assert Monitor(sources).telemetry().source.state == "missing"


def test_read_only_database_and_no_source_mutation(sources):
    before = hashlib.sha256(sources.decisions.read_bytes()).hexdigest()
    with read_db(sources.decisions) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("DELETE FROM decisions")
    monitor = Monitor(sources)
    monitor.overview()
    monitor.performance()
    monitor.health()
    assert hashlib.sha256(sources.decisions.read_bytes()).hexdigest() == before


def test_wal_committed_updates_visible(sources):
    writer = sqlite3.connect(sources.decisions)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        with read_db(sources.decisions) as reader:
            assert reader.execute("SELECT status FROM decisions WHERE id=1").fetchone()[0] == "ABSTAIN"
        writer.execute("UPDATE decisions SET status='TEST_UPDATED' WHERE id=1")
        writer.commit()
        with read_db(sources.decisions) as reader:
            assert reader.execute("SELECT status FROM decisions WHERE id=1").fetchone()[0] == "TEST_UPDATED"
    finally:
        writer.close()


def test_failed_refresh_retains_values_but_marks_error(sources):
    monitor = Monitor(sources)
    monitor.reader.decisions()
    sources.decisions.unlink()
    old = monitor.reader.cache["decisions"]
    monitor.reader.cache["decisions"] = (0, old[1], old[2])
    page = monitor.decisions()
    assert len(page.rows) == 3
    assert page.source.state == "missing"
    assert "Retaining last successful" in page.source.detail


def test_timestamp_states():
    assert freshness(None, 2).state == "missing"
    assert freshness("2026-10-09T12:00:00", 2).state == "missing"
    assert freshness((now() + timedelta(minutes=2)).isoformat(), 2).state == "future"
    assert freshness((now() - timedelta(minutes=2)).isoformat(), 2).state == "stale"


def test_api_filters_and_guardrails(sources):
    with TestClient(create_app(sources)) as client:
        for route in (
            "overview",
            "market",
            "telemetry",
            "predictions",
            "decisions",
            "performance",
            "resolutions",
            "health",
            "settings",
        ):
            assert client.get("/api/" + route).status_code == 200, route
        response = client.get(
            "/api/predictions?availability=available&horizon=240&minimum=0.7&outcome=verified"
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert client.get("/api/decisions?page_size=1").json()["rows"][0]["id"] in (1, 2, 3)
        assert client.get("/api/decisions?search=%27%20OR%201=1--").json()["total"] == 0
        for query in (
            "minimum=1.5",
            "page_size=5000",
            "horizon=13",
            "sort=DROP",
            "minimum=.8&maximum=.2",
            "after=2026-01-01T00:00:00",
        ):
            assert client.get("/api/decisions?" + query).status_code == 422
        assert client.post("/api/decisions").status_code == 405
        assert client.post("/api/settings", json={"path": "C:/private"}).status_code == 405
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
        assert not any(
            route.path.endswith(("start", "stop", "execute", "sql")) for route in client.app.routes
        )


def test_active_market_selected_over_later_expired_row(sources):
    lines = sources.telemetry.read_text().splitlines()
    with sources.telemetry.open("a") as file:
        row = next(csv.DictReader(lines))
        row["market_id"] = "expired-test"
        row["observed_at"] = (now() + timedelta(seconds=1)).isoformat()
        row["market_end_at"] = (now() - timedelta(minutes=1)).isoformat()
        writer = csv.DictWriter(file, fieldnames=lines[0].split(","))
        writer.writerow(row)
    assert Monitor(sources).telemetry().current.market_id == "test-market"


def test_header_only_csv_does_not_claim_recent_collector(sources):
    header = sources.telemetry.read_text().splitlines()[0]
    sources.telemetry.write_text(header + "\n")
    telemetry = Monitor(sources).telemetry()
    assert telemetry.current is None
    assert telemetry.source.state == "missing"


def test_invalid_report_is_explicitly_unavailable(sources):
    sources.report.write_text('{"report_version":"unknown"}')
    report = Monitor(sources).performance()
    assert report.report is None
    assert report.source.state == "error"


def test_history_is_bounded(sources):
    from dataclasses import replace

    page = Monitor(replace(sources, recent_limit=2)).decisions()
    assert page.total == 2
    assert {r.id for r in page.rows} == {2, 3}


@pytest.mark.parametrize("corrupt_pnl", [False, True])
@pytest.mark.parametrize("outcome", [0, 1])
def test_settlement_metrics_require_full_evidence(sources, corrupt_pnl, outcome):
    at = now().isoformat()
    net_pnl = 4.9 if outcome else -5.1
    with closing(sqlite3.connect(sources.decisions)) as db, db:
        db.execute("ALTER TABLE decisions ADD COLUMN snapshot_id TEXT")
        db.execute(
            "UPDATE decisions SET status='SHADOW_FILLED', execution_price=.5, snapshot_id='fixture-snapshot' WHERE id=1"
        )
        target = db.execute("SELECT target_at_utc FROM decisions WHERE id=1").fetchone()[0]
    with closing(sqlite3.connect(sources.resolutions)) as db, db:
        db.execute(
            "UPDATE resolutions SET settlement_status='SETTLED', settled_at_utc=?, label_yes=?", (at, outcome)
        )
    with closing(sqlite3.connect(sources.trades)) as db, db:
        for definition in [
            "condition_id TEXT",
            "side TEXT",
            "status TEXT",
            "execution_price REAL",
            "filled_size REAL",
            "entry_fee REAL",
            "label_yes INTEGER",
            "realized_pnl REAL",
            "settled_at_utc TEXT",
        ]:
            db.execute("ALTER TABLE entries ADD COLUMN " + definition)
        db.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            (1, "test-market", "YES", "SETTLED", 0.5, 10, 0.1, outcome, 900 if corrupt_pnl else net_pnl, at),
        )
        db.execute(
            "INSERT INTO entry_decision_context VALUES (?,?)",
            (
                1,
                json.dumps(
                    {
                        "snapshot_id": "fixture-snapshot",
                        "prediction_timestamp_utc": target,
                        "strategy_action": "BUY_YES",
                    }
                ),
            ),
        )
        db.execute("ALTER TABLE entry_events ADD COLUMN event_type TEXT")
        db.execute("ALTER TABLE entry_events ADD COLUMN payload_json TEXT")
        for index, event in enumerate(["ENTRY_RESERVED", "ENTRY_FILLED", "ENTRY_SETTLED"]):
            db.execute(
                "INSERT INTO entry_events VALUES (?,?,?,?)",
                (index + 1, 1, event, json.dumps({"label_yes": outcome, "realized_pnl": net_pnl})),
            )
    portfolio = Monitor(sources).portfolio()
    if corrupt_pnl:
        assert portfolio.realized_pnl is None
        assert portfolio.win_rate is None
        assert "withheld" in portfolio.detail
        assert portfolio.pnl_history == []
        assert portfolio.fees is None
    else:
        assert portfolio.realized_pnl == pytest.approx(net_pnl)
        assert portfolio.win_rate == outcome
        assert portfolio.settled == 1
        assert portfolio.fees == pytest.approx(0.1)
        assert portfolio.total_fills == 1
        assert portfolio.pnl_history[-1]["pnl"] == pytest.approx(net_pnl)


@pytest.mark.parametrize(
    "age,state,expected",
    [
        (0, "running", "Runtime reports running"),
        (30, "running", "stale heartbeat"),
        (0, "failed", "Runtime reports failed"),
        (-30, "running", "future heartbeat"),
    ],
)
def test_runtime_heartbeat_drives_paper_mode_and_health(sources, age, state, expected):
    path = sources.trades.parent / "runtime_status.json"
    path.write_text(
        json.dumps(
            dict(
                mode="paper_execution",
                state=state,
                observed_at=(now() - timedelta(seconds=age)).isoformat(),
                kill_switch=False,
            )
        )
    )
    overview = Monitor(sources).overview()
    assert overview.mode == "PAPER EXECUTION"
    assert expected in overview.health.process_status


def test_missing_ledger_does_not_report_zero_pnl(sources):
    sources.trades.unlink()
    portfolio = Monitor(sources).portfolio()
    assert portfolio.realized_pnl is None
    assert portfolio.exposure is None
    assert portfolio.source.state == "missing"


def test_pending_reservations_are_included_in_capital_at_risk(sources):
    with closing(sqlite3.connect(sources.trades)) as db, db:
        db.execute("ALTER TABLE entries ADD COLUMN status TEXT")
        db.execute("ALTER TABLE entries ADD COLUMN reserved_cost REAL")
        db.execute("INSERT INTO entries VALUES (1, 'PENDING', 3.25)")
    portfolio = Monitor(sources).portfolio()
    assert portfolio.pending == 1
    assert portfolio.reserved == portfolio.exposure == 3.25
    assert portfolio.realized_pnl == portfolio.fees == 0
    assert portfolio.total_fills == 0
    assert portfolio.win_rate is None


def test_typed_input_telemetry_is_read_only(tmp_path):
    from app.data import Reader
    path=tmp_path/'input.sqlite3'
    timestamp=now().isoformat()
    payload=json.dumps({'condition_id':'market','reference_price':42000,'observed_at':{'__polybtc_datetime_utc__':timestamp},'reference_timestamp':{'__polybtc_datetime_utc__':timestamp},'yes_ask':.52,'no_ask':.5})
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE acquisition(id TEXT PRIMARY KEY,snapshot TEXT)')
        db.execute('CREATE TABLE input_observations(sequence INTEGER PRIMARY KEY,acquisition_id TEXT)')
        db.execute('INSERT INTO acquisition VALUES (?,?)',('evidence',payload))
        db.execute('INSERT INTO input_observations VALUES (1,?)',('evidence',))
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    reader=Reader(Settings(telemetry=path))
    rows,status=reader.telemetry()
    assert status.state=='ok'
    assert rows[0]['market_id']=='market' and rows[0]['btc_price']==42000
    assert rows[0]['reference_timestamp']==timestamp
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
