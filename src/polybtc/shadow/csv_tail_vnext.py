from __future__ import annotations

import csv
import hashlib
import io
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TAIL_VERSION = "csv_tail_vnext_v1"
SCHEMA_VERSION = 1


class SourceChanged(RuntimeError):
    """Source requires operator review before continuing."""


class InvalidCSV(RuntimeError):
    """A complete CSV record could not be parsed safely."""


@dataclass(frozen=True, slots=True)
class TailRow:
    row_id: str
    source_line_offset: int
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class TailBatch:
    rows: tuple[TailRow, ...]
    end_prefix_sha256: str
    start_offset: int
    end_offset: int
    source_identity: str
    file_size: int


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(stat: os.stat_result) -> str:
    return f"{stat.st_dev}:{stat.st_ino}"


def _decode_csv_row(
    raw: bytes,
    headers: tuple[str, ...],
) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
        reader = csv.reader(
            io.StringIO(text, newline=""),
            strict=True,
        )
        records = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise InvalidCSV("Invalid UTF-8 or CSV row") from exc

    if len(records) != 1:
        raise InvalidCSV("Expected exactly one physical CSV record")

    values = records[0]

    if len(values) != len(headers):
        raise InvalidCSV("CSV column count differs from header")

    return dict(zip(headers, values))


