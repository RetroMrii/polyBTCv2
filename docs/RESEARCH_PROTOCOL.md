# PolyBTC Research protocol

R0 version 1 · 2026-10-14 · Protocol for review before new experiments. This document specifies methodology, not permission to run R1 or change operation.

## 1. Register the experiment before measuring its final result

Each experiment card must record: question/hypothesis; immutable dataset paths/hashes and market IDs; UTC boundaries; label/feature versions; data exclusions; candidate families and search budget; baseline definitions; fitting/calibration/selection rules; primary metric; minimum worthwhile effect; uncertainty method/block length; multiplicity family; cost/risk assumptions; power/sample and stopping plan; random seeds; software versions; output paths; and decision on positive, negative or inconclusive results.

An incomplete card cannot advance to a confirmatory test. Practical effect sizes and block lengths must be chosen from economic requirements and development-only diagnostics, not final outcomes. Freeze one candidate and its complete preprocessing/calibration/policy before the final readout. Log all attempted variants, not only the winner.

## 2. Data classes and chronological isolation

- **Exploratory/development:** all exposed S5 inputs/outcomes, historical training data and previously inspected evaluations. Reuse for diagnosis with explicit labels, never as a new untouched test.
- **Training:** earliest partition; fit features, scaling/imputation and model parameters here. Use market-grouped chronological inner validation for tuning/early stopping; random row splits are not independent validation.
- **Calibration/selection:** strictly later markets; fit probability calibration and choose a policy/combination here, with a declared search budget. Reserve internal chronological validation when comparing many calibrators. Calibration fit scores are not performance evidence.
- **Final test:** strictly later, market-disjoint data whose outcomes have not influenced any model, threshold or feature decision. Read once after the candidate and analysis plan freeze. Newly accumulated data is not automatically untouched: maintain an access/exposure register.
- **Prospective replication:** genuinely later acquisition after freeze, independently labelled, with the same candidate and protocol. Any substantive change starts a new candidate/version and a new final period.

Record the exact membership and availability of training labels as of each fit. A later known resolution must not be treated as available earlier. Purge market overlap and declare a boundary gap covering the longest feature lookback/label-information dependency where windows overlap. Historical context may be read across a boundary only when its actual availability and allowed reuse were specified; no test labels or future normalization statistics may cross it. Walk-forward folds repeat these rules at each fit time.

## 3. Causal features and labels

Every feature needs its formula, source, market/token/interval binding, upstream timestamp, collector observation, first receipt/publication evidence and dependency window. It is eligible only if all required information was available by its prediction cutoff. Distinguish event time from availability time; unknown availability is a limitation, not permission to assume zero latency. Preserve rejected/missing rows and coverage denominators. Never fill missing observations using future values or backdate them.

Check the exact causal reference anchor and all consumed inputs, rather than requiring irrelevant history or overlooking a dependency. Preserve the baseline 3,000 ms reference and 500 ms book policies at their appropriate prediction/execution deadlines; negative source ages are invalid. Broader historical cohorts may support explicitly qualified forecasting research, not silently verified execution claims. Inspect clock accuracy and discontinuities separately from monotonic processing durations.

Outcomes require official settlement provenance: market/condition ID, tokens, final outcome/payout, resolution time, source/version and validation status. Retain raw responses and first retrieval time when available. Missing/conflicting/unresolved labels are excluded or tracked pending, never converted to NO. Local BTC/reference-price proxy outcomes, if separately studied, must be labelled proxies and excluded from official-outcome claims. The current registry's missing raw-response/retrieval evidence remains a documented gap, not a solved requirement.

## 4. Matched forecast evaluation

Compare the candidate and raw normalized market midpoint on the same eligible market/horizon rows and cutoff. A fitted market-only calibration/control uses the same chronological fitting privileges as the candidate. Include constant/class-prior controls, unchanged HGB3 and predeclared combinations where appropriate. The market midpoint is a forecast benchmark, not a fill price.

Primary score: **Brier loss**, `(p-y)^2`; log loss is a mandatory corroborating proper score. Report clipping convention for numerical endpoints. Report accuracy, reliability curves, fixed-bin ECE, probability bands, horizon results and coverage as diagnostics. ECE or accuracy alone cannot select a winner. Weight each market equally overall; share its weight across eligible horizons. Report per-horizon results separately and disclose selective missingness; compare models on their intersection and report lost coverage.

For each market compute a paired mean loss difference, `d = candidate loss - comparator loss`. Negative favors candidate. Confidence intervals must retain all rows/horizons of a market together and account for serial dependence across markets. Predeclare chronological day/block resampling or an appropriate time-series variance estimate using development data; report the block definition, effective units and sensitivity. Do not resample snapshot rows independently. Too few independent days/blocks yields an inconclusive result. Conditional intervals for one fitted model do not include calibration/model-selection uncertainty; quantify that on development folds and require prospective replication.

