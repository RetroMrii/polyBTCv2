# S5: Strategy economics audit

Date: 2026-10-14. Research only. **Outcome C — the market benchmark is superior or indistinguishable on the defensible paired evidence; HGB3 has not demonstrated incremental value that supports deploying a model-based strategy.** This is not proof that HGB3 can never add value. The strict later cohort has only 55 markets, and economic simulation has only 36. Neither positive executable edge nor profitability is established.

Operational strategy, model, thresholds, state and live authorization were not changed. Research scripts, documents, frozen derived inputs and a separately named exploratory calibration description are the only additions. No new dependencies or network requests were used.

## Current economics and intent

`src/polybtc/strategy/vnext.py:VNextStrategy.evaluate` chooses the market-favored side from `m=YES_mid/(YES_mid+NO_mid)`. Exactly neutral market probability abstains. HGB3 must be nonneutral, agree across 0.5, and be within an absolute 0.05 of m. This is a **maximum disagreement** rule, not a minimum edge rule. At the boundary HGB3=0.5, the earlier direction check can determine the terminal reason, but no trade is allowed.

The normalized midpoint is a two-book quote summary, not an independently calibrated settlement probability. It does not include spread crossing, fees or queue competition. With complementary midpoints it is the YES midpoint; otherwise normalization also incorporates book inconsistency/asynchrony.

```text
side = YES if m > 0.5 else NO
q_A = m if YES else 1-m
execution_price = selected_ask + one_tick
fee_allowance/share = fee_rate/4 + 0.00001
EV_A/share = q_A - execution_price - fee_allowance
```

HGB3 does not supply q_A. `runner_vnext.py` supplies a verified fee descriptor and the conservative fee allowance; `VNextStrategy` checks displayed selected-side depth >=5, price <=$0.70 and EV >0. The runner supplies reference age 3,000 ms and book age 500 ms explicitly; the standalone research class's 2,000 ms default is not the operational configuration.

Risk retains five shares, $7 maximum order value, $25 maximum open exposure, $10 daily realized loss and one entry per market. The executor rechecks quote freshness, provenance, tick/minimum-size/depth and reservation before a simulated fill. Negative source ages remain invalid. Model confidence never waives those requirements.

**Design assessment:** The formula is explicit in code and covered by tests; this audit finds no accidental variable substitution to repair automatically. Earlier `strategy/consensus.py` intentionally required direction agreement and a five-point gap (originally horizons 60/30); it did not establish a calibrated payout estimate or positive-EV requirement. The harness calls for cost-aware probabilistic trading but does not provide statistical justification for using the quote itself as expected payout. Thus market-based EV is an intentional conservative implementation with an incomplete/unsupported economic specification for finding *model-derived* mispricing. No retained document establishes that five percentage points is a calibrated uncertainty bound. Tight disagreement filtering may reject erroneous forecasts, but also rejects large genuine model edges; agreement does not validate probability accuracy.

For consistent complementary books, selected midpoint <= ask, so adding spread/slippage and a positive fee generally makes market-based EV negative. This explains the observed zero qualifications without proving a software malfunction. Inconsistent normalized books can break that simple inequality, so it is not a universal impossibility theorem. Changing to HGB3 payout probability would be a strategy change, not a harmless bug fix.

## Alternative specifications for review

| Policy | Estimated probability | Side selection | Status |
|---|---|---|---|
| A, current | Normalized market midpoint | Market-favored side, raw HGB3 agreement/gap | Operational implementation, unchanged |
| B, model-based | Earlier-period calibrated HGB3 | Candidate: side with highest positive cost-adjusted edge | Research hypothesis; not supported for promotion |
| C, combination | (1-alpha)*market + alpha*calibrated HGB3 | Candidate: highest positive cost-adjusted edge | Alpha fitted only on earlier calibration; no promotion |
| No-trade | No probability needed for trading | No entries | Zero PnL/exposure baseline |
| Market forecast | Normalized contemporaneous midpoint | Forecast scoring only | Paired predictive benchmark |
| Additional controls | Constant 0.5; equal market/raw mixture | Forecast scoring only | Untuned diagnostic controls |

The comparison report separates **EV substitution with every legacy agreement/gap rule preserved** from the explicit alternative side-selection hypotheses. The latter deliberately omit agreement/gap as research questions; they are not eligible operational settings. A defensible future candidate would require a training-defined uncertainty margin and conservative executable costs, not simply a probability exceeding an ask. Confidence intervals for an average Brier difference are not per-trade probability intervals.

## Research data inventory

The following are overlapping sources and derivatives, not independent datasets to concatenate. Full columns, hashes, label counts and boundaries are in `POLYBTC_S5_EVIDENCE.json`. Unix-second fields below are preserved as recorded.

