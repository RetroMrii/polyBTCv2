# P-PAPER-L1 — Timing and horizon investigation

## Outcome

The dominant observed blocker is stale reference data at the prediction cutoff. A separate, confirmed runtime selection defect discarded valid earlier causal snapshots. The late-horizon gaps reflect missing published/acquired observations, not an early scheduler firing. Two narrow corrections have been implemented and tested; no recorded opportunity has been executed or re-finalized. Zero fills cannot be attributed solely to the selector defect, and the fixes do not guarantee fills.

## Scope and reproducibility

Inspection snapshot: 2026-10-12, decision targets through 17:32:00 UTC; capture began at 2026-10-12T17:33:45.019838+00:00. Sources were opened read-only. The runtime was not stopped, restarted, or reconfigured. Consequently, this is a bounded observation of a running deployment, not a database-wide atomic snapshot.

- State: `data/paper/vnext_verified/{decisions,receipts,csv_tail,trades}.sqlite3`.
- Acquisition: `data/live/vnext_market_snapshots.csv` and `data/live/paper_acquisition.sqlite3`.
- CSV read ended at the retained checkpoint byte 31528055.
- 5,236 snapshots were reconstructed from original CSV bytes and persistent receipt times. IDs were recomputed from original file identity, byte offset and row bytes; no ingest times were fabricated.
- Focus: 17:00–17:32 UTC decision targets, 38 decisions and 964 consumed observations. The supplemental acquisition-only series has 965 records; its denominator is distinct.
- 21 verification results were reproduced from retained evidence and fee descriptors. All source flags matched. Eight already contained the new diagnostics, which reproduced exactly; diagnostics for the other 13 were recomputed in memory.
- The ledger still contained zero entries at the validation check.

Detailed per-decision timelines, full snapshot IDs, selected anchors, diagnostics and distributions: [P_PAPER_L1_EVIDENCE.json](P_PAPER_L1_EVIDENCE.json). All ages and delays below are milliseconds unless specified. Percentiles use linear interpolation, including maximum; small-sample p99 is descriptive, not a robust tail estimate.

## Counts

Whole inspected journal: **206 decisions** — 114 `unverified_input_provenance`, 42 `snapshot_arrived_after_target`, 46 `stale_horizon`, 3 `missing_reference_return_30s`, and 1 `missing_horizon`. The user’s eight-row summary was a smaller moving window.

| Focus horizon | Provenance | Arrived after target | Stale horizon | Total |
|---:|---:|---:|---:|---:|
| 240s | 6 | 1 | 0 | 7 |
| 180s | 4 | 3 | 0 | 7 |
| 120s | 5 | 1 | 0 | 6 |
| 90s | 3 | 3 | 0 | 6 |
| 60s | 3 | 2 | 1 | 6 |
| 30s | 0 | 0 | 6 | 6 |

## Ranked causes and corrections

1. **Reference freshness dominates (data availability).** All 21 evaluated prediction references exceeded 2,000 ms at their cutoff, and all 17 available execution references exceeded 2,000 ms at evaluation. Already at collection, 723/964 reference samples (75.0%) were stale. This cannot be repaired by accelerating only post-collection processing.

2. **Latest-observation selection ignored causal receipt time (implementation defect, corrected).** The shared selector ranked pre-target observations, then the runtime rejected the chosen row if its receipt was late. It never fell back to an earlier row received by the target. All 10 focused late-arrival decisions, and 38/42 in the whole inspected journal, had such an earlier row within the unchanged 10-second horizon lag. The corrected selector recovered all 10 focused alternatives in read-only replay. **All 10 alternatives still had stale prediction references**, so this is recovery of horizon selection, not proof of source eligibility or fills.

3. **Collection/ingestion/evaluation delay consumes the book budget (operational timing).** Observation-to-receipt median was 542 ms, already longer than the 500 ms book budget before adding source age. Some evaluated snapshots were older still. Storage/CSV publication, polling, checkpoint hashing and other processing are not separately timestamped, so this measurement cannot be assigned entirely to one component.

4. **Recent observations disappear before late horizons (availability gap, precise upstream cause unrecorded).** All seven focused stale horizons had zero acquisition records in their target-minus-10-seconds interval. Selection cannot recover an observation that was never retained. Complete-book checks, reference availability, auxiliary-feature warmup and request errors are possible collector return paths, but the stored successful rows do not identify which path caused each gap. Do not call this proven empty-book behavior or a scheduler bug.

5. **Collector held an earlier cached reference across book requests (avoidable acquisition delay, corrected).** It selected `feed.latest()` before Gamma work and sequential YES/NO requests. Those requests had median combined build time 164 ms and p99 1,808 ms. It now samples the existing local feed again after the book responses and recomputes its auxiliary features from that same sample. The original source timestamp and matching raw evidence are retained. No additional network request, altered sampling interval, or changed age threshold is introduced. Exact retrospective eligibility gain is not identifiable: full feed arrival history was not retained.

