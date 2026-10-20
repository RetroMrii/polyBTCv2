from datetime import datetime, timezone
from dataclasses import replace

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.data.validation import ValidationError, validate_condition_id, validate_snapshot


VALID_ID = "0x" + "a" * 64


def test_condition_id_accepts_32_byte_hex() -> None:
    validate_condition_id(VALID_ID)


def test_condition_id_rejects_bad_value() -> None:
    with pytest.raises(ValidationError):
        validate_condition_id("not-a-condition-id")


def test_snapshot_rejects_crossed_yes_book() -> None:
    row = SnapshotRecord(
        snapshot_id="snap_test",
        condition_id=VALID_ID,
        observed_at=datetime.now(timezone.utc),
        source_name="test",
        ingested_at=datetime.now(timezone.utc),
        reference_price=75000.0,
        strike=75000.0,
        seconds_to_expiry=120,
        yes_bid=0.60,
        yes_ask=0.50,
    )
    with pytest.raises(ValidationError):
        validate_snapshot(row)


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("suffix,value", [
    ("book_timestamp", datetime(2026, 10, 12)),
    ("book_age_ms", -1), ("tick_size", 0), ("min_order_size", 0),
])
def test_current_snapshot_side_fields_are_validated(side, suffix, value):
    now = datetime.now(timezone.utc)
    row = SnapshotRecord(snapshot_id="schema-check", condition_id=VALID_ID,
                         observed_at=now, ingested_at=now, source_name="test")
    validate_snapshot(row)
    with pytest.raises(ValidationError):
        validate_snapshot(replace(row, **{f"{side}_{suffix}": value}))
