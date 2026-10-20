# PolyBTC v2 — Development Stages

> **R0 context note — 2026-10-14:** The development plan below is preserved as historical context. The current primary objective is quantitative ML research under the [research question](RESEARCH_QUESTION.md), [protocol](RESEARCH_PROTOCOL.md) and [R0–R4 roadmap](RESEARCH_ROADMAP.md). Earlier live-capital/production milestones are not research-stage requirements or authorization. This note changes documentation only; the original phase definitions below remain intact.

## Document Purpose

This document defines the staged development plan for **PolyBTC v2**, a new-generation BTC 5-minute Polymarket trading system.

PolyBTC v2 is not an incremental repair of PolyBTC v1.1. It is a separate research and development track designed to preserve the operational lessons from v1.1 while replacing the heuristic predictive core with an evidence-driven forecasting, strategy, risk, execution, and accounting architecture.

The purpose of this document is to:

- define the order of development
- prevent premature implementation
- establish stage-specific validation gates
- separate forecasting from trading logic
- prevent data leakage and execution overestimation
- preserve reproducibility
- protect the existing v1.1 production system
- make ChatGPT-assisted development consistent across project conversations

The production PolyBTC v1.1 system must remain isolated from this project unless a narrowly scoped telemetry change is explicitly approved.

---

# Core Development Principles

PolyBTC v2 must follow these principles throughout development.

## 1. Evidence before architecture complexity

Do not assume machine learning will produce a trading edge.

The first objective is to determine whether the available data contains statistically defensible predictive information beyond the market itself.

Complex models must only be introduced after strong simple baselines are measured.

---

## 2. Prediction is not trading

The model must estimate the probability of the market outcome.

The model must not decide whether to place an order.

The system must preserve the following separation:

```text
market/reference data
        ↓
feature generation
        ↓
prediction model
        ↓
probability calibration
        ↓
strategy / expected value
        ↓
risk layer
        ↓
execution
        ↓
portfolio/accounting
        ↓
settlement/reconciliation
```

---

## 3. Historical correctness before backtest sophistication

A realistic simulator is useless if the historical dataset is wrong.

Before building strategy simulations, confirm:

- timestamp semantics
- market identity
- authoritative resolution outcome
- reference-price provenance
- bid/ask correctness
- chronological feature availability
- missing data behavior
- duplicate observations
- market lifecycle consistency

---

## 4. Executable prices matter

Mid-price PnL may be used for diagnostics only.

Any performance claim intended to guide capital deployment must eventually account for:

- executable bid/ask
- spread
- fees
- slippage
- order latency
- partial fills
- liquidity/depth
- minimum size constraints
- stale quotes
- failed orders
- reconciliation

---

## 5. Effective sample size is market-level

Multiple snapshots from one 5-minute market are not independent outcomes.

Train/validation/test isolation must operate at least at the market level and chronologically.

Never randomly split snapshot rows when observations from the same market share one final resolution label.

---

## 6. Research artifacts must be reproducible

Every meaningful experiment should record:

```text
dataset version
feature version
label version
model type
hyperparameters
training period
validation period
test period
calibration method
random seed where relevant
metrics
artifact paths
code/config version
```

---

# High-Level Phase Map

```text
P0  Specification and forensic data audit
P1  Canonical schemas and historical ingestion
P2  v1.1 telemetry extension
P3  Resolution reconstruction and label validation
P4  Dataset builder and feature pipeline
P5  Baseline predictive models
P6  Probability calibration
P7  Extended predictive models
P8  Strategy and expected-value simulator
P9  Position-management and re-entry research
P10 Realistic execution backtester
P11 Walk-forward and robustness evaluation
P12 Paper trading and shadow deployment
P13 Small live-capital validation
P14 Productionization and controlled migration
```

No later phase should be treated as mandatory merely because the earlier phase was completed.

A phase may conclude that the project should stop, redesign assumptions, collect more data, or return to an earlier stage.

---

# P0 — Specification and Forensic Data Audit

