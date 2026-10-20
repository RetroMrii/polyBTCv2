from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class Source(BaseModel):
    state: Literal["ok", "missing", "error", "stale", "future", "unavailable"]
    detail: str = ""
    timestamp: str | None = None
    age_seconds: float | None = None


class Reason(BaseModel):
    category: str
    explanation: str


class ReasonCatalogEntry(Reason):
    source_locations: list[str]


class Decision(BaseModel):
    id: int
    condition_id: str
    horizon_seconds: int
    target_at_utc: str
    processed_at_utc: str
    status: str
    reason: str
    snapshot_id: str | None = None
    snapshot_observed_at_utc: str | None = None
    snapshot_ingested_at_utc: str | None = None
    snapshot_source: str | None = None
    horizon_gap_seconds: float | None = None
    model_probability_yes: float | None = Field(None, ge=0, le=1)
    prediction_market_probability_yes: float | None = Field(None, ge=0, le=1)
    market_probability_yes: float | None = Field(None, ge=0, le=1)
    execution_price: float | None = None
    model_probability_no: float | None = None
    probability_difference: float | None = None
    reason_info: Reason
    verified_outcome: int | None = None
    outcome_state: str = "unavailable"
    validation_warnings: list[str] = []


class DecisionPage(BaseModel):
    rows: list[Decision]
    total: int
    page: int
    page_size: int
    source: Source
    scope: str
    reasons: list[str]


class Market(BaseModel):
    market_id: str
    question: str = ""
    observed_at: str | None = None
    market_end_at: str | None = None
    btc_price: float | None = None
    strike: float | None = None
    seconds_to_expiry: float | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    yes_bid_size: float | None = None
    yes_ask_size: float | None = None
    no_bid_size: float | None = None
    no_ask_size: float | None = None
    reference_timestamp: str | None = None
    yes_book_timestamp: str | None = None
    no_book_timestamp: str | None = None
    reference_age_ms: float | None = None
    yes_book_age_ms: float | None = None
    no_book_age_ms: float | None = None
    market_probability_yes: float | None = None
    distance: float | None = None
    yes_spread: float | None = None
    no_spread: float | None = None
    active: bool = False
    warnings: list[str] = []
    source_health: dict[str, Source] = {}


class TelemetryPoint(BaseModel):
    market_id: str
    observed_at: str
    btc_price: float | None


class Telemetry(BaseModel):
    current: Market | None
    rows: list[TelemetryPoint]
    source: Source
    scope: str
    generated_at: str


class Resolution(BaseModel):
    condition_id: str
    label_yes: int = Field(ge=0, le=1)
    resolved_at_utc: str
    evidence_source: str
    evidence_id: str
    settlement_status: Literal["VERIFIED", "SETTLED"]
    settled_at_utc: str | None = None


class ResolutionPage(BaseModel):
    rows: list[Resolution]
    source: Source
    scope: str


class Score(BaseModel):
    n: int
    unique_markets: int
    brier: float = Field(ge=0, le=1)
    log_loss: float = Field(ge=0)
    mean_predicted_yes: float = Field(ge=0, le=1)
    actual_yes_rate: float = Field(ge=0, le=1)


class HorizonScore(BaseModel):
    resolved_decisions: int
    model: Score | None
    market: Score | None
    paired_n: int
    paired_model: Score | None
    paired_market: Score | None


class Calibration(BaseModel):
    range: str
    n: int
    avg_probability: float = Field(ge=0, le=1)
    yes_frequency: float = Field(ge=0, le=1)


class Report(BaseModel):
    report_version: Literal["vnext_prospective_prediction_report_v2"]
    created_at_utc: str
    coverage: dict[str, int]
    model_all_resolved: Score | None
    market_all_resolved: Score | None
    paired_model: Score | None
    paired_market: Score | None
    by_horizon: dict[str, HorizonScore]
    calibration_model: list[Calibration]
    interpretation: str
    journal_reasons: dict[str, int]


class Portfolio(BaseModel):
    source: Source
    entries: list[dict[str, JsonValue]] = []
    filled: int | None = None
    settled: int | None = None
    realized_pnl: float | None = None
    exposure: float | None = None
    win_rate: float | None = None
    pending: int | None = None
    reserved: float | None = None
    fees: float | None = None
    total_fills: int | None = None
    pnl_history: list[dict[str, JsonValue]] = []
    detail: str


class Performance(BaseModel):
    report: Report | None
    source: Source
    portfolio: Portfolio
    coverage_over_time: list[dict[str, JsonValue]]
    warnings: list[str]


class Health(BaseModel):
    generated_at: str
    sources: dict[str, Source]
    process_status: str
    recent_decisions: int
    prediction_count_15m: int
    predictions_per_minute_15m: float
    reason_counts: dict[str, int]
    missing_telemetry: dict[str, int]
    telemetry_sample_size: int
    latest_market: str | None
    scope: str


class Overview(BaseModel):
    generated_at: str
    mode: Literal["SHADOW ONLY", "PAPER EXECUTION", "UNKNOWN"] = "UNKNOWN"
    telemetry: Telemetry
    decisions: DecisionPage
    active_predictions: list[Decision]
    resolutions: ResolutionPage
    portfolio: Portfolio
    health: Health
    provenance: str
