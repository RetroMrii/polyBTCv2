# PolyBTC Research: question, scope and hypotheses

R0 · 2026-10-14 · Documentation transition for review. No experiment or operational change is performed in R0.

## Research question

**Can a machine-learning model provide a statistically reliable and economically exploitable edge in Polymarket's five-minute Bitcoin prediction markets?**

Market prices are a strong competing forecast, not simply a source of entry prices. BTC direction prediction can be useful relative to chance while adding nothing beyond information already reflected in those prices. Short horizons also leave little time to acquire, process and execute on any advantage. The research must distinguish information, reliable probability estimation and executable opportunity.

The unit of outcome is one resolved five-minute market. Horizons 240, 180, 120, 90, 60 and 30 seconds are repeated forecasts of that outcome, not independent trials. Studying this sample cannot establish the efficiency or inefficiency of all prediction markets.

## What counts as edge?

| Claim | Required evidence | Insufficient evidence |
|---|---|---|
| Predictive edge | Proper scoring-rule improvement over a predeclared uninformed baseline on later eligible markets | Above-50% accuracy without class balance or uncertainty |
| Incremental predictive edge | Matched improvement over contemporaneous market-only probabilities, with dependence-aware uncertainty and a declared practical effect size | Beating chance, mismatched samples, or comparison with stale quotes |
| Economic edge | Frozen policy, available executable quotes, applicable cost model, causal risk/accounting, positive after-cost performance and independent replication | Positive estimated EV, midpoint PnL, a few winning bets or passing software tests |

Probability forecasts estimate uncertainty; they are not objective winning probabilities. Statistical significance alone need not imply a worthwhile economic effect. Forecast improvement need not survive spread, fees, latency, slippage or risk constraints.

## Testable hypotheses

The [protocol](RESEARCH_PROTOCOL.md#hypotheses-and-decision-rules) defines signed effects, tests, multiplicity and decision gates. These statements are research hypotheses, not established facts.

| Hypothesis | Proposed comparison | Interpretation |
|---|---|---|
| H0: ML does not improve forecasting beyond market probabilities | Frozen candidate versus matched raw and fitted market-only controls | Failure to reject is not proof that no ML model can work |
| H1: BTC dynamics or microstructure add information | Market-only control versus the same model family augmented with eligible features; predeclared ablations | Isolates additional features from merely changing model complexity |
| H2: Market-relative models outperform standalone BTC-outcome models | Market-relative versus standalone BTC model on identical observations; both also compared with market-only | Beating a weak standalone model alone does not establish edge |
| H3: Forecast improvement survives executable costs | Frozen candidate policy versus no trade and a matched market-only policy under identical execution/risk assumptions | Requires positive net economics as well as incremental benefit |

S5 is a provisional negative baseline: [summary and limitations](RESEARCH_BASELINE_S5.md). It does not validate H1–H3, nor does it establish a universal H0. The next step is to establish which market-relative inputs actually exist and were available at each deadline, not to train a larger model by default.

## Research and operational boundaries

| Responsibility | Existing locations | Research role and boundary |
|---|---|---|
| Research data collection | `scripts/operations/collect_vnext_local.py`, `src/polybtc/data/`, `data/raw/`, `data/live/` | Preserve raw observations, metadata and timestamps; a running collector is not a verified research dataset by itself |
| Offline feature engineering | `src/polybtc/data/dataset/`, `causal_features_vnext.py`, `scripts/modeling/`, `scripts/research/` | Build separately versioned causal features; no alteration of operational source rows |
| Model development | `src/polybtc/modeling/`, modeling scripts, `data/models/`, `data/experiments/` | Train only in authorized research stages; preserve the frozen HGB3 artifact |
| Chronological evaluation | Existing research scripts, `tests/modeling/`, `tests/research/` | Market-grouped comparisons and explicit sample membership; never infer validation from a filename |
| Probability calibration | Existing calibration modules/scripts; S5 exploratory calibration JSON | Fit only on earlier data; a research calibrator is not installed into the paper runner |
| Execution-cost simulation | `src/polybtc/strategy/`, `execution/`, `risk/`, standalone research analyses | Reuse pure calculations where appropriate; simulated entries remain separate from operational ledgers |
| Legacy paper trading | `src/polybtc/shadow/`, `data/paper/`, `dashboard/` | Preserve integration, durability and diagnostic history; paper activity is not the primary research success criterion |
| Disabled live execution | Existing CLOB adapter, live accounting and authorization gates | Retained engineering capability; no activation or live-capital stage in R0–R4 |

This is a conceptual ownership map, not a filesystem migration proposal. Keep current paths, compatibility launchers, historical notebooks, datasets, state and models. No new service layer or framework is needed for R0. If later work needs code restructuring, propose a bounded change separately.

## Authority and historical continuity

The research question, [protocol](RESEARCH_PROTOCOL.md) and [roadmap](RESEARCH_ROADMAP.md) supersede the earlier integration-first work queue for future research planning. They do not retrospectively edit the harness, P0–P14 definitions, P-EX results or S1–S5 findings. Existing safety and preservation constraints continue to apply. `p13_*`/`p14_*` research filenames are historical experiment IDs, not live-readiness milestones.

Only documentation is authorized in R0. No process is started, stopped or reconfigured; no collector, model, strategy, threshold, database or authorization state is changed. R1 begins only after review of this transition.