## Objective

Determine exactly what data and system behavior already exist before writing the v2 architecture around assumptions.

P0 is a research and specification phase.

Do not build the trading bot in this phase.

---

## Primary Questions

P0 must answer:

1. What files and data sources exist?
2. What does each field actually mean?
3. Which timestamps represent:
   - observation time
   - market start
   - market close
   - order submission
   - fill
   - resolution
   - settlement
4. Which identifiers uniquely represent a market?
5. Which source contains the authoritative final outcome?
6. Which historical observations are raw versus derived?
7. Which data was filtered by v1.1 strategy logic?
8. Are old records sampled uniformly?
9. Are there missing periods?
10. Can Chainlink/reference data be reconstructed consistently?
11. Can Polymarket order-book history be reconstructed?
12. How many unique markets exist?
13. How many resolved markets exist?
14. How many observations exist per market?
15. What is the effective sample size?
16. What production state/accounting inconsistencies exist?
17. Which fields would cause leakage if used incorrectly?

---

## Inputs

Inspect all available v1/v1.1 artifacts, including where available:

```text
btc_5m_hybrid_bot.py
btc_5m_hybrid_strategy.py
btc_5m_state.json
btc_5m_decisions.csv
btc_5m_trades.csv
environment/config files
Discord/log output
Polymarket account history export
settlement/redeem records
supporting scripts
historical research files
```

---

## P0 Deliverables

### P0-A — System Architecture Map

Document the current v1.1 components:

```text
market discovery
reference pricing
Polymarket pricing
strategy
risk
execution
logging
state
settlement
reconciliation
deployment
```

For each component identify whether it should be:

```text
REUSE
ADAPT
REPLACE
DEFER
```

---

### P0-B — Data Dictionary

For every important historical field document:

```text
field name
source file
data type
example
semantic meaning
raw or derived
timestamp behavior
nullable?
safe for modeling?
potential leakage risk?
```

---

### P0-C — Dataset Inventory

Measure:

```text
file size
row count
unique market count
date range
missing values
duplicate rows
duplicate timestamps
rows per market
resolved market count
trade count
fill count
```

---

### P0-D — Timestamp Specification

Define one canonical timestamp convention.

Recommended:

```text
UTC
timezone-aware
high precision where supported
```

Distinguish:

```text
event_time
observed_at
received_at
submitted_at
filled_at
resolved_at
redeemed_at
```

Do not collapse these into one generic timestamp.

---

### P0-E — Identifier Specification

Determine canonical use of:

```text
market_id
condition_id
market_slug
YES token_id
NO token_id
order_id
fill_id
prediction_id
strategy_decision_id
```

---

### P0-F — Leakage Audit

Explicitly identify:

#### Data leakage

Examples:

```text
same market in train and test
future rolling-window samples
future order-book information
future reference-price information
incorrect sorting
cross-market contamination
```

#### Target leakage

Examples:

```text
final resolution price
winner field
redeem status
realized PnL
settlement result
post-market exit information
```

#### Selection bias

Examples:

```text
only logging strategy-eligible timestamps
training only on actual v1.1 trades
discarding difficult markets
```

---

## P0 Exit Criteria

P0 is complete only when:

- the existing system architecture is documented
- current historical schemas are understood
- a canonical market identifier is selected
- a canonical timestamp standard is selected
- resolution-source requirements are defined
- known missing telemetry is documented
- leakage risks are explicitly recorded
- the approximate effective sample size is known
- no major unresolved ambiguity remains about what historical rows represent

If these conditions are not met, do not start model development.

---

# P1 — Canonical Schemas and Historical Ingestion

## Objective

Create the clean internal data model that v2 research and production systems will use.

Do not use the existing CSV formats as the long-term canonical schema.

They should be treated as source formats.

---

## Core Logical Tables

### Markets

Example fields:

```text
market_id
condition_id
slug
question
yes_token_id
no_token_id
market_start_ts
market_end_ts
strike
resolution
resolved_at
resolution_source
```

