from dataclasses import dataclass

import pytest

from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.service_runtime_vnext import (
    RuntimeConfig,
    VNextServiceRuntime,
)


@dataclass
class FakeCycle:
    source_rows: int = 2
    new_receipts: int = 2
    cached_snapshots: int = 30
    decisions: tuple = ()
    checkpoint_bytes: int = 500


class FakeService:
    def __init__(self):
        self.calls = []
        self.fail = False

    def run_once(self, **kwargs):
        self.calls.append(kwargs)

        if self.fail:
            raise RuntimeError("injected_failure")

        return FakeCycle()


def unverified_sources():
    return VerifiedSources(
        reference_source_verified=False,
        yes_book_source_verified=False,
        no_book_source_verified=False,
        fee_policy_verified=False,
    )


def verified_sources():
    return VerifiedSources(True, True, True, True)


def test_safe_defaults():
    service = FakeService()

    runtime = VNextServiceRuntime(
        service=service,
        sources=unverified_sources(),
    )

    result = runtime.run_once()

    assert result.source_rows == 2
    assert result.new_receipts == 2
    assert result.checkpoint_bytes == 500
    assert service.calls[0]["kill_switch"] is True
    assert service.calls[0]["fee_rate"] is None


def test_unverified_sources_cannot_disable_kill_switch():
    with pytest.raises(
        ValueError,
        match="Kill switch",
    ):
        VNextServiceRuntime(
            service=FakeService(),
            sources=unverified_sources(),
            fee_rate=0.07,
            config=RuntimeConfig(kill_switch=False),
        )


def test_missing_fee_cannot_disable_kill_switch():
    with pytest.raises(
        ValueError,
        match="fee rate",
    ):
        VNextServiceRuntime(
            service=FakeService(),
            sources=verified_sources(),
            fee_rate=None,
            config=RuntimeConfig(kill_switch=False),
        )


def test_stop_on_error():
    service = FakeService()
    service.fail = True

    runtime = VNextServiceRuntime(
        service=service,
        sources=unverified_sources(),
    )

    with pytest.raises(
        RuntimeError,
        match="injected_failure",
    ):
        runtime.run_forever()

    assert runtime._stop.is_set()
    assert len(service.calls) == 1


def test_manual_stop_prevents_cycles():
    service = FakeService()

    runtime = VNextServiceRuntime(
        service=service,
        sources=unverified_sources(),
    )

    runtime.stop()
    runtime.run_forever()

    assert service.calls == []


def test_continuous_loop_stops_after_three_cycles():
    service = FakeService()
    holder = {}

    def sleep_and_stop(_seconds):
        if len(service.calls) >= 3:
            holder["runtime"].stop()

    runtime = VNextServiceRuntime(
        service=service,
        sources=unverified_sources(),
        config=RuntimeConfig(
            interval_seconds=0.01,
        ),
        sleeper=sleep_and_stop,
    )

    holder["runtime"] = runtime
    runtime.run_forever()

    assert len(service.calls) == 3
    assert runtime._stop.is_set()
