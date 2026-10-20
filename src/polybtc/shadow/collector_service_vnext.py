from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.collector_bridge_vnext import (
    VNextCollectorBridge,
)
from polybtc.shadow.csv_tail_vnext import (
    TailRow,
    VNextCSVTailer,
)
from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.stream_driver_vnext import (
    VNextSnapshotStreamDriver,
)


SERVICE_VERSION = "collector_service_vnext_v1"
HISTORY_RETENTION_SECONDS = 900

RowConverter = Callable[[TailRow], SnapshotRecord]


@dataclass(frozen=True, slots=True)
class ServiceResult:
    source_rows: int
    new_receipts: int
    cached_snapshots: int
    decisions: tuple
    checkpoint_bytes: int


from polybtc.data.snapshot_codec_vnext import _utc, _serialize, _deserialize


class VNextSnapshotHistory:
    """
    Durable, bounded snapshot-history cache.

    Does not reconstruct ingest times or modify
    prediction data after it has been persisted.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._connect() as conn:
            # FULL durability with WAL avoids rollback-journal create/delete
            # barriers for each incoming observation.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    condition_id TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_snapshot_history_observed
                ON snapshots(observed_at_utc)
            """)

    def _connect(self):
        conn = sqlite3.connect(
            str(self.path),
            timeout=15,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def store(
        self,
        rows: list[SnapshotRecord],
    ) -> None:
        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            for row in rows:
                payload = _serialize(row)

                existing = conn.execute(
                    """
                    SELECT record_json
                    FROM snapshots
                    WHERE snapshot_id=?
                """,
                    (row.snapshot_id,),
                ).fetchone()

                if existing is not None:
                    if existing["record_json"] != payload:
                        raise ValueError(
                            "Conflicting cached snapshot: " + row.snapshot_id
                        )

                    continue

                conn.execute(
                    """
                    INSERT INTO snapshots (
                        snapshot_id,
                        condition_id,
                        observed_at_utc,
                        record_json
                    )
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        row.snapshot_id,
                        row.condition_id.strip().lower(),
                        _utc(row.observed_at).isoformat(),
                        payload,
                    ),
                )

            conn.execute("COMMIT")

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def load(self) -> list[SnapshotRecord]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT record_json
                FROM snapshots
                ORDER BY observed_at_utc, snapshot_id
            """).fetchall()

        return [_deserialize(row["record_json"]) for row in rows]

    def prune(self, *, at: datetime, retain_ids=()) -> int:
        """
        Prune only after successful downstream
        processing and CSV acknowledgement.
        """
        cutoff = (_utc(at) - timedelta(seconds=HISTORY_RETENTION_SECONDS)).isoformat()

        with self._connect() as conn:
            ids = tuple(retain_ids)
            extra = ' AND snapshot_id NOT IN ('+','.join('?' for _ in ids)+')' if ids else ''
            cursor = conn.execute('DELETE FROM snapshots WHERE observed_at_utc < ?'+extra, (cutoff,*ids))

            return cursor.rowcount


class VNextCollectorService:
    """
    Executes one read-only collector-processing cycle.

    The caller provides a converter for the production
    CSV schema.

    No polling loop, network calls, real orders,
    market discovery, or settlement.

    Only one service worker may process this source
    and its state databases at a time.
    """

    def __init__(
        self,
        *,
        tailer: VNextCSVTailer,
        bridge: VNextCollectorBridge,
        history: VNextSnapshotHistory,
        driver: VNextSnapshotStreamDriver,
        converter: RowConverter,
    ) -> None:
        if not callable(converter):
            raise TypeError("Row converter must be callable")

        self.tailer = tailer
        self.bridge = bridge
        self.history = history
        self.driver = driver
        self.converter = converter
        self._memory = None

        paths = [
            tailer.state_path.resolve(),
            bridge.path.resolve(),
            history.path.resolve(),
            driver.journal.path.resolve(),
            driver.adapter.runner.ledger.path.resolve(),
        ]

        if len(paths) != len(set(paths)):
            owner = getattr(bridge, 'store', None)
            if owner is None or any(part is not owner for part in (
                getattr(tailer,'owner',None),getattr(history,'owner',None),
                getattr(driver.journal,'store',None),getattr(driver.adapter.runner.ledger,'store',None),
            )):
                raise ValueError("Service state databases must be separate or share one explicit owner")

    def run_once(
        self,
        *,
        sources: VerifiedSources,
        fee_rate: float | None,
        kill_switch: bool = False,
        evaluate_decisions: bool = True,
    ) -> ServiceResult:
        if not isinstance(evaluate_decisions, bool):
            raise TypeError("evaluate_decisions must be a boolean")
        if not isinstance(sources, VerifiedSources):
            raise TypeError("Expected VerifiedSources")

        guard=getattr(self,"clock_guard",None)
        if guard:guard.stage="input_receipt"
        if self._memory is None:
            self._memory={row.snapshot_id:row for row in self.history.load()}
        batch = self.tailer.poll()

        # The complete source row must first pass
        # the production schema converter.
        converted: list[SnapshotRecord] = []

        for tail_row in batch.rows:
            snapshot = self.converter(tail_row)

            if not isinstance(snapshot, SnapshotRecord):
                raise TypeError("Converter must return SnapshotRecord")

            if snapshot.snapshot_id != tail_row.row_id:
                raise ValueError("Converter must preserve stable tail row_id")

            converted.append(snapshot)

        # Persist first-receipt time before trying to
        # build a model decision. Replayed batches get
        # their original receipt times.
        atomic_receipt = getattr(self.tailer, 'receipt_checkpoint_atomic', False)
        if atomic_receipt and converted:
            with self.bridge.store.atomic():
                intake = self.bridge.ingest(converted)
                self.tailer.ack(batch)
        else:
            intake = self.bridge.ingest(converted)

        # Receipts are durable and the source remains unacknowledged. Merge
        # the new rows with durable history for evaluation; persist the cache
        # before acknowledgement, avoiding a redundant disk barrier while the
        # execution quote is aging. A crash re-reads the original CSV/receipt;
        # immutable journal claims prevent any second evaluation or fill.
        cached = dict(self._memory) if self._memory is not None else {row.snapshot_id: row for row in self.history.load()}
        for row in intake.snapshots:
            if row.snapshot_id in cached and cached[row.snapshot_id] != row:
                raise ValueError("Conflicting cached snapshot: " + row.snapshot_id)
            cached[row.snapshot_id] = row
        history_rows = list(cached.values())
        if atomic_receipt:
            self._memory = cached  # Cursor is durable even if the next clock sample pauses.

        # A no-row cycle must still advance time-driven
        # horizon finalization.
        #
        # Do not use a historical target horizon as the
        # processing clock.
        if guard:guard.stage="post_intake"
        processing_at = _utc(self.bridge.clock())
        if processing_at < intake.received_at_utc:
            raise RuntimeError("Processing clock moved backwards")

        results = []
        try:
            if evaluate_decisions:
                guard = getattr(self, 'clock_guard', None)
                epoch = guard.eligible_after if guard else None
                eligible_history = history_rows if epoch is None else [
                    row for row in history_rows
                    if row.observed_at >= epoch and row.ingested_at >= epoch
                    and row.market_end_at is not None
                    and row.market_end_at-timedelta(seconds=300) >= epoch
                ]
                if guard:guard.stage="verification_inference_execution"
                results = self.driver.process(
                    snapshots=eligible_history,
                    at=processing_at,
                    sources=sources,
                    fee_rate=fee_rate,
                    kill_switch=kill_switch,
                )
        finally:
            # Also preserve history on an evaluation exception. If this write
            # itself fails, the checkpoint still cannot advance.
            self.history.store(intake.snapshots)
            self._memory = cached

        # Nothing above is acknowledged until all
        # downstream operations have returned.
        if not atomic_receipt and batch.end_offset != batch.start_offset:
            self.tailer.ack(batch)

        # Pruning is deliberately last. If this fails,
        # the acknowledged stream remains recoverable.
        pending = [*self.driver.journal.decisions(status='AWAITING_EXECUTION_ADAPTER'),
                   *self.driver.journal.decisions(status='PROCESSING')]
        pending_markets = {row['condition_id'] for row in pending}
        retained = {row.snapshot_id for row in cached.values() if row.condition_id.strip().lower() in pending_markets}
        self.history.prune(at=processing_at, retain_ids=retained)
        cutoff = processing_at-timedelta(seconds=HISTORY_RETENTION_SECONDS)
        self._memory = {key:row for key,row in cached.items() if row.observed_at >= cutoff or key in retained}

        return ServiceResult(
            source_rows=len(batch.rows),
            new_receipts=intake.new_records,
            cached_snapshots=len(history_rows),
            decisions=tuple(results),
            checkpoint_bytes=self.tailer.checkpoint(),
        )
