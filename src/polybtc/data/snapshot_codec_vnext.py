"""Canonical snapshot encoding shared by acquisition and consumers."""

from __future__ import annotations
import json
from dataclasses import asdict
from datetime import datetime, timezone
from polybtc.data.schema import SnapshotRecord


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _json_default(value):
    if isinstance(value, datetime):
        return {"__polybtc_datetime_utc__": _utc(value).isoformat()}

    raise TypeError(f"Unsupported snapshot JSON type: {type(value)!r}")


def _json_object_hook(value):
    if len(value) == 1 and "__polybtc_datetime_utc__" in value:
        return datetime.fromisoformat(value["__polybtc_datetime_utc__"])

    return value


def _serialize(row: SnapshotRecord) -> str:
    return json.dumps(
        asdict(row),
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _deserialize(payload: str) -> SnapshotRecord:
    return SnapshotRecord(
        **json.loads(
            payload,
            object_hook=_json_object_hook,
        )
    )
