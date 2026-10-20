"""Bounded offline settlement in the sole paper writer, after evaluation."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import time
from polybtc.shadow.settlement_vnext import VerifiedResolution, VNextSettlementService


class SettlementHandoff:
    def __init__(self, input_path, store, ledger, clock):
        self.store = store
        self.clock = clock
        self.reader = sqlite3.connect(
            Path(input_path).resolve().as_uri() + "?mode=ro", uri=True
        )
        self.service = VNextSettlementService(
            registry_path=store.path, ledger=ledger, store=store
        )
        self.next_check = 0.0
        self.seen = set()

    def run_once(self):
        if time.monotonic() < self.next_check:
            return
        self.next_check = time.monotonic() + 1.0
        has_input = self.reader.execute(
            "SELECT 1 FROM sqlite_master WHERE name='input_resolutions'"
        ).fetchone()
        items = (
            self.reader.execute("SELECT condition_id,payload FROM input_resolutions")
            if has_input
            else ()
        )
        # Register every retained input once per process, even when a migrated
        # registry already exists, so conflicting evidence cannot be hidden.
        for market, payload in items:
            if market in self.seen:
                continue
            item = json.loads(payload)
            item["resolved_at_utc"] = datetime.fromisoformat(item["resolved_at_utc"])
            with self.store.atomic():
                self.service.register(VerifiedResolution(**item))
                self.service.settle(condition_id=market, at=self.clock())
            self.seen.add(market)
            break
        row = self.store.connection.execute(
            "SELECT r.condition_id FROM resolutions r JOIN entries e ON r.condition_id=e.condition_id WHERE r.settlement_status='VERIFIED' AND e.status IN ('FILLED','SETTLED') LIMIT 1"
        ).fetchone()
        if row:
            with self.store.atomic():
                self.service.settle(condition_id=row[0], at=self.clock())

    def close(self):
        self.reader.close()
