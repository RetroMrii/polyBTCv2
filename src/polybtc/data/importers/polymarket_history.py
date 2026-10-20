from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AccountHistoryRecord:
    source_row_number: int
    market_name: str
    action: str
    usdc_amount: float | None
    token_amount: float | None
    token_name: str
    timestamp: datetime
    tx_hash: str


def _parse_timestamp(value: str) -> datetime:
    raw = value.strip()

    if raw.isdigit():
        return datetime.fromtimestamp(
            int(raw),
            tz=timezone.utc,
        )

    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            f"Polymarket history timestamp is naive: {value!r}"
        )
    return dt.astimezone(timezone.utc)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    return None if value == "" else float(value)


def load_polymarket_history(
    path: str | Path,
) -> list[AccountHistoryRecord]:
    records: list[AccountHistoryRecord] = []

    with Path(path).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row_number, row in enumerate(reader, start=2):
            records.append(
                AccountHistoryRecord(
                    source_row_number=row_number,
                    market_name=row["marketName"].strip(),
                    action=row["action"].strip(),
                    usdc_amount=_float_or_none(
                        row.get("usdcAmount")
                    ),
                    token_amount=_float_or_none(
                        row.get("tokenAmount")
                    ),
                    token_name=row.get(
                        "tokenName",
                        "",
                    ).strip(),
                    timestamp=_parse_timestamp(
                        row["timestamp"]
                    ),
                    tx_hash=row.get("hash", "").strip(),
                )
            )

    return records


def account_record_id(
    record: AccountHistoryRecord,
) -> str:
    basis = (
        f"{record.market_name}|{record.action}|"
        f"{record.timestamp.isoformat()}|"
        f"{record.tx_hash}|{record.source_row_number}"
    ).encode("utf-8")
    return (
        "acct_"
        + hashlib.sha256(basis).hexdigest()[:24]
    )
