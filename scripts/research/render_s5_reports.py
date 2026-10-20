"""Render S5 documentation from frozen research evidence; no operational reads."""
from pathlib import Path
import json
import math
from html import escape

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs'
r=json.loads((DOC/'POLYBTC_S5_EVIDENCE.json').read_text())
raw=json.loads((ROOT/'data/research/s5_v1/inputs.json').read_text())
names={'market':'Market midpoint','raw':'Raw HGB3','platt':'Platt HGB3','isotonic':'Isotonic HGB3','combination':'Market/Platt blend','equal_raw':'Equal market/raw blend','half':'Constant 0.5'}


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n'


def f(x):return 'N/A' if x is None else f'{x:.6f}'
def interval(v):return '['+', '.join(f(x) for x in v)+']'


def save(name,text):
    (DOC/name).write_text(text.strip()+'\n',encoding='utf-8')


commands=r'''
```powershell
Set-Location H:\PolyBTCv2
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_s5.py
.\.venv-execution\Scripts\python.exe -B scripts/research/render_s5_reports.py
.\.venv-execution\Scripts\python.exe -B -m pytest tests/research/test_s5_audit.py -q --basetemp=H:\PolyBTCv2\.pytest_cache\s5_research_tests
```

`audit_s5.py --capture` was used once to read operational data into the separate, versioned `data/research/s5_v1/inputs.json`; it refuses to overwrite that file. Do not delete it to refresh a result. A later study must use a new research version and predeclared cutoff. Reproduction without `--capture` uses frozen observations/labels, the frozen artifact hash and existing historical research files, not a changing operational journal. The pytest base directory is research scratch only. All operational database reads use SQLite `mode=ro` and `query_only`; socket connections are disabled in the audit command. No trading services are instantiated.
'''

inventory_rows=[]
for i in r['inventory']:
    inventory_rows.append([f"`{i['path']}`",i['rows'],i['markets'] or 'N/A',f"{i['first']} to {i['last']}"])

audit='''# S5: Strategy economics audit

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

'''+table(['Dataset','Rows','Markets','Recorded boundary'],inventory_rows)+'''
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

'''+commands+'''
Six focused research tests cover equal-market weighting, finite endpoint log loss, reliability-bin endpoints, paired/block uncertainty identity, SQLite write rejection, and NO-side payoff/fees/one-entry enforcement. Initial pytest temporary-directory access failed; rerunning with a new workspace-local scratch directory passed. Hash checks confirm the main model and training CSV match the manifest; no operational regression suite is claimed because production code was not edited.

Companions: [calibration report](POLYBTC_S5_CALIBRATION_REPORT.md), [strategy comparison](POLYBTC_S5_STRATEGY_COMPARISON.md), [machine evidence](POLYBTC_S5_EVIDENCE.json), [frozen derived inputs](../data/research/s5_v1/inputs.json).
'''
save('POLYBTC_S5_STRATEGY_ECONOMICS_AUDIT.md',audit)

