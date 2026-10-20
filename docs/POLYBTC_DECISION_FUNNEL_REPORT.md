# PolyBTC v2 — Decision funnel and execution latency

Forensic report: 2026-10-13. Times are UTC unless specified. **No operational code, model, strategy, limits, checkpoints, receipts, decisions or positions were changed. No network requests or operational decision replay were performed.** Existing SQLite files were opened with `mode=ro` and `query_only`; only documentation and analysis scratch files were written.

## Conclusion

**D — a measurable combination explains the terminal rejection distribution. However, this cohort does not demonstrate economically qualifying trades lost to latency under the current strategy.**

Across 300 decisions, 143 (47.7%) stopped at horizon/data/provenance gates; 60 (20.0%) passed provenance but expired at the later runner freshness check; 97 (32.3%) reached strategy and all abstained economically. Zero qualified for risk reservation or simulation.

Latency is real: 55 verified book observations subsequently crossed 500 ms, and five references crossed 3,000 ms. At their earliest supported causal handoff, 68 additional selected observations could pass input gates. **The unchanged strategy rejects all 68**, producing zero counterfactual qualifying trades, not 68 missed fills.

The key economic finding is that **implemented EV uses market-implied probability, not HGB3 probability**. HGB3 controls agreement/gap checks. All 97 actual strategy observations, and all 165 earliest-source-verified selected observations, have nonpositive EV under that formula. This is a cohort finding, not proof that HGB3 lacks predictive skill or that future opportunities are impossible.

[Machine-readable evidence](POLYBTC_DECISION_FUNNEL_EVIDENCE.json) includes all 300 decisions, reconstructed prices/timestamps, verification diagnostics, counterfactual outcomes and reproduction checks.

## 1. Active configuration and investigation window

The active heartbeat identifies PID **22196**, clock session `cc8651aa-930c-453f-96cc-775e1cc56202`, CSV transport, `paper_execution`, paper fills enabled, kill switch false, live disabled and state running. Windows process inspection gives start **14:30:11.035867 UTC** (17:30:11 local UTC+3). The captured heartbeat is retained in JSON; it continued advancing during inspection. There are no retained `clock_events`.

| Setting | Observed value |
|---|---|
| CSV | `H:\PolyBTCv2\data\live\vnext_market_snapshots.csv` |
| Acquisition evidence | `H:\PolyBTCv2\data\live\paper_acquisition.sqlite3` |
| Fee cache | `H:\PolyBTCv2\data\live\paper_fees.sqlite3` |
| Paper state | `H:\PolyBTCv2\data\paper\vnext_verified` |
| Journal / positions | `decisions.sqlite3` / `trades.sqlite3` within that state directory |
| Model | `data/models/main/hgb3_expanded_v2.joblib` |
| Model SHA-256 | `42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4` |
| Runtime pause | 0.05 s after cycle work |
| Reference / books | 3,000 ms / 500 ms |
| Finalization grace / further execution wait | 2 s / up to 1 s |
| Collector pause | Documented 0.1 s; actual command-line arguments unavailable |

The documented collector command is consistent with observed subsecond cadence. Its default remains 1 second, but default is not evidence of the active argument. CIM command-line inspection was denied; no escalation or setting change was attempted.

**Frozen window:** targets after process start and before **18:40:00**, covering 50 complete five-minute markets. IDs **338028–338327**, targets **14:31:00–18:39:30**, exactly **50 decisions per horizon**. The partial market beginning 18:40 and subsequent updates are excluded. The captured byte checkpoint in JSON is a reconstruction boundary, not an assertion of the end-of-window offset.

There are **28,995 receipted observations** across those 50 markets, no duplicated `(market, observed_at)` and no out-of-order observations in the inspected CSV sequence. All current `entries`, `entry_events` and `entry_decision_context` tables contain zero rows. Older regression/simplification results are historical context, not pooled observations.

## 2. Decision funnel

The code is not a strictly sequential funnel: the driver computes verification first, but the runner computes features and HGB3 **before rejecting false source flags**. Therefore 65 provenance failures still have model probabilities. A populated probability does not establish strategy evaluation.