| Dataset | Rows | Markets | Recorded boundary |
|---|---|---|---|
| `data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv` | 33366 | 5588 | 2026-09-17T17:26:00+00:00 to 2026-10-11T15:04:30+00:00 |
| `data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2_evaluation_predictions.csv` | 6662 | 1118 | 2026-10-07 17:56:00+00:00 to 2026-10-11 15:04:30+00:00 |
| `data/experiments/model_expansion/vm_expansion_v2/verified_resolutions.csv` | 857 | 857 | 2026-10-01T19:35:53+00:00 to 2026-10-11T15:10:52+00:00 |
| `data/normalized/p4_supervised_v1.csv` | 16388 | 2737 | 2026-09-17T17:26:00+00:00 to 2026-10-01T17:09:30+00:00 |
| `data/normalized/market_resolutions.csv` | 3017 | 3017 | 2026-09-15T18:26:27+00:00 to 2026-10-01T17:11:29+00:00 |
| `data/experiments/p13_model_improvement/p13_prospective_supervised.csv` | 11935 | 1995 | 2026-10-01T17:16:00+00:00 to 2026-10-08T16:04:30+00:00 |
| `data/normalized/p115_market_anchored_walk_forward_predictions.csv` | 8914 | 1994 | 2026-09-24T18:56:00+00:00 to 2026-10-01T17:09:00+00:00 |
| `data/experiments/p14_market_relative/p14_execution_abstention_rows.csv` | 14238 | 678 | 2026-10-06T06:28:00+00:00 to 2026-10-08T16:03:00+00:00 |
| `data/raw/v1.1/btc_5m_market_snapshots_v1_4.csv` | 158284 | 2852 | 2026-10-01T17:15:08.609988+00:00 to 2026-10-11T15:05:22.306045+00:00 |
| `data/raw/p12/btc_5m_market_snapshots_p12.csv` | 111417 | 2000 | 2026-10-01T17:15:08.609988+00:00 to 2026-10-08T16:05:56.313337+00:00 |
| `data/raw/p13/btc_1m_ohlc.csv` | 11086 | N/A | 1791060180 to 1791730860 |
| `data/external/bitcoin_history/btcusd_1-min_data.csv` | 7758900 | N/A | 1325376060 to 1790910000 |

The full v2 training set contains 33,366 rows / 5,588 markets: historical v1.1 2,737 markets, prospective P13 1,995, VM expansion 856. The saved evaluation CSV is a predecessor fitted on the earlier 60% partition, not the current full-data-refit artifact. The 6,662 historical test rows have only 5,054 paired market prices; 1,608 cannot enter model-versus-market comparison. All these test markets were subsequently incorporated in the deployed refit. Historical research also reused several periods for model-family/feature selection. Treat its scores as development evidence.

Historical raw snapshots have bid/ask and some depth/timing telemetry but lack the modern independently retained acquisition/receipt binding and actual decision deadlines. `build_p4_extension_from_p12.py` selects by observed time and ten-second lag; it cannot prove a quote was received by that time. Feature-only expanded CSVs cannot establish executable fills. P4/P13 labels originate in the resolution-validation pipeline; do not relabel these snapshots as live-verified observations. P11/P12/P14 execution CSVs are prior simulations, not venue fills or independent v2 tests. P11.5 market-anchored and equal-weight baselines exist and are reported as historical context, not pooled into the new test.

The external BTC one-minute history and local RTDS OHLC can support context/volatility research, not official Polymarket settlement labels. No BTC-price proxy label is used in S5. Historical v1/v1.1 order/fill telemetry is likewise not a validated execution test of the current model.

## Prospective data and causal quality

Frozen journal window: **2026-10-12 14:41:00 through 2026-10-13 21:19:30 UTC**, targets before 21:20. It contains **1,032 decisions / 172 markets**. The registry contains 171 market labels; 1,026 decisions join a label and six do not. They are missing retained resolutions, not assumed NO outcomes. The 50 markets in the earlier funnel report are all labelled now.

CSV `data/live/vnext_market_snapshots.csv`, sidecar `paper_acquisition.sqlite3`, receipt/checkpoint and decision databases under `data/paper/vnext_verified` were read without mutation. Source row identities are reconstructed from the captured source identity, byte offset and raw line. The frozen JSON records the exact checkpoint, CSV-prefix hash, model hash, labels and selected quotes; bytes appended later are outside this study.

706 decisions have reconstructable current causal features; 705 reproduce the stored model probability within 1e-12. The remaining decision (337751) has no stored probability because it stopped at `market_already_expired`; this is not a conflicting prediction. The other 326 have no reconstructed selected features. Of the 705 matches, 141 fail prediction-reference/anchor verification, leaving 564. A further 405 lack fresh, bound **prediction-time books**, leaving **159 paired rows / 97 markets**. All 159 have retained labels. This additional book filter is deliberate: comparing a fresh model to stale market prices would bias incremental-value analysis. It is stricter than the model's three-feature needs; missingness strongly changes horizon coverage.