class VNextCSVTailer:
    """
    Read-only append follower with explicit ACK.

    Source files must use UTF-8 CSV with one record
    per physical line. Embedded newlines inside quoted
    fields are not supported.

    poll() never advances the durable checkpoint.
    ack() advances it after downstream success.

    Only one tailer process may own a given state
    database and source. The caller must enforce
    single-worker ownership.
    """

    def __init__(
        self,
        *,
        csv_path: Path,
        state_path: Path,
        startup: Literal["end", "beginning"] = "end",
        max_batch_rows: int = 200,
        max_line_bytes: int = 65536,
    ) -> None:
        self.csv_path = Path(csv_path)
        self.state_path = Path(state_path)

        if startup not in ("end", "beginning"):
            raise ValueError("Invalid startup policy")

        if max_batch_rows <= 0 or max_line_bytes <= 0:
            raise ValueError("Invalid tail limits")

        self.startup = startup
        self.max_batch_rows = max_batch_rows
        self.max_line_bytes = max_line_bytes

        self.state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.state_path),
            timeout=15,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tail_state (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    source_path TEXT NOT NULL,
                    source_identity TEXT NOT NULL,
                    header_sha256 TEXT NOT NULL,
                    header_end_offset INTEGER NOT NULL,
                    offset_bytes INTEGER NOT NULL,
                    acknowledged_prefix_sha256 TEXT NOT NULL
                )
            """)

            version = conn.execute("PRAGMA user_version").fetchone()[0]

            if version not in (0, SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported tail schema version: {version}")

            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _source_header(self):
        if not self.csv_path.is_file():
            raise FileNotFoundError(self.csv_path)

        with self.csv_path.open("rb") as file:
            stat = os.fstat(file.fileno())
            raw = file.readline(self.max_line_bytes + 1)

            if not raw.endswith(b"\n") or len(raw) > self.max_line_bytes:
                raise InvalidCSV("Missing or oversized complete header")

            try:
                decoded = raw.decode("utf-8-sig")
                headers = next(
                    csv.reader(
                        io.StringIO(decoded, newline=""),
                        strict=True,
                    )
                )
            except (UnicodeError, csv.Error, StopIteration) as exc:
                raise InvalidCSV("Invalid CSV header") from exc

            if (
                not headers
                or any(not name.strip() for name in headers)
                or len(headers) != len(set(headers))
            ):
                raise InvalidCSV("Empty or duplicate CSV column names")

            return (
                stat,
                raw,
                tuple(headers),
                file.tell(),
            )

    def _prefix_hash(self, offset: int) -> str:
        digest = hashlib.sha256()

        with self.csv_path.open("rb") as file:
            remaining = offset

            while remaining > 0:
                chunk = file.read(min(1048576, remaining))

                if not chunk:
                    raise SourceChanged("Source shorter than checkpoint")

                digest.update(chunk)
                remaining -= len(chunk)

        return digest.hexdigest()

    def _state(self):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM tail_state WHERE id=1").fetchone()

    def _ensure_state(self):
        state = self._state()

        if state is not None:
            return state

        stat, header, _, header_end = self._source_header()

        if self.startup == "beginning":
            offset = header_end
        else:
            # Start at the end of the last complete
            # physical record, not inside a partial row.
            with self.csv_path.open("rb") as file:
                data = file.read()

            last_newline = data.rfind(b"\n")
            offset = max(header_end, last_newline + 1)

        prefix = self._prefix_hash(offset)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                """
                INSERT OR IGNORE INTO tail_state (
                    id,
                    source_path,
                    source_identity,
                    header_sha256,
                    header_end_offset,
                    offset_bytes,
                    acknowledged_prefix_sha256
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(self.csv_path.resolve()),
                    _identity(stat),
                    _hash(header),
                    header_end,
                    offset,
                    prefix,
                ),
            )

            conn.execute("COMMIT")

        return self._state()

    def poll(self) -> TailBatch:
        state = self._ensure_state()

        if str(self.csv_path.resolve()) != state["source_path"]:
            raise SourceChanged(
                f"Configured source path changed: checkpoint {self.state_path.resolve()} "
                f"belongs to '{state['source_path']}', requested '{self.csv_path.resolve()}'. "
                "Resume the collector and runtime with the checkpoint's original CSV path. "
                "Do not delete or edit the checkpoint or trading ledger to switch sources."
            )

        stat, header, headers, header_end = self._source_header()

        if _identity(stat) != state["source_identity"]:
            raise SourceChanged("Source file rotated or replaced")

        if _hash(header) != state["header_sha256"]:
            raise SourceChanged("CSV header changed")

        offset = int(state["offset_bytes"])

        if offset < header_end or stat.st_size < offset:
            raise SourceChanged("Source truncated below checkpoint")

        if self._prefix_hash(offset) != state["acknowledged_prefix_sha256"]:
            raise SourceChanged("Acknowledged source bytes were modified")

        rows: list[TailRow] = []
        end_offset = offset

        with self.csv_path.open("rb") as file:
            file.seek(offset)

            while len(rows) < self.max_batch_rows:
                line_start = file.tell()
                raw = file.readline(self.max_line_bytes + 1)

                if not raw:
                    break

                if len(raw) > self.max_line_bytes:
                    raise InvalidCSV("CSV line exceeds safety limit")

                if not raw.endswith(b"\n"):
                    # Partial trailing write:
                    # leave it unacknowledged.
                    break

                # A complete physical line is one
                # record under this collector contract.
                values = _decode_csv_row(raw, headers)

                row_id = _hash(
                    (state["source_identity"] + ":" + str(line_start) + ":").encode(
                        "utf-8"
                    )
                    + raw
                )

                rows.append(
                    TailRow(
                        row_id=row_id,
                        source_line_offset=line_start,
                        values=values,
                    )
                )

                end_offset = file.tell()

        return TailBatch(
            rows=tuple(rows),
            start_offset=offset,
            end_offset=end_offset,
            source_identity=state["source_identity"],
            file_size=stat.st_size,
            end_prefix_sha256=self._prefix_hash(end_offset),
        )

    def ack(self, batch: TailBatch) -> None:
        """
        Commit the batch boundary only after successful
        downstream processing.

        Raises on out-of-order ACK or modified source.
        """
        state = self._state()

        if state is None:
            raise RuntimeError("Tailer not initialized")

        if batch.start_offset != state["offset_bytes"]:
            raise RuntimeError("Out-of-order or duplicate ACK")

        stat, header, _, _ = self._source_header()

        if (
            _identity(stat) != batch.source_identity
            or _identity(stat) != state["source_identity"]
            or _hash(header) != state["header_sha256"]
            or stat.st_size < batch.end_offset
        ):
            raise SourceChanged("Source changed before acknowledgement")

        # Verify the already-acknowledged prefix AND
        # compute a new immutable checkpoint fingerprint.
        if self._prefix_hash(batch.start_offset) != state["acknowledged_prefix_sha256"]:
            raise SourceChanged("Acknowledged prefix changed before ACK")

        new_hash = self._prefix_hash(batch.end_offset)

        if new_hash != batch.end_prefix_sha256:
            raise SourceChanged("Unacknowledged batch bytes were modified")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            cursor = conn.execute(
                """
                UPDATE tail_state
                SET offset_bytes=?,
                    acknowledged_prefix_sha256=?
                WHERE id=1
                  AND offset_bytes=?
                  AND source_identity=?
                  AND acknowledged_prefix_sha256=?
            """,
                (
                    batch.end_offset,
                    new_hash,
                    batch.start_offset,
                    batch.source_identity,
                    state["acknowledged_prefix_sha256"],
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Concurrent checkpoint modification")

            conn.execute("COMMIT")

    def checkpoint(self) -> int:
        return int(self._ensure_state()["offset_bytes"])
