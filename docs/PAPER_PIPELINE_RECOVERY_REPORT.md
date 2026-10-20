# PolyBTC v2 — End-to-end paper pipeline recovery

## Scope and evidence

This investigation reads the original operational state without resetting checkpoints,
rewriting finalized decisions, or altering collected rows. Original state is
`data/paper/vnext_verified`, acquisition is `data/live/vnext_market_snapshots.csv`,
with `paper_acquisition.sqlite3` and `paper_fees.sqlite3` alongside it. The last
saved original runtime heartbeat says **stopped at 18:10:38 UTC**, not running.
Its lock file dates the latest startup to 17:50:29 UTC. The selected post-restart
window is 17:51:00–18:09:30 UTC on 2026-10-12: **24 decisions**, including all 20
reported provenance rejections. Inspection began at 19:48 UTC. Times below are UTC.

The bounded CSV checkpoint was 31,987,165 bytes. Original file identity, byte offset
and raw row bytes reproduced 5,899 durable snapshot IDs and receipt times; 653
observations lie in the selected window. Acquisition canonical IDs deliberately
exclude runtime snapshot IDs and first-receipt times. No identity repair or raw
source timestamp substitution was needed.

- [Original measured decisions and distributions](PAPER_PIPELINE_RECOVERY_EVIDENCE.json)
- [Read-only recheck with consumed-anchor verification](PAPER_PIPELINE_RECOVERY_RECHECK.json)
- [55-second public RTDS probe, original payloads and actual arrival times](PAPER_PIPELINE_FEED_PROBE.json)
- [Durable SQLite write benchmark](PAPER_PIPELINE_SQLITE_BENCHMARK.json)
- [Component-level receipt/commit/close benchmark](PAPER_PIPELINE_RECEIPT_IO_BENCHMARK.json)

## Post-restart baseline

| Horizon | Provenance rejection | Missing 30s anchor | Stale horizon | Total |
|---:|---:|---:|---:|---:|
| 240 | 3 | 1 | 0 | 4 |
| 180 | 4 | 0 | 0 | 4 |
| 120 | 4 | 0 | 0 | 4 |
| 90 | 4 | 0 | 0 | 4 |
| 60 | 4 | 0 | 0 | 4 |
| 30 | 1 | 0 | 3 | 4 |
| Total | 20 | 1 | 3 | 24 |

Horizon selection delivered a causal prediction for 21/24 opportunities (87.5%).
All 21 supplied a distinct execution snapshot and compatible paper fee descriptor.
All 21 persisted verification flag sets reproduced from retained evidence; failures
were freshness, not missing records, canonical mismatches, raw malformed responses,
market/token associations or fee applicability. HGB3 generated probabilities for
20/24 opportunities (83.3%); the other selected opportunity lacked a causal anchor.
None reached strategy in this original window. No `snapshot_arrived_after_target`
remains in the window: the previous selection correction is functioning.

Overlapping failure counts among 21 source-verification attempts:

| Constraint | Failed | Rate |
|---|---:|---:|
| Prediction reference at target, maximum 2,000 ms | 18 | 85.7% |
| Execution reference at evaluation, maximum 2,000 ms | 19 | 90.5% |
| YES book at evaluation, maximum 500 ms | 17 | 81.0% |
| NO book at evaluation, maximum 500 ms | 15 | 71.4% |
| Any row in the previously supplied full history stale | 21 | 100% |
| Actual consumed historical anchor stale, corrected scope | 12 | 57.1% |
| Actual consumed anchor absent | 1 | 4.8% |

Removing unused historical rows alone recovers **zero** original decisions.
Rechecking at the original execution receipt time also recovers **zero**. An
explicit hypothetical acquisition-time lower bound, removing transport delay,
still recovers zero for these recorded prediction/execution pairs. Counterfactuals
are analytical only; no receipt, decision or stored timestamp was changed.

### Measured distributions (milliseconds)

Percentiles use linear interpolation. Small-sample p99 is descriptive.

