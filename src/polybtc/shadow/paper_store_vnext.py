"""Single-thread SQLite ownership for the consolidated paper store.

Component leases retain legacy repository APIs. Nested BEGIN/COMMIT pairs are
savepoints, so one owner can commit an entire paper outcome atomically.
"""

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import threading
from uuid import uuid4


class PaperStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, isolation_level=None, timeout=15)
        self.connection.row_factory = sqlite3.Row
        for pragma in (
            "journal_mode=WAL",
            "synchronous=FULL",
            "foreign_keys=ON",
            "busy_timeout=15000",
        ):
            self.connection.execute("PRAGMA " + pragma)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS component_versions (component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
        )
        self.thread = threading.get_ident()

    def lease(self, component):
        if threading.get_ident() != self.thread:
            raise RuntimeError("Paper store has one owning thread")
        return ComponentLease(self, component)

    @contextmanager
    def atomic(self):
        lease = self.lease("owner")
        try:
            lease.execute("BEGIN IMMEDIATE")
            yield
            lease.execute("COMMIT")
        except BaseException:
            if lease.in_transaction:
                lease.execute("ROLLBACK")
            raise
        finally:
            lease.close()

    def close(self):
        self.connection.close()


class ComponentLease:
    def __init__(self, store, component):
        self.store = store
        self.component = component
        self.active = False
        self.savepoint = None

    @property
    def in_transaction(self):
        return self.active

    @property
    def row_factory(self):
        return self.store.connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self.store.connection.row_factory = value

    def execute(self, sql, parameters=()):
        db = self.store.connection
        statement = sql.strip().rstrip(";")
        upper = statement.upper()
        if upper.startswith("BEGIN"):
            if self.active:
                raise RuntimeError("Transaction already active on lease")
            if db.in_transaction:
                self.savepoint = "lease_" + uuid4().hex
                result = db.execute("SAVEPOINT " + self.savepoint)
            else:
                result = db.execute(statement)
            self.active = True
            return result
        if upper in ("COMMIT", "ROLLBACK"):
            if not self.active:
                raise RuntimeError("No transaction owned by lease")
            if self.savepoint:
                if upper == "ROLLBACK":
                    db.execute("ROLLBACK TO " + self.savepoint)
                result = db.execute("RELEASE " + self.savepoint)
            else:
                result = db.execute(upper)
            self.active = False
            self.savepoint = None
            return result
        if upper == "PRAGMA USER_VERSION":
            return db.execute(
                "SELECT COALESCE((SELECT version FROM component_versions WHERE component=?),0)",
                (self.component,),
            )
        match = re.fullmatch(r"PRAGMA\s+USER_VERSION\s*=\s*(\d+)", upper)
        if match:
            return db.execute(
                "INSERT INTO component_versions VALUES (?,?) ON CONFLICT(component) DO UPDATE SET version=excluded.version",
                (self.component, int(match[1])),
            )
        if upper.startswith("PRAGMA ") and "=" in upper and db.in_transaction:
            key, value = upper[7:].split("=", 1)
            key = key.strip()
            value = value.strip()
            expected = {
                "SYNCHRONOUS": ("FULL", 2),
                "FOREIGN_KEYS": ("ON", 1),
                "JOURNAL_MODE": ("WAL", "wal"),
                "BUSY_TIMEOUT": ("15000", 15000),
            }
            if key in expected:
                name, actual = expected[key]
                if value != name or db.execute("PRAGMA " + key).fetchone()[0] != actual:
                    raise RuntimeError("Unexpected transaction pragma: " + key)
                return db.execute("PRAGMA " + key)
        return db.execute(sql, parameters)

    def executemany(self, *args):
        return self.store.connection.executemany(*args)

    def close(self):
        if self.active:
            self.execute("ROLLBACK")

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        if self.active:
            self.execute("ROLLBACK" if kind else "COMMIT")
        self.close()