| Stage | Count / 300 | Conditional result |
|---|---|---|
| Acquired market represented by decision | 300 (100%) | 50 acquired markets; excludes never-discovered markets |
| Causal horizon selected | 222 (74.0%) | 78 stale-horizon rejections |
| Prediction features available | 222 (74.0%) | 222/222 selected; exact causal anchors reconstructed |
| Source and applicable paper-fee verification passed | 157 (52.3%) | 157/222 attempts (70.7%); fees individually pass 222/222 |
| HGB3 inference actually completed | 222 (74.0%) | Includes 65 unverified; 157 on verified inputs |
| Later runner execution-source freshness passed | 97 (32.3%) | 97/157 verified (61.8%) |
| Strategy evaluated | 97 (32.3%) | 97/97 later-fresh |
| Economic qualification | 0 | 0/97 strategy evaluations |
| Risk reservation | 0 | Not reached; conditional approval rate undefined |
| Paper execution / fill | 0 | Not reached; conditional simulator success rate undefined |

Each decision's furthest executed and safety-cleared stages are recorded in JSON. Read-only reproduction matched **222/222 source-flag records**, **222/222 HGB3 probabilities within 1e-12**, and **97/97 economic terminal reasons**. These used the evidence verifier and pure feature/model/strategy functions, never operational journal/ledger replay.

### Common-denominator attribution

| Terminal category | Count | % of all 300 |
|---|---:|---:|
| Horizon data unavailable | 78 | 26.0% |
| Provenance/source freshness or missing execution | 65 | 21.7% |
| Post-verification book expiry | 55 | 18.3% |
| Post-verification reference expiry | 5 | 1.7% |
| Strategy economic abstention | 97 | 32.3% |
| Risk rejection / simulator rejection / fill | 0 / 0 / 0 | 0% |

### Rejections by horizon

Each horizon denominator is 50; a count of one equals 2% of that horizon. Reasons are mutually exclusive.

| Terminal reason | 240 s | 180 s | 120 s | 90 s | 60 s | 30 s | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| stale_horizon | 0 | 0 | 5 | 11 | 18 | 44 | 78 |
| unverified_input_provenance | 12 | 10 | 13 | 10 | 17 | 3 | 65 |
| stale_market_books | 14 | 10 | 8 | 13 | 9 | 1 | 55 |
| stale_reference | 1 | 2 | 2 | 0 | 0 | 0 | 5 |
| probability_gap_too_large | 12 | 14 | 14 | 10 | 1 | 1 | 52 |
| model_market_disagreement | 3 | 6 | 4 | 0 | 2 | 1 | 16 |
| price_ceiling_exceeded | 7 | 8 | 3 | 6 | 3 | 0 | 27 |
| market_direction_neutral | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| insufficient_net_ev | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

Source-verification passes by horizon: **38, 40, 32, 29, 15, 3**. Strategy reached: **23, 28, 22, 16, 6, 2**. The 30-second horizon is primarily a data-coverage problem.

## 3. Acquisition and provenance

For **all 78 stale horizons**, retained acquisition and received history contain **zero observations in target−10 seconds through target** for that market. No eligible earlier snapshot was overlooked among the 222 selected predictions: reconstructed latest causal selection matches the journal. The 2-second finalization grace is distinct from the 10-second maximum horizon observation lag.

Of 28 missing-execution cases, 24 have no acquired or receipted post-target observation before verification. Four have quotes already beyond the driver's 2-second observation-delay limit. Even at earliest target+2-second finalization, the latest available YES book was **1,687, 1,749, 661 and 1,910 ms** old respectively (338194, 338230, 338259, 338308). Faster processing with unchanged grace cannot make these meet 500 ms. Collector skip reasons were not retained; missing bids/asks, reference availability and network failures cannot be distinguished from gaps alone.

Verification diagnostics overlap; denominator **222 attempts**, including 28 without execution snapshots:

| Constraint | Failed decisions | % of 222 |
|---|---:|---:|
| Prediction reference stale at target | 30 | 13.5% |
| Consumed historical anchor stale | 5 | 2.3% |
| Execution reference stale | 16 | 7.2% |
| Execution YES book stale | 15 | 6.8% |
| Execution NO book stale | 8 | 3.6% |
| Missing eligible execution evidence | 28 | 12.6% |
| Fee descriptor/applicability failure | 0 | 0% |
| Retained identity/canonical binding failure | 0 | 0% |

The historical check applies to the exact consumed anchor, not every history row. No relaxation is justified.

Distinct retained reference timestamps advance at median/p90 **1,000/1,000 ms**, p99 **3,000 ms**, maximum gap **195 seconds**. This is retained data, not a complete websocket log; collector outages can hide feed messages. Cadence can meet 3,000 ms but does not guarantee availability.

Across all **28,995 rows**, reference staleness increases from **587 (2.0%) at observation** to **3,433 (11.8%) at receipt**. YES books exceed 500 ms in **445 (1.5%) at observation** and **7,984 (27.5%) at receipt**; NO in **357 (1.2%)** and **4,366 (15.1%)**. These are row rates, not decision rates.


## 4. Timing evidence and limitations

Source timestamps, observation, acquisition `captured`, first receipt and verification's supplied UTC deadline are retained. Request durations use `perf_counter`: complete request times, not one-way network latency. Reported reference latency measures a local cached-feed read, **not upstream websocket delivery**.

`claimed_at_utc` and `completed_at_utc` equal `checked_at_utc` for **all 222 attempts**. The adapter passes the same `now` into claim and completion. These are not times sampled after commit; subtraction would falsely report zero duration. `processed_at_utc` is the service sample passed into initial horizon processing, not commit completion. Across bounded-wait cycles, its difference from verification includes waiting and work.

| Measurement | Availability |
|---|---|
| Expiry / target | Snapshot expiry retained; target persisted |
| Source timestamps / observation / evidence capture | Retained and raw-bound; capture precedes evidence commit |
| CSV publication | Code emits `publication ... published_at=...`; no retained operational log found |
| First receipt | Retained, sampled before receipt transaction completes |
| Verification deadline | Retained, sampled before verifier work, not its return |
| Durable claim completion | Not separately sampled/persisted |
| Model start/end | Not separately sampled/persisted |
| Final runner freshness | Code emits `execution_freshness ... evaluated_at=...`; no retained file found |
| Executor time | Not reached |
| SQLite busy/lock/fsync durations | Not separately measured |

No collector/runner log files were found under operational live/paper state or among repository logs. Available dashboard files are HTTP/server logs. Terminal scrollback elsewhere may still exist. Captured console output could recover publication and final freshness times; it cannot retrospectively supply unlogged commit/inference durations.

### Measured distributions (milliseconds)

Selected execution evidence exists for **194 decisions**. Quantiles use linear interpolation. p99 with fewer than 200 samples is descriptive, not a stable tail-latency SLA.

| Measurement | n | Median | p90 | p99 | Max |
| --- | --- | --- | --- | --- | --- |
| YES request duration | 194 | 75.96 | 87.71 | 137.72 | 186.51 |
| NO request duration | 194 | 75.00 | 87.82 | 108.70 | 152.57 |
| Collector build | 194 | 154.43 | 173.68 | 240.29 | 262.53 |
| Observation → evidence capture | 194 | 0.43 | 0.65 | 3.35 | 3.86 |
| Observation → first receipt | 194 | 250.64 | 373.80 | 481.42 | 1871.94 |
| Capture → first receipt | 194 | 250.24 | 373.29 | 481.00 | 1871.55 |
| Receipt → verification deadline | 194 | 105.96 | 160.81 | 1229.43 | 1704.68 |
| Target → verification deadline | 222 | 2471.00 | 3130.21 | 3535.39 | 3794.72 |
| Initial processing → verification deadline | 222 | 88.39 | 804.78 | 1240.23 | 1650.14 |

The **250.64 ms** median observation-to-receipt segment combines evidence persistence, CSV publication, polling, parsing and other acquisition/runner work. **It cannot be assigned entirely to external latency or SQLite.** The **105.96 ms** median receipt-to-verification segment is internal delay before the supplied verification deadline. Actual verification work, adapter reads, claim durability, inference and the later clock sample follow that deadline and lack separate retained measurements.