| Measurement | N | Median | p90 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| Collector observation → retained evidence capture | 653 | 0.578 | 0.855 | 3.776 | 4.331 |
| Collector observation → first durable receipt timestamp | 653 | 460.765 | 656.287 | 989.472 | 2,213.789 |
| Reference source age at collection | 653 | 2,009.995 | 2,503.834 | 3,228.624 | 4,022.368 |
| Snapshot build duration | 653 | 162.732 | 619.987 | 1,295.088 | 2,524.433 |
| Same-market sample spacing | 648 | 1,386.704 | 1,829.144 | 2,719.583 | 6,449.378 |
| Target → recorded processing time | 24 | 2,345.893 | 2,660.525 | 2,894.923 | 2,919.174 |
| Execution observation → recorded verification | 21 | 1,016.332 | 1,329.637 | 1,768.390 | 1,795.571 |
| Execution receipt → recorded verification | 21 | 761.428 | 942.315 | 1,238.318 | 1,307.646 |
| Execution reference age | 21 | 3,180.026 | 4,083.363 | 4,430.939 | 4,478.318 |
| Execution YES book age | 21 | 1,070.438 | 1,593.174 | 1,753.042 | 1,767.296 |
| Execution NO book age | 21 | 962.438 | 1,519.174 | 1,693.280 | 1,696.026 |

Source timestamps, observation, capture, receipts and journal values are recorded.
Market start is reconstructed from expiry minus 300 seconds and validated by the
retained slug/interval; target is expiry minus the horizon. Original capture time
precedes evidence commit, so it is **not** CSV publication completion. Publication
completion was not independently recorded in the original data. Original journal
claim/completion/verification reused the same logical clock; they are not independent
wall-clock latency probes. Their apparent equality does not imply instantaneous
work. New collector publication logs and instrumented validation record actual
wall-clock publication and stage durations separately.

At collection, 334/653 reference ages exceeded their allowed range. Signed CLOB
ages were frequently negative (YES median -39.519 ms; NO median -119.282 ms),
consistent with a clock-domain offset, but insufficient to assign which clock is
wrong. Negative ages remain rejected at evaluation; no clock offset is invented.
The aggregate observation-time out-of-range counts (YES 612, NO 640) include
negative ages and must not be described as all stale books.

## Root causes, classification and coordinated corrections

1. **Durable I/O consumed the quote budget — confirmed implementation/performance
   defect on this storage path.** Evidence/history used rollback journals, and
   short-lived WAL connections forced last-connection checkpoints. Fully durable
   small rollback writes measured 394–567 ms. Component measurement of the real
   receipt bridge measured COMMIT 163–437 ms plus CLOSE 93–184 ms. Keeping an idle
   reader open measured CLOSE 0.118–0.253 ms and subsequent COMMIT 44–121 ms
   (first commit 325 ms). These are bounded local benchmarks, not a storage SLA.
   Both evidence/history now use WAL with FULL synchronization. Idle read-only
   lifetime handles avoid per-operation WAL teardown without holding a transaction,
   pinning a WAL snapshot, sharing writer connections or disabling checkpoints.

2. **A redundant history-cache durability barrier sat before evaluation — corrected
   implementation ordering.** Evidence and first receipts remain durable before
   evaluation. New rows merge with existing history with conflict checks. The
   replayable history cache persists in `finally`, before checkpoint acknowledgement.
   If it fails, the source stays unacknowledged and original receipts recover it;
   journal claims and terminal decisions prevent a repeated evaluation/fill.
   The new failure-injection test proves that boundary across a real runtime restart.

3. **Every supplied historical row was treated as a model dependency — confirmed
   contract mismatch, corrected.** The locked model has exactly three features:
   relative distance from strike, horizon, and current reference divided by one
   selected 30-second historical anchor minus one. Selection is now shared by
   inference and verification. Prediction, selected anchor and execution still
   require retained evidence, exact canonical binding, causal deadlines, reference
   semantics and unchanged freshness. The selected anchor must match the interval;
   a stale/missing/malformed selected anchor fails rather than selecting another
   price that passes. Unused historical values cannot affect either model features
   or verification. The anchor ID and new verifier version are persisted.