---

### Snapshots

One row per observation timestamp.

```text
snapshot_id
market_id
observed_at

reference_price
reference_timestamp
reference_age_ms

strike
seconds_to_expiry

yes_bid
yes_ask
yes_bid_size
yes_ask_size

no_bid
no_ask
no_bid_size
no_ask_size

book_timestamp
book_age_ms

tick_size
minimum_order_size
fee_rate

collector_version
```

---

### Labels

```text
market_id
resolved_yes
resolution_reference_price
resolved_at
resolution_source
label_version
```

---

### Orders

```text
order_id
market_id
token_id
strategy_decision_id
side
limit_price
requested_size
submitted_at
status
```

---

### Fills

```text
fill_id
order_id
filled_at
price
size
fee
```

---

### Predictions

```text
prediction_id
snapshot_id
model_id
raw_score
raw_probability
calibrated_probability
```

---

### Strategy Decisions

```text
strategy_decision_id
prediction_id
market_price
gross_edge
estimated_fee
estimated_slippage
net_expected_value
decision
reason
```

---

## Historical Importers

Build importers for the existing v1.1 sources.

Each importer must:

- preserve original source information
- normalize fields
- validate types
- validate timestamps
- flag malformed rows
- preserve unknown values as missing rather than inventing data
- avoid silently altering historical values

---

## Data Validation

Tests should verify:

- no invalid timestamp ordering
- no impossible prices
- no negative share sizes
- no YES/NO token swaps
- no market identifier collisions
- no malformed state transitions
- no duplicate primary keys
- no rows assigned to the wrong market

---

## P1 Deliverables

```text
canonical schema definitions
historical data importers
validation tests
import report
normalized historical dataset
source-to-canonical mapping documentation
```

---

## P1 Exit Criteria

P1 is complete when historical v1.1 data can be reproducibly imported into the canonical v2 structure without silent corruption.

---

# P2 — v1.1 Telemetry Extension

## Objective

Add only the minimum production telemetry needed to improve future v2 datasets.

Do not modify the v1.1 predictive or execution strategy unless separately approved.

---

## High-Priority Telemetry

Collect raw observations independently of the current heuristic decision.

Recommended fields:

```text
observed_at
market_id
condition_id
yes_token_id
no_token_id

reference_price
reference_timestamp
reference_age_ms

strike
seconds_to_expiry

yes_bid
yes_ask
yes_bid_size
yes_ask_size

no_bid
no_ask
no_bid_size
no_ask_size

book_timestamp
book_age_ms

tick_size
minimum_order_size
fee_rate

reference_source_status
clob_status
reference_latency_ms
clob_latency_ms
```

---

## Sampling Policy

The snapshot collector should not depend on whether the v1.1 strategy chooses:

```text
BUY
SKIP
too_early
too_close_to_strike
spread_too_wide
insufficient_edge
```

Strategy filtering must not determine which observations become available for v2 model training.

---

## Storage

Use a separate telemetry output from the existing operational logs.

Potential examples:

```text
btc_5m_market_snapshots.csv
```

or preferably partitioned/compressed files later.

---

## P2 Exit Criteria

P2 is complete when:

- raw snapshots are collected consistently
- collection does not alter trading behavior
- telemetry survives restarts
- timestamps are validated
- missing/stale feed states are visible
- production overhead remains acceptable

---

# P3 — Resolution Reconstruction and Label Validation

## Objective

Create an authoritative market-resolution dataset.

The label must represent the actual Polymarket market result.

---

## Primary Label

```text
y = 1  if market resolves YES / UP
y = 0  if market resolves NO / DOWN
```

---

## Requirements

Resolution logic must not infer the label solely from:

```text
local position state
local PnL
local cashout behavior
manual redemption
v1.1 open_positions
```

Use an authoritative market outcome source.

---

## Validation

Cross-check where possible against:

```text
Polymarket market result
account history
redeemed positions
reference close price
contract metadata
```

