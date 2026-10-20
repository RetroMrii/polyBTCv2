# S5: Executable strategy comparison

Date: 2026-10-14. **Outcome C — no demonstrated incremental forecast value or deployable after-cost edge.** No operational strategy changes are recommended. A small near-zero hypothetical basket is not evidence of profitability.

## Common inputs and simulation scope

Start with 1,032 journal opportunities; 705 stored HGB3 predictions reproduce, 564 also have verified causal prediction reference/anchor, and 159 have a fresh bound contemporaneous market benchmark and official-source registry label. Of those, 66 earlier observations fit calibration; **93 later observations / 55 markets** form the chronological forecast evaluation. Only **43 of those / 36 markets** actually reached strategy after execution-source and fee checks. They are the common economic denominator below. The other 50 later rows are not counted as executable candidates. Earlier funnel totals 97 strategy evaluations / 300 decisions describe a different window and eligibility set; they are not contradictory.

No finalized decision is replayed into a journal. No freshness recovery is assumed. The 68 idealized latency recoveries from the earlier funnel are excluded. This conditional simulation uses retained quotes known to have reached the original strategy's final freshness check, not a newly measured executor timestamp. Added calibration work could consume the remaining book budget. Consequently even these entries are **hypothetical**, not observed or assured fills.

Each row retains model probability, prediction/market IDs, calibrated estimates, executable two-sided asks/depth, source timestamps, fee descriptor, minimum size and ticks. Labels are registry-verified official-source outcomes. Full quote and per-trade details are in `POLYBTC_S5_EVIDENCE.json` / frozen `inputs.json`. Unknown resolution-retrieval and final executor times prevent a fully observed portfolio/fill replay.

## Execution and risk assumptions

- Buy five shares at selected ask + one tick, using the same maximum YES/NO tick input as the runner. Price <=$0.70, sufficient selected ask depth and minimum size <=5 remain mandatory. Maximum permitted quantity is five shares; if the depth/minimum-size/price tests fail, no partial smaller order is assumed.
- Qualification fee allowance is rate/4+$0.00001 per share. At rate 0.07 it is $0.01751. Simulated charged cash fee is `round(5*rate*price*(1-price),5)`, preserving full shares. This is the explicit **paper cash model**, not independently authenticated actual venue fee collection or share deduction. Applicable live accounting remains outside this claim.
- Maximum possible loss is five-share acquisition cost plus charged fee. Enforce $7 order limit, $25 total open capital, and one entry per market in timestamp order. No operational positions were readjusted or reserved.
- Settlement receipt time is not retained. For the offline scenario, **do not release any capital or realize any PnL until the end of the session**. Thus daily realized PnL remains zero during entry selection and cannot supply funds to a later trade. This conservative holding scenario is not a reconstruction of actual settlement cadence. At the end, label every selected contract and calculate its payout. The reported drawdown is cumulative labelled PnL in entry order, not an observed mark-to-market equity curve. It does not prove that an alternative settlement schedule would pass daily-loss checks.
- Books must pass 500 ms and reference 3,000 ms in the original control flow. No future timestamp allowance, maker fill, queue priority, deeper-book liquidity, latency recovery or price improvement is invented.

## Controlled comparison: change estimated payout only

A uses market probability. B_raw is diagnostic uncalibrated HGB3, B_platt uses earlier fitted Platt probability, C uses the fixed 13.61% Platt / 86.39% market combination. **All choose the existing market side and retain raw-HGB3 directional agreement and five-point gap**, isolating EV substitution. C uses the execution midpoint for its current quote component; its forecasting calibration weight was fitted at prediction cutoffs. That timing/context shift is another unvalidated assumption, not a calibration guarantee.

| Policy | Positive-EV rows | Price/depth/direction/gap pass | Hypothetical entries | Labelled net PnL | Entry-order drawdown | Win rate |
|---|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 0.000000 | 0.000000 | N/A |
| B_raw_diagnostic | 13 | 0 | 0 | 0.000000 | 0.000000 | N/A |
| B_platt | 0 | 0 | 0 | 0.000000 | 0.000000 | N/A |
| C | 0 | 0 | 0 | 0.000000 | 0.000000 | N/A |


No-trade baseline: zero entries, zero PnL, zero drawdown; win rate and trade forecast scores undefined. For the controlled policies, all trade-level forecast scores are likewise undefined because there are no trades. A, calibrated B and C have nonpositive EV for all 43 selected-side inputs. Raw HGB3 produces 13 positive estimates, but seven fail the legacy gap and six fail the ceiling. A positive uncalibrated estimate is not proof of a true edge.

## Explicit alternative: let calibrated estimates choose either side

The following **post-hoc research hypotheses** choose the side with larger `q_side-ask-tick-fee`, require that edge to be positive, and remove the old direction/gap filters. Both sides retain the same freshness, prices, depth, minimum-size, size, fee and capital assumptions. This is a different strategy specification, not a recommended operational relaxation. It often buys the market underdog because the small-sample Platt fit pulls forecasts toward 0.5.

| Policy | Positive-EV rows | Price/depth/direction/gap pass | Hypothetical entries | Labelled net PnL | Entry-order drawdown | Win rate |
|---|---|---|---|---|---|---|
| B_platt | 40 | 39 | 23 | 0.036340 | 7.358290 | 0.217391 |
| C | 14 | 14 | 13 | -6.381450 | 7.533590 | 0.076923 |


The column labelled entry constraints omits agreement/gap for these explicit alternatives. B has 40 positive-edge observations, 39 size/price passes; three later same-market entries and 13 capital-limit attempts are rejected, leaving 23 distinct markets. C has 14 positive observations and one repeated-market rejection, leaving 13. The B basket's **+$0.03634 total** is effectively flat at this sample size; C loses **$6.38145**. This is conditional paper accounting on labelled contracts, not cash earned. Neither identifies a credible positive-expectation policy.