4. **Processing was evaluated using an earlier intake clock — safety defect,
   corrected.** Processing time is sampled after intake; each decision samples time
   before verification. The runner rechecks source/fee age after inference and the
   executor samples time after reservation. Clock rollback fails closed. This can
   correctly reject additional opportunities; it never makes stale data verified.

5. **Repeated INSERT OR IGNORE wrote the SQLite sequence on every poll — corrected
   avoidable disk work.** Existing market/horizon records are now checked under the
   same write transaction before insertion. The sequence no longer advances for
   old finalized decisions. Awaiting-only journal queries avoid loading historical
   diagnostic payloads into the dispatch loop. Unique keys/claims remain authoritative.

6. **Public TWAP lag plus slow collection/poll cadence — genuine upstream and
   configuration constraints, not timestamp mapping defects.** In a direct 55-event
   probe, all 54 source intervals were exactly 1,000 ms. Arrival source-age median
   was 1,262.826 ms, p90 1,685.417, p99 2,056.227, maximum 2,070.415, minimum 720.892;
   2/55 updates were already stale on arrival. Thus this feed can sometimes satisfy
   2,000 ms, but cannot guarantee continuous eligibility. The publisher-envelope
   timestamp is not substituted for the payload observation timestamp. Cross-clock
   envelope-to-local differences include negative values and are not a one-way
   network-latency measurement. No different spot feed or unverified PolyBolt
   subscription was needed to establish these facts. The optional existing PolyBolt
   transport remains available but was not authenticated or validated in this task.

7. **Startup/warmup and incomplete market books remove observations — legitimate
   availability limits with improved diagnostics.** Decision 315356 targeted
   17:51:00; its prediction at 17:50:59.635609 needed an anchor at or before
   17:50:29.635609, but first retained market observation was 17:50:47.475525.
   The anchor was unavailable, not incorrectly selected. Stale decisions 316343,
   320496 and 335723 missed the target-minus-10-second window by having last-row
   gaps 28.154598, 26.618226 and 17.670650 seconds. A read-only acquisition query also found zero retained observations in each
   valid target-minus-10-second window. Their targets were processed
   after the unchanged two-second grace, not prematurely. Correct scheduling
   cannot recover absent rows. The exact original collector skip cause was not
   retained. A prospective instrumented run subsequently recorded 158 incomplete-book
   skips, supporting that path for the new run without asserting it proves every
   historical gap. New `acquisition_wait` codes distinguish these causes.

8. **No downstream model/feature/strategy-interface defect found.** Original journal
   probabilities already proved HGB3 v2 inference worked on genuine retained inputs.
   Integration tests additionally cover valid sources, fee evidence, actual model,
   unchanged strategy EV/price/depth checks, risk rejection, simulated execution,
   settlement and restart. Operational strategy evidence is reported separately below.

9. **Immediate claim at grace was phase-sensitive to the reference publication
   cadence — confirmed handoff defect, corrected.** After latency corrections,
   diagnostic decision 3 for target 20:13:00 failed its immediate attempt. A retained
   cycle at 20:13:02.475058 had a newer, genuinely available observation passing all
   four source/fee flags with the same frozen prediction and anchor. See
   [the exact retained evidence check](PAPER_PIPELINE_HANDOFF_EVIDENCE.json).
   That analytical check did not replay or alter the finalized decision. New paper
   decisions may instead stay unclaimed up to one second beyond the existing grace
   when only execution freshness/availability is transiently invalid. This interval
   is the measured source cadence, not a changed prediction horizon or freshness
   tolerance. Untrusted prediction/history, bad binding and invalid fees finalize
   normally. The deadline is fixed from the original target; restart cannot extend
   it. Waiting depends only on source freshness/availability, never on the model,
   market direction, price attractiveness or EV. The first eligible handoff is
   evaluated once, including a strategy SKIP. There is no retry of finalized decisions.

## Implementation map