Across all 28,995 rows, receipt delay is median **366.49 ms**, p90 **598.90**, p99 **1,637.36**, max **4,890.32**. Selected execution quotes are a fresher subset. Observation spacing is median **354.21 ms**, p90 **411.34**, p99 **941.08**, max **194,990.27**. A 50 ms polling pause does not mean a 50 ms complete runtime cycle.

### Source age by available boundary (milliseconds; n=194)

| Source / boundary | Median | p90 | p99 | Max |
| --- | --- | --- | --- | --- |
| YES / observation | 1.09 | 29.54 | 72.58 | 449.85 |
| NO / observation | -76.99 | -52.69 | 22.38 | 449.85 |
| Reference / observation | 2008.03 | 2504.83 | 2796.38 | 3072.22 |
| YES / receipt | 251.47 | 377.84 | 515.85 | 1882.27 |
| NO / receipt | 176.69 | 305.53 | 445.17 | 1809.27 |
| Reference / receipt | 2263.08 | 2806.26 | 3117.93 | 4191.27 |
| YES / verification | 362.82 | 493.37 | 1818.78 | 1954.06 |
| NO / verification | 286.82 | 421.13 | 1743.13 | 1881.06 |
| Reference / verification | 2397.71 | 2960.75 | 4074.83 | 4263.06 |

**Clock/source alignment remains uncertain:** 94/194 selected YES and 189/194 selected NO timestamps are ahead of collector observation; median NO age there is **−76.99 ms**. Across all rows those counts are 13,586 and 27,646. One selected NO quote and 167/28,995 NO rows are ahead at first receipt. No terminal verification diagnostic reports a future timestamp at its actual verification deadline. The collector records modest future-relative timestamps; verifier/runner still enforce nonnegative age at their deadlines.

Do not clamp negative ages or interpret them as negative network latency. `MarketCollector.collect` samples observation after both requests. The discrepancy is real in retained timestamps, but local clock error versus upstream timestamp semantics cannot be resolved here. Read-only `w32tm /query /status /verbose` was denied; no NTP request or time correction was made. No detected discontinuity does not prove absolute UTC accuracy. Counterfactual budgets are conditional on these recorded clocks, not independent NTP attestations.

### Proven post-verification expiry

All 55 `stale_market_books` decisions have successful verification and HGB3 probability but no execution-market probability. Their code path rejects after inference and a new clock sample, before strategy. The five `stale_reference` decisions also lack execution-market probability: these are **runner expiry**, not recurrence of the old strategy configuration mismatch.

For 157 verified decisions, remaining minimum YES/NO book budget at verification is median **148.50 ms**, p90 **282.77**, p99 **353.82**, max **362.65**, minimum **2.202 ms**. The 55 subsequently expired books had median **54.46 ms** remaining, range **2.202–170.622 ms**. Their verification-to-final-sample delay was strictly greater than each individual remaining budget. These are **lower bounds**, not measured model/claim durations. Exact final-check latency distributions are unavailable.

Example **338320**, target 18:34:00, expiry 18:35:00:

| Event | UTC |
|---|---|
| Reference source | 18:34:00.000000 |
| YES / NO sources | 18:34:02.023000 / 02.094000 |
| Observation / evidence capture | 18:34:02.041376 / 02.042101 |
| First receipt | 18:34:02.382967 |
| Verification / recorded claim-dispatch field | 18:34:02.501913 |
| Final runner freshness | Not retained; necessarily later than 18:34:02.523000 |

YES age at verification was **478.913 ms**, leaving **21.087 ms**. The exact later check, claim completion, publication and inference timing cannot be fabricated from these records.


## 5. Strategy economics

The runner explicitly supplies 3,000 ms reference and 500 ms books. Its strategy requires maximum execution price $0.70, absolute probability gap ≤0.05, positive net EV, at least five displayed shares and one tick of slippage. The standalone research strategy's 2,000 ms default is overridden; the previous mismatch is not present in this session.