| Alternative | Trade forecast Brier | Trade forecast log loss | Entries by horizon |
|---|---|---|---|
| B_platt | 0.176736 | 0.538722 | {'90': 2, '60': 2, '240': 5, '180': 10, '120': 4} |
| C | 0.071009 | 0.270700 | {'180': 3, '120': 4, '240': 2, '30': 1, '90': 2, '60': 1} |

These trade-score cohorts differ, so the lower C Brier cannot establish C's superiority; it buys mostly low-probability outcomes. Forecast quality must be judged on the common 93-row cohort, where neither model variant beats market. Only 23 and 13 trades are available, with correlated market regimes and a fitted calibration based on 42 markets. No statistically credible economic-confidence claim can be made from this basket. Full-session risk-dependent trade selection would also change under different settlement timing.

### Representative trade arithmetic

- B_platt, decision **338031**, NO: calibrated selected probability 0.361987, execution price $0.34, estimated edge $0.004477/share. Five-share fee $0.07854, maximum loss $1.77854; registered outcome wins, labelled scenario PnL $3.22146. This was not an operational entry.
- C, decision **338053**, YES: calibrated selected probability 0.092762, execution price $0.07, estimated edge $0.005252/share. Five-share fee $0.02279, maximum loss $0.37279; registered outcome loses, labelled scenario PnL $-0.37279. This was not an operational entry.

## Robustness: diagnostics, never threshold selection

The controlled A/B_platt/C policies remain at zero entries with zero or two slippage ticks, doubled fee rate, two/five-point probability haircuts, widened gap or an 80-cent price ceiling. Those sensitivities do not authorize any operational change. Haircuts are stress assumptions, **not statistically fitted confidence bounds**.

Raw-HGB3 sensitivity shows how easy it is to manufacture apparent opportunities from a small sample:

| Raw diagnostic variation | Entries | Labelled net PnL |
|---|---|---|
| zero_ticks | 1 | 1.426500 |
| two_ticks | 0 | 0.000000 |
| double_fee | 0 | 0.000000 |
| uncertainty_2pp | 0 | 0.000000 |
| uncertainty_5pp | 0 | 0.000000 |
| gap_10pp | 0 | 0.000000 |
| gap_unbounded | 2 | -2.147000 |
| ceiling_80c_diagnostic | 3 | 3.988380 |

Do not choose the favorable zero-tick or 80-cent result. They change protected execution assumptions, rely on one or three selected markets and were inspected on the same outcomes. There is no out-of-sample profitability conclusion or threshold recommendation.

For the explicit best-side alternatives:

| Alternative | Stress | Entries | Labelled net PnL |
|---|---|---|---|
| B_platt | two_ticks | 22 | 0.109100 |
| B_platt | double_fee | 22 | 0.107500 |
| B_platt | uncertainty_5pp | 24 | -4.870460 |
| C | two_ticks | 6 | -5.865570 |
| C | double_fee | 1 | -0.618530 |
| C | uncertainty_5pp | 1 | -0.584270 |

Changing costs or a probability haircut also changes which entries are selected and when the capital cap binds; total PnL need not move monotonically. B's few cents at baseline, two ticks or doubled fees are not a stable economic edge; a five-point haircut produces a loss. C remains negative in the tested stresses. Spread is paid through actual asks, and one/two additional ticks represent adverse executable-price stress. No artificial tightening of recorded spreads or subsidized fees is used in the baseline.

### Latency stress

At persisted source-verification time plus the following hypothetical additional delays, this many of the 43 inputs still satisfy all source-age limits:

| Additional ms after recorded verification | Passing source ages |
|---|---|
| 0 | 43 |
| 50 | 43 |
| 100 | 42 |
| 250 | 11 |
| 500 | 0 |

These are source-age arithmetic bounds, not measured added latency after the final runner check. That check's exact timestamp and calibration/executor duration were not persisted. The original 43 reached strategy, but no newly fitted policy has demonstrated an actual timely fill. Causal cutoff and timestamp values never change in this sensitivity.

### Uncertainty, drift, horizon and volatility

The forecast report shows raw model-versus-market Brier uncertainty crossing zero, poorer calibrated scores, small tail bins and a severely undercovered 30-second horizon. Fixed 30-second TWAP-return regimes both favor market; genuine spot-volatility conditioning is not available here. Neither a per-horizon calibration nor per-regime entry threshold is justified by these samples. The 42-market calibration can drift or overfit; uncertainty in it is not captured by merely applying the fitted number to an ask.

## Decision and next step

**Select Outcome C.** Raw HGB3 has some predictive information relative to a constant forecast, but the available paired evidence does not establish incremental value over market. No calibrated alternative demonstrates credible executable economic benefit. Small sample size, raw-resolution retention gaps, execution timing and capital-release uncertainty remain research limitations; they do not justify selecting the most favorable sensitivity.

The smallest useful next stage is a preregistered, read-only prospective forecast study with retained raw settlement evidence and actual execution timing. Investigate market-relative features/residual prediction only on training/selection periods, then freeze one candidate. Keep current paper operation unchanged for review. Promote no candidate unless it passes the data, paired-score uncertainty, calibration and after-cost acceptance criteria in the economics audit. Paper-only prospective testing would require a separate authorization after that evidence exists.

Reproduction: [audit commands](POLYBTC_S5_STRATEGY_ECONOMICS_AUDIT.md). Supporting [forecast report](POLYBTC_S5_CALIBRATION_REPORT.md) and [evidence](POLYBTC_S5_EVIDENCE.json). Operational PnL, risk reservations and positions were not modified.