parts=r['partitions']; scores=r['prospective']['overall']; deltas=r['prospective']['paired_deltas']
scoretable=table(['Forecast','Rows / markets','Brier','Log loss','Accuracy','ECE'],[[names[c],f"{m['rows']} / {m['markets']}",f(m['brier']),f(m['log_loss']),f(m['accuracy']),f(m['ece'])] for c,m in scores.items()])
citab=table(['Forecast minus market','Brier delta','95% market-cluster CI','95% six-market block CI','Log-loss delta / cluster CI'],[[names[c],f(v['brier']['delta']),interval(v['brier']['ci95']),interval(v['brier']['six_market_block_ci95']),f(v['log_loss']['delta'])+' / '+interval(v['log_loss']['ci95'])] for c,v in deltas.items() if c not in ('half',)])
horizons=table(['Horizon','Rows / markets','Market Brier','Raw Brier','Platt Brier','Blend Brier'],[[h,f"{v['raw']['rows']} / {v['raw']['markets']}",*[f(v[c]['brier']) for c in ('market','raw','platt','combination')]] for h,v in sorted(r['prospective']['by_horizon'].items(),key=lambda x:-int(x[0]))])
historical=r['historical_predecessor']['results']['overall']
historic_table=table(['Predecessor test forecast','Brier','Log loss','Accuracy','ECE'],[[names[c],*[f(m[k]) for k in ('brier','log_loss','accuracy','ece')]] for c,m in historical.items()])
sd=deltas['raw']['brier']['market_delta_sd']; planned=math.ceil(((1.96+.84)*sd/.01)**2)
calibration=f'''# S5: Probability calibration and incremental forecast value

Date: 2026-10-14. **Outcome C, provisional:** the retained market benchmark is better on point estimates; no credible incremental improvement by frozen HGB3 or its fitted combinations is demonstrated. Brier uncertainty for raw HGB3 includes equality, so this is not a universal inferiority claim. A larger genuinely prospective final test remains necessary.

## Separation and eligibility

The main artifact SHA-256 is `{raw['model_sha256']}`. Its manifest and training CSV hash agree. It was created 2026-10-12 08:45:19 UTC and refitted on **33,366 rows / 5,588 markets**, prediction times 2026-09-17 17:26 through 2026-10-11 15:04:30. No operational candidate market overlaps those training IDs. Current stored probabilities reproduce from the unchanged artifact on **705 selected decisions**; 159 additionally satisfy causal reference/anchor provenance, fresh paired prediction books and official-source registry labels.

{table(['Partition','Rows','Markets','First prediction UTC','Last prediction UTC','YES markets'],[[name,v['rows'],v['markets'],v['first'],v['last'],v['yes_markets']] for name,v in parts.items()])}

Split boundary is **2026-10-13 14:30 UTC**, the session boundary used in the funnel investigation. Market IDs do not cross partitions; all earlier labels' recorded resolution times precede this boundary. Calibration and combination fitting use only the earlier partition. Later prices were already inspected for infrastructure diagnostics, but their labels did not fit these calibrators. This is an exploratory chronological holdout for a frozen model, **not a prospectively preregistered strategy-selection test**. The S5 readout and sensitivities now consume it for research; do not retune and call it untouched again. Full raw resolution/retrieval evidence is absent from the registry, so label-availability/finality claims remain conditional as explained in the economics audit.

Forecast comparisons use market midpoint from the **same selected prediction snapshot**, available by the cutoff, rather than a later execution quote. Both books must have source ages 0–500 ms at cutoff, reference 0–3,000 ms, causal anchor and bound retained evidence. Operational inference can run when books fail this stricter paired-benchmark test; those rows are not pooled here. No outcomes were proxied from spot BTC. Missingness is selective and late horizons are especially underrepresented.

## Methods fixed before calibration fitting

Raw HGB3 is the identity-calibrated artifact. Platt calibration is logistic regression on logit(raw p), C=1, L2 regularization, lbfgs, with one total unit of weight per calibration market. Its fitted slope is **{r['calibration']['platt_coefficient']:.6f}** and intercept **{r['calibration']['platt_intercept']:.6f}**. Isotonic regression is increasing, clips outside its training range and uses the same weights. With only 42 calibration markets, isotonic is exploratory and can create unjustified endpoint certainty.

Strategy C's forecasting probability is `(1-alpha)*market + alpha*Platt(raw)`, with alpha constrained to [0,1] and minimizing weighted Brier **on calibration only**. Fitted alpha is **{r['calibration']['combination_model_weight']:.6f}** (13.61% model, 86.39% market). This two-stage fit is itself in-sample on a small calibration set; its performance must be judged only later. The equal raw/market blend and constant 0.5 are untuned controls. No method was attached to the deployed artifact; parameters are in `data/research/s5_v1/calibration_s5_exploratory_v1.json` and are marked exploratory.

Metrics give **each market equal total weight**; its available horizons share that weight. Accuracy uses p>=0.5 as YES. Natural-log loss clips probabilities to [1e-15,1-1e-15] only for numerical scoring; this does not change forecasts or execution. ECE uses ten fixed equal-width [0,.1), ... bins, last bin includes 1; it is the market-weighted absolute difference between bin mean forecast and outcome rate. Empty bins are omitted. ECE is bin-dependent and is not a proper scoring rule or proof of tradability.

## Later paired forecast metrics

{scoretable}

Lower Brier/log loss is better. Platt's compression toward 0.5 hurts later discrimination/confidence. Isotonic has lower binned ECE than raw but much worse log loss, including incorrect endpoint forecasts; do not select it by ECE alone. The blend closely tracks market but does not improve it. Raw HGB3 beats the uninformed 0.5 control, which shows some outcome information, but **information beyond market is the relevant question**.

## Uncertainty and dependence

Paired differences are computed within each market over its matched horizons. Intervals use 2,000 resamples of whole markets (seed 20261014), preserving all horizon dependence. A circular moving-block sensitivity resamples six successive eligible markets ordered by target time. Those blocks are not necessarily contiguous 30-minute periods because acquisition coverage has gaps. Neither interval captures all longer regime dependence or calibration-fitting uncertainty; these are conditional intervals for the fitted models, not simultaneous multiple-comparison guarantees.

{citab}

Positive deltas favor market. Raw Brier's interval crosses zero; its log-loss cluster interval favors market, but 55 markets over part of one day cannot establish broad superiority. No choice of method/horizon is promoted from a favorable slice. For planning only, observed paired-market Brier SD {sd:.4f} implies roughly **{planned} independent evaluation markets** to detect a 0.01 Brier difference at nominal 5% two-sided significance/80% power using a normal approximation. Serial dependence, calibration estimation and selection require inflation; the audit's 2,000-evaluation-market floor must be revised if the resulting confidence interval remains too wide.

## Horizon and probability-band diagnostics

{horizons}

Raw HGB3 is better on the 240-second point estimate (19 observations), but worse on the other observed horizons. Two 30-second observations cannot support a policy conclusion. Full per-horizon accuracy/log loss/ECE for every forecast and every nonempty probability bin are in the JSON. These are diagnostic slices, not additional threshold-selection datasets.

![Later reliability curves](POLYBTC_S5_RELIABILITY.svg)

The plot uses bin mean predicted probability versus weighted observed YES frequency; diagonal means calibrated. Line segments merely connect occupied bins, not fitted probability functions. Small and empty bins make visual ranking unreliable.

'''
for c in ('market','raw','platt','isotonic','combination'):
    calibration+='\n### '+names[c]+' probability bands\n\n'+table(['Band','Rows / markets','Mean forecast','YES frequency','Within-bin Brier','Within-bin log loss'],[[f"{b['lower']:.1f}–{b['upper']:.1f}",f"{b['rows']} / {b['markets']}",f(b['predicted']),f(b['observed']),f(b['brier']),f(b['log_loss'])] for b in scores[c]['reliability']])