For every included row, the selected observation and exact 30-second reference anchor were received by the target; canonical retained raw evidence binds market, tokens, reference/strike and books. Reference age <=3,000 ms and both prediction book ages in [0,500] ms are required at the appropriate deadline. Anchor freshness is checked at its own observation; it is historical input, not a current execution quote. The features are `(reference-strike)/strike`, target horizon, and `reference/current_anchor-1`; no labels or post-cutoff prices enter them. The three-feature artifact is unchanged. This confirms present feature causality, not historical receipt availability.

The paper strike remains the collector's nearest-boundary TWAP within five seconds, not independently authenticated official opening-price evidence. Historical training reference-provider differences and TWAP smoothing may create distribution shift. The model's internal `early_stopping=auto` used a random internal training validation fraction; that is not the external chronological test and does not justify calling internal scores independent market tests. The inspected artifact has 200 iterations and three features.

## Resolution provenance limits

`resolution_sync_vnext.sync_once` registers only VALID Gamma/Data API agreements after checking condition, closed/resolved status, exact binary payout, token mapping, winning token and resolution time. The current registry stores label, source version, evidence hash and resolved time. It does **not** retain the full fetched responses, winner token or retrieval time needed to independently recompute that hash or reproduce when a label became available. S5 uses these registry-verified official-source labels, not newly fetched confirmations. Every included label resolves after its prediction; all calibration labels resolve before the evaluation boundary. No label is inferred from probabilities or local BTC.

Consequently this is a conditional evaluation of the retained verification pipeline, not fresh independent attestation of settlement finality. Unknown label-receipt times also limit exact historical portfolio settlement/reuse of capital. Clock alignment remains a limitation: retained negative observation-relative source ages were documented in the funnel audit. Here negative ages at evaluation deadlines are excluded, but no independent NTP measurement was available to prove absolute UTC accuracy.

## Recommended next stage and acceptance

Do not change the paper strategy based on S5. Continue model/feature and market-relative research, with the no-trade baseline available. Pre-register one primary forecast comparison and one candidate before collecting its final test period. Use at least **1,000 distinct eligible calibration markets and 2,000 later eligible evaluation markets over at least 14 calendar days**, with both outcomes and adequate coverage per horizon (target >=300 final-test markets per claimed horizon). Extend collection until counts and uncertainty requirements are met; this is a planning floor, not a power guarantee or instruction to wait idly.

Retain immutable model/calibration hashes, actual prediction receipts and dependency IDs, two-sided books/depth/minimum size/ticks, fee descriptor and applicable accounting, actual final-check/executor timing, and raw official resolution responses plus first retrieval timestamps. Preserve all rejected opportunities and skip reasons. Keep the final outcome labels hidden from parameter selection until the predeclared readout. The existing sample is now development evidence and must not be recycled as that final test.

Promotion requires reproducible improvement over market on paired chronological data with market/day dependence reflected in uncertainty, calibration stable across declared horizons/regimes, positive after-cost economic results with a lower confidence bound supporting the claim, and survival of predeclared latency/slippage/uncertainty stress. An adequate number of independent candidate trades is required; fewer than 100 resolved candidate markets is a review stop for profitability claims, not proof that 100 guarantees power. Actual paper execution and settlement must then be observed prospectively with all safeguards. No profitable candidate is recommended now.

## Reproduction and validation


```powershell
Set-Location H:\PolyBTCv2
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_s5.py
.\.venv-execution\Scripts\python.exe -B scripts/research/render_s5_reports.py
.\.venv-execution\Scripts\python.exe -B -m pytest tests/research/test_s5_audit.py -q --basetemp=H:\PolyBTCv2\.pytest_cache\s5_research_tests
```

`audit_s5.py --capture` was used once to read operational data into the separate, versioned `data/research/s5_v1/inputs.json`; it refuses to overwrite that file. Do not delete it to refresh a result. A later study must use a new research version and predeclared cutoff. Reproduction without `--capture` uses frozen observations/labels, the frozen artifact hash and existing historical research files, not a changing operational journal. The pytest base directory is research scratch only. All operational database reads use SQLite `mode=ro` and `query_only`; socket connections are disabled in the audit command. No trading services are instantiated.

Six focused research tests cover equal-market weighting, finite endpoint log loss, reliability-bin endpoints, paired/block uncertainty identity, SQLite write rejection, and NO-side payoff/fees/one-entry enforcement. Initial pytest temporary-directory access failed; rerunning with a new workspace-local scratch directory passed. Hash checks confirm the main model and training CSV match the manifest; no operational regression suite is claimed because production code was not edited.

Companions: [calibration report](POLYBTC_S5_CALIBRATION_REPORT.md), [strategy comparison](POLYBTC_S5_STRATEGY_COMPARISON.md), [machine evidence](POLYBTC_S5_EVIDENCE.json), [frozen derived inputs](../data/research/s5_v1/inputs.json).
