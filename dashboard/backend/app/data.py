"""Bounded reads only. Never imports trading code or opens a writable live DB."""

import csv
import io
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock

from .schemas import Source


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    try:
        if value is None or value == "":
            return None
        raw = str(value)
        if raw.replace(".", "", 1).isdigit():
            number = float(raw)
            return datetime.fromtimestamp(number / 1000 if number > 1e11 else number, timezone.utc)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def probability(value):
    result = number(value)
    return result if result is not None and 0 <= result <= 1 else None


def freshness(value, threshold, detail="", at=None):
    date = stamp(value)
    if date is None:
        return Source(state="missing", detail="Timestamp missing or invalid. " + detail)
    age = ((at or now()) - date).total_seconds()
    state = "future" if age < 0 else "stale" if age > threshold else "ok"
    return Source(state=state, timestamp=date.isoformat(), age_seconds=age, detail=detail)


@contextmanager
def read_db(path):
    if not path.is_file():
        raise FileNotFoundError("Source database is missing")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")

        def authorize(action, first, second, database, trigger):
            if action in (
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
                sqlite3.SQLITE_RECURSIVE,
            ):
                return sqlite3.SQLITE_OK
            if (
                action == sqlite3.SQLITE_PRAGMA
                and second is None
                and first in ("query_only", "data_version", "schema_version")
            ):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)
        # Abort unexpectedly expensive queries in ~100 ms, never hold a long read.
        deadline = time.monotonic() + 0.1
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        yield conn
    finally:
        conn.close()


class Reader:
    def __init__(self, settings):
        self.settings = settings
        self.cache = {}
        self.lock = RLock()

    def cached(self, key, ttl, loader):
        with self.lock:
            old = self.cache.get(key)
            if old and time.monotonic() - old[0] < ttl:
                return old[1], old[2]
            try:
                value = loader()
                status = Source(state="ok", detail="Read-only source available", timestamp=now().isoformat())
                self.cache[key] = (time.monotonic(), value, status)
                return value, status
            except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
                status = Source(
                    state="missing" if isinstance(error, FileNotFoundError) else "error",
                    detail="Source unavailable ("
                    + type(error).__name__
                    + ")."
                    + (" Retaining last successful read." if old else ""),
                    timestamp=old[2].timestamp if old else None,
                )
                value = old[1] if old else None
                self.cache[key] = (time.monotonic(), value, status)
                return value, status

    def decisions(self):
        def load():
            with read_db(self.settings.decisions) as db:
                return [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (self.settings.recent_limit,)
                    )
                ]

        return self.cached("decisions", 1.5, load)

    def resolutions(self):
        def load():
            with read_db(self.settings.resolutions) as db:
                return [
                    dict(r) for r in db.execute("SELECT * FROM resolutions ORDER BY rowid DESC LIMIT 3000")
                ]

        return self.cached("resolutions", 15, load)

    def telemetry(self):
        def load():
            path = self.settings.telemetry
            if path.suffix in ('.sqlite3','.db'):
                with read_db(path) as db:
                    records=db.execute('SELECT a.snapshot FROM input_observations o JOIN acquisition a ON a.id=o.acquisition_id ORDER BY o.sequence DESC LIMIT 300').fetchall()
                rows=[]
                for record in reversed(records):
                    item=json.loads(record[0])
                    row={k:(v.get('__polybtc_datetime_utc__') if isinstance(v,dict) and '__polybtc_datetime_utc__' in v else v) for k,v in item.items()}
                    row['market_id']=row['condition_id']
                    row['btc_price']=row['reference_price']
                    rows.append(row)
                return rows
            with path.open("rb") as file:
                header = file.readline()
                file.seek(0, 2)
                size = file.tell()
                start = max(len(header), size - self.settings.tail_bytes)
                file.seek(start)
                if start > len(header):
                    file.readline()  # Discard potentially incomplete leading record.
                tail = file.read(self.settings.tail_bytes)
            # The collector emits one physical line per CSV record. Ignore a partial write.
            end = tail.rfind(b"\n")
            tail = tail[: end + 1] if end >= 0 else b""
            rows = list(csv.DictReader(io.StringIO((header + tail).decode("utf-8-sig"))))
            return [r for r in rows if None not in r and r.get("market_id") and stamp(r.get("observed_at"))]

        return self.cached("telemetry", 1, load)

    def report(self):
        def load():
            from .schemas import Report

            if self.settings.report.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Report too large")
            return Report.model_validate(json.loads(self.settings.report.read_text(encoding="utf-8")))

        return self.cached("report", 30, load)

    def runtime(self):
        def load():
            path = self.settings.trades.parent / "runtime_status.json"
            if path.stat().st_size > 65536:
                raise ValueError("Heartbeat too large")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("mode") not in ("paper_execution", "research", "data_collection")
                or payload.get("state") not in ("starting", "running", "stopping", "stopped", "failed")
            ):
                raise ValueError("Invalid runtime heartbeat")
            return payload

        return self.cached("runtime", 1, load)