| First economic rejection | Count | % of 97 strategy calls | % of all 300 |
|---|---:|---:|---:|
| Probability gap too large | 52 | 53.6% | 17.3% |
| Price ceiling exceeded | 27 | 27.8% | 9.0% |
| Model/market direction disagreement | 16 | 16.5% | 5.3% |
| Market direction neutral | 1 | 1.0% | 0.3% |
| Insufficient net EV | 1 | 1.0% | 0.3% |

These are **first-failure counts**. Recomputing independent constraints on the same 97 observations gives overlapping failures: direction disagreement **16**, gap >5 percentage points **69**, price above $0.70 **68**, insufficient displayed depth **0**, nonpositive implemented EV **97**. Only one original terminal reason mentions EV because earlier gates stop the other 96 first.

The exact implemented calculation is:

```text
m = YES_mid / (YES_mid + NO_mid)
selected side = YES if m > 0.5, otherwise NO (m == 0.5 abstains)
payout probability = m for YES, 1-m for NO
execution price = selected ask + one conservative tick
fee allowance = fee_rate / 4 + 0.00001
net EV/share = payout probability - execution price - fee allowance
```

HGB3 probability must agree in direction and stay within 0.05 of `m`, but is **not** the payout probability in EV. With approximately complementary books, normalized midpoint is near/below executable ask. Spread crossing, one tick and fees then make EV negative. This is not an impossibility theorem for all books: normalization across inconsistent/asynchronous books can differ from the raw midpoint. It is negative for **all 194 selected execution observations here**, including all 165 earliest-verifiable ones.

For actual strategy calls, implemented EV/share ranges **−$0.093120 to −$0.005635**, median **−$0.032510**. YES+NO mids range 0.96–1.04. Every retained policy has rate 0.07, giving allowance **$0.01751/share**. This is a conservative bound plus margin for the existing paper `rate × price × (1-price)` cash-fee model, not an authenticated live charged fee.

Agreement/gap rules constrain model disagreement and therefore forecast risk, but do not establish calibration. The ceiling limits paid price and the slippage tick budgets adverse movement. Depth and minimum order size remain execution constraints. Risk limits remain five shares, $7 maximum order value, $25 open exposure, $10 daily loss and one entry per market. Risk reservations and simulator calls were never reached: zero risk/minimum-size/simulator rejection counts do not prove hypothetical orders would pass them.

### Supplied examples matched to retained decisions

| Example | Decision / target | Reconstruction |
|---|---|---|
| A | 338316 / 18:31:00, 240 s | HGB3 YES 0.377555; market YES 0.355 at both snapshots. NO market probability 0.645, ask 0.65, tick 0.01: EV = 0.645−0.66−0.01751 = **−0.03251**. HGB3-based diagnostic NO EV would be lower, −0.055065. |
| B | 338313 / 18:28:30, 90 s | HGB3 0.814225; prediction market 0.757426; execution market 0.705. Gap **0.109225** fails. Ask 0.71 + tick = **0.72** also exceeds ceiling. Implemented EV **−0.03251**. |
| C | 338320 / 18:34:00, 60 s | HGB3 YES 0.048179, market YES 0.015. Faster processing selects NO at ask 0.99 + tick = **1.00**, failing the $0.70 ceiling. It is not a missed qualifying trade. |

This does not automatically justify a strategy change. Market probability in EV is demonstrably what current code and tests implement. Whether this matches intended economic specification is a separate design decision, not an authorized silent bug fix. The evidence is negative executable EV across observed candidates, not merely infrequent trading.

## 6. Infrastructure-only counterfactual

For each of 194 selected executions, earliest supported handoff is the maximum of **actual first receipt**, prediction/anchor receipts, retained execution capture, applicable fee retrieval and **target+2 seconds**. Evidence commits before CSV publication. No source/receipt timestamp is altered. Prediction, causal anchor, model, prices, source/fee/economic limits and finalization grace remain fixed. No finalized decision is replayed in operational state.

At this bound the real verifier passes **165/194** selected observations: original 157 plus eight formerly unverified (**338029, 338124, 338131, 338172, 338192, 338256, 338258, 338275**). Among the 157, 60 expired later. Thus **68 additional strategy evaluations** are gate-recoverable with zero additional processing delay.

