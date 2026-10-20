from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from typing import Any

from .schema import LabelRecord, MarketRecord, SnapshotRecord

_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class ValidationError(ValueError):
    pass


def require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field_name} must be normalized to UTC")


def validate_condition_id(condition_id: str) -> None:
    if not _CONDITION_ID_RE.fullmatch(condition_id):
        raise ValidationError(f"invalid condition_id: {condition_id!r}")


def validate_probability(value: float | None, field_name: str) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValidationError(f"{field_name} must be in [0, 1], got {value}")


def validate_positive(value: float | None, field_name: str) -> None:
    if value is not None and value <= 0:
        raise ValidationError(f"{field_name} must be > 0, got {value}")


def validate_nonnegative(value: float | None, field_name: str) -> None:
    if value is not None and value < 0:
        raise ValidationError(f"{field_name} must be >= 0, got {value}")


def validate_market(record: MarketRecord) -> None:
    validate_condition_id(record.condition_id)
    require_utc(record.market_end_at, "market_end_at")
    require_utc(record.ingested_at, "ingested_at")
    if record.market_start_at is not None:
        require_utc(record.market_start_at, "market_start_at")
        if record.market_start_at >= record.market_end_at:
            raise ValidationError("market_start_at must precede market_end_at")
    if record.resolved_at is not None:
        require_utc(record.resolved_at, "resolved_at")
    if record.resolution_retrieved_at is not None:
        require_utc(record.resolution_retrieved_at, "resolution_retrieved_at")
    if record.label_yes not in (None, 0, 1):
        raise ValidationError("label_yes must be 0, 1, or None")
    if record.winning_outcome is not None and record.label_yes is not None:
        expected = 1 if record.winning_outcome.value == "YES" else 0
        if record.label_yes != expected:
            raise ValidationError("winning_outcome and label_yes disagree")


def validate_snapshot(record: SnapshotRecord) -> None:
    validate_condition_id(record.condition_id)
    require_utc(record.observed_at, "observed_at")
    require_utc(record.ingested_at, "ingested_at")
    for field_name in (
        "source_event_at", "received_at", "reference_timestamp",
        "yes_book_timestamp", "no_book_timestamp",
    ):
        value = getattr(record, field_name)
        if value is not None:
            require_utc(value, field_name)
    for field_name in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
        validate_probability(getattr(record, field_name), field_name)
    for field_name in ("yes_bid_size", "yes_ask_size", "no_bid_size", "no_ask_size"):
        validate_nonnegative(getattr(record, field_name), field_name)
    validate_positive(record.reference_price, "reference_price")
    validate_positive(record.strike, "strike")
    validate_nonnegative(record.seconds_to_expiry, "seconds_to_expiry")
    validate_nonnegative(record.reference_age_ms, "reference_age_ms")
    for side in ("yes", "no"):
        name = f"{side}_book_age_ms"
        validate_nonnegative(getattr(record, name), name)
        for suffix in ("tick_size", "min_order_size"):
            name = f"{side}_{suffix}"
            validate_positive(getattr(record, name), name)
    # Fee policy is separate from SnapshotRecord and validated by the fee cache
    # and execution boundary; there is no snapshot fee_rate field.
    if record.yes_bid is not None and record.yes_ask is not None and record.yes_bid > record.yes_ask:
        raise ValidationError("yes_bid cannot exceed yes_ask")
    if record.no_bid is not None and record.no_ask is not None and record.no_bid > record.no_ask:
        raise ValidationError("no_bid cannot exceed no_ask")


def validate_label(record: LabelRecord) -> None:
    validate_condition_id(record.condition_id)
    require_utc(record.retrieved_at, "retrieved_at")
    if record.resolved_at is not None:
        require_utc(record.resolved_at, "resolved_at")
    if record.label_yes not in (None, 0, 1):
        raise ValidationError("label_yes must be 0, 1, or None")
    if record.validation_status.value == "VALID":
        if record.winning_outcome is None or record.label_yes is None:
            raise ValidationError("VALID label requires winning_outcome and label_yes")
    if record.winning_outcome is not None and record.label_yes is not None:
        expected = 1 if record.winning_outcome.value == "YES" else 0
        if record.label_yes != expected:
            raise ValidationError("winning_outcome and label_yes disagree")


def validate_no_naive_datetimes(record: Any) -> None:
    if not is_dataclass(record):
        raise TypeError("record must be a dataclass instance")
    for f in fields(record):
        value = getattr(record, f.name)
        if isinstance(value, datetime):
            require_utc(value, f.name)