| File | Functions / behavior |
|---|---|
| `src/polybtc/shadow/runner_vnext.py` | `reference_anchor_30s`, `_reference_return_30s`, `VNextShadowRunner.evaluate`: shared exact dependency; real-time post-inference/execution age checks |
| `src/polybtc/shadow/source_verification_vnext.py` | `verify`, `SourceVerificationResult.provenance`: verify consumed anchor, retain anchor ID/version, fail closed on missing anchor |
| `src/polybtc/shadow/acquisition_evidence.py` | store initialization/close: WAL FULL and idle reader lifetime; raw attestation/binding unchanged |
| `src/polybtc/shadow/sqlite_wal_vnext.py` | `WALReaders`: read-only, transaction-free handles; explicit close; ordinary checkpoints remain possible |
| `src/polybtc/shadow/collector_service_vnext.py` | history initialization and `run_once`: WAL; conflict-checked merge; cache commit before acknowledgement; current processing clock |
| `src/polybtc/shadow/orchestrator_vnext.py` | `process`, `decisions`: avoid no-op sequence writes; filter awaiting dispatch reads |
| `src/polybtc/shadow/stream_driver_vnext.py` | `process`: measured per-decision clock; awaiting-only query; bounded pre-claim execution-evidence handoff |
| `src/polybtc/shadow/service_runtime_vnext.py` | runtime lifetime/stop/error paths release idle WAL readers |
| `scripts/operations/run_vnext_shadow.py` | `build_runtime`, CLI: wire clocks/WAL paths; configurable `--poll-interval`, same default 0.25 |
| `scripts/operations/collect_vnext_local.py` | `collect`, `main`: explicit skip codes, actual publication-completion logs, evidence handle shutdown |
| `tests/shadow/` | targeted anchor, freshness deadline, sequence, WAL and failure/restart regressions |
| `docs/PAPER_TRADING.md` | compatible commands, timing/diagnostics and restart procedure |

Root compatibility launchers remain valid. No production v1.1 module, model artifact,
calibration, strategy/risk formula, entry threshold or order control was edited.

## Validation and operational outcome

**STRATEGY_REACHED_WITH_REAL_VERIFIED_INPUTS**

The prospective run used the actual collector, public RTDS/Gamma/CLOB responses,
CSV publisher/tailer, durable evidence/receipt/history/journal databases, fee cache,
HGB3 v2 artifact, source verifier and strategy. Collector and runtime ran concurrently
in separate threads with real clocks, isolated under
`data/validation/pipeline_recovery_20261012T201639Z`. Fills were disabled throughout.
The strategy observer only recorded its input/output and forwarded the unchanged
return value. No source flags, model result, timestamp or quote were mocked.

**Recorded decision 1** in that directory's `paper/decisions.sqlite3`:

- Market `0x9248b96c8affde0f3e779c2a21b502935ddab0673d133b8bcb18fc6fa5eeed00`,
  interval **20:20:00–20:25:00**, horizon **240 seconds**, prediction target **20:21:00**.
- Selected prediction: observed **20:20:59.023489**, published **59.346101**,
  first received **59.386155**, reference event **20:20:58**.
- Selected 30-second anchor: observed **20:20:28.680679**, published **28.851115**,
  received **28.863135**, reference event **20:20:27**.
- Execution: observed **20:21:02.044533**, evidence captured **02.044923**,
  published **02.410341**, received **02.438437**; reference event **20:21:01**,
  YES book **02.356**, NO book **02.430**.
- Journal processing **20:21:02.491061**; verification/claim logical timestamp
  **02.607299**; actual strategy observation **02.710076**. Journal completion
  still records the dispatch timestamp, not an independently measured commit end.
- Prediction reference age **2,000 ms**, consumed-anchor reference age
  **1,680.679 ms**. At the runner's post-inference check, execution reference
  age **1,709.976 ms**, YES **353.976 ms**, NO **279.976 ms**.
- All source flags and both fee checks **true**; source diagnostics **empty**.
  Re-opening retained evidence read-only reproduced the complete verification
  provenance exactly, including the three canonical evidence IDs.