Disagreements must be logged rather than silently resolved.

---

## P3 Deliverables

```text
market-resolution table
resolution-source documentation
label-validation script
unresolved/disputed market report
label_version identifier
```

---

## P3 Exit Criteria

P3 is complete when training labels are reproducible and independent of local strategy behavior.

---

# P4 — Dataset Builder and Feature Pipeline

## Objective

Create reproducible model-ready datasets without future leakage.

---

## Dataset Unit

Each training row should represent:

```text
one market
at one prediction timestamp/horizon
```

with one eventual market-resolution label.

---

## Initial Prediction Horizons

Recommended research horizons:

```text
240 seconds to expiry
180 seconds
120 seconds
90 seconds
60 seconds
30 seconds
```

The exact horizons may be changed after inspecting coverage.

---

## Raw Feature Groups

### Contract/reference state

```text
reference_price
strike
distance_from_strike
absolute_distance
seconds_to_expiry
```

### Reference-price dynamics

```text
return_5s
return_15s
return_30s
return_60s
distance_velocity
acceleration
realized_volatility
high_low_range
trend persistence
```

### Polymarket state

```text
yes_bid
yes_ask
no_bid
no_ask
mid prices
spread
top-of-book depth
book imbalance
market-implied probability
short-horizon quote movement
```

---

## Feature Rules

Every feature must satisfy:

```text
feature_information_time <= prediction_timestamp
```

No exception.

---

## Versioning

Every dataset build must include:

```text
dataset_version
feature_version
label_version
date range
market count
row count
build timestamp
code/config identifier
```

---

## P4 Exit Criteria

P4 is complete when the same configuration can rebuild the same dataset deterministically from the canonical data.

---

# P5 — Baseline Predictive Models

## Objective

Establish strong interpretable baselines before introducing complex models.

---

## Baseline 0 — Market Probability

Measure the predictive quality of Polymarket itself.

Potential representations:

```text
YES ask
YES mid
normalized YES/NO mid
```

Report:

```text
log loss
Brier score
calibration
ROC-AUC where useful
sample counts
```

---

## Baseline 1 — Existing v1/v1.1 Heuristic

Treat the current heuristic probability as a benchmark.

Do not assume it is calibrated.

Measure its true out-of-sample behavior.

---

## Baseline 2 — Logistic Regression

Start with simple features such as:

```text
distance_from_strike
seconds_to_expiry
distance × time transformation
short-term return
realized volatility
```

---

## Baseline 3 — Regularized Logistic Regression

Evaluate:

```text
L1
L2
elastic-net where justified
```

to test whether a larger feature set provides stable incremental signal.

---

## Split Rules

Never randomly split snapshot rows.

Use chronological market-level splits.

Example:

```text
training period
validation period
untouched test period
```

---

## P5 Exit Criteria

P5 is complete when:

- all baseline metrics are known
- model performance is measured out-of-sample
- market baseline performance is known
- calibration quality is known
- coefficient behavior is inspected
- no leakage is detected

If ML does not improve on relevant baselines, do not hide that result.

---

# P6 — Probability Calibration

## Objective

Convert model output into probabilities that are empirically meaningful.

---

## Candidate Methods

```text
Platt scaling
isotonic regression
```

Potential future methods may be tested only if needed.

---

## Evaluation

Measure:

```text
Brier score
log loss
reliability curves
probability-bin counts
calibration slope/intercept where useful
```

---

## Isolation Rules

Calibration must use only historical information that precedes the final evaluation period.

Do not fit calibration on the final test set.

---

## P6 Exit Criteria

A calibrated model must demonstrate stable behavior across multiple probability ranges and chronological periods.

---

# P7 — Extended Predictive Models

## Objective

Test whether nonlinear models create additional out-of-sample predictive value.

---

## Candidate Models

Potential progression:

```text
HistGradientBoosting
XGBoost
LightGBM
other tree-based models if justified
```

Neural networks are out of scope unless simpler models have already demonstrated reliable residual signal.

---

## Research Questions

