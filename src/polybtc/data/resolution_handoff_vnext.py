"""Background acquisition of verified outcomes; only acquisition main writes input."""

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from queue import Queue, Empty, Full
import sqlite3
from threading import Thread
from types import SimpleNamespace


def initialize(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS input_resolutions (condition_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        for action in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_resolution_{action} BEFORE {action} ON input_resolutions BEGIN SELECT RAISE(ABORT,'Immutable resolution'); END"
            )


class ResolutionWorker(Thread):
    def __init__(self, input_path, state_dir, stop):
        super().__init__(daemon=True, name="vnext-resolution-acquisition")
        self.path = Path(input_path).resolve()
        state = Path(state_dir).resolve()
        marker = json.loads((state / "paper_layout.json").read_text(encoding="utf-8"))
        if (
            marker.get("status") != "complete"
            or Path(marker["input_path"]).resolve() != self.path
        ):
            raise ValueError(
                "Resolution worker requires matching completed paper layout"
            )
        self.journal = state / "paper.sqlite3"
        self.stop_event = stop
        self.queue = Queue(maxsize=64)
        self.failure = None
        initialize(self.path)

    def resolutions(self):
        # Migrated registered outcomes already have durable verified evidence in
        # paper state. Never refetch the whole historical book at cutover.
        markets = set()
        for path, table in (
            (self.path, "input_resolutions"),
            (self.journal, "resolutions"),
        ):
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (table,)
                ).fetchone():
                    markets.update(
                        row[0]
                        for row in db.execute("SELECT condition_id FROM " + table)
                    )
        return [{"condition_id": market} for market in sorted(markets)]

    def register(self, resolution):
        try:
            self.queue.put_nowait(resolution)
        except Full:
            raise RuntimeError("Resolution queue full; retry on next acquisition pass")
        return SimpleNamespace(status="QUEUED")

    def run(self):
        from polybtc.data.resolution_sync_vnext import sync_once

        while not self.stop_event.is_set():
            try:
                sync_once(
                    journal_path=self.journal,
                    service=self,
                    now=datetime.now(timezone.utc),
                    limit=32,
                )
            except ValueError as exc:
                self.failure = exc
                return
            except Exception:
                logging.getLogger(__name__).exception(
                    "Resolution acquisition failed; retrying"
                )
            self.stop_event.wait(60)

    def drain(self):
        if self.failure is not None:
            raise RuntimeError("Resolution validation conflict") from self.failure
        # Called by acquisition main, never by the network worker.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            for _ in range(64):
                try:
                    resolution = self.queue.get_nowait()
                except Empty:
                    break
                item = asdict(resolution)
                item["resolved_at_utc"] = resolution.resolved_at_utc.isoformat()
                payload = json.dumps(item, sort_keys=True, separators=(",", ":"))
                prior = db.execute(
                    "SELECT payload FROM input_resolutions WHERE condition_id=?",
                    (resolution.condition_id,),
                ).fetchone()
                if prior and prior[0] != payload:
                    raise RuntimeError("Conflicting retained resolution")
                db.execute(
                    "INSERT OR IGNORE INTO input_resolutions VALUES (?,?)",
                    (resolution.condition_id, payload),
                )