6. **History-wide verification exceeds inference’s actual reference dependency (conservative policy, unchanged).** Details below demonstrate the dependency. Removing this check alone would recover zero of the focused decisions because their prediction references fail independently.

## Timing measurements

| Measurement | N | Median | p90 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| observation_to_capture_ms | 964 | 0.568 | 0.804 | 3.977 | 5.050 |
| capture_to_receipt_ms | 964 | 540.910 | 791.987 | 1,277.342 | 2,765.954 |
| observation_to_receipt_ms | 964 | 542.149 | 792.536 | 1,277.783 | 2,766.710 |
| snapshot_build_latency_ms | 964 | 164.120 | 679.116 | 1,808.458 | 6,066.307 |
| same_market_observation_spacing_ms | 957 | 1,434.125 | 1,944.298 | 3,722.126 | 10,112.340 |
| target_to_processed_ms | 38 | 2,365.094 | 2,748.660 | 3,103.763 | 3,223.634 |
| execution_observation_to_verification_ms | 17 | 417.054 | 1,369.388 | 1,681.850 | 1,740.018 |
| execution_receipt_to_verification_ms | 17 | 0.000 | 961.797 | 1,187.777 | 1,227.949 |
| reference_age_at_observation_ms | 964 | 2,338.160 | 3,077.916 | 4,533.967 | 8,185.456 |
| reference_age_at_verification_ms | 17 | 3,351.913 | 4,588.708 | 5,504.666 | 5,649.893 |
| yes_book_age_at_observation_ms | 964 | 50.547 | 253.747 | 1,184.611 | 4,816.060 |
| yes_book_age_at_verification_ms | 17 | 716.679 | 2,149.978 | 2,534.053 | 2,543.226 |
| no_book_age_at_observation_ms | 964 | -32.036 | -2.304 | 618.667 | 1,427.815 |
| no_book_age_at_verification_ms | 17 | 378.717 | 1,484.531 | 1,891.467 | 1,926.035 |
| sampled_reference_event_spacing_ms | 936 | 2,000.000 | 2,000.000 | 7,000.000 | 107,000.000 |

**Timestamp interpretation:** upstream reference/book timestamps, collector `observed_at`, evidence `captured`, and persistent first receipt are recorded values. Market start is reconstructed as expiry minus 300 seconds and checked against the retained interval/slug; target is expiry minus horizon. `captured` is sampled before attestation and the evidence transaction; it is not evidence commit completion or CSV availability. CSV append/fsync completion has no independent timestamp. Publication is bounded by evidence capture and first receipt for those consumed rows; its exact contribution is unknown.

**The journal times are not separate wall-clock probes.** `VNextCollectorService.run_once()` passes one `processing_at` sampled at intake (or the empty-cycle clock) into the driver. `processed_at`, `claimed_at`, verification `checked_at`, and completion reuse it. Equal values do not demonstrate zero inference, verification, or transaction latency. The measured receipt-to-verification distribution describes logical evaluation time, and actual elapsed compute/claim/commit delays cannot be recovered from these fields.

The 2-second finalization grace is intentional. Focused decisions fired 2.050–3.224 seconds after target, never before it, with 0.050–1.224 seconds beyond the grace. The execution selector takes the latest available eligible row, not the original prediction row; a 2-second grace does not by itself force a 2-second-old execution quote.

## Individual freshness failures

For the 21 source-verification opportunities (overlapping failures):

| Constraint | Failures | Denominator | Percentage |
|---|---:|---:|---:|
| Prediction reference older than 2,000 ms | 21 | 21 | 100% |
| At least one historical reference older than 2,000 ms at its own observation | 21 | 21 | 100% |
| Execution reference older than 2,000 ms, execution snapshot present | 17 | 17 | 100% |
| Execution YES book older than 500 ms, execution snapshot present | 9 | 17 | 52.9% |
| Execution NO book older than 500 ms, execution snapshot present | 8 | 17 | 47.1% |
| Execution snapshot missing | 4 | 21 | 19.0% |

For the 964 consumed observations, before subsequent processing delay:

| Source | Stale | Future-dated | Fresh |
|---|---:|---:|---:|
| reference | 723 (75.0%) | 0 (0.0%) | 241 (25.0%) |
| yes_book | 70 (7.3%) | 0 (0.0%) | 894 (92.7%) |
| no_book | 15 (1.6%) | 880 (91.3%) | 69 (7.2%) |