Test:

- nonlinear distance/time interactions
- order-book imbalance effects
- volatility-regime interaction
- spread/liquidity interaction
- quote momentum
- cross-feature interactions
- horizon-specific model behavior

---

## Guardrails

Do not evaluate dozens of models and hyperparameters against the final holdout.

Use validation periods for model selection.

---

## P7 Exit Criteria

Complex models must show meaningful and robust improvement over simple baselines.

Marginal gains that disappear across periods should not justify additional production complexity.

---

# P8 — Strategy and Expected-Value Simulator

## Objective

Transform calibrated probabilities into hypothetical trade decisions.

The prediction model remains unchanged.

---

## Required Separation

Input:

```text
calibrated P(YES)
market executable prices
fees
slippage assumptions
risk-independent strategy parameters
```

Output:

```text
trade direction
gross edge
estimated transaction cost
net expected value
trade/no-trade
```

---

## YES/NO Evaluation

Evaluate both sides coherently.

```text
P(NO) = 1 - P(YES)
```

unless a later research experiment explicitly justifies another formulation.

---

## Strategy Variables

Examples:

```text
minimum expected value
minimum probability confidence
maximum spread
minimum liquidity
allowed time-to-expiry range
```

---

## P8 Exit Criteria

The strategy simulator must be fully separable from the model and must produce deterministic decisions for a fixed prediction stream.

---

# P9 — Position Management and Re-Entry Research

## Objective

Determine how repeated decisions within one market should translate into positions.

Do not hard-code the v1.1 behavior.

---

## Policies to Compare

Examples:

```text
one entry per market
one entry + hold to settlement
one entry + cashout
re-entry after profit
re-entry after stop
maximum N entries
scale-in
scale-out
position reversal
no re-entry after profitable exit
no re-entry after loss
```

---

## Experimental Requirement

All policies should be evaluated against the same underlying prediction stream.

This prevents predictive-model changes from becoming confounded with position-management changes.

---

## Metrics

```text
realized PnL
expected PnL
maximum drawdown
trade count
market count
turnover
average win
average loss
win rate
profit factor
risk-adjusted return metrics
```

---

## P9 Exit Criteria

Select policies based on robust out-of-sample evidence, not isolated profitable examples.

---

# P10 — Realistic Execution Backtester

## Objective

Model the difference between theoretical strategy decisions and achievable fills.

---

## Execution Levels

### Level 0 — Mid-Price

Diagnostic only.

Never treat as executable performance.

### Level 1 — Bid/Ask Crossing

Trade against recorded bid/ask.

### Level 2 — Bid/Ask + Fees

Apply historical or correct fee schedule.

### Level 3 — Slippage + Latency

Include:

```text
decision latency
request latency
quote movement
slippage assumptions
```

### Level 4 — Depth-Constrained Fills

Use available size/depth where historical data supports it.

### Level 5 — Empirically Calibrated Execution

Use actual observed paper/live order behavior to estimate:

```text
fill probability
fill delay
partial-fill behavior
slippage distribution
cancel probability
```

---

## Execution Risks to Represent

```text
stale quote
quote disappears
partial fill
unfilled order
timeout
cancel race
network error
uncertain submission
minimum size
minimum notional
tick-size rounding
fee-rate changes
```

---

## P10 Exit Criteria

Backtest results intended for deployment decisions must include transaction costs and realistic execution assumptions.

---

# P11 — Walk-Forward and Robustness Evaluation

## Objective

Test whether the system survives changing market conditions.

---

## Evaluation Framework

Use:

```text
rolling training windows
rolling validation windows
forward test windows
expanding windows where justified
purged time-series validation if overlapping information requires it
```

---

## Regime Analysis

Inspect results across:

```text
high volatility
low volatility
strong trends
mean-reverting periods
wide-spread markets
thin-liquidity markets
different times of day
different market regimes
```

---

## Robustness Questions