| Evidence class | Finding |
|---|---|
| Demonstrated source-gate recovery | Eight failed verifications pass at recorded causal handoff. Example 338029: YES age 421.007 ms at receipt versus 526.628 ms at verification. |
| Potential full-processing recovery | These eight plus 60 later-expired observations have positive earlier budgets; actual verifier/commit/inference feasibility is unmeasured. |
| Additional strategy outcomes | 28 gap, 24 ceiling, 12 disagreement, four insufficient EV: **zero qualify**. |
| Remaining 29 selected executions | Fixed prediction/anchor or execution source constraints still fail at earliest handoff. One also has a future NO time there and an independently stale fixed anchor. |
| 28 missing executions | 24 no post-target acquisition; four already too old at permitted finalization. |
| 78 stale horizons | Absent observations before causal cutoff; faster downstream work cannot create them. |

The 68 candidates' tightest earlier book/reference budget has median **159.97 ms**, p90 **242.36**, p99 **305.12**, range **41.69–321.65 ms**. These are available budgets, not achieved processing times. A benchmark under actual I/O contention is required before declaring complete timing recovery.

**68 source-gate recoveries are demonstrated analytically; complete processing recovery remains potential, and zero qualifying trades or fills are demonstrated.** The scope is the recorded selections and actual receipts, not every hypothetical alternative quote or undiscovered market.

## 7. Economic sensitivity — offline only

Changing only the gap allowance on **97 already-verified, later-fresh actual strategy observations** produces:

| Gap allowance | Gap rejects | Ceiling rejects | EV rejects | Disagreement | Neutral | Qualifying trades |
| --- | --- | --- | --- | --- | --- | --- |
| 0.05 | 52 | 27 | 1 | 16 | 1 | 0 |
| 0.1 | 23 | 48 | 9 | 16 | 1 | 0 |
| 0.2 | 2 | 62 | 16 | 16 | 1 | 0 |
| 1.0 | 0 | 62 | 18 | 16 | 1 | 0 |

A looser gap changes visible rejection reasons, not the qualifying count. Minimum EV is already zero; reducing it below zero accepts negative EV under the current formula. Looser agreement also admits more unvalidated forecast/market divergence. This sample does not quantify resulting calibration risk or justify tuning.

As **diagnostic arithmetic only**, substituting HGB3's selected-side probability yields positive cost-adjusted estimates in 33/97 actual strategy observations, but **zero** satisfy the other unchanged direction/gap/price/depth gates. Among 165 earliest-source-verified observations, only **338178** has both positive HGB3-based diagnostic EV and those gates: **+$0.000801/share**, versus implemented **−$0.03251/share**. It actually failed post-verification book freshness. Calling it a missed trade would require *both* changing EV semantics and fixing timing. This tiny estimate is not a current-strategy opportunity, calibrated edge, risk approval, fill or out-of-sample profit. No outcome/calibration study or threshold optimization was performed.

## 8. Root-cause ranking and smallest next step

1. **Economic qualification is absent for inspected selected inputs.** Eliminating demonstrated timing losses alone would not create fills. Clarify the intentional use of market probability in EV before attributing the result to HGB3 forecast failure. Do not substitute model probability automatically.
2. **Acquisition/causal coverage is the largest first-terminal category:** 143/300 horizon/provenance failures, particularly late horizons. Capture collector skip reasons to distinguish unavailable upstream books/reference from collector behavior. Fixed stale prediction/anchor data cannot be repaired by a faster executor.
3. **Internal elapsed work consumes a real budget:** 60/157 verified decisions expire; eight more could verify at earlier actual receipts. Verifier work, claim durability, inference, scheduling/history overhead and SQLite contention cannot be ranked from existing timings. Reducing polling alone cannot be promised to fix this.
4. **Absolute source/clock alignment is unverified:** negative capture-relative book ages warrant renewed clock/timestamp diagnosis. No clock discontinuity does not establish accuracy.

