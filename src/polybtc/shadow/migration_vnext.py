"""Offline, copy-only legacy paper migration. Originals are never opened writable."""

from __future__ import annotations
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from polybtc.shadow.paper_store_vnext import PaperStore
from polybtc.shadow.acquisition_evidence import (
    AcquisitionEvidenceStore,
    binding,
    digest,
)
from polybtc.shadow.converter_vnext import convert_v1_tail_row
from polybtc.shadow.collector_bridge_vnext import _fingerprint


def ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def copy_schema_data(source, destination):
    objects = source.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
    ).fetchall()
    counts = {}
    for item in objects:
        if item["type"] != "table":
            continue
        name = item["name"]
        if destination.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (name,)
        ).fetchone():
            raise ValueError("Conflicting migration schema: " + name)
        destination.execute(item["sql"])
        columns = source.execute("PRAGMA table_info(" + quote(name) + ")").fetchall()
        statement = (
            "INSERT INTO "
            + quote(name)
            + " VALUES ("
            + ",".join("?" for _ in columns)
            + ")"
        )
        count = 0
        cursor = source.execute("SELECT * FROM " + quote(name))
        while batch := cursor.fetchmany(256):
            destination.executemany(statement, [tuple(r) for r in batch])
            count += len(batch)
        counts[name] = count
    # Install triggers AFTER copying data; historical events must not be emitted twice.
    for item in objects:
        if item["type"] != "table":
            destination.execute(item["sql"])
    if source.execute(
        "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'"
    ).fetchone():
        for row in source.execute("SELECT * FROM sqlite_sequence"):
            destination.execute(
                "DELETE FROM sqlite_sequence WHERE name=?", (row["name"],)
            )
            destination.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", tuple(row)
            )
    return counts