calibration+='\n### ECE bin sensitivity\n\n'+table(['Bins',*[names[c] for c in ('market','raw','platt','isotonic','combination')]],[[n,*[f(v[c]) for c in ('market','raw','platt','isotonic','combination')]] for n,v in r['ece_bin_sensitivity'].items()])
calibration+='''
### Distribution drift and return regimes

Earlier-versus-later scores are retained in JSON. Earlier calibration has 23 YES markets out of 42, later evaluation 25 out of 55; horizon availability also differs. These small samples cannot establish a stable recalibration function. The regime diagnostic uses the earlier median absolute 30-second TWAP return, not an outcome-selected threshold or realized spot volatility.

'''+table(['TWAP-return regime','Rows','Market Brier','Raw Brier'],[[name,v['market']['rows'],f(v['market']['brier']),f(v['raw']['brier'])] for name,v in r['return_regimes'].items() if isinstance(v,dict)])+'''
Both return-regime point estimates favor market. Absolute smoothed TWAP return is only a volatility proxy; no reliable independent high/low realized-volatility execution study is available in this prospective cohort. It must not be presented as one.

## Historical predecessor calibration: context only

Chronological market-grouped training/calibration/evaluation counts were 3,352/1,118/1,118 markets. Their periods were September 17–October 3, October 3–7, October 7–11 respectively. Only 5,054 of 6,662 test rows (1,117 of 1,118 markets) have a paired market forecast. The following recomputation gives each market equal weight, so it differs from older row-weighted report totals.

'''+historic_table+'''
Market is better on this paired predecessor cohort too. Calibration moves scores slightly without closing the gap. These saved predictions came from a different, earlier-partition fitted model; all evaluation markets then entered the final artifact's training. They are **not** independent performance of the frozen artifact, and repeated historical model-selection work further limits inference. Do not deploy its stored calibrators onto the full refit.

## Conclusion

No calibration or combination is justified for operational promotion. Preserve raw HGB3 and current operation pending review; research model/feature additions against the strong market benchmark rather than fitting trading thresholds to these outcomes. The economics audit specifies the next genuinely prospective dataset and acceptance gates. No forecast probability is asserted to be objective truth.

Reproduce with the commands in [the audit](POLYBTC_S5_STRATEGY_ECONOMICS_AUDIT.md). [Machine evidence](POLYBTC_S5_EVIDENCE.json) contains complete metrics, conditional intervals, bin points, parameters, hashes, exclusions and row membership.
'''
save('POLYBTC_S5_CALIBRATION_REPORT.md',calibration)
with (DOC/'POLYBTC_S5_CALIBRATION_REPORT.md').open('a',encoding='utf-8') as out:
    out.write('\n## Other existing benchmarks (archival context)\n\nThese are existing saved research predictions, not newly trained or independently evaluated candidates. They overlap historical development periods; comparisons across panels or against the prospective 55-market sample are invalid. No current-v2 deployment decision is based on them.\n\n')
    for path,panel in r['archived_benchmarks'].items():
        out.write('`'+path+'` — '+panel['first']+' to '+panel['last']+'\n\n')
        out.write(table(['Forecast','Rows / markets','Brier','Log loss'],[[c,f"{m['rows']} / {m['markets']}",f(m['brier']),f(m['log_loss'])] for c,m in panel['metrics'].items()])+'\n')