**Recommended next implementation slice: bounded timing instrumentation on the existing CSV path, with no decision-semantics change.** Preserve original deadline fields; add genuine UTC and monotonic markers for receipt commit, verifier start/end, claim commit completion, model start/end, final freshness and terminal completion. Capture existing publication/skip logs, correlate by snapshot/decision ID, and buffer diagnostic writes until after the decision rather than adding an fsync to the 500 ms path. Measure instrumentation overhead. No architecture migration, external dependency or threshold change is needed.

Then remove the measured dominant avoidable cost while retaining actual-time checks. One confirmed needless-work path is already visible: false source flags still trigger HGB3 inference (**65/222 attempts**). A narrow pre-inference rejection could remove that work, but its impact on valid-decision latency is unmeasured and it intentionally changes diagnostic probability availability for rejected inputs. Preserve the same provenance reason, fee evidence and one-attempt claim semantics if approved; do not claim it recovers qualifying trades.

Regression plan for that future slice: preserve selected prediction/anchor/quote IDs and terminal reasons on retained fixtures; assert genuinely sampled commit/end times rather than recycled dispatch time; inject slow verification, inference and lock acquisition and retain >500 ms book, >3,000 ms reference and future-time rejection; verify false source flags skip model work; preserve restart/claim idempotency and zero live calls. Compare instrumentation overhead in isolated tests and collect a complete prospective session before making latency-improvement claims.

## 9. Limitations and outstanding questions

- The denominator covers discovered journaled opportunities, not never-discovered markets. These are 50 markets with correlated horizons, not 300 independent trading experiments.
- Final-check/publication/commit/inference timestamps are missing at requested granularity. Claim/completion equality reflects timestamp reuse. No component duration was invented.
- Recorded ages depend on local/source clocks, and many capture ages are negative. Independent current NTP offset, upstream timestamp semantics and exact collector command line remain unresolved. No tolerances or offsets were changed.
- Retained evidence replay verifies the implemented identity/time rules, not OS clock accuracy, upstream finality or forecast calibration.
- Console logs may exist outside inspected paths. They would improve timing attribution, not change EV arithmetic for these prices.
- Actual strategy freshness is established by the historical control flow, not a persisted final timestamp. Gap-only sensitivity preserves that known outcome; it does not claim a newly executed trade.
- Risk/minimum-size/simulator paths were not reached. Qualification alone would not prove later execution or settlement profitability.
- Previous reports were read for architecture and regression context; this report measures the current complete-market session and excludes its running tail.

## Source-code references

- [Collector](../scripts/operations/collect_vnext_local.py): `MarketCollector.collect`, sequential books at lines 543–549, final observation at 597; `main` commits evidence before CSV and logs publication.
- [Verifier](../src/polybtc/shadow/source_verification_vnext.py): `verify`, consumed anchor and supplied-deadline checks; [acquisition evidence](../src/polybtc/shadow/acquisition_evidence.py): canonical binding/raw attestation and explicit paper fee model.
- [Driver](../src/polybtc/shadow/stream_driver_vnext.py): `process`, quote selection, two-second observation limit and bounded wait; [coordinator](../src/polybtc/shadow/coordinator_vnext.py) reuses this path.
- [Adapter](../src/polybtc/shadow/adapter_vnext.py): `evaluate` passes `now` to claim/completion; [journal](../src/polybtc/shadow/orchestrator_vnext.py): `claim` line 435 and `complete_abstention` line 530 serialize supplied times.
- [Runner](../src/polybtc/shadow/runner_vnext.py): inference line 268 precedes source-flag rejection; clock sample 301; freshness 395–419; strategy 507; reserve/executor checks 649/690.
- [Strategy](../src/polybtc/strategy/vnext.py): market payout probability 189/195, execution price 215, EV 224; [features](../src/polybtc/data/dataset/features.py): normalized midpoint 113.
- [Risk](../src/polybtc/risk/vnext.py), [executor](../src/polybtc/shadow/executor_vnext.py): downstream safeguards; [runtime](../src/polybtc/shadow/service_runtime_vnext.py), [collector service](../src/polybtc/shadow/collector_service_vnext.py): receipt/history/polling boundaries.
- [Dashboard](../dashboard/backend/app/services.py): reason categories and probability display. Attribution here uses the journal and actual control flow, not dashboard categories alone.
