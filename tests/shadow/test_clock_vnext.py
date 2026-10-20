from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from polybtc.shadow.clock_vnext import ClockGuard, ClockPaused


class Clock:
    def __init__(self):
        self.utc = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        self.mono = 0.0

    def advance(self, elapsed, adjust=0):
        self.mono += elapsed
        self.utc += timedelta(seconds=elapsed + adjust)

    def guard(self, path):
        return ClockGuard(path, utc=lambda: self.utc, monotonic=lambda: self.mono)


@pytest.mark.parametrize("elapsed,adjust", [(0.1, -0.2), (1, -0.2), (1, 2)])
def test_discontinuities_are_durable_and_never_clamped(tmp_path, elapsed, adjust):
    clock = Clock()
    guard = clock.guard(tmp_path / "journal.db")
    first = guard.now()
    clock.advance(elapsed, adjust)
    with pytest.raises(ClockPaused):
        guard.now()
    assert guard.incident["observed_utc"] == clock.utc.isoformat()
    reopened = clock.guard(guard.path)
    with pytest.raises(ClockPaused):
        reopened.now()
    assert reopened.incident == guard.incident
    with pytest.raises(ValueError):
        reopened.acknowledge("wrong-event")


def test_confirmation_waits_for_new_market_and_survives_restart(tmp_path):
    clock = Clock()
    guard = clock.guard(tmp_path / "journal.db")
    guard.now()
    clock.advance(0.1, -0.2)
    with pytest.raises(ClockPaused):
        guard.now()
    with pytest.raises(ValueError):
        guard.acknowledge(guard.incident["event_id"])
    clock.advance(1)
    guard.acknowledge(guard.incident["event_id"])
    reopened = clock.guard(guard.path)
    with pytest.raises(ClockPaused):
        reopened.now()
    clock.advance(301)
    assert reopened.now() == clock.utc
    assert reopened.eligible_after == datetime(2026, 10, 13, 12, 5, tzinfo=timezone.utc)


def test_ordinary_slew_and_durable_startup_watermark(tmp_path):
    clock = Clock()
    guard = clock.guard(tmp_path / "journal.db")
    guard.now()
    for _ in range(20):
        clock.advance(0.1, -0.00005)
        assert guard.now() == clock.utc
    other = ClockGuard(
        tmp_path / "other.db",
        utc=lambda: clock.utc,
        monotonic=lambda: clock.mono,
        watermark=clock.utc + timedelta(seconds=1),
    )
    with pytest.raises(ClockPaused):
        other.now()
    assert other.incident["reason"] == "utc_before_durable_state"


def test_clock_incident_inside_atomic_outcome_survives_rollback(tmp_path):
    from polybtc.shadow.paper_store_vnext import PaperStore

    clock = Clock()
    store = PaperStore(tmp_path / "paper.db")
    guard = ClockGuard(
        store.path, utc=lambda: clock.utc, monotonic=lambda: clock.mono, store=store
    )
    guard.now()
    with pytest.raises(ClockPaused):
        with store.atomic():
            clock.advance(0.1, -0.2)
            guard.now()
    assert guard.pending
    guard.flush()
    assert not guard.pending
    reopened = clock.guard(store.path)
    with pytest.raises(ClockPaused):
        reopened.now()
    assert reopened.incident["event_id"] == guard.incident["event_id"]
    store.close()


def test_incident_persistence_failure_is_fatal(tmp_path, monkeypatch):
    clock = Clock()
    guard = clock.guard(tmp_path / "journal.db")
    guard.now()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(guard, "_append", fail)
    clock.advance(0.1, -0.2)
    with pytest.raises(OSError, match="disk full"):
        guard.now()


def test_second_adjustment_invalidates_first_confirmation(tmp_path):
    clock = Clock()
    guard = clock.guard(tmp_path / "journal.db")
    guard.now()
    clock.advance(0.1, -0.2)
    with pytest.raises(ClockPaused):
        guard.now()
    old = guard.incident["event_id"]
    clock.advance(1, 10)
    with pytest.raises(ClockPaused):
        guard.now()
    with pytest.raises(ValueError):
        guard.acknowledge(old)
    reopened = clock.guard(guard.path)
    assert reopened.high_water == clock.utc


@pytest.mark.parametrize("populated", [False, True])
def test_runtime_pauses_after_intake_without_ack_or_evaluation(tmp_path, populated):
    from tests.shadow import test_collector_service_vnext as helper
    from polybtc.shadow.service_runtime_vnext import VNextServiceRuntime

    (tmp_path / "source.csv").write_bytes(
        helper.HEADER + (helper.ROW if populated else b"")
    )
    service, driver = helper.build_service(tmp_path, helper.T0)
    clock = Clock()
    clock.utc = helper.T0 + timedelta(seconds=1)
    calls = 0

    def utc():
        nonlocal calls
        calls += 1
        if calls == 3:
            clock.advance(0.1, -0.2)
        return clock.utc

    guard = ClockGuard(tmp_path / "clock.db", utc=utc, monotonic=lambda: clock.mono)
    service.bridge.clock = guard.now
    service.clock_guard = guard
    runtime = VNextServiceRuntime(
        service=service, sources=helper.sources(), clock_guard=guard
    )
    assert runtime.run_once() is None
    assert not driver.calls
    assert service.bridge.receipt_count() == int(populated)
    assert service.tailer.checkpoint() == len(helper.HEADER)
    assert guard.incident["stage"] == "post_intake"
    if populated:
        with service.bridge._connect() as db:
            original = db.execute(
                "SELECT first_received_at_utc FROM receipts"
            ).fetchone()[0]
    clock.advance(1)
    guard.acknowledge(guard.incident["event_id"])
    with pytest.raises(ClockPaused):
        guard.now()
    clock.advance(301)
    runtime.run_once()
    assert driver.calls[-1]["snapshots"] == []
    if populated:
        with service.bridge._connect() as db:
            assert (
                db.execute("SELECT first_received_at_utc FROM receipts").fetchone()[0]
                == original
            )
    runtime.stop()