NO books were frequently tens of milliseconds ahead of collection time (median age −32 ms). This is present in retained data despite the earlier clock correction; it does not prove the Windows clock is currently wrong. The future-time lower bound remains enforced. Evaluation later than collection can make such a timestamp non-future, but faster processing must never be credited with accepting a still-future source.

**Delay counterfactual:** evaluating each retained execution quote at its first receipt, with original prediction/history checks, produces **0 source passes**. An explicitly optimistic in-memory counterfactual removes transport/receipt delay down to evidence capture and also produces **0**. No persisted timestamps were altered. Four opportunities lack an execution snapshot entirely. These counts describe source verification only, not strategy approval.

**Upstream cadence:** distinct reference event timestamps retained by the collector have median/p90 spacing of 2 seconds, p99 7 seconds and max 107 seconds. This is a subsampled series of successful collection, not the complete websocket stream or arrival cadence. It therefore cannot prove that the upstream service inherently updates only every two seconds or that its cadence is fundamentally incompatible with the limit. 241 observed samples actually meet the 2-second limit. However, a roughly 2-second sampled spacing plus delivery/collection/receipt age leaves very little budget, and all measured prediction opportunities failed it. No source receive-time distribution is available to separate upstream delay from local cache sampling.

## Representative decision traces

All times below are UTC on 2026-10-12. Full timestamps for every focused decision are in the JSON artifact.

### Late arrival: decision 280840, 180-second horizon

- Market 17:25:00–17:30:00; target 17:27:00; finalized 17:27:02.899657 (no adapter claim).
- Selected observation 17:26:59.996166; evidence captured 17:26:59.996800; first receipt 17:27:00.363524. It was observed before target but received 363.524 ms after target. CSV publication relative to the target is not independently known.
- Its reference event was 17:26:58; YES book 17:26:59.977; NO book 17:27:00.055.
- Earlier causal observation: 17:26:58.395462, captured 17:26:58.396047, received 17:26:58.854818. Horizon gap 1.604538 seconds, safely inside 10 seconds. Its reference was 17:26:56, hence still 4 seconds old at target.
- Market observations started at 17:25:07.372259, well before this target. Discovery/warmup did not prevent the earlier candidate. This is selector behavior, not a post-target observation or premature finalization.

### Late arrival: decision 290573, 180-second horizon

- Market 17:30:00–17:35:00; target 17:32:00; finalized 17:32:02.560356 (no adapter claim).
- Chosen observation 17:31:59.985711; captured 17:31:59.986204; received 17:32:00.294171.
- Available alternative observed 17:31:58.155865, captured 17:31:58.159074, received 17:31:58.884664. Reference 17:31:55; again selecting it repairs causality but does not make the reference fresh.

### Stale horizons: decisions 285042 and 286242

- Market 17:25:00–17:30:00. Last retained observation 17:28:20.218895, captured 17:28:20.219497, received 17:28:20.802047.
- At target 17:29:00, the valid observation interval was [17:28:50, 17:29:00]; the latest row missed its lower edge by 29.781105 seconds. Horizon gap was 39.781105 seconds. Finalized 17:29:02.401399.
- At target 17:29:30, the valid interval was [17:29:20, 17:29:30]; the latest row missed its lower edge by 59.781105 seconds. Gap was 69.781105 seconds. Finalized 17:29:32.061285.
- Both the consumed CSV/receipts and acquisition database lack rows in those intervals. Claims and executions are absent. Correct scheduling cannot recover these windows.

### Provenance: decision 289033, 240-second horizon

- Market 17:30:00–17:35:00; target 17:31:00. Prediction observed 17:30:58.008508, captured 17:30:58.009093, received 17:30:58.750188. Reference event 17:30:55: 5,000 ms old at target.
- Execution observed 17:31:01.960715, captured 17:31:01.961152, received 17:31:02.217551. Claim, verification and completion all store the same logical 17:31:02.217551.
- Execution reference 17:31:00: 2,217.551 ms old. YES book 17:31:01.960: 257.551 ms old; NO book 17:31:02.031: 186.551 ms old. Here both books pass; the reference fails.
- The actual 30-second anchor was observed 17:30:26.847158, received 17:30:27.245718, reference event 17:30:25. It is fresh at its own observation. Nevertheless 24/34 supplied history rows are stale, and the prediction/current reference independently fails.

### Provenance: decision 283633, 90-second horizon

- Market 17:25:00–17:30:00; target 17:28:30; prediction observation 17:28:20.218895, received 17:28:20.802047. Gap 9.781105 seconds is still within the horizon selector limit.
- Reference event 17:28:19 is 11 seconds old at target. Logical evaluation 17:28:32.149275 has no execution snapshot. Of 122 history rows, 87 are stale. The actual anchor observed 17:27:48.964018 has reference event 17:27:47 and is itself fresh.