- Does the edge exist across multiple periods?
- Does it depend on one short date range?
- Does one horizon dominate?
- Does one feature dominate?
- Does small parameter movement destroy profitability?
- Does calibration degrade over time?
- Does execution cost erase the apparent edge?

---

## P11 Exit Criteria

A candidate system should not proceed if profitability depends on:

```text
one lucky time period
one fragile threshold
unrealistic fills
heavy test-set tuning
```

---

# P12 — Paper Trading and Shadow Deployment

## Objective

Run the complete v2 inference and decision stack on live data without risking capital.

---

## Shadow Pipeline

```text
live market data
        ↓
snapshot
        ↓
features
        ↓
model
        ↓
calibration
        ↓
strategy
        ↓
risk
        ↓
hypothetical execution
        ↓
paper position lifecycle
        ↓
settlement
        ↓
performance report
```

---

## Compare Offline vs Live

Measure:

```text
feature distributions
missing-data rates
latency
prediction distributions
calibration drift
strategy trade frequency
simulated slippage
settlement correctness
```

---

## P12 Exit Criteria

Proceed only when:

- live feature generation matches research behavior
- state survives restart
- settlement lifecycle is correct
- shadow predictions are reproducible
- observed live conditions broadly match backtest assumptions
- no unexplained large performance divergence exists

---

# P13 — Small Live-Capital Validation

## Objective

Validate the execution and accounting stack with minimal capital risk.

This stage is not intended to obtain statistical significance quickly.

---

## Initial Rules

Use:

```text
small position sizes
strict daily loss limit
strict maximum exposure
limited concurrent markets
explicit live arming
kill switch
high-confidence logging
```

---

## Validate

Focus on:

```text
order submission
fill behavior
actual fees
actual slippage
partial fills
timeouts
position accounting
restart recovery
settlement
redeemability
reconciliation
```

Predictive performance remains important, but execution validation is a primary purpose of this stage.

---

## P13 Exit Criteria

Live execution must behave consistently with the simulator before increasing exposure.

---

# P14 — Productionization and Controlled Migration

## Objective

Convert the validated v2 stack into the primary production system without compromising operational safety.

---

## Production Requirements

```text
systemd service
explicit live arming
real-order permission gate
config isolation
atomic state persistence
restart recovery
reconciliation
Discord alerts
health monitoring
kill switch
daily loss control
drawdown control
log rotation
dataset capture
model/version tracking
```

---

## Migration Strategy

Do not immediately remove v1.1.

Possible migration pattern:

```text
v1.1 production
v2 shadow
        ↓
v2 small live
        ↓
v2 larger controlled live
        ↓
v2 primary
        ↓
v1.1 retired or retained as fallback/archive
```

---

# Cross-Cutting Architecture Requirements

## Prediction Layer

Must output probabilities or scores only.

Must not:

```text
place orders
size positions
manage stops
alter portfolio state
```

---

## Calibration Layer

Must be separately versioned from the model.

A new calibrator should not require retraining the base model unless necessary.

---

## Strategy Layer

Consumes:

```text
probabilities
market prices
transaction-cost estimates
```

Produces trade intent.

---

## Risk Layer

Must remain independent from model fitting.

Examples:

```text
max position size
max exposure per market
daily loss limit
drawdown limit
spread limit
liquidity limit
stale-data protection
consecutive-loss policy
kill switch
```

---

## Execution Layer

Responsible only for translating approved trade intent into exchange actions.

Must support idempotency and restart-safe behavior.

---

## Portfolio/Accounting Layer

Economic position must be derived from actual fills and settlement state.

Do not assume:

```text
order submitted = position
local open position = economically open
market expired = position resolved
manual redeem = automatically reflected locally
```

---

## Market Lifecycle

Market state should be represented separately from position state.

Example market lifecycle:

```text
discovered
open
expired
resolution_pending
resolved
claimable
redeemed
closed
```

Example position lifecycle:

```text
candidate
order_pending
partially_filled
open
exit_pending
closed
settlement_pending
reconciled
```

---

# Experiment Integrity Rules

