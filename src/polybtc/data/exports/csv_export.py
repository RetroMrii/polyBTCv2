from __future__ import annotations

import csv
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def write_dataclasses_csv(
    records: Iterable[Any],
    path: str | Path,
) -> int:
    records = list(records)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        output.write_text("", encoding="utf-8")
        return 0

    if not is_dataclass(records[0]):
        raise TypeError(
            "write_dataclasses_csv expects dataclass instances"
        )

    fieldnames = list(asdict(records[0]).keys())

    with output.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()

        for record in records:
            row = {
                key: _normalize(value)
                for key, value in asdict(record).items()
            }
            writer.writerow(row)

    return len(records)
