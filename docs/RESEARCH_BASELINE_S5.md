# Research baseline: S5 and the decision funnel

R0 summary · 2026-10-14. This document summarizes existing evidence; it does not rerun or revise S5. The original S5 files and derived research artifacts remain unchanged.

## Baseline conclusion

**S5 selected Outcome C: no demonstrated incremental predictive value from frozen HGB3 over the market benchmark, and no credible after-cost advantage.** This is a provisional negative finding for the tested artifact, inputs and periods. It is not proof that every ML model or market-relative feature set will fail.

Original evidence:

- [Decision-funnel report](POLYBTC_DECISION_FUNNEL_REPORT.md) and [evidence](POLYBTC_DECISION_FUNNEL_EVIDENCE.json).
- [S5 economics audit](POLYBTC_S5_STRATEGY_ECONOMICS_AUDIT.md).
- [S5 calibration report](POLYBTC_S5_CALIBRATION_REPORT.md).
- [S5 strategy comparison](POLYBTC_S5_STRATEGY_COMPARISON.md).
- [S5 machine-readable evidence](POLYBTC_S5_EVIDENCE.json), [frozen inputs](../data/research/s5_v1/inputs.json) and [exploratory calibration parameters](../data/research/s5_v1/calibration_s5_exploratory_v1.json).

## Distinct cohorts: do not combine denominators

| Study/cohort | Recorded scope | Finding |
|---|---|---|
| Decision funnel, October 13 session | 300 decisions / 50 markets; targets 14:31–18:39:30 UTC | 222 selected horizons, 157 source/fee passes, 97 strategy evaluations, zero economic qualifications, reservations or fills |
| Expanded S5 journal capture | 1,032 decisions / 172 markets; October 12 14:41 through October 13 21:19:30 UTC | 705 stored predictions reproduced; 564 also had verified prediction reference/anchor; 159 had a fresh matched market benchmark and label |
| S5 calibration | 66 observations / 42 markets; October 12 14:47 through October 13 10:56 UTC | Earlier fitting partition; not independent evidence of calibration quality |
| S5 later forecast evaluation | 93 observations / 55 markets; October 13 14:33–21:13 UTC | Chronological paired evaluation, cutoff October 13 14:30 UTC |
| S5 common executable comparison | 43 later observations / 36 markets | Subset that actually reached strategy after the original execution-source checks |

In the funnel, 143/300 stopped at horizon/provenance gates, 60/300 expired after verification and 97/300 abstained economically. The 68 additional idealized latency-recoverable observations still failed unchanged economic rules; they were not fills or part of S5's executable sample.

Of S5's 1,032 decisions, 327 lacked a matching recorded/reconstructable probability (one had reconstructable features but had stopped before recording inference), 141 then failed reference/anchor verification and 405 then failed the stricter fresh prediction-book pairing. All remaining 159 had registry labels. Six decisions in the broader capture lacked retained labels; none was assigned a proxy outcome.

## Model and historical-data status

The frozen artifact is `data/models/main/hgb3_expanded_v2.joblib`, SHA-256
`42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`.
It uses relative reference-to-strike distance, target horizon and causal 30-second reference return. It outputs raw, uncalibrated probabilities.

The artifact was refitted on **33,366 rows / 5,588 markets**, September 17 17:26 through October 11 15:04:30 UTC, and created October 12. The saved historical 60/20/20 evaluation predictions belong to an earlier-partition fitted predecessor; those evaluation markets subsequently entered the full refit. They cannot independently validate this frozen artifact. Historical raw/normalized/P13/P14 files overlap and must not be counted as new markets without membership checks.

S5 found zero training-market overlap for its captured prospective markets and reproduced 705 probabilities from the unchanged model. Its later test was exploratory and already exposed through the S5 readout; **all inspected S5 outcomes now belong to development evidence**, even where they were genuinely post-training.

## Paired forecast results

Each market has equal total weight, divided among its available horizons. Lower Brier and log loss are better. ECE used ten fixed equal-width bins and is diagnostic rather than a proper scoring rule.