## Final Test Set

The final test period must be touched rarely.

Do not repeatedly change the strategy based on final test results.

---

## Hyperparameter Search

Hyperparameters are selected on training/validation periods only.

---

## Threshold Search

Trading thresholds such as:

```text
minimum edge
minimum EV
maximum spread
time window
```

must be selected on development/validation periods, not the final holdout.

---

## Reporting

Always distinguish:

```text
training performance
validation performance
test performance
paper performance
shadow performance
live performance
```

Never merge these into a single headline result.

---

# Required Metrics

## Prediction

```text
log loss
Brier score
calibration curve
ROC-AUC where useful
precision/recall where useful
probability-bin sample counts
```

---

## Strategy

```text
expected value
trade frequency
edge distribution
average executable entry price
```

---

## Trading

```text
realized PnL
return on capital
average win
average loss
win rate
profit factor
maximum drawdown
turnover
exposure
risk-adjusted return metrics where meaningful
```

---

## Execution

```text
fill rate
partial-fill rate
slippage
submission latency
fill latency
cancel rate
timeout rate
reconciliation incidents
```

---

# Stop Conditions

Development should pause and reassess if any of the following occurs:

- authoritative labels cannot be reconstructed reliably
- historical timestamps are too ambiguous
- snapshot data is heavily filtered and cannot be repaired
- model advantage disappears after chronological testing
- calibration is unstable
- apparent profitability disappears with realistic execution cost
- strategy depends on one narrow historical regime
- paper results diverge substantially from backtest assumptions
- live execution behavior cannot be reconciled reliably

A negative research conclusion is a valid outcome.

The system should not be forced into production merely because development effort has already been invested.

---

# Current Project State

At the beginning of PolyBTC v2 development:

```text
### P10 Final Status — COMPLETE

P10 implemented and validated a realistic execution backtesting stack.

Implemented:

- exact P4 -> raw snapshot execution lineage
- recorded executable ask crossing
- taker-fee scenario modeling
- quote-age / stale-book analysis
- latency characterization
- minimum order-size enforcement
- tick-size validation
- top-of-book depth constraints
- deterministic adverse-slippage stress scenarios
- 5-share minimum executable position mapping

Key findings:

- 1,952 / 1,952 candidate entries had exact P4-to-raw snapshot lineage.
- Recorded strategy prices matched raw executable asks for all candidate entries.
- Minimum order size was 5 shares for all audited candidate entries.
- Top-of-book depth supported the minimum order for 1,944 / 1,952 audited entries.
- Typical book latency was approximately 85 ms median and approximately 100 ms p90.
- Book freshness contained a severe stale tail, so stale quotes cannot be treated as executable.
- Fee-adjusted gross signal survived before freshness/slippage constraints.
- Combined realistic execution results were materially weaker on validation than on development holdout.
- One- and two-tick adverse execution could eliminate several validation-period edges.
- Price-band configurations showed greater execution robustness, but they must not be selected based on repeatedly inspected validation results.
- Level 5 empirical fill calibration remains deferred until sufficient paper/live execution data exists.

Final P10 artifacts:

- `src/polybtc/execution/model.py`
- `tests/trading/test_execution_model.py`
- `scripts/run_p10_backtest.py`
- `scripts/run_p10_combined_backtest.py`
- `data/normalized/p10_level2_fee_scenario_report.json`
- `data/normalized/p10_combined_execution_trades.csv`
- `data/normalized/p10_combined_execution_report.json`

P10 conclusion:

Realistic execution does not eliminate all evidence of economic signal, but profitability is not stable enough across evaluated periods to justify deployment claims.

P11 walk-forward and robustness evaluation is required before paper/shadow deployment.
P11 — NOT STARTED
P12 — NOT STARTED
P13 — NOT STARTED
P14 — NOT STARTED
```

The immediate objective is:

```text
START P0
```

and produce a verified forensic audit of the existing PolyBTC v1/v1.1 system before implementing the v2 data/model stack.
