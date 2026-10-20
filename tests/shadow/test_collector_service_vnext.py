from datetime import datetime, timedelta, timezone

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.collector_bridge_vnext import (
    VNextCollectorBridge,
)
from polybtc.shadow.collector_service_vnext import (
    VNextCollectorService,
    VNextSnapshotHistory,
)
from polybtc.shadow.csv_tail_vnext import (
    VNextCSVTailer,
)
from polybtc.shadow.runner_vnext import VerifiedSources


T0 = datetime(
    2026,
    10,
    9,
    12,
    0,
    0,
    tzinfo=timezone.utc,
)

HEADER = b"observed_at,condition_id,btc_price\n"
ROW = b"2026-10-09T12:00:00+00:00,m-001,40010\n"


class RecordingDriver:
    def __init__(self, journal, runner):
        self.journal = journal

        class Adapter:
            pass

        self.adapter = Adapter()
        self.adapter.runner = runner
        self.calls = []
        self.fail = False

    def process(self, **kwargs):
        if self.fail:
            raise RuntimeError("injected_driver_failure")

        self.calls.append(kwargs)
        return []


class Paths:
    def decisions(self, *, status=None):
        return []

    def __init__(self, base):
        self.path = base


class DummyRunner:
    def __init__(self, ledger_path):
        self.ledger = Paths(ledger_path)


def converter(tail_row):
    values = tail_row.values
    observed = datetime.fromisoformat(values["observed_at"])

    return SnapshotRecord(
        snapshot_id=tail_row.row_id,
        condition_id=values["condition_id"],
        observed_at=observed,
        ingested_at=observed,
        source_name="test_csv",
        reference_price=float(values["btc_price"]),
        reference_timestamp=observed,
        strike=40000.0,
        market_end_at=observed + timedelta(seconds=60),
    )


def build_service(tmp_path, at):
    tailer = VNextCSVTailer(
        csv_path=tmp_path / "source.csv",
        state_path=tmp_path / "tail.sqlite3",
        startup="beginning",
    )

    bridge = VNextCollectorBridge(
        state_path=tmp_path / "receipts.sqlite3",
        clock=lambda: at,
    )

    history = VNextSnapshotHistory(tmp_path / "history.sqlite3")

    driver = RecordingDriver(
        Paths(tmp_path / "journal.sqlite3"),
        DummyRunner(tmp_path / "trades.sqlite3"),
    )

    service = VNextCollectorService(
        tailer=tailer,
        bridge=bridge,
        history=history,
        driver=driver,
        converter=converter,
    )

    return service, driver


def sources():
    # Test-only flags. No fee verification implied
    # for real prospective operation.
    return VerifiedSources(True, True, True, False)


def test_service_persists_snapshot(tmp_path):
    (tmp_path / "source.csv").write_bytes(HEADER + ROW)

    service, driver = build_service(
        tmp_path,
        T0 + timedelta(seconds=1),
    )

    result = service.run_once(
        sources=sources(),
        fee_rate=None,
    )

    assert result.source_rows == 1
    assert result.new_receipts == 1

    assert len(service.history.load()) == 1
    assert len(driver.calls) == 1

    persisted = service.history.load()[0]

    assert persisted.ingested_at == (T0 + timedelta(seconds=1))


def test_restart_preserves_history(tmp_path):
    (tmp_path / "source.csv").write_bytes(HEADER + ROW)

    first, _ = build_service(
        tmp_path,
        T0 + timedelta(seconds=1),
    )

    first.run_once(
        sources=sources(),
        fee_rate=None,
    )

    reopened, driver = build_service(
        tmp_path,
        T0 + timedelta(seconds=2),
    )

    result = reopened.run_once(
        sources=sources(),
        fee_rate=None,
    )

    assert result.source_rows == 0
    assert len(reopened.history.load()) == 1
    assert len(driver.calls[0]["snapshots"]) == 1


def test_driver_failure_does_not_ack(tmp_path):
    (tmp_path / "source.csv").write_bytes(HEADER + ROW)

    service, driver = build_service(
        tmp_path,
        T0 + timedelta(seconds=1),
    )

    initial_offset = service.tailer.poll().start_offset
    driver.fail = True

    with pytest.raises(
        RuntimeError,
        match="injected_driver_failure",
    ):
        service.run_once(
            sources=sources(),
            fee_rate=None,
        )

    assert service.tailer.checkpoint() == initial_offset

    # Receipt is durable before evaluation; history is also persisted
    # when the downstream failure unwinds.
    assert len(service.history.load()) == 1

    driver.fail = False

    retried = service.run_once(
        sources=sources(),
        fee_rate=None,
    )

    assert retried.source_rows == 1
    assert retried.new_receipts == 0

    assert service.tailer.checkpoint() > initial_offset


def test_no_new_rows_still_invokes_driver(tmp_path):
    (tmp_path / "source.csv").write_bytes(HEADER)

    service, driver = build_service(
        tmp_path,
        T0 + timedelta(seconds=2),
    )

    result = service.run_once(
        sources=sources(),
        fee_rate=None,
    )

    assert result.source_rows == 0
    assert len(driver.calls) == 1


def test_converter_failure_does_not_ack(tmp_path):
    (tmp_path / "source.csv").write_bytes(HEADER + ROW)

    service, _ = build_service(
        tmp_path,
        T0 + timedelta(seconds=1),
    )

    initial_offset = service.tailer.poll().start_offset

    service.converter = lambda row: None

    with pytest.raises(TypeError):
        service.run_once(
            sources=sources(),
            fee_rate=None,
        )

    assert service.tailer.checkpoint() == initial_offset
    assert service.history.load() == []


def test_cached_snapshot_conflict_rejected(tmp_path):
    history = VNextSnapshotHistory(tmp_path / "history.sqlite3")

    first = converter(
        type(
            "TailRowStub",
            (),
            {
                "row_id": "stable-id",
                "values": {
                    "observed_at": T0.isoformat(),
                    "condition_id": "m-001",
                    "btc_price": "40010",
                },
            },
        )()
    )

    history.store([first])

    from dataclasses import replace

    conflicting = replace(
        first,
        reference_price=41000.0,
    )

    with pytest.raises(
        ValueError,
        match="Conflicting cached snapshot",
    ):
        history.store([conflicting])

    assert len(history.load()) == 1