## Actual inference dependencies and history verification

`runner_vnext._reference_return_30s()` filters for same-market, positive reference price, observed and ingested by the prediction cutoff, observed no later than prediction-observation minus 30 seconds, and reference event no later than cutoff. It chooses the latest eligible observation and rejects an anchor more than 10 seconds behind the desired anchor time. The scalar return is prediction reference / selected anchor reference minus one.

The model receives exactly three scalar features: `relative_distance_from_strike` from the prediction row/reference/strike, the configured `target_horizon_seconds`, and this `reference_return_30s`. Other historical reference prices, the collector’s momentum/volatility, and historical books are not supplied to inference. The prediction book baseline is used separately by the decision logic and still requires its existing binding checks.

Thus verifying every unused historical row is not necessary to authenticate these three feature values, but narrowing the rule would change a deliberate conservative safety policy. A safe future change would share the exact anchor selector between feature construction and verification (including tie order, receipt cutoff, reference cutoff, expiry/market binding and lag checks); verify the prediction reference/strike and the consumed anchor with retained raw evidence; retain current execution reference/books and fee checks; and persist the consumed IDs. Do not simply discard stale rows before anchor selection, which could change the model feature.

All 21 focused decisions had an actual anchor; 6 anchors were fresh at their own observation, 15 were not. Even the six fresh-anchor cases have stale prediction references. **No history-policy change was made.**

## Code paths and implemented changes

- `src/polybtc/data/dataset/horizons.py::select_market_horizons`: new optional `require_received_by_target`; runtime selection prefers candidates both observed and received by target. The historical research default remains unchanged. A stale causal alternative still fails the 10-second lag limit; if none is causal, the existing late-arrival rejection remains.
- `src/polybtc/shadow/orchestrator_vnext.py::VNextDecisionOrchestrator.process`: enables causal receipt filtering. The two-second grace, fixed targets, unique journal constraints and finalized records are unchanged.
- `scripts/operations/collect_vnext_local.py::MarketCollector.collect`: refreshes the existing local reference cache after book acquisition; price, source timestamp, retained raw reference and auxiliary features use the same refreshed sample. Missing refresh/feature data continues to skip publication.
- `src/polybtc/shadow/collector_bridge_vnext.py::ingest` records the first receipt; `collector_service_vnext.py::run_once` chooses the cycle processing time; `stream_driver_vnext.py::process` supplies causal history and the latest eligible execution quote.
- `source_verification_vnext.py::verify` evaluates prediction reference age at target, history reference age at each observation, and execution source ages at logical evaluation time. No changes here in L1.

## Validation and operational effect

- 83 tests passed across horizon selection, orchestrator, collector, stream driver, paper integration, provenance and paper-mode safety.
- After adding the explicit finalized-abstention regression, all 12 orchestrator tests passed (one additional distinct test; 84 distinct tests total).
- Read-only replay through the actual corrected selector recovered the earlier causal snapshot in 10/10 focused late-arrival cases. It wrote no journal rows.
- Collector tests simulate a newer reference arriving during book acquisition and verify price, timestamp, features and raw attestation remain consistent. Missing refreshed data fails closed; network calls are forbidden in those tests.
- Exact-target receipt and exact 10-second horizon boundaries remain accepted; older causal rows remain stale; missing causal rows remain rejected; research selection defaults remain unchanged.
- A previously finalized late-arrival abstention stays immutable even when an earlier causal row subsequently appears.

To load the corrections, restart only the collector and paper runtime with their existing commands, CSV and state paths. No process was restarted as part of this investigation. Historical decisions will not be replayed. Any improvement must be measured on new markets; no forward fill or profitability result is claimed.

## Remaining minimal plan

1. On new data, compare observation-to-receipt ages and target reference ages after the two corrections; count eligibility independently of strategy fills.
2. Add independent stage timing for evidence commit completion, CSV publication completion, poll/receipt, actual verification/claim/completion, and collector skip reasons. Keep raw event timestamps intact and do not backdate prior records. This is needed to attribute storage/poll/compute latency and explain late-market gaps.
3. Measure complete reference event arrival timestamps from the existing feed to separate upstream cadence and delivery latency from collector subsampling. No network probe was needed or made for this investigation.
4. Investigate the frequent small future NO-book timestamps using those measurements; retain the negative-age rejection.
5. Consider narrowing history verification only as a separately validated change using the exact shared consumed-anchor selection above. It has zero demonstrated eligibility benefit in this sample.

No model artifact, strategy, fee, risk limit, source freshness limit, database, checkpoint or collected CSV was modified by this work. No live trading was enabled. Only application code, isolated synthetic test files and these report artifacts were written.