# Dependency-free SVG of the recorded reliability points (no remote resources).
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="850" height="570" viewBox="0 0 850 570">','<rect width="850" height="570" fill="white"/>','<g font-family="Arial,sans-serif" font-size="13" fill="#263238">','<text x="60" y="28" font-size="19">S5 later reliability: 93 observations / 55 markets</text>']
for i in range(6):
    a=i/5;x=70+440*a;y=490-440*a
    svg.extend([f'<path d="M {x} 50 V 490 M 70 {y} H 510" stroke="#e4e7eb"/>',f'<text x="{x-8}" y="510">{a:.1f}</text>',f'<text x="35" y="{y+5}">{a:.1f}</text>'])
svg.append('<path d="M 70 490 L 510 50" stroke="#666" stroke-dasharray="5 5"/>')
for j,(c,color) in enumerate(zip(('market','raw','platt','isotonic','combination'),('#111111','#1769aa','#cf4b00','#8856a7','#00856a'))):
    curve=scores[c]['reliability'];points=' '.join(f"{70+440*b['predicted']},{490-440*b['observed']}" for b in curve)
    svg.append(f'<polyline points="{points}" stroke="{color}" fill="none" stroke-width="2"/>')
    for b in curve:svg.append(f'<circle cx="{70+440*b["predicted"]}" cy="{490-440*b["observed"]}" r="4" fill="{color}"><title>{escape(names[c])}: n={b["rows"]}, markets={b["markets"]}</title></circle>')
    svg.append(f'<text x="555" y="{90+32*j}" fill="{color}">{escape(names[c])}</text>')
