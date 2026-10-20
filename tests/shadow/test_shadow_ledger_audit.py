import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.strategy.vnext import (
    Action,
    StrategyInput,
    VNextStrategy,
)


NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def decision(market="audit-market"):
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


def reserve(ledger, market="audit-market"):
    result = ledger.reserve(
        decision=decision(market),
        risk_gate=VNextRiskGate(),
        requested_size=5.0,
        minimum_order_size=5.0,
        at=NOW,
    )

    assert result.approved
    return result


def fill(ledger, market="audit-market"):
    ledger.record_fill(
        condition_id=market,
        execution_price=0.66,
        filled_size=5.0,
        entry_fee=0.05,
        at=NOW + timedelta(seconds=1),
    )


@pytest.fixture
def ledger(tmp_path):
    return VNextShadowLedger(tmp_path / "audit.sqlite3")


def test_new_database_version_two(ledger):
    with sqlite3.connect(ledger.path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]

    assert version == 3


def test_reservation_creates_event(ledger):
    reserve(ledger)

    events = ledger.events("audit-market")

    assert len(events) == 1
    assert events[0]["event_type"] == "ENTRY_RESERVED"
    assert events[0]["payload"]["side"] == "YES"
    assert events[0]["payload"]["reserved_cost"] == (pytest.approx(3.35))


def test_fill_and_settlement_event_order(ledger):
    reserve(ledger)
    fill(ledger)

    pnl = ledger.settle(
        condition_id="audit-market",
        label_yes=1,
        at=NOW + timedelta(minutes=5),
    )

    events = ledger.events("audit-market")

    assert [event["event_type"] for event in events] == [
        "ENTRY_RESERVED",
        "ENTRY_FILLED",
        "ENTRY_SETTLED",
    ]

    assert [e["event_id"] for e in events] == sorted(e["event_id"] for e in events)

    assert events[-1]["payload"]["realized_pnl"] == (pytest.approx(pnl))


def test_rejection_event(ledger):
    reserve(ledger)

    ledger.reject_pending(
        condition_id="audit-market",
        reason="audit_test_rejection",
        at=NOW + timedelta(seconds=1),
    )

    events = ledger.events("audit-market")

    assert [e["event_type"] for e in events] == [
        "ENTRY_RESERVED",
        "ENTRY_REJECTED",
    ]


def test_idempotent_settlement_no_duplicate_event(ledger):
    reserve(ledger)
    fill(ledger)

    ledger.settle(
        condition_id="audit-market",
        label_yes=1,
        at=NOW + timedelta(minutes=5),
    )

    initial_count = len(ledger.events())

    ledger.settle(
        condition_id="audit-market",
        label_yes=1,
        at=NOW + timedelta(minutes=6),
    )

    assert len(ledger.events()) == initial_count


def test_events_cannot_be_updated_or_deleted(ledger):
    reserve(ledger)

    with sqlite3.connect(ledger.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                UPDATE entry_events
                SET event_type='ENTRY_FILLED'
                WHERE event_id=1
            """)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                DELETE FROM entry_events
                WHERE event_id=1
            """)


def test_invalid_status_transition_rolls_back(ledger):
    reserve(ledger)

    with sqlite3.connect(ledger.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""
                UPDATE entries
                SET status='SETTLED'
                WHERE condition_id='audit-market'
            """)

    assert ledger.positions()[0].status == "PENDING"

    assert [e["event_type"] for e in ledger.events()] == ["ENTRY_RESERVED"]


def test_failed_fill_has_no_fill_event(ledger):
    reserve(ledger)

    with pytest.raises(ValueError):
        ledger.record_fill(
            condition_id="audit-market",
            execution_price=0.70,
            filled_size=5.0,
            entry_fee=0.05,
            at=NOW + timedelta(seconds=1),
        )

    assert [e["event_type"] for e in ledger.events()] == ["ENTRY_RESERVED"]


def test_restart_preserves_event_history(ledger):
    reserve(ledger)
    fill(ledger)

    reopened = VNextShadowLedger(ledger.path)

    assert reopened.events() == ledger.events()


def test_schema_reopen_idempotent(ledger):
    reserve(ledger)

    before = ledger.events()

    VNextShadowLedger(ledger.path)
    VNextShadowLedger(ledger.path)

    assert ledger.events() == before


def test_v1_to_v2_migration_preserves_entries(tmp_path):
    path = tmp_path / "legacy.sqlite3"

    # Build a database using the v1 ledger code without
    # modifying the main project module.
    # Temporarily downgrade a newly created empty v2 DB:
    # remove v2 triggers/events and restore user_version=1.
    original = VNextShadowLedger(path)

    reserve(original, "legacy-market")

    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER trg_entry_transition_audit")
        conn.execute("DROP TRIGGER trg_entry_status_guard")
        conn.execute("DROP TRIGGER trg_entry_reserved_audit")
        conn.execute("DROP TRIGGER trg_entry_events_no_update")
        conn.execute("DROP TRIGGER trg_entry_events_no_delete")
        conn.execute("DROP TABLE entry_events")
        conn.execute("PRAGMA user_version=1")

    upgraded = VNextShadowLedger(path)

    assert upgraded.positions()[0].status == "PENDING"

    events = upgraded.events("legacy-market")

    assert len(events) == 1
    assert events[0]["event_type"] == ("LEGACY_STATE_IMPORTED")

    assert events[0]["payload"]["imported_status"] == ("PENDING")

    # Upgrading again cannot duplicate imported events.
    reopened = VNextShadowLedger(path)
    assert reopened.events() == events

    # New transitions are audited after migration.
    fill(reopened, "legacy-market")

    assert [event["event_type"] for event in reopened.events("legacy-market")] == [
        "LEGACY_STATE_IMPORTED",
        "ENTRY_FILLED",
    ]
