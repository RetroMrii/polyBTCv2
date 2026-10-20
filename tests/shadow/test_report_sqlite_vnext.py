import json
import sqlite3
from pathlib import Path

import pytest

from polybtc.shadow.report_sqlite_vnext import (
    build_sqlite_shadow_report,
)


TARGET = "2026-10-09T15:04:00.000000+00:00"
SETTLED = "2026-10-09T15:05:05.000000+00:00"


def setup_databases(tmp_path):
    journal = tmp_path / "decisions.sqlite3"
    ledger = tmp_path / "trades.sqlite3"
    registry = tmp_path / "resolutions.sqlite3"

    with sqlite3.connect(journal) as db:
        db.execute("""
            CREATE TABLE decisions (
                condition_id TEXT,
                horizon_seconds INTEGER,
                status TEXT,
                reason TEXT,
                snapshot_id TEXT,
                target_at_utc TEXT,
                execution_price REAL,
                model_probability_yes REAL
            )
        """)
        db.execute(
            """
            INSERT INTO decisions VALUES
            ('market-a',60,'SHADOW_FILLED',
             'ledger_fill_reconciled',
             'snapshot-a',?,0.60,0.80)
        """,
            (TARGET,),
        )

    with sqlite3.connect(registry) as db:
        db.execute("""
            CREATE TABLE resolutions (
                condition_id TEXT,
                label_yes INTEGER,
                settlement_status TEXT
            )
        """)
        db.execute("""
            INSERT INTO resolutions VALUES
            ('market-a',1,'SETTLED')
        """)

    context = {
        "snapshot_id": "snapshot-a",
        "prediction_timestamp_utc": TARGET,
        "strategy_action": "BUY_YES",
    }

    with sqlite3.connect(ledger) as db:
        db.execute("""
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                condition_id TEXT,
                side TEXT,
                status TEXT,
                execution_price REAL,
                filled_size REAL,
                entry_fee REAL,
                label_yes INTEGER,
                realized_pnl REAL,
                settled_at_utc TEXT
            )
        """)

        db.execute("""
            CREATE TABLE entry_decision_context (
                entry_id INTEGER,
                context_json TEXT
            )
        """)

        db.execute("""
            CREATE TABLE entry_events (
                entry_id INTEGER,
                event_id INTEGER,
                event_type TEXT,
                occurred_at_utc TEXT,
                payload_json TEXT
            )
        """)

        db.execute(
            """
            INSERT INTO entries VALUES
            (1,'market-a','YES','SETTLED',
             0.60,5,0.05,1,1.95,?)
        """,
            (SETTLED,),
        )

        db.execute(
            """
            INSERT INTO entry_decision_context
            VALUES (1,?)
        """,
            (json.dumps(context),),
        )

        for event_id, event_type in enumerate(
            [
                "ENTRY_RESERVED",
                "ENTRY_FILLED",
                "ENTRY_SETTLED",
            ],
            start=1,
        ):
            payload = (
                {
                    "label_yes": 1,
                    "realized_pnl": 1.95,
                }
                if event_type == "ENTRY_SETTLED"
                else {}
            )

            db.execute(
                """
                INSERT INTO entry_events
                VALUES (1,?,?,?,?)
            """,
                (
                    event_id,
                    event_type,
                    SETTLED,
                    json.dumps(payload),
                ),
            )

    return journal, ledger, registry


def report(paths):
    return build_sqlite_shadow_report(
        journal_path=paths[0],
        ledger_path=paths[1],
        registry_path=paths[2],
    )


def test_reads_persisted_settlement(tmp_path):
    paths = setup_databases(tmp_path)

    result = report(paths)

    assert result.settled_trades == 1
    assert result.winning_trades == 1
    assert result.net_pnl == pytest.approx(1.95)
    assert result.total_stake == pytest.approx(3.00)
    assert result.roi_on_settled_stake == pytest.approx(1.95 / 3.00)


def test_rejects_wrong_recorded_pnl(tmp_path):
    paths = setup_databases(tmp_path)

    with sqlite3.connect(paths[1]) as db:
        db.execute("""
            UPDATE entries
            SET realized_pnl=9.99
            WHERE condition_id='market-a'
        """)

    with pytest.raises(ValueError, match="PnL mismatch"):
        report(paths)


def test_rejects_registry_label_conflict(tmp_path):
    paths = setup_databases(tmp_path)

    with sqlite3.connect(paths[2]) as db:
        db.execute("""
            UPDATE resolutions
            SET label_yes=0
            WHERE condition_id='market-a'
        """)

    with pytest.raises(ValueError, match="label mismatch"):
        report(paths)


def test_rejects_missing_decision_context(tmp_path):
    paths = setup_databases(tmp_path)

    with sqlite3.connect(paths[1]) as db:
        db.execute("""
            DELETE FROM entry_decision_context
            WHERE entry_id=1
        """)

    with pytest.raises(
        ValueError,
        match="Missing immutable decision context",
    ):
        report(paths)


def test_rejects_missing_audit_event(tmp_path):
    paths = setup_databases(tmp_path)

    with sqlite3.connect(paths[1]) as db:
        db.execute("""
            DELETE FROM entry_events
            WHERE event_type='ENTRY_FILLED'
        """)

    with pytest.raises(
        ValueError,
        match="Incomplete settlement audit",
    ):
        report(paths)


def test_does_not_modify_databases(tmp_path):
    paths = setup_databases(tmp_path)

    before = []

    for path in paths:
        with sqlite3.connect(path) as db:
            before.append(db.total_changes)

    report(paths)
    report(paths)

    assert report(paths).net_pnl == pytest.approx(1.95)