svg.extend(['<text x="145" y="540">Mean predicted YES probability within fixed bins</text>','<text transform="translate(17 380) rotate(-90)">Weighted observed YES frequency</text>','<text x="555" y="285">Small bins; no per-bin</text>','<text x="555" y="305">confidence claim.</text>','<text x="555" y="345">Each market has equal</text>','<text x="555" y="365">total weight.</text>','</g></svg>'])
save('POLYBTC_S5_RELIABILITY.svg','\n'.join(svg))

econ=r['economic_comparison']
def economic_table(items):
    return table(['Policy','Positive-EV rows','Price/depth/direction/gap pass','Hypothetical entries','Labelled net PnL','Entry-order drawdown','Win rate'],[[n,v['counts'].get('positive_ev',0),v['counts'].get('entry_constraints_pass',0),v['hypothetical_trades'],f(v['net_hypothetical_pnl']),f(v['ex_post_entry_order_drawdown']),f(v['win_rate'])] for n,v in items.items()])

comparison=f'''# S5: Executable strategy comparison

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

{economic_table(econ['baseline'])}

No-trade baseline: zero entries, zero PnL, zero drawdown; win rate and trade forecast scores undefined. For the controlled policies, all trade-level forecast scores are likewise undefined because there are no trades. A, calibrated B and C have nonpositive EV for all 43 selected-side inputs. Raw HGB3 produces 13 positive estimates, but seven fail the legacy gap and six fail the ceiling. A positive uncalibrated estimate is not proof of a true edge.

## Explicit alternative: let calibrated estimates choose either side

The following **post-hoc research hypotheses** choose the side with larger `q_side-ask-tick-fee`, require that edge to be positive, and remove the old direction/gap filters. Both sides retain the same freshness, prices, depth, minimum-size, size, fee and capital assumptions. This is a different strategy specification, not a recommended operational relaxation. It often buys the market underdog because the small-sample Platt fit pulls forecasts toward 0.5.

{economic_table(econ['alternative_best_side_without_agreement_gap'])}

The column labelled entry constraints omits agreement/gap for these explicit alternatives. B has 40 positive-edge observations, 39 size/price passes; three later same-market entries and 13 capital-limit attempts are rejected, leaving 23 distinct markets. C has 14 positive observations and one repeated-market rejection, leaving 13. The B basket's **+$0.03634 total** is effectively flat at this sample size; C loses **$6.38145**. This is conditional paper accounting on labelled contracts, not cash earned. Neither identifies a credible positive-expectation policy.

'''
comparison+='\n'+table(['Alternative','Trade forecast Brier','Trade forecast log loss','Entries by horizon'],[[n,f(v['trade_forecast_brier']),f(v['trade_forecast_log_loss']),str(v['by_horizon'])] for n,v in econ['alternative_best_side_without_agreement_gap'].items()])+'''
These trade-score cohorts differ, so the lower C Brier cannot establish C's superiority; it buys mostly low-probability outcomes. Forecast quality must be judged on the common 93-row cohort, where neither model variant beats market. Only 23 and 13 trades are available, with correlated market regimes and a fitted calibration based on 42 markets. No statistically credible economic-confidence claim can be made from this basket. Full-session risk-dependent trade selection would also change under different settlement timing.

### Representative trade arithmetic

'''
for n in ('B_platt','C'):
    if econ['alternative_best_side_without_agreement_gap'][n]['trades']:
        t=econ['alternative_best_side_without_agreement_gap'][n]['trades'][0]
        comparison+=f"- {n}, decision **{t['id']}**, {t['side'].upper()}: calibrated selected probability {t['estimated_probability']:.6f}, execution price ${t['execution_price']:.2f}, estimated edge ${t['estimated_ev']:.6f}/share. Five-share fee ${t['fee']:.5f}, maximum loss ${t['maximum_loss']:.5f}; registered outcome {'wins' if t['won'] else 'loses'}, labelled scenario PnL ${t['hypothetical_pnl']:.5f}. This was not an operational entry.\n"
