from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..schema import SnapshotRecord
from ..validation import validate_snapshot


@dataclass(frozen=True, slots=True)
class V1DecisionAudit:
    question: str
    model_probability: float | None
    market_probability: float | None
    edge: float | None
    action: str
    reason: str


def _optional_float(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timestamp is not timezone-aware: {raw!r}")
    return value.astimezone(timezone.utc)


def deterministic_snapshot_id(
    condition_id: str,
    observed_at: datetime,
    source_row_number: int,
) -> str:
    payload = (
        f"v1_decisions|{condition_id}|{observed_at.isoformat()}|"
        f"{source_row_number}"
    ).encode("utf-8")
    return "snap_" + hashlib.sha256(payload).hexdigest()[:24]


def iter_v1_decisions(
    path: str | Path,
    *,
    ingested_at: datetime | None = None,
) -> Iterator[tuple[SnapshotRecord, V1DecisionAudit]]:
    source_path = Path(path)
    ingestion_time = (
        ingested_at or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {
            "timestamp",
            "market_id",
            "question",
            "btc_price",
            "strike",
            "seconds_to_expiry",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "model_probability",
            "market_probability",
            "edge",
            "action",
            "reason",
        }
        if set(reader.fieldnames or []) != expected:
            raise ValueError(
                f"unexpected decision schema: {reader.fieldnames}"
            )

        for row_number, row in enumerate(reader, start=2):
            observed_at = _parse_utc(row["timestamp"])
            condition_id = row["market_id"].strip()

            snapshot = SnapshotRecord(
                snapshot_id=deterministic_snapshot_id(
                    condition_id,
                    observed_at,
                    row_number,
                ),
                condition_id=condition_id,
                observed_at=observed_at,
                source_name="polybtc_v1_1_decisions",
                ingested_at=ingestion_time,
                reference_price=_optional_float(row["btc_price"]),
                strike=_optional_float(row["strike"]),
                seconds_to_expiry=_optional_float(
                    row["seconds_to_expiry"]
                ),
                yes_bid=_optional_float(row["yes_bid"]),
                yes_ask=_optional_float(row["yes_ask"]),
                no_bid=_optional_float(row["no_bid"]),
                no_ask=_optional_float(row["no_ask"]),
                source_file=source_path.name,
                source_row_number=row_number,
                collector_version="v1.1",
            )
            validate_snapshot(snapshot)

            audit = V1DecisionAudit(
                question=row["question"].strip(),
                model_probability=_optional_float(
                    row["model_probability"]
                ),
                market_probability=_optional_float(
                    row["market_probability"]
                ),
                edge=_optional_float(row["edge"]),
                action=row["action"].strip(),
                reason=row["reason"].strip(),
            )

            yield snapshot, audit


def load_v1_decisions(
    path: str | Path,
    *,
    ingested_at: datetime | None = None,
) -> list[tuple[SnapshotRecord, V1DecisionAudit]]:
    return list(iter_v1_decisions(path, ingested_at=ingested_at))
