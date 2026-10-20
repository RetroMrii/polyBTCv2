"""Committed typed observations, with durable consumer receipt/cursor ownership."""

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import sqlite3
from polybtc.data.snapshot_codec_vnext import _deserialize
from polybtc.shadow.csv_tail_vnext import SourceChanged


@dataclass(frozen=True)
class ObservationRow:
    row_id: str
    snapshot: object
    sequence: int


@dataclass(frozen=True)
class ObservationBatch:
    rows: tuple
    start_offset: int
    end_offset: int
    source_identity: str


class SQLiteInputTailer:
    receipt_checkpoint_atomic = True

    def __init__(self, input_path, store):
        self.input_path = Path(input_path).resolve()
        self.owner = store
        self.state_path = store.path
        self.reader = sqlite3.connect(self.input_path.as_uri() + "?mode=ro", uri=True)
        self.reader.row_factory = sqlite3.Row
        self.identity = self.reader.execute(
            "SELECT value FROM input_metadata WHERE name='identity'"
        ).fetchone()[0]
        with store.atomic():
            store.connection.execute(
                "CREATE TABLE IF NOT EXISTS input_cursor (id INTEGER PRIMARY KEY CHECK(id=1), input_path TEXT NOT NULL, input_identity TEXT NOT NULL, sequence INTEGER NOT NULL)"
            )
            old = store.connection.execute(
                "SELECT * FROM input_cursor WHERE id=1"
            ).fetchone()
            if old is None:
                self.reader.close()
                raise SourceChanged(
                    "Missing migrated input cursor; never reset availability"
                )
            elif (
                old["input_path"] != str(self.input_path)
                or old["input_identity"] != self.identity
            ):
                raise SourceChanged("Typed input store binding changed")

    def checkpoint(self):
        return self.owner.connection.execute(
            "SELECT sequence FROM input_cursor WHERE id=1"
        ).fetchone()[0]

    def poll(self):
        identity = self.reader.execute(
            "SELECT value FROM input_metadata WHERE name='identity'"
        ).fetchone()[0]
        if identity != self.identity:
            raise SourceChanged("Typed input identity changed")
        start = self.checkpoint()
        maximum = self.reader.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM input_observations"
        ).fetchone()[0]
        if maximum < start:
            raise SourceChanged("Input stream truncated below durable cursor")
        items = self.reader.execute(
            "SELECT o.sequence,o.runtime_id,o.source_file,a.id,a.snapshot FROM input_observations o LEFT JOIN acquisition a ON a.id=o.acquisition_id WHERE o.sequence>? ORDER BY o.sequence LIMIT 256",
            (start,),
        ).fetchall()
        rows = []
        for item in items:
            if (
                item["snapshot"] is None
                or hashlib.sha256(item["snapshot"].encode()).hexdigest() != item["id"]
            ):
                raise SourceChanged("Canonical input hash mismatch")
            row = replace(
                _deserialize(item["snapshot"]),
                snapshot_id=item["runtime_id"],
                source_file=item["source_file"],
            )
            rows.append(ObservationRow(row.snapshot_id, row, item["sequence"]))
        return ObservationBatch(
            tuple(rows), start, rows[-1].sequence if rows else start, self.identity
        )

    def ack(self, batch):
        if batch.source_identity != self.identity:
            raise SourceChanged("Wrong typed input batch")
        if batch.end_offset < batch.start_offset:
            raise SourceChanged("Invalid input cursor")
        result = self.owner.connection.execute(
            "UPDATE input_cursor SET sequence=? WHERE id=1 AND sequence=?",
            (batch.end_offset, batch.start_offset),
        )
        if result.rowcount != 1:
            raise SourceChanged("Input cursor advanced concurrently")

    def close(self):
        self.reader.close()


class InputHistory:
    """Rebuildable projection; original inputs and first receipts are authoritative."""

    def __init__(self, input_path, store):
        self.owner = store
        self.path = store.path
        self.reader = sqlite3.connect(
            Path(input_path).resolve().as_uri() + "?mode=ro", uri=True
        )
        self.reader.row_factory = sqlite3.Row

    def load(self):
        # Reconstruct once at startup. The coordinator retains/prunes its memory
        # window thereafter. No historical receipt is manufactured.
        receipts = {
            r["snapshot_id"]: r["first_received_at_utc"]
            for r in self.owner.connection.execute(
                "SELECT snapshot_id,first_received_at_utc FROM receipts"
            )
        }
        from datetime import datetime

        result = []
        for item in self.reader.execute(
            "SELECT o.runtime_id,o.source_file,a.id,a.snapshot FROM input_observations o LEFT JOIN acquisition a ON a.id=o.acquisition_id ORDER BY o.sequence"
        ):
            if item["runtime_id"] in receipts:
                if (
                    item["snapshot"] is None
                    or hashlib.sha256(item["snapshot"].encode()).hexdigest()
                    != item["id"]
                ):
                    raise SourceChanged("Canonical history hash mismatch")
                result.append(
                    replace(
                        _deserialize(item["snapshot"]),
                        snapshot_id=item["runtime_id"],
                        source_file=item["source_file"],
                        ingested_at=datetime.fromisoformat(
                            receipts[item["runtime_id"]]
                        ),
                    )
                )
        if len(result) != len(receipts):
            raise SourceChanged("Receipted input missing from authoritative history")
        return result

    def store(self, rows):
        # The input is already committed, and its receipt committed with cursor.
        # No second persisted copy or write barrier is necessary.
        return None

    def prune(self, *, at, retain_ids=()):
        return 0

    def close(self):
        self.reader.close()
