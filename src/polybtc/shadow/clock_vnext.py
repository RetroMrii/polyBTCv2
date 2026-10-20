"""Fail-closed UTC discontinuity handling; monotonic time is never market time."""

from __future__ import annotations
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
from uuid import uuid4


class ClockPaused(RuntimeError):
    pass


class ClockGuard:
    # Health detection budget, NOT an allowance for source ages/future sources.
    MAX_DISCONTINUITY_SECONDS = 0.05
    STABILIZATION_SECONDS = 2.0

    def __init__(
        self,
        path: Path,
        *,
        utc=None,
        monotonic=time.monotonic,
        watermark=None,
        store=None,
    ):
        self.path = Path(path)
        self.store = store
        self.pending = []
        self.stage = "startup"
        self.utc = utc or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic
        self.session = str(uuid4())
        self.previous = None
        self.high_water = watermark
        self.incident = None
        self.eligible_after = None
        self.stable_since = None
        self._acknowledged = False
        with closing(self._db()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS clock_events (sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            records = db.execute(
                "SELECT kind,payload FROM clock_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        if records:
            kind, payload = records
            item = json.loads(payload)
            if kind == "incident":
                self.incident = item
                self.high_water = max(
                    filter(
                        None,
                        (
                            self.high_water,
                            datetime.fromisoformat(item["high_water_utc"]),
                        ),
                    )
                )
            elif kind == "acknowledged":
                self.eligible_after = datetime.fromisoformat(item["eligible_after_utc"])
                self._acknowledged = True
                if item.get("high_water_utc"):
                    self.high_water = max(
                        filter(
                            None,
                            (
                                self.high_water,
                                datetime.fromisoformat(item["high_water_utc"]),
                            ),
                        )
                    )
            else:
                raise ValueError("Unknown persisted clock event")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _append(self, event_id, kind, payload):
        if self.store is not None and self.store.connection.in_transaction:
            # The coordinator unwinds/rolls back its outcome transaction before
            # persisting this incident. A durable PROCESSING claim remains.
            self.pending.append((event_id, kind, payload))
            return
        # Explicit close: never keep an accidental SQLite writer alive.
        db = self._db()
        try:
            with db:
                db.execute(
                    "INSERT INTO clock_events(event_id,kind,payload) VALUES (?,?,?)",
                    (
                        event_id,
                        kind,
                        json.dumps(payload, sort_keys=True, allow_nan=False),
                    ),
                )
        finally:
            db.close()

    def flush(self):
        if self.store is not None and self.store.connection.in_transaction:
            raise RuntimeError(
                "Clock incident cannot be flushed inside an outcome transaction"
            )
        while self.pending:
            self._append(*self.pending[0])
            self.pending.pop(0)

    def _sample(self):
        before = self.monotonic()
        utc = self.utc()
        after = self.monotonic()
        if utc.tzinfo is None or utc.utcoffset() is None:
            raise ValueError("Clock UTC must be timezone-aware")
        if not all(math.isfinite(v) for v in (before, after)) or after < before:
            raise RuntimeError("Invalid monotonic clock")
        return utc.astimezone(timezone.utc), before, after

    def _observe(self):
        current = self._sample()
        utc, before, after = current
        reason = None
        elapsed = utc_delta = None
        if self.previous:
            old_utc, old_before, old_after = self.previous
            elapsed = before - old_after
            utc_delta = (utc - old_utc).total_seconds()
            if before < old_after:
                raise RuntimeError("Monotonic clock moved backwards")
            # UTC elapsed must lie within the bracketed monotonic elapsed range,
            # allowing only the explicit discontinuity detection budget.
            upper_elapsed = after - old_before
            if utc_delta < 0:
                reason = "utc_moved_backwards"
            elif (
                utc_delta < elapsed - self.MAX_DISCONTINUITY_SECONDS
                or utc_delta > upper_elapsed + self.MAX_DISCONTINUITY_SECONDS
            ):
                reason = "utc_discontinuity"
        elif self.high_water is not None and utc < self.high_water:
            reason = "utc_before_durable_state"
        self.high_water = max(filter(None, (self.high_water, utc)))
        if reason and not (self.incident is not None and self.previous is None):
            item = dict(
                event_id=str(uuid4()),
                session=self.session,
                reason=reason,
                stage=self.stage,
                detection_budget_seconds=self.MAX_DISCONTINUITY_SECONDS,
                stabilization_seconds=self.STABILIZATION_SECONDS,
                previous_utc=self.previous[0].isoformat() if self.previous else None,
                observed_utc=utc.isoformat(),
                monotonic_elapsed_seconds=elapsed,
                utc_elapsed_seconds=utc_delta,
                high_water_utc=self.high_water.isoformat(),
            )
            self._append(item["event_id"], "incident", item)
            self.incident = item
            self._acknowledged = False
            self.stable_since = None
        if reason:
            self.stable_since = None
        elif self.stable_since is None:
            self.stable_since = after
        self.previous = current
        return current

    def now(self):
        utc, _, after = self._observe()
        if self.incident:
            raise ClockPaused(
                "Clock health requires explicit confirmation: "
                + self.incident["event_id"]
            )
        if self._acknowledged and (
            utc < self.eligible_after
            or self.stable_since is None
            or after - self.stable_since < self.STABILIZATION_SECONDS
        ):
            raise ClockPaused(
                "Clock recovery: waiting for stable time and a fresh full market"
            )
        return utc

    def acknowledge(self, event_id):
        """Operator has independently verified OS clock accuracy; never infer it."""
        utc, _, _ = self._observe()
        if self.incident is None or self.incident["event_id"] != event_id:
            raise ValueError("Clock confirmation must name the current incident")
        if utc < self.high_water:
            raise ValueError("UTC has not reached the durable clock high-water mark")
        boundary = datetime.fromtimestamp(
            (int(utc.timestamp()) // 300 + 1) * 300, timezone.utc
        )
        payload = dict(
            event_id=event_id,
            acknowledged_at_utc=utc.isoformat(),
            eligible_after_utc=boundary.isoformat(),
            high_water_utc=self.high_water.isoformat(),
            session=self.session,
        )
        self._append(event_id, "acknowledged", payload)
        self.incident = None
        self.eligible_after = boundary
        self._acknowledged = True
        self.stable_since = None

    def status(self):
        return dict(
            session=self.session,
            incident=self.incident,
            eligible_after_utc=self.eligible_after.isoformat()
            if self.eligible_after
            else None,
            high_water_utc=self.high_water.isoformat() if self.high_water else None,
        )
