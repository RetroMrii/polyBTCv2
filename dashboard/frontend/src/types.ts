export type Source = {
  state: string;
  detail: string;
  timestamp: string | null;
  age_seconds: number | null;
};
export type Decision = {
  id: number;
  condition_id: string;
  horizon_seconds: number;
  target_at_utc: string;
  processed_at_utc: string;
  status: string;
  reason: string;
  reason_info: { category: string; explanation: string };
  model_probability_yes: number | null;
  model_probability_no: number | null;
  prediction_market_probability_yes: number | null;
  market_probability_yes: number | null;
  probability_difference: number | null;
  execution_price: number | null;
  snapshot_id: string | null;
  snapshot_observed_at_utc: string | null;
  snapshot_ingested_at_utc: string | null;
  verified_outcome: number | null;
  outcome_state: string;
  validation_warnings: string[];
};
export type DecisionPage = {
  rows: Decision[];
  total: number;
  page: number;
  page_size: number;
  source: Source;
  scope: string;
  reasons: string[];
};
export type Market = {
  market_id: string;
  question: string;
  observed_at: string | null;
  market_end_at: string | null;
  btc_price: number | null;
  strike: number | null;
  seconds_to_expiry: number | null;
  active: boolean;
  yes_bid: number | null;
  yes_ask: number | null;
  no_bid: number | null;
  no_ask: number | null;
  yes_bid_size: number | null;
  yes_ask_size: number | null;
  no_bid_size: number | null;
  no_ask_size: number | null;
  reference_timestamp: string | null;
  yes_book_timestamp: string | null;
  no_book_timestamp: string | null;
  reference_age_ms: number | null;
  yes_book_age_ms: number | null;
  no_book_age_ms: number | null;
  market_probability_yes: number | null;
  distance: number | null;
  yes_spread: number | null;
  no_spread: number | null;
  warnings: string[];
  source_health: Record<string, Source>;
};
export type Telemetry = {
  current: Market | null;
  rows: Pick<Market, "market_id" | "observed_at" | "btc_price">[];
  source: Source;
  scope: string;
  generated_at: string;
};
export type Resolution = {
  condition_id: string;
  label_yes: number;
  resolved_at_utc: string;
  evidence_source: string;
  evidence_id: string;
  settlement_status: string;
  settled_at_utc: string | null;
};
export type ResolutionPage = {
  rows: Resolution[];
  source: Source;
  scope: string;
};
export type Portfolio = {
  source: Source;
  entries: Record<string, unknown>[];
  filled: number | null;
  settled: number | null;
  realized_pnl: number | null;
  exposure: number | null;
  win_rate: number | null;
  pending: number | null;
  reserved: number | null;
  fees: number | null;
  total_fills: number | null;
  pnl_history: { time: string; entry_id: number; pnl: number }[];
  detail: string;
};
export type Health = {
  generated_at: string;
  sources: Record<string, Source>;
  process_status: string;
  recent_decisions: number;
  prediction_count_15m: number;
  predictions_per_minute_15m: number;
  reason_counts: Record<string, number>;
  missing_telemetry: Record<string, number>;
  telemetry_sample_size: number;
  latest_market: string | null;
  scope: string;
};
export type Overview = {
  generated_at: string;
  mode: string;
  telemetry: Telemetry;
  decisions: DecisionPage;
  active_predictions: Decision[];
  resolutions: ResolutionPage;
  portfolio: Portfolio;
  health: Health;
  provenance: string;
};
export type Score = {
  n: number;
  unique_markets: number;
  brier: number;
  log_loss: number;
  mean_predicted_yes: number;
  actual_yes_rate: number;
};
export type HorizonScore = {
  model: Score | null;
  market: Score | null;
  paired_model: Score | null;
  paired_market: Score | null;
  paired_n: number;
  resolved_decisions: number;
};
export type Report = {
  report_version: string;
  created_at_utc: string;
  coverage: Record<string, number>;
  model_all_resolved: Score | null;
  market_all_resolved: Score | null;
  paired_model: Score | null;
  paired_market: Score | null;
  by_horizon: Record<string, HorizonScore>;
  calibration_model: {
    range: string;
    n: number;
    avg_probability: number;
    yes_frequency: number;
  }[];
  interpretation: string;
};
export type Performance = {
  report: Report | null;
  source: Source;
  portfolio: Portfolio;
  coverage_over_time: {
    time: string;
    decisions: number;
    predictions: number;
    verified: number;
  }[];
  warnings: string[];
};
export type SettingsResponse = {
  paths: Record<string, string>;
  path_editing: string;
  operational_controls: string;
};
export type Preferences = {
  refresh: number;
  pageSize: number;
  window: number;
  timezone: string;
  density: string;
  animations: boolean;
  theme: string;
};