- Model features: relative distance **-0.0002704947863224796**, horizon **240**,
  30-second reference return **-0.00012421654906269453**.
- Actual HGB3 probability YES **0.25046665036190147**; market probability YES
  **0.255**; YES ask **0.26**, NO ask **0.75**; fee estimate **0.01751/share**.
- Existing strategy returned **ABSTAIN / `price_ceiling_exceeded`**. Direction and
  probability-gap gates passed, but the NO execution price would be **0.76** after
  the existing one-tick slippage allowance, exceeding **0.70**. The strategy
  correctly stopped before its subsequent EV branch; that branch was not reordered
  to manufacture a result. Existing positive/negative EV and risk tests passed.
- Zero ledger entries, zero fills, zero errors, zero live orders. The diagnostic
  acquisition/runtime stopped after this strategy result.

Full IDs, retained evidence mapping, source/fee provenance, model features,
actual strategy input/output and timing distributions are in
[PAPER_PIPELINE_SUCCESS_EVIDENCE.json](PAPER_PIPELINE_SUCCESS_EVIDENCE.json).
The complete run, including original reference arrivals and all stage timings,
is retained in the validation directory's `result.json`, SQLite databases and CSV.

### Stage status

PASS/FIXED below means demonstrated on this genuine observation; it is not a
claim that every future input is eligible.

| Stage | Status | Evidence / remaining limitation |
|---|---|---|
| Live reference acquisition | PASS | Original RTDS 60-second TWAP events; some updates remain legitimately stale |
| Market discovery and metadata | PASS | Actual Gamma condition, interval, outcome/token mapping attested |
| YES/NO CLOB books | PASS | Original bound books passed 500 ms at strategy; incomplete books remain legitimate skips |
| Snapshot construction | PASS | Actual collector-shaped row; original upstream timestamps retained |
| Retained acquisition evidence | FIXED | WAL FULL/lifetime handles; canonical IDs and raw attestations reproduced |
| CSV publication | PASS | Actual publication completion timestamps; evidence committed first |
| CSV ingestion/checkpoint | PASS | 113 durable receipts with real byte-derived IDs; checkpoint not fabricated |
| Snapshot history | FIXED | Exact consumed anchor; cache commit precedes acknowledgement; crash recovery tested |
| Horizon scheduling/handoff | FIXED | Frozen causal prediction; bounded unclaimed execution wait; no terminal replay |
| Causal features | FIXED | Shared anchor dependency and unchanged feature values/order |
| Source and fee verification | FIXED | All four source/fee flags true; no diagnostics; supported explicit paper fee scope |
| HGB3 v2 inference | PASS | Frozen model generated the recorded real probability |
| Strategy evaluation | PASS | Recorded price-ceiling abstention; no input-provenance failure |
| Original long-running deployment | UNVERIFIED | Original runtime remains stopped; restart it with the documented original paths |
| Continuous market eligibility | UNVERIFIED | One genuine completed horizon proves integration, not an availability SLA |

The successful run retained 115 acquisitions and ingested 113 (98.3%); two rows
published during shutdown remain in the diagnostic CSV, unacknowledged for future
intake rather than assigned artificial receipts. One horizon was evaluated and
reached strategy (1/1); the run deliberately stopped at success, so this must not
be presented as an unbiased 100% market-opportunity success rate.

| Successful-run measurement (ms) | N | Median | p90 | p99 | Max |
|---|---:|---:|---:|---:|---:|
| Observation → publication | 115 | 219.699 | 338.192 | 449.575 | 467.181 |
| Observation → receipt | 113 | 338.335 | 577.706 | 757.294 | 777.585 |
| Evidence commit | 115 | 101.812 | 166.955 | 221.835 | 227.131 |
| Source verification | 1 | 7.902 | 7.902 | 7.902 | 7.902 |
| HGB3 inference | 1 | 16.356 | 16.356 | 16.356 | 16.356 |
| Claim → runner → completion call | 1 | 186.749 | 186.749 | 186.749 | 186.749 |

