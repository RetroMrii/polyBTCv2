# R1 — Proposed R2 experiment card

Status: **proposal for review, not registered or run**. Recommendation: **collect additional data before modeling**. The [audit](POLYBTC_R1_COVERAGE_REPORT.md) establishes that a small market-relative experiment is technically feasible, but its current verified comparison cohort is too small and temporally concentrated for defensible model selection or incremental-edge claims. No R2 experiment begins with this report.

## Question and bounded candidates

Does collector-reference displacement and causal 30-second reference momentum improve forecasts beyond contemporaneous Polymarket probability, with the same model family and fitting privileges?

| Candidate | Inputs | Proposed family |
|---|---|---|
| A — Fitted market control | `logit(q)` and categorical requested horizon | L2 logistic regression |
| B — Market-relative augmentation | A plus D=(R−K)/K and existing causal r30 | The same logistic regression, penalty search and weighting |
| C — Standalone BTC | D, r30 and the same horizon indicators; no market probability | The same logistic regression, penalty search and weighting |

Untuned controls: raw q, constant 0.5 and development class prior. Frozen HGB3 may be included as an explicitly exposed-development reference, not retested as a fresh model on its training markets. No tree search, new feed, retraining of deployed HGB3 or trading policy optimization is proposed.

Use identical `market × horizon` IDs from the intersection for A/B/C and controls. The primary comparison is B minus A, accompanied by B minus raw q and B minus C. A must receive the same calibration, regularization search and horizon treatment as B/C. A weak or deliberately uncalibrated control cannot establish incremental value.

Top-size imbalance is feasible without additional loss, but exclude it from the first primary B to keep the question narrow. A single predeclared secondary ablation adding `I_Y−I_N` could be authorized later within an explicit multiplicity/search budget; it is not an invitation to search combinations. Market lags and sampled volatility have substantial coverage losses and do not belong in the initial primary set. No feature decision above used final outcomes.

## Data and causal contract

- Current core: **159 observations / 97 markets**, Oct 12–13, already exposed S5 development evidence. Sizes preserve all 159. No split of these two days makes them an adequate new final test.
- Historical exploratory ceiling: **25,121 finite matched rows / 5,587 markets** in the frozen v2 training dataset. Their missing original receipt proof and prior model-selection exposure prohibit treating them as equivalent verified data. Any use for preliminary numerical debugging must be separately labelled and cannot satisfy the main acceptance gate.
- Future core definition: latest received observation at cutoff T=expiry−H, lag <=10 sec; raw binding and token/interval match; both books 0–500 ms old; current reference 0–3,000 ms old; existing r30 anchor with its own observation-time freshness and receipt by T. Opening reference remains explicitly a collector TWAP proxy unless official strike evidence is separately acquired.
- No future interpolation, cross-market anchor substitution or imputation in the primary comparison. Preserve exclusion flags for every opportunity, including unlabelled ones. Drop missing/conflicting labels, never assign NO by default. Retain official raw settlement evidence and first retrieval for future fit-time label eligibility.
- All new rows need source and membership hashes plus a label-exposure register. October 14–17 raw prices are not automatically a final test: their availability is unverified, labels are absent, and prior work has inspected their covariates.

## Chronology and sample plan

Proposed development design: three expanding market-disjoint folds on the early development period. Each fold has an earlier fit block, a later calibration block and a still later validation block. Advance all boundaries by whole markets; labels must have been available before their fit/calibration use. Purge at least the longest consumed feature window at boundaries; conservatively propose a five-minute boundary gap, to be registered. Fit scaling only on fit rows; no normalization over future partitions.

Propose one small regularization grid `{0.1, 1, 10}` for each A/B/C, chosen only by market-weighted development Brier. Use either identity probabilities or one logistic calibration fitted on the later calibration block; choose that rule in advance, or include its selection within the same declared budget. No isotonic fitting on this tiny sample. Freeze one complete A/B/C specification before later confirmatory comparison.

Planning floors inherited from the protocol: **1,000 independent markets for calibration and 2,000 later evaluation markets spanning at least 14 days**, plus a separate earlier training/development period. These are not sufficient by themselves; revise using development-only paired-loss variance, serial dependence and per-horizon coverage. At the observed 15.4% opportunity retention, six horizons do not create six independent samples; do not turn a row target into a market guarantee. The current 97 markets over two dates are inadequate for the proposed three-fold design and final test. Exact training count, period boundaries and per-horizon minimums remain unregistered.

Use a future fixed calendar readout with a minimum eligible-market gate, or a fixed eligible-market target with a predeclared maximum duration; choose **one** before acquisition outcomes are inspected. If the gate fails, report insufficient data. Do not stop early for favorable significance. R2 uses development/calibration only; R3 owns the untouched final readout and R4 prospective replication.

## Metrics and decision rules

Primary: Brier loss, one total weight per market divided among its eligible horizons. Mandatory corroboration: log loss with a predeclared endpoint clipping convention. Diagnostics: fixed ten-bin reliability/ECE, coverage, horizon and probability-band results. Accuracy is not the selection metric.

Paired differences are candidate loss minus comparator loss on the same rows, aggregated by market. Use two-sided 95% intervals retaining whole markets and chronological day/moving-block dependence. Choose block length on development diagnostics; report block/day counts and sensitivity. With only two days, do not claim reliable dependence-aware confidence intervals. Selection uncertainty must be addressed through development folds and subsequent prospective replication, not a single conditional bootstrap.

Follow `RESEARCH_PROTOCOL.md`: improvement must exceed a registered practical Brier margin `delta_pred>0` against A **and** raw q, with log-loss deterioration upper bound within the predeclared margin (default zero). B versus C addresses market-relative value only if B also beats market controls. Predeclare gatekeeping or Holm familywise 5% control for confirmatory comparisons; horizon slices are descriptive unless separately registered. An inconclusive result is not equivalence or proof of no possible edge.

Economic viability is a later separate gate. Forecast gains do not authorize entries. Retain actual ask/tick/fee/depth, 500/3,000-ms freshness, latency and all existing price/size/risk limits for any future cost simulation. Require actual fee and settlement availability rather than assuming zero latency or immediate capital recycling. No EV, probability-gap or entry-price sweep is part of R2.

## Registration and acceptance checklist

Still requiring registration **before fitting**: exact immutable source/market manifests and UTC partition boundaries; handling of exposed historical data; provider/strike and label provenance acceptance; scaling/logit clipping; penalty and calibration search budget; random seed/software versions/output IDs; practical Brier/log-loss margins; primary comparison family and multiplicity method; block length and power calculation; development/calibration counts and horizon minima; fixed stopping/readout rule. This card does not imply those choices have been approved.

Acceptance before R2 starts:

1. Review R1 and approve the bounded candidate set and data contract.
2. Establish enough receipt-backed, officially labelled development markets/days to run the declared folds without reusing S5 as an untouched test; preserve raw label/retrieval evidence and provider/clock limitations.
3. Freeze the completed card and manifests. Verify market separation, causal anchors, missingness, label availability and matched A/B/C membership with focused research checks.
4. Reserve a genuinely later, unexposed evaluation period for R3. Report negative/inconclusive results without adding variants after final outcomes are read.

No new service layer is required. The next authorized work should address the specific coverage/provenance gaps using the existing acquisition and research infrastructure; changes to collection or official-label retention require separate review. **Do not begin R2 until R1 and the completed experiment card are reviewed.**
