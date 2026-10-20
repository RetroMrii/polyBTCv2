from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Outcome(StrEnum):
    YES = "YES"
    NO = "NO"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Decision(StrEnum):
    TRADE = "TRADE"
    SKIP = "SKIP"


class ResolutionValidationStatus(StrEnum):
    VALID = "VALID"
    UNRESOLVED = "UNRESOLVED"
    MISSING = "MISSING"
    DISPUTED = "DISPUTED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class MarketRecord:
    condition_id: str
    question: str
    market_end_at: datetime
    source_name: str
    ingested_at: datetime
    market_slug: str | None = None
    yes_token_id: str | None = None
    no_token_id: str | None = None
    market_start_at: datetime | None = None
    strike: float | None = None
    closed: bool | None = None
    resolved: bool | None = None
    resolved_at: datetime | None = None
    winning_outcome: Outcome | None = None
    winning_token_id: str | None = None
    label_yes: int | None = None
    resolution_source: str | None = None
    resolution_source_version: str | None = None
    resolution_retrieved_at: datetime | None = None
    source_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    snapshot_id: str
    condition_id: str
    observed_at: datetime
    source_name: str
    ingested_at: datetime

    source_event_at: datetime | None = None
    received_at: datetime | None = None

    reference_price: float | None = None
    reference_timestamp: datetime | None = None
    reference_age_ms: float | None = None
    reference_latency_ms: float | None = None

    strike: float | None = None
    seconds_to_expiry: float | None = None
    market_end_at: datetime | None = None

    yes_bid: float | None = None
    yes_ask: float | None = None
    yes_bid_size: float | None = None
    yes_ask_size: float | None = None

    no_bid: float | None = None
    no_ask: float | None = None
    no_bid_size: float | None = None
    no_ask_size: float | None = None

    yes_book_timestamp: datetime | None = None
    yes_book_age_ms: float | None = None
    yes_book_latency_ms: float | None = None

    no_book_timestamp: datetime | None = None
    no_book_age_ms: float | None = None
    no_book_latency_ms: float | None = None

    yes_tick_size: float | None = None
    yes_min_order_size: float | None = None
    no_tick_size: float | None = None
    no_min_order_size: float | None = None

    snapshot_build_latency_ms: float | None = None

    momentum_60s: float | None = None
    volatility_60s: float | None = None

    yes_token_id: str | None = None
    no_token_id: str | None = None

    source_file: str | None = None
    source_row_number: int | None = None
    collector_version: str | None = None


@dataclass(frozen=True, slots=True)
class LabelRecord:
    condition_id: str
    resolution_source: str
    retrieved_at: datetime
    validation_status: ResolutionValidationStatus
    resolved_at: datetime | None = None
    winning_outcome: Outcome | None = None
    winning_token_id: str | None = None
    label_yes: int | None = None
    resolution_source_version: str | None = None
    label_version: str | None = None
    validation_note: str | None = None


@dataclass(frozen=True, slots=True)
class OrderRecord:
    order_id: str
    condition_id: str
    token_id: str
    outcome: Outcome
    side: OrderSide
    submitted_at: datetime
    limit_price: float
    requested_size: float
    source_name: str
    ingested_at: datetime
    strategy_decision_id: str | None = None
    order_type: str | None = None
    status: str | None = None
    cancelled_at: datetime | None = None
    failure_reason: str | None = None
    source_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class FillRecord:
    fill_id: str
    condition_id: str
    side: OrderSide
    filled_at: datetime
    price: float
    size: float
    source_name: str
    ingested_at: datetime
    order_id: str | None = None
    token_id: str | None = None
    outcome: Outcome | None = None
    fee: float | None = None
    transaction_hash: str | None = None
    source_record_id: str | None = None
    reconciliation_status: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    prediction_id: str
    snapshot_id: str
    condition_id: str
    model_id: str
    predicted_at: datetime
    feature_version: str
    model_version: str
    raw_score: float | None = None
    raw_probability_yes: float | None = None
    calibrated_probability_yes: float | None = None
    calibration_version: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyDecisionRecord:
    strategy_decision_id: str
    prediction_id: str
    condition_id: str
    decision_at: datetime
    selected_outcome: Outcome | None
    decision: Decision
    strategy_version: str
    executable_price: float | None = None
    gross_edge: float | None = None
    estimated_fee: float | None = None
    estimated_slippage: float | None = None
    net_expected_value: float | None = None
    reason: str | None = None