## 5. Hypotheses and decision rules

Use the following tests before any new final evaluation. `delta_pred > 0` is the minimum practically relevant Brier reduction recorded in the experiment card; it is not an operational entry threshold. Also register the permitted log-loss deterioration (zero unless an alternative is justified in advance) and the practical economic margin with its units/denominator. Log-loss corroboration requires the upper confidence bound of its paired difference to stay within that registered margin. Missing margins or an unspecified uncertainty method block a confirmatory readout; R0 does not choose them by fitting S5 results.

| Claim | Null / comparison | Decision criterion |
|---|---|---|
| H0, no incremental ML value | Mean paired difference versus raw market >=0; also compare fitted market-only control | Evidence against H0 requires upper end of dependence-aware 95% CI <0; advancement requires upper end <`-delta_pred` against the stronger predeclared market control and raw market, with no material log-loss deterioration |
| H1, added feature information | Augmented-minus-market-only loss >=0 within a matched model family | Predeclared feature-group ablation passes the same practical-improvement criterion; coverage must not create a favorable different sample |
| H2, benefit of market-relative formulation | Market-relative-minus-standalone loss >=0 | Pass the same criterion versus standalone **and** retain improvement versus market controls; winning only against standalone is insufficient |
| H3, executable benefit | Mean net economic result <=0 and candidate-minus-matched-market-policy result <=0 | Lower 95% bounds exceed zero (and the preregistered practical economic margin), with costs, causal risk/settlement, declared stress and prospective replication satisfied |

Use two-sided 95% intervals with the stated directional gate; do not switch to a favorable one-sided test after inspection. Where multiple confirmatory candidates, features or horizons are claimed, control the familywise error at 5% (e.g. preregistered Holm-adjusted tests/inverted intervals) or use a prespecified gatekeeping family. Plain nominal intervals are descriptive unless they are the sole registered comparison. Report effect sizes, uncertainty and all tests regardless of direction. An interval crossing zero means inconclusive, not equivalence; equivalence would need its own prior margins and test.

Do not repeatedly peek and stop when significant. Fix the sample/horizon/readout rule or preregister a valid sequential design. Sample targets are market/day counts, not rows. S5's 1,000 calibration / 2,000 evaluation markets over >=14 days are planning floors, subject to power, serial dependence, label quality and per-horizon coverage; they are not guarantees of adequacy.

## 6. Executable economics and risk

Freeze side selection, estimated outcome probability, uncertainty margin and entry policy before testing. Compare current market-based EV, model-based and market/model variants as separately named research specifications; never silently redefine the operational strategy. Use selected-side winning probability (1-p for NO), available ask, tick, spread, depth/minimum size, actual fee descriptor and explicit fee accounting, slippage and measured availability/latency. Keep a no-trade baseline and a matched market-only policy.

Preserve the baseline $0.70 ceiling, five-share sizing, $7 order cap, $25 exposure, $10 daily realized-loss limit and one entry per market. Research sensitivities are labelled alternatives, not operational changes. Report rejected/unavailable attempts, partial/non-fills, maximum loss and costs. Missing final execution timing or applicable fee/settlement evidence prevents a verified executable claim; optimistic latency recovery stays a counterfactual. Retained quote depth is not proof of a future fill.

Use a causal portfolio simulation with actual label-retrieval/settlement availability before releasing capital. If unavailable, report bounded assumptions and do not claim a fully reconstructed risk path. Report labelled hypothetical PnL, return denominator, trade count/frequency, drawdown, exposure, win rate and proper scores on traded forecasts. Do not compare different traded subsets as though matched. Preserve chronological equity paths for drawdown; uncertainty for mean economic performance must use predeclared dependent market/day blocks including abstentions and account for policy selection. A resampled mean interval is not a drawdown guarantee. Few trades or unverified execution yield insufficient economic evidence even if scores improve.

## 7. Reporting and reproducibility

Every report includes denominators/exclusions, membership overlap checks, data/label exposure, time boundaries, model/calibrator hashes, commands/environment, all candidate results, costs/stress, uncertainty limitations and one conclusion: incremental and economic evidence; predictive-only improvement; no demonstrated incremental value; or insufficient valid data. Report negative and null outcomes with the same detail as favorable ones. Failed engineering checks and statistical findings are separate.

Version new artifacts separately and keep raw data/S5 history immutable. Offline analyses must not instantiate writable operational services or write trades to operational databases. Tests validate leakage, calculations, provenance and reproduction, not profitability. Review precedes each roadmap stage; no result grants paper-strategy changes or live authorization.