This final run used a 0.1-second acquisition pause and 0.05-second runtime pause.
Storage latency varies substantially; earlier instrumented runs and benchmarks
are retained rather than selectively discarded. Cycle-wide timing medians in the
JSON include empty polls, and must not be read as medians of write commits alone.

### Tests and preservation

- Broader suite: **505 passed in 614.91 seconds** across `tests/shadow`,
  `tests/data`, `tests/modeling` and `tests/trading` during the coordinated work.
- Final changed-path suite after all corrections: **113 passed in 80.28 seconds**.
  This includes real-model synthetic pipeline integration, exact consumed-anchor
  verification, strict freshness boundaries, post-inference/post-reservation
  expiry, no-op journal polling, WAL FULL/reopen/checkpoint behavior, cache-failure
  recovery without a second fill, pending handoff restart, timeout finalization,
  and immediate rejection of untrusted prediction evidence.
- The new restart test initially reused a fixture helper that inserted the same
  fee row twice. That fixture was corrected to reopen its existing cache; the final
  suite above passes. No runtime fee-policy behavior was changed for the test.
- Root compatibility launchers accept their documented commands (`--help` checked).
  No network call was introduced in decision processing. Integration tests prohibit
  network access; real public acquisition ran separately from evaluation.
- No critical safety failure remains in the relevant validation. Synthetic fixtures
  prove failure/recovery interfaces; the separately retained prospective run is the
  proof of genuine verified inputs reaching strategy.

Final changed-path validation command:

```powershell
.\.venv-execution\Scripts\python.exe -B -m pytest tests/shadow/test_collector_service_vnext.py tests/shadow/test_paper_acquisition.py tests/shadow/test_runner_vnext.py tests/shadow/test_source_verification_vnext.py tests/shadow/test_orchestrator_vnext.py tests/shadow/test_collect_vnext_local.py tests/shadow/test_paper_mode_vnext.py tests/shadow/test_service_runtime_vnext.py tests/shadow/test_stream_driver_vnext.py -q --basetemp=.pytest_cache/recovery-release-validation -p no:cacheprovider
```

Use a new `--basetemp` name for a later Windows rerun to avoid stale temp ACLs.
Counts from the broad and focused suites overlap and are not additive.

[The preservation check](PAPER_PIPELINE_PRESERVATION.json) confirms original state
still has **234 decisions**, maximum ID **335723**, **5,899 receipts**, checkpoint
**31,987,165**, the same CSV length, **zero ledger entries**, unchanged reason counts
and unchanged model hash. No original process was restarted or its state replayed.
The updated [operating procedure](PAPER_TRADING.md) preserves the original source,
evidence, fees and state paths and shows the validated polling/acquisition settings.


## Safety and remaining risks

All source trust/binding requirements for consumed inputs, 500 ms book and 2,000 ms
reference limits, fee verification, 5% disagreement limit, EV formula/threshold,
position sizing, price/order/exposure/daily-loss caps and one-entry-per-market rule
are unchanged. Live execution remains unavailable in this runtime. Diagnostic live
runs keep the paper kill switch on and do not send any order. Original finalized
rows, receipts, CSV contents, checkpoints, trades and research artifacts are retained.

The model SHA-256 remains
`42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`.

Remaining operational risks are variable upstream lag, future-dated book stamps
relative to the local clock, incomplete books near expiry, warmup on mid-market
startup, and durable storage latency tails. Faster polling is not permission to
ignore any of them. Original CSV prefix integrity hashing remains enabled; a
31,987,165-byte prefix hash measured approximately 28–29 ms in five reads, and its
cost grows with the file. An eventual archival/rotation scheme would need an
explicit, integrity-preserving checkpoint migration; none was improvised here.
A bounded successful strategy evaluation does not establish continuous eligibility,
fill realism, account readiness or profitability. Paper fees and nearest-boundary
strike retain their existing explicitly labeled assumptions. No live account or
settlement economics is certified by this report.
