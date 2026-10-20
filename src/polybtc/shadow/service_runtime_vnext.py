from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from polybtc.shadow.collector_service_vnext import (
    VNextCollectorService,
)
from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.sqlite_wal_vnext import WALReaders
from polybtc.shadow.operating_mode_vnext import OperatingMode, supported_mode
from polybtc.shadow.clock_vnext import ClockPaused


LOG = logging.getLogger("polybtc.shadow.vnext.runtime")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    version: str = "service_runtime_vnext_v1"
    interval_seconds: float = 0.25
    kill_switch: bool = True
    stop_on_error: bool = True
    mode: OperatingMode = OperatingMode.RESEARCH_SHADOW
    paper_execution_enabled: bool = False

    def __post_init__(self):
        object.__setattr__(self, "mode", supported_mode(self.mode))
        if any(type(value) is not bool for value in (
            self.kill_switch, self.stop_on_error, self.paper_execution_enabled,
        )):
            raise ValueError("Runtime execution controls must be booleans")
        if self.paper_execution_enabled and self.mode is not OperatingMode.PAPER_EXECUTION:
            raise ValueError("Paper execution requires paper_execution mode")


@dataclass(frozen=True, slots=True)
class CycleSummary:
    observed_at_utc: str
    source_rows: int
    new_receipts: int
    cached_snapshots: int
    decisions: int
    checkpoint_bytes: int
    mode: str = OperatingMode.RESEARCH_SHADOW.value
    paper_execution_enabled: bool = False
    kill_switch: bool = True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VNextServiceRuntime:
    """
    Continuous read-only intake and shadow processing.

    Does not create network clients or submit orders.

    The caller owns:
      - CSV source selection
      - row conversion
      - provenance assertions
      - fee policy
      - database paths

    The runtime stops on unexpected processing errors
    by default. It does not automatically reset or
    reconcile unresolved trading-ledger claims.
    """

    def __init__(
        self,
        *,
        service: VNextCollectorService,
        sources: VerifiedSources,
        fee_rate: float | None = None,
        config: RuntimeConfig | None = None,
        clock: Callable[[], datetime] = _utc_now,
        sleeper: Callable[[float], None] = time.sleep,
        status_path: Path | None = None,
        model_path: Path | None = None,
        database_paths=(),
        operating_configuration=None,
        clock_guard=None,
        resources=(),
        maintenance=None,
    ) -> None:
        self.maintenance=maintenance
        self._resources = list(resources)
        self.service = service
        self.clock_guard = clock_guard
        self._last_publication = None
        self.operating_configuration = dict(operating_configuration or {})
        self.sources = sources
        self.fee_rate = fee_rate
        self.config = config or RuntimeConfig()
        self.clock = clock
        self.sleeper = sleeper

        if not math.isfinite(self.config.interval_seconds) or self.config.interval_seconds <= 0:
            raise ValueError("Polling interval must be positive")

        if not isinstance(sources, VerifiedSources):
            raise TypeError("Expected VerifiedSources")

        if self.config.mode is OperatingMode.PAPER_EXECUTION:
            from polybtc.shadow.source_verification_vnext import VNextSourceVerificationAdapter
            from polybtc.data.fee_policy_cache_vnext import VNextFeePolicyCache
            from polybtc.shadow.executor_vnext import VNextShadowExecutor
            from polybtc.shadow.operating_mode_vnext import bind_state_directory

            driver = self.service.driver
            if not isinstance(driver.source_verifier, VNextSourceVerificationAdapter):
                raise ValueError("Paper mode requires the independent source verifier")
            if not isinstance(driver.fee_cache, VNextFeePolicyCache):
                raise ValueError("Paper mode requires a market-specific fee cache")
            if type(driver.adapter.runner.executor) is not VNextShadowExecutor:
                raise ValueError("Paper mode requires the shadow-only executor")
            # Builders bind state before creating DBs. Never adopt legacy state.
            state_dir = driver.adapter.runner.ledger.path.parent
            state_paths = (
                self.service.tailer.state_path, self.service.bridge.path,
                self.service.history.path, driver.journal.path,
                driver.adapter.runner.ledger.path,
            )
            if any(Path(path).resolve().parent != state_dir.resolve() for path in state_paths):
                raise ValueError("Every paper runtime database must use its isolated state directory")
            bind_state_directory(state_dir, OperatingMode.PAPER_EXECUTION)
        elif not self.config.kill_switch:
            if not all(
                (
                    sources.reference_source_verified,
                    sources.yes_book_source_verified,
                    sources.no_book_source_verified,
                    sources.fee_policy_verified,
                )
            ):
                raise ValueError(
                    "Kill switch cannot be disabled "
                    "without verified source and fee policy"
                )

            if fee_rate is None:
                raise ValueError("Verified fee rate required")
            raise ValueError("Research and collection runtimes cannot enable execution; use paper mode")

        self._stop = threading.Event()
        self.status_path, self.model_path = status_path, model_path
        self._failed = False
        self._in_cycle = False
        self._last_summary = None
        self._model = None
        if model_path is not None:
            from polybtc.operations import model_identity
            self._model = model_identity(model_path)
        self._wal_readers = WALReaders(database_paths)
        try:
            self._publish('starting')
        except BaseException:
            self._close_resources()
            raise

    def _close_resources(self):
        self._wal_readers.close()
        while self._resources:
            self._resources.pop().close()

    def _publish(self, state):
        if self.status_path is not None:
            stamp = time.monotonic()
            if self._last_publication is not None and self._last_publication[0] == state and stamp-self._last_publication[1] < 1.0:
                return
            from polybtc.operations import atomic_status
            atomic_status(self.status_path, dict(version=self.config.version,pid=os.getpid(),
                observed_at=self.clock().isoformat(),state=state,mode=self.config.mode.value,
                kill_switch=self.config.kill_switch,live_enabled=False,model=self._model,
                poll_interval_seconds=self.config.interval_seconds,
                operating_configuration=self.operating_configuration,
                clock_health=self.clock_guard.status() if self.clock_guard else None,
                last_cycle=asdict(self._last_summary) if self._last_summary else None,
                failure='runtime_cycle_failed' if self._failed else None))
            self._last_publication = (state, stamp)

    def stop(self) -> None:
        self._stop.set()
        self._publish('failed' if self._failed else 'stopping' if self._in_cycle else 'stopped')
        if not self._in_cycle:
            self._close_resources()

    def run_once(self) -> CycleSummary | None:
        if self._stop.is_set(): raise RuntimeError('Runtime stopped')
        try:
            if self.clock_guard is not None:
                self.clock_guard.stage="cycle_start"
                self.clock_guard.now()
            if self.model_path is not None:
                from polybtc.operations import model_identity
                if model_identity(self.model_path)['sha256']!=self._model['sha256']:
                    raise RuntimeError('Model artifact changed during runtime')
            if self._stop.is_set():
                raise RuntimeError('Runtime stopped before cycle')
            self._in_cycle=True
            result=self._cycle()
            self._in_cycle=False
            self._last_summary=result
            self._publish('stopped' if self._stop.is_set() else 'running')
            if self._stop.is_set():
                self._close_resources()
            return result
        except ClockPaused:
            self._in_cycle = False
            if self.clock_guard is not None:
                try:
                    self.clock_guard.flush()
                except BaseException:
                    self._failed = True
                    self._stop.set()
                    self._publish('failed')
                    raise
            self._publish('clock_paused')
            return None
        except KeyboardInterrupt:
            self._in_cycle=False
            self.stop()
            raise
        except Exception:
            self._in_cycle=False
            self._failed=True
            self._stop.set()
            try:
                self._publish('failed')
            finally:
                self._close_resources()
            raise

    def _cycle(self) -> CycleSummary:
        # A true kill switch always wins; merely choosing paper mode cannot arm it.
        kill_switch = self.config.kill_switch
        if self.config.mode is OperatingMode.PAPER_EXECUTION:
            kill_switch = kill_switch or not self.config.paper_execution_enabled
        elif self.config.mode is OperatingMode.DATA_COLLECTION:
            kill_switch = True
        result = self.service.run_once(
            sources=self.sources,
            fee_rate=self.fee_rate,
            kill_switch=kill_switch,
            evaluate_decisions=self.config.mode is not OperatingMode.DATA_COLLECTION,
        )

        if self.maintenance is not None and not self._stop.is_set():
            if self.clock_guard:self.clock_guard.stage="settlement"
            self.maintenance()

        summary = CycleSummary(
            observed_at_utc=self.clock().isoformat(),
            source_rows=result.source_rows,
            new_receipts=result.new_receipts,
            cached_snapshots=result.cached_snapshots,
            decisions=len(result.decisions),
            checkpoint_bytes=result.checkpoint_bytes,
            mode=self.config.mode.value,
            paper_execution_enabled=self.config.paper_execution_enabled,
            kill_switch=kill_switch,
        )

        LOG.info(
            "cycle %s",
            json.dumps(
                summary.__dict__
                if hasattr(summary, "__dict__")
                else {
                    "observed_at_utc": summary.observed_at_utc,
                    "source_rows": summary.source_rows,
                    "new_receipts": summary.new_receipts,
                    "cached_snapshots": summary.cached_snapshots,
                    "decisions": summary.decisions,
                    "checkpoint_bytes": summary.checkpoint_bytes,
                    "mode": summary.mode,
                    "paper_execution_enabled": summary.paper_execution_enabled,
                    "kill_switch": summary.kill_switch,
                },
                sort_keys=True,
            ),
        )

        return summary

    def run_forever(self) -> None:
        LOG.info(
            "Starting %s, mode=%s, kill_switch=%s, paper_execution_enabled=%s",
            self.config.version,
            self.config.mode.value,
            self.config.kill_switch,
            self.config.paper_execution_enabled,
        )

        while not self._stop.is_set():
            try:
                self.run_once()

            except KeyboardInterrupt:
                LOG.info("Keyboard interrupt received")
                self.stop()
                break

            except Exception:
                LOG.error("Collector cycle failed; runtime stopped")
                self.stop()
                raise

            if not self._stop.is_set():
                self.sleeper(self.config.interval_seconds)

        LOG.info("Runtime stopped")