comparison+='''
## Robustness: diagnostics, never threshold selection

The controlled A/B_platt/C policies remain at zero entries with zero or two slippage ticks, doubled fee rate, two/five-point probability haircuts, widened gap or an 80-cent price ceiling. Those sensitivities do not authorize any operational change. Haircuts are stress assumptions, **not statistically fitted confidence bounds**.

Raw-HGB3 sensitivity shows how easy it is to manufacture apparent opportunities from a small sample:

'''+table(['Raw diagnostic variation','Entries','Labelled net PnL'],[[k,v['hypothetical_trades'],f(v['net_hypothetical_pnl'])] for k,v in econ['sensitivity']['B_raw_diagnostic'].items()])+'''
Do not choose the favorable zero-tick or 80-cent result. They change protected execution assumptions, rely on one or three selected markets and were inspected on the same outcomes. There is no out-of-sample profitability conclusion or threshold recommendation.

For the explicit best-side alternatives:

'''+table(['Alternative','Stress','Entries','Labelled net PnL'],[[n,k,v['hypothetical_trades'],f(v['net_hypothetical_pnl'])] for n,ss in econ['alternative_stress'].items() for k,v in ss.items()])+'''
Changing costs or a probability haircut also changes which entries are selected and when the capital cap binds; total PnL need not move monotonically. B's few cents at baseline, two ticks or doubled fees are not a stable economic edge; a five-point haircut produces a loss. C remains negative in the tested stresses. Spread is paid through actual asks, and one/two additional ticks represent adverse executable-price stress. No artificial tightening of recorded spreads or subsidized fees is used in the baseline.

### Latency stress

At persisted source-verification time plus the following hypothetical additional delays, this many of the 43 inputs still satisfy all source-age limits:

'''+table(['Additional ms after recorded verification','Passing source ages'],list(econ['verification_deadline_plus_ms_pass_counts'].items()))+'''
These are source-age arithmetic bounds, not measured added latency after the final runner check. That check's exact timestamp and calibration/executor duration were not persisted. The original 43 reached strategy, but no newly fitted policy has demonstrated an actual timely fill. Causal cutoff and timestamp values never change in this sensitivity.

### Uncertainty, drift, horizon and volatility

The forecast report shows raw model-versus-market Brier uncertainty crossing zero, poorer calibrated scores, small tail bins and a severely undercovered 30-second horizon. Fixed 30-second TWAP-return regimes both favor market; genuine spot-volatility conditioning is not available here. Neither a per-horizon calibration nor per-regime entry threshold is justified by these samples. The 42-market calibration can drift or overfit; uncertainty in it is not captured by merely applying the fitted number to an ask.

## Decision and next step

**Select Outcome C.** Raw HGB3 has some predictive information relative to a constant forecast, but the available paired evidence does not establish incremental value over market. No calibrated alternative demonstrates credible executable economic benefit. Small sample size, raw-resolution retention gaps, execution timing and capital-release uncertainty remain research limitations; they do not justify selecting the most favorable sensitivity.

The smallest useful next stage is a preregistered, read-only prospective forecast study with retained raw settlement evidence and actual execution timing. Investigate market-relative features/residual prediction only on training/selection periods, then freeze one candidate. Keep current paper operation unchanged for review. Promote no candidate unless it passes the data, paired-score uncertainty, calibration and after-cost acceptance criteria in the economics audit. Paper-only prospective testing would require a separate authorization after that evidence exists.

Reproduction: [audit commands](POLYBTC_S5_STRATEGY_ECONOMICS_AUDIT.md). Supporting [forecast report](POLYBTC_S5_CALIBRATION_REPORT.md) and [evidence](POLYBTC_S5_EVIDENCE.json). Operational PnL, risk reservations and positions were not modified.
'''
save('POLYBTC_S5_STRATEGY_COMPARISON.md',comparison)
print('Rendered three S5 reports and reliability SVG.')