def migrate(*, state_dir, evidence_db, fee_cache, destination):
    state_dir = Path(state_dir).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(
            "Migration destination must not exist; incomplete copies are never activated"
        )
    if destination.is_relative_to(state_dir) or state_dir.is_relative_to(destination):
        raise ValueError("Migration destination must be separate from original state")
    marker = json.loads((state_dir / "runtime_mode.json").read_text(encoding="utf-8"))
    if marker != {
        "version": 1,
        "mode": "paper_execution",
        "live_trading_enabled": False,
    }:
        raise ValueError("Expected original paper mode")
    destination.mkdir(parents=True)
    new_state = destination / "state"
    new_state.mkdir()
    manifest = dict(
        version=1,
        status="incomplete",
        source_state=str(state_dir),
        created_at=datetime.now(timezone.utc).isoformat(),
        counts={},
    )
    manifest_path = new_state / "paper_layout.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with ExitStack() as stack:
        paths = {
            "journal": state_dir / "decisions.sqlite3",
            "ledger": state_dir / "trades.sqlite3",
            "receipts": state_dir / "receipts.sqlite3",
            "resolutions": state_dir / "resolutions.sqlite3",
            "checkpoint": state_dir / "csv_tail.sqlite3",
            "acquisition": Path(evidence_db),
            "fees": Path(fee_cache),
        }
        sources = {
            key: stack.enter_context(closing(ro(path)))
            for key, path in paths.items()
            if path.exists()
        }
        for key in (
            "journal",
            "ledger",
            "receipts",
            "checkpoint",
            "acquisition",
            "fees",
        ):
            if key not in sources:
                raise ValueError("Missing migration input: " + key)
        versions = {
            k: db.execute("PRAGMA data_version").fetchone()[0]
            for k, db in sources.items()
        }
        for db in sources.values():
            db.execute("BEGIN")
        tail = dict(
            sources["checkpoint"].execute("SELECT * FROM tail_state").fetchone()
        )
        csv_path = Path(tail["source_path"])
        csv_stat = csv_path.stat()
        if csv_stat.st_size != tail["offset_bytes"]:
            raise ValueError(
                "Drain and stop the legacy runtime before migration; CSV is not fully acknowledged"
            )
        csv_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if csv_hash != tail["acknowledged_prefix_sha256"]:
            raise ValueError("CSV differs from acknowledged prefix")
        manifest["legacy_checkpoint"] = tail
        manifest["csv_sha256"] = csv_hash
        store = PaperStore(new_state / "paper.sqlite3")
        stack.callback(store.close)
        store.connection.execute("PRAGMA foreign_keys=OFF")
        with store.atomic():
            for key in ("journal", "ledger", "receipts", "resolutions"):
                if key not in sources:
                    continue
                manifest["counts"][key] = copy_schema_data(
                    sources[key], store.connection
                )
                store.connection.execute(
                    "INSERT INTO component_versions VALUES (?,?)",
                    (key, sources[key].execute("PRAGMA user_version").fetchone()[0]),
                )
        store.connection.execute("PRAGMA foreign_keys=ON")
        if store.connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Migrated foreign key mismatch")
        input_path = destination / "input.sqlite3"
        inp = stack.enter_context(closing(sqlite3.connect(input_path)))
        inp.execute("PRAGMA synchronous=FULL")
        with inp:
            inp.execute("BEGIN IMMEDIATE")
            for key in ("acquisition", "fees"):
                manifest["counts"][key] = copy_schema_data(sources[key], inp)
        acq = AcquisitionEvidenceStore(input_path, create=True, stream=True)
        stack.callback(acq.close)
        mappings = {}
        receipts = {
            r["snapshot_id"]: dict(r)
            for r in sources["receipts"].execute("SELECT * FROM receipts")
        }
        with csv_path.open("rb") as f:
            headers = next(csv.reader([f.readline().decode("utf-8-sig")]))
            while f.tell() < tail["offset_bytes"]:
                offset = f.tell()
                line = f.readline()
                sid = hashlib.sha256(
                    (tail["source_identity"] + ":" + str(offset) + ":").encode() + line
                ).hexdigest()
                if sid not in receipts:
                    continue
                snapshot = convert_v1_tail_row(
                    SimpleNamespace(
                        row_id=sid,
                        values=dict(
                            zip(headers, next(csv.reader([line.decode("utf-8")])))
                        ),
                    ),
                    source_file=csv_path.name,
                )
                if _fingerprint(snapshot) != receipts[sid]["source_fingerprint"]:
                    raise ValueError("Legacy receipt fingerprint mismatch")
                key = digest(binding(snapshot))
                if key in mappings:
                    raise ValueError(
                        "Two legacy receipt identities share an acquisition record; review required"
                    )
                mappings[key] = (sid, csv_path.name)
        if len(mappings) != len(receipts):
            raise ValueError(
                "A legacy receipt cannot be reconstructed from original CSV"
            )
        found = set()
        with inp:
            for row in inp.execute(
                "SELECT id,snapshot FROM acquisition ORDER BY captured,id"
            ).fetchall():
                key, payload = row
                item = json.loads(payload)
                mapped = mappings.get(key)
                if mapped:
                    found.add(key)
                inp.execute(
                    "INSERT INTO input_observations(acquisition_id,runtime_id,source_file,observed_at,condition_id) VALUES (?,?,?,?,?)",
                    (
                        key,
                        mapped[0] if mapped else "acquisition:" + key,
                        mapped[1] if mapped else None,
                        item["observed_at"]["__polybtc_datetime_utc__"],
                        item["condition_id"],
                    ),
                )
        if found != set(mappings):
            raise ValueError(
                "Some legacy receipts lack retained acquisition evidence; migration remains incomplete"
            )
        identity = inp.execute(
            "SELECT value FROM input_metadata WHERE name='identity'"
        ).fetchone()[0]
        seq = inp.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM input_observations"
        ).fetchone()[0]
        with store.atomic():
            store.connection.execute(
                "CREATE TABLE input_cursor (id INTEGER PRIMARY KEY CHECK(id=1),input_path TEXT NOT NULL,input_identity TEXT NOT NULL,sequence INTEGER NOT NULL)"
            )
            store.connection.execute(
                "INSERT INTO input_cursor VALUES (1,?,?,?)",
                (str(input_path), identity, seq),
            )
        manifest.update(
            input_path=str(input_path),
            paper_path=str(store.path),
            input_identity=identity,
            cutover_sequence=seq,
            legacy_receipts_mapped=len(found),
        )
        for key, db in sources.items():
            db.execute("ROLLBACK")
            if db.execute("PRAGMA data_version").fetchone()[0] != versions[key]:
                raise ValueError("Source changed during migration: " + key)
        if (
            csv_path.stat().st_size != csv_stat.st_size
            or hashlib.sha256(csv_path.read_bytes()).hexdigest() != csv_hash
        ):
            raise ValueError("CSV changed during migration")
        for db in (store.connection, inp):
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Migrated database integrity check failed")
        (new_state / "runtime_mode.json").write_text(
            json.dumps(marker, sort_keys=True), encoding="utf-8"
        )
        manifest["status"] = "complete"
        from polybtc.operations import atomic_status

        atomic_status(manifest_path, manifest)
    return manifest