| Forecast | Brier | Log loss | Accuracy | ECE |
|---|---:|---:|---:|---:|
| Market midpoint | 0.123156 | 0.385148 | 0.836364 | 0.095407 |
| Raw HGB3 | 0.150580 | 0.465150 | 0.772727 | 0.136479 |
| Platt HGB3 | 0.181082 | 0.548944 | 0.818182 | 0.189739 |
| Isotonic HGB3 | 0.184132 | 0.860512 | 0.656061 | 0.078945 |
| Market/Platt combination | 0.126235 | 0.401337 | 0.836364 | 0.096927 |

Raw-minus-market Brier difference was **+0.027424**, with 95% market-cluster interval **[-0.006809, +0.064703]**; six-market-block sensitivity was **[-0.012964, +0.068115]**. The intervals include equality. Market is better on point estimates; this is not definitive universal superiority. Platt/isotonic fitted on only 42 markets did not improve later proper scores. The combination assigned 13.61% to Platt and 86.39% to market, fitted on the earlier period only, and did not beat market.

These are conditional, small-sample intervals, not comprehensive model-selection uncertainty or a guarantee across regimes. The 30-second horizon had only two later observations. More favorable individual horizons or bin-level ECE must not be selected retrospectively as proof of edge.

## Economic interpretation

The existing strategy estimates payout from **market-implied probability**; raw HGB3 serves as a direction/gap filter. On approximately complementary books, paying the ask plus a tick and fees generally makes that market-based EV negative. Replacing the payout probability is a strategy specification change, not an automatic bug fix.

On S5's 43 common executable observations, current market-based EV, raw-model EV substitution, calibrated-model EV substitution and the blend all produced **zero entries with the existing agreement/gap/price/depth rules**. Raw model estimates were positive for 13 rows, but other constraints rejected all 13.

Post-hoc alternatives that chose either side and omitted the agreement/gap filters yielded 23 hypothetical Platt entries with **+$0.03634** total labelled net PnL, and 13 blend entries with **-$6.38145**. They used paper cash fees, five shares and conservative no-capital-release during the session; exact execution and settlement-receipt timing were unavailable. These are conditional simulations, not operational fills, deployable policies or credible profitability evidence. Favorable sensitivity results from one or three trades do not overturn the conclusion.

## Limitations carried into R1

- Strict eligible samples are small and selectively missing, especially late horizons.
- Official-source registry labels were validated by the existing pipeline, but raw resolution responses and first retrieval timestamps were not retained for full independent re-attestation and settlement-availability replay.
- Some source/clock alignment questions and final execution/inference timing measurements remain unresolved; measured data must not be replaced by inferred zero latency.
- Historical provider/strike semantics and receipt coverage differ from the prospective pipeline. The collector's nearest-boundary TWAP strike is not independently authenticated official opening-price evidence.
- Fee simulation preserves the existing explicit cash model; it is not proof of actual venue fee collection/fill mechanics.
- Calibration and market-relative policy selection need more independent markets/days. Research scripts, passing tests and successful integration establish implementation behavior, not economic benefit.

S5 recommended at least 1,000 calibration and 2,000 later evaluation markets over at least 14 days, adequate per-horizon coverage, and dependence-aware power checks. These are planning floors to revisit in a registered experiment, not a reason to invent data or claim readiness by count alone.

## Reproduction

R0 only inspected the existing reports/evidence; **the commands below were not run during R0**. Run from `H:\PolyBTCv2` using the existing pinned `.venv-execution` environment. The original S5 commands are:

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_s5.py
.\.venv-execution\Scripts\python.exe -B scripts/research/render_s5_reports.py
.\.venv-execution\Scripts\python.exe -B -m pytest tests/research/test_s5_audit.py -q --basetemp=.pytest_cache/s5-reproduction-unique
```

The first two commands regenerate S5 research outputs at fixed paths. **To preserve the original evidence, reproduce in a separate copied checkout/workspace with the same relative input paths and compare outputs there.** Do not run them in the original workspace during R0, use `--capture` to replace a cohort, or treat a regenerated result as new validation. The capture refuses to overwrite existing inputs. Use a fresh scratch test directory, never operational state. New research must use distinct version/output IDs after authorization.

The S5 evidence records input/model/script hashes, software versions, seeds and row membership. Its six focused research tests passed during S5. That historical test result is not a new R0 test run. Full statistical comparison, timing limitations and dataset inventory remain in the unchanged original reports linked above.
