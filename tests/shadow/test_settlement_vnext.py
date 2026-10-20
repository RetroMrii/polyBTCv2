from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from contextlib import contextmanager

import pytest

from polybtc.shadow.settlement_vnext import (
    VerifiedResolution,
    VNextSettlementService,
)


T0 = datetime(
    2026,
    10,
    9,
    15,
    5,
    tzinfo=timezone.utc,
)


@dataclass
class Position:
    condition_id: str
    status: str = "FILLED"


class FakeLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.items = [Position("market-001")]
        self.settle_calls = []
        with self._connection() as conn:
            conn.execute("CREATE TABLE entries (condition_id TEXT, status TEXT, label_yes INTEGER, realized_pnl REAL)")

    @contextmanager
    def _connection(self):
        # The service now verifies durable evidence on the recovery path.
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def positions(self):
        return list(self.items)

    def settle(self, condition_id, label_yes, at):
        self.settle_calls.append((condition_id, label_yes, at))
        self.items[0].status = "SETTLED"
        with self._connection() as conn:
            conn.execute("INSERT INTO entries VALUES (?, 'SETTLED', ?, ?)",
                         (condition_id, label_yes, 1.0))


@pytest.fixture
def setup(tmp_path):
    ledger = FakeLedger(tmp_path / "trades.sqlite3")
    service = VNextSettlementService(
        registry_path=tmp_path / "resolutions.sqlite3",
        ledger=ledger,
    )
    return service, ledger


def outcome(label=1):
    return VerifiedResolution(
        condition_id="market-001",
        label_yes=label,
        resolved_at_utc=T0,
        evidence_source="verified_test_fixture",
        evidence_id="fixture-resolution-001",
    )


def test_unverified_market_not_settled(setup):
    service, ledger = setup

    result = service.settle(
        condition_id="market-001",
        at=T0,
    )

    assert result.status == "UNRESOLVED"
    assert ledger.settle_calls == []


def test_verified_resolution_settles(setup):
    service, ledger = setup
    service.register(outcome())

    result = service.settle(
        condition_id="market-001",
        at=T0,
    )

    assert result.status == "SETTLED"
    assert len(ledger.settle_calls) == 1
    assert type(ledger.settle_calls[0][1]) is int
    assert ledger.settle_calls[0][1] == 1
    assert service.resolutions()[0]["settlement_status"] == "SETTLED"


def test_repeated_settlement_is_idempotent(setup):
    service, ledger = setup
    service.register(outcome())

    service.settle(condition_id="market-001", at=T0)
    service.settle(condition_id="market-001", at=T0)

    assert len(ledger.settle_calls) == 1


def test_conflicting_label_rejected(setup):
    service, _ = setup
    service.register(outcome(label=1))

    with pytest.raises(ValueError, match="Conflicting"):
        service.register(outcome(label=0))


def test_duplicate_evidence_preserved(setup):
    service, _ = setup

    service.register(outcome())
    second = service.register(outcome())

    assert second.reason == "resolution_already_registered"
    assert len(service.resolutions()) == 1


def test_unfilled_position_not_settled(setup):
    service, ledger = setup
    ledger.items[0].status = "PENDING"

    service.register(outcome())

    result = service.settle(
        condition_id="market-001",
        at=T0,
    )

    assert result.reason == "position_not_filled"
    assert ledger.settle_calls == []


def test_cannot_settle_before_resolution_time(setup):
    service, ledger = setup
    service.register(outcome())

    result = service.settle(
        condition_id="market-001",
        at=T0 - timedelta(seconds=1),
    )

    assert result.reason == "before_resolution_timestamp"
    assert ledger.settle_calls == []


def test_restart_recovers_settled_position(tmp_path):
    path = tmp_path / "resolutions.sqlite3"
    ledger = FakeLedger(tmp_path / "trades.sqlite3")

    first = VNextSettlementService(
        registry_path=path,
        ledger=ledger,
    )

    first.register(outcome())

    # Simulate interruption after the ledger
    # committed settlement but before registry ACK.
    ledger.settle(condition_id="market-001", label_yes=1, at=T0)
    ledger.settle_calls.clear()

    reopened = VNextSettlementService(
        registry_path=path,
        ledger=ledger,
    )

    result = reopened.settle(
        condition_id="market-001",
        at=T0,
    )

    assert result.status == "SETTLED"
    assert ledger.settle_calls == []
    assert reopened.resolutions()[0]["settlement_status"] == "SETTLED"


def test_missing_position_does_not_settle(setup):
    service, ledger = setup
    ledger.items.clear()
    service.register(outcome())

    result = service.settle(
        condition_id="market-001",
        at=T0,
    )

    assert result.status == "NO_POSITION"
