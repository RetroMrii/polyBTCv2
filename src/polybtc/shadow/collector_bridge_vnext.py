from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.stream_driver_vnext import (
    StreamResult,
    VNextSnapshotStreamDriver,
)


BRIDGE_VERSION = "collector_bridge_vnext_v1"
SCHEMA_VERSION = 1

# Used only to exclude importer-generated ingest times
# from the immutable source-record fingerprint.
_FINGERPRINT_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _fingerprint(row: SnapshotRecord) -> str:
    """
    Fingerprint the imported source record while
    excluding its reconstructed ingest timestamp.

    A record with the same snapshot_id but different
    source contents is a data integrity conflict.
    """
    source_record = replace(
        row,
        ingested_at=_FINGERPRINT_TIME,
    )

    return hashlib.sha256(repr(source_record).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IntakeResult:
    snapshots: list[SnapshotRecord]
    new_records: int
    previously_received: int
    received_at_utc: datetime


class VNextCollectorBridge:
    """
    Durable first-receipt tracking for SnapshotRecord.

    The caller supplies snapshots from the existing
    v1.1 importer. This bridge does not parse CSV,
    poll external APIs, or reconstruct receipt times
    from historical source timestamps.

    Restart invariant:
      Same snapshot_id + same source contents
      -> same persisted first-receipt timestamp.

    No execution or trading occurs here.
    """

    def __init__(
        self,
        *,
        state_path: Path,
        clock: Callable[[], datetime] | None = None,
        store=None,
    ) -> None:
        self.store = store
        self.path = Path(state_path)
        if store is not None and self.path.resolve()!=store.path: raise ValueError("Store/path mismatch")
        self.clock = clock or (lambda: datetime.now(timezone.utc))

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.store is not None: return self.store.lease("receipts")
        conn = sqlite3.connect(
            str(self.path),
            timeout=15,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")

        return conn

    def _initialize(self) -> None:
        conn = self._connect()

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")

            version = conn.execute("PRAGMA user_version").fetchone()[0]

            if version not in (0, SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported bridge schema: {version}")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    snapshot_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    first_received_at_utc TEXT NOT NULL,
                    bridge_version TEXT NOT NULL
                )
            """)

            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

            conn.execute("COMMIT")

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def ingest(
        self,
        rows: list[SnapshotRecord],
    ) -> IntakeResult:
        now = _utc(self.clock())
        seen: dict[str, tuple[SnapshotRecord, str]] = {}

        # Validate every record before modifying state.
        for row in rows:
            if not isinstance(row, SnapshotRecord):
                raise TypeError("Expected SnapshotRecord")

            if not isinstance(row.snapshot_id, str) or not row.snapshot_id.strip():
                raise ValueError("Invalid snapshot_id")

            if not isinstance(row.condition_id, str) or not row.condition_id.strip():
                raise ValueError("Invalid condition_id")

            observed = _utc(row.observed_at)

            # A future local write timestamp cannot be
            # accepted as a past observation.
            if observed > now:
                raise ValueError("Snapshot observation is in the future")

            fingerprint = _fingerprint(row)
            existing = seen.get(row.snapshot_id)

            if existing is not None and existing[1] != fingerprint:
                raise ValueError(
                    "Conflicting snapshot_id in input batch: " + row.snapshot_id
                )

            seen[row.snapshot_id] = (
                row,
                fingerprint,
            )

        if not seen:
            return IntakeResult([], 0, 0, now)
        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            normalized: list[SnapshotRecord] = []
            new_records = 0
            previously_received = 0

            for snapshot_id, (row, fingerprint) in seen.items():
                existing = conn.execute(
                    """
                    SELECT
                        source_fingerprint,
                        first_received_at_utc
                    FROM receipts
                    WHERE snapshot_id=?
                """,
                    (snapshot_id,),
                ).fetchone()

                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO receipts (
                            snapshot_id,
                            source_fingerprint,
                            first_received_at_utc,
                            bridge_version
                        )
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            snapshot_id,
                            fingerprint,
                            _stamp(now),
                            BRIDGE_VERSION,
                        ),
                    )

                    received = now
                    new_records += 1

                else:
                    if existing["source_fingerprint"] != fingerprint:
                        raise ValueError(
                            "Previously recorded snapshot "
                            "has conflicting source contents: " + snapshot_id
                        )

                    received = _utc(
                        datetime.fromisoformat(existing["first_received_at_utc"])
                    )
                    previously_received += 1

                normalized.append(
                    replace(
                        row,
                        ingested_at=received,
                    )
                )

            conn.execute("COMMIT")

            normalized.sort(
                key=lambda row: (
                    _utc(row.observed_at),
                    _utc(row.ingested_at),
                    row.snapshot_id,
                )
            )

            return IntakeResult(
                snapshots=normalized,
                new_records=new_records,
                previously_received=previously_received,
                received_at_utc=now,
            )

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def process(
        self,
        *,
        rows: list[SnapshotRecord],
        driver: VNextSnapshotStreamDriver,
        sources: VerifiedSources,
        fee_rate: float | None,
        kill_switch: bool = False,
    ) -> tuple[IntakeResult, list[StreamResult]]:
        """
        Pass the same receipt clock to the driver.

        This prevents the caller from substituting an
        earlier historical prediction timestamp for
        the actual prospective processing time.

        Intake and journal updates use separate SQLite
        transactions. On failure, persisted receipts
        remain available for restart-safe reprocessing.
        """
        intake = self.ingest(rows)

        results = driver.process(
            snapshots=intake.snapshots,
            at=intake.received_at_utc,
            sources=sources,
            fee_rate=fee_rate,
            kill_switch=kill_switch,
        )

        return intake, results

    def receipt_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT COUNT(*) AS total
                FROM receipts
            """).fetchone()

        return int(row["total"])
