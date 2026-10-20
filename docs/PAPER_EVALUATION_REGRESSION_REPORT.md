# Paper evaluation regression — 2026-10-13

Outcome A for the confirmed configuration regression: fixed and reproduced with retained real inputs. Subsequent live validation is still required. Missing acquisition intervals and marginal execution timing remain real limitations; this report does not claim that every horizon is now eligible.

All times below are UTC on October 12 unless stated otherwise (local Israel time was UTC+3). Inspection used read-only SQLite connections, the checkpoint-bound CSV, retained raw acquisition evidence, and the unchanged HGB3 expanded v2 artifact. No upstream requests, operational replay, state reset, or live orders were made.

## Findings ranked by impact

1. **Confirmed configuration defect, fixed:** runner and shadow executor had been manually changed to 3,000 ms, while `VNextShadowRunner.__init__` still constructed `VNextStrategy()` with its standalone `StrategyConfig.max_reference_age_ms=2000`. Ten recent decisions passed provenance, runner execution freshness and inference, then returned `stale_reference` from `VNextStrategy.evaluate`. Their non-null execution-market probabilities distinguish this path from the runner's earlier freshness rejection. The runner now explicitly supplies its reference allowance to both strategy and executor. The standalone strategy default remains unchanged; production v1.1 is untouched.
2. **Missing acquired observations, legitimate horizon rejection:** all 29 `stale_horizon` decisions in the 84-decision investigation window have **zero retained acquisition records and zero causally available CSV snapshots in target minus 10 seconds through target** for their market. No eligible earlier snapshot was overlooked. Of those 29, 22 are at horizons 60/30. This is an acquisition coverage problem, not an effect of the reference allowance or a demonstrated selection regression. The exact collector skip reason is unavailable because operational collector logs were not retained. Incomplete books are one possible cause, not a proven cause for these intervals. Do not replace missing observations with late data.
3. **Execution latency, legitimate safety rejection:** five later decisions passed source verification but exceeded 500 ms at the post-claim/post-model runner check. The median YES age was already 437 ms at verification. This leaves little budget for claim durability and inference. The final wall-clock check is necessary. Its precise historical timestamp was not persisted; new logs record it. Two later provenance failures would pass at their actual first receipt under current limits, showing some avoidable intake-to-verification delay, but this does not prove they would also pass after claim/model processing.
4. **Genuine source limitations remain:** later prediction reference, consumed anchor, execution reference, and book staleness occur independently. Two later decisions lack a post-target execution observation altogether. A 3,000 ms reference allowance cannot correct these book/coverage failures. Retained reference event timestamps typically advance each second, but delivery/cache age is often around two seconds. The cadence is not fundamentally incompatible with 3,000 ms: actual verified decisions exist. It does not guarantee freshness at either prediction or execution deadlines.
5. **Misleading monitoring, fixed:** the dashboard reason text hard-coded a 2,000 ms runner limit. It now describes the actual gate without assigning today's limit to historical decisions. Runtime status now records paths and effective limits/polling; successful source provenance also records limits. Collector startup logs record acquisition settings. Strategy calls and post-inference execution ages are now explicit log events.

## Journal evidence and rates

Full journal: 324 decisions, maximum ID 337811. Investigation window: targets 20:31 through 21:39:30, 84 decisions. The earlier claimed 50/50 rate cannot be reconstructed exactly without its intended time window. The previous isolated successful validation remains documented in `PAPER_PIPELINE_RECOVERY_REPORT.md`; it is not mixed into operational counts here.

These comparison windows deliberately exclude the uncertain restart/transition interval 21:03–21:10. Earlier diagnostics explicitly record 2,000 ms; later evidence establishes 3,000 ms. They are observed cohorts, not a controlled experiment or exact edit timestamps.

| Terminal reason | Earlier 20:30–21:03, n=38 | Later 21:10–21:40, n=36 |
|---|---:|---:|
| Unverified provenance | 23 (60.5%) | 8 (22.2%) |
| Stale horizon | 9 (23.7%) | 11 (30.6%) |
| Strategy reference mismatch | 0 | 10 (27.8%) |
| Post-verification stale books | 0 | 5 (13.9%) |
| Probability gap | 3 (7.9%) | 1 (2.8%) |
| Price ceiling | 1 (2.6%) | 1 (2.8%) |
| Expired market | 1 (2.6%) | 0 |
| Missing reference anchor | 1 (2.6%) | 0 |
| Fills / execution reservations | 0 | 0 |

Strategy was actually called for **4/38 (10.5%) earlier and 12/36 (33.3%) later**, including its freshness abstentions. Later decisions 337782 (21:16) and 337788 (21:21) reached economic checks and returned probability gap and price ceiling respectively. Thus the claim of no subsequent strategy evaluations is contradicted by the journal. Ten of twelve later strategy calls were stopped by the inconsistent reference check. Source verification passed in 17/36 later opportunities, or 17/25 (68%) of attempts with verification records.

Later individual verification failures, denominator 25 verified/attempted source records (overlap allowed): prediction reference 1/25, consumed historical anchor 1/25, execution reference 1/25, YES book 4/25, NO book 1/25, missing execution evidence 2/25, fee failures 0/25, identity/binding failures 0/25. Missing/late prediction and missing anchor terminal outcomes are zero in this later cohort. All remaining book/reference failures are freshness or missing-execution failures, not unexplained evidence-ID mismatches. Empty detailed diagnostics for missing execution are accompanied by the explicit `missing_execution_evidence` reason.

All 84 decisions by horizon:

| Horizon | Stale horizon | Provenance | Strategy stale reference | Stale books | Economic abstention | Other |
|---|---:|---:|---:|---:|---:|---:|
| 240 | 0 | 8 | 1 | 1 | 3 | 1 missing anchor |
| 180 | 1 | 7 | 2 | 2 | 2 | 0 |
| 120 | 3 | 5 | 3 | 2 | 1 | 0 |
| 90 | 3 | 8 | 3 | 0 | 0 | 0 |
| 60 | 9 | 4 | 1 | 0 | 0 | 0 |
| 30 | 13 | 0 | 0 | 0 | 0 | 1 expired |

## Timing reconstruction

`select_market_horizons` selects the latest observation actually received by the target, with a maximum observation lag of 10 seconds. The orchestrator first finalizes at target plus 2 seconds. **Stale horizon refers to the age of the available prediction observation, not a deadline missed because processing happened two seconds after target.** The paper driver can wait for execution evidence until target plus 3 seconds; this never changes the selected prediction or authorizes finalized replay.

Representative retained records:

| Decision | Expiry | Target | Latest causal observation / receipt | Processing | Explanation |
|---|---|---|---|---|---|
| 337733 | 20:35:00 | 20:34:30 | 20:34:11.524669 / 11.819434 | 20:34:32.056138 | 18.475 s prediction gap; no raw acquisition in final 10 s |
| 337744 | 20:45:00 | 20:44:00 | 20:43:30.952969 / 31.262238 | 20:44:02.038479 | 29.047 s gap; not late ingestion |
| 337771 | 21:10:00 | 21:07:00 | 21:06:25.800261 / 25.995464 | 21:07:02.050110 | 34.200 s gap, even at horizon 180 |
| 337784 | 21:20:00 | 21:18:00 | 21:17:59.452876 / 59.823495 | 21:18:02 (see JSON for precision) | Selected correctly; upstream prediction reference was 21:17:56, 4,000 ms old at target |
| 337797 | 21:30:00 | 21:28:30 | 21:28:28.664989 / 29.034407 | 21:28:32.231299 | Prediction valid, no post-target execution observation; final check 21:28:33.010214 |

Decision 337778 illustrates latency: prediction observed 21:12:59.356135, received 59.529930, target 21:13:00. Execution observed 21:13:02.549294, evidence captured 02.549674, received 02.796939. Verification/claim dispatch at 02.861934 saw YES timestamp 02.427000, age 434.934 ms, and NO 02.509000, age 352.934 ms. All source flags passed; the subsequent runner check returned `stale_market_books`. At least 65.066 ms of additional elapsed time would exhaust the YES budget. The actual post-model timestamp and separate claim/model durations are unavailable historically, not reconstructed as facts.

For every selected prediction in the 84-decision cohort, reconstruction selected the same latest causal snapshot as the journal. No missed causal alternative was found. The missing-anchor case is retained separately in the detailed evidence, and fails before provenance because inference needs that exact anchor.

## Delay distributions

Later cohort: 1,731 acquired/ingested rows; execution distributions use 23 decisions with an execution snapshot. Milliseconds, linear-interpolated percentiles.

| Measurement | Median | p90 | p99 | Maximum |
|---|---:|---:|---:|---:|
| Observation → first receipt | 260.1 | 420.5 | 545.4 | 1,356.8 |
| Reference age at observation | 2,079.4 | 2,651.3 | 3,216.1 | 4,612.0 |
| YES age at observation | 114.4 | 137.2 | 426.6 | 1,518.8 |
| NO age at observation | 38.1 | 53.9 | 321.1 | 1,518.8 |
| Target → initial journal processing | 2,243.8 | 2,441.2 | 2,625.5 | 2,636.5 |
| Execution observation → verification | 317.8 | 394.8 | 577.5 | 604.7 |
| Execution receipt → verification | 93.5 | 130.2 | 141.9 | 142.7 |
| Execution reference age at verification | 2,288.2 | 2,774.9 | 3,010.1 | 3,051.9 |
| Execution YES age at verification | 436.7 | 559.0 | 938.5 | 1,005.4 |
| Execution NO age at verification | 351.7 | 442.0 | 599.4 | 628.3 |

Later acquisition freshness failures: reference 43/1,731 (2.48%), YES 14/1,731 (0.81%), NO 9/1,731 (0.52%); zero future-dated rows. Earlier YES/NO median ages were -325/-405 ms and many rows were future-dated. Clock correction is consistent with this change and removes falsely favorable signed age; no artificial offset was introduced. Earlier receipt p99 was 20.05 seconds, maximum 58.13 seconds, consistent with a processing interruption; exact process restart times are unavailable. The later distribution improved substantially.

Across the full investigation window, acquisition requests/build time median was 154 ms, p90 172 ms, p99 216 ms. Same-market observation spacing median was 413 ms, p90 768 ms, p99 1,325 ms. The collector's configured pause is only one part of this period: sequential books, evidence durability and CSV publication contribute. Successful rapid cycles rule out a one-second pause throughout this run, but do not independently establish the exact CLI flag. The collector's reference refresh remains a local cache reread after books, preserving price, timestamp and raw evidence.

Independent CSV publication completion timestamps and per-stage claim/inference timing were not retained for these operational decisions. Evidence `captured` is before evidence commit/publication; it is not a publication timestamp. Receipt is first runtime availability, not upstream event time. Journal `claimed_at` and `completed_at` reuse dispatch time and are not independent commit timestamps. These limitations prohibit asserting exact network/SQLite scheduling contributions. The new logs make the final execution check observable.

Two later provenance rejects, 337806 and 337807, pass reconstructed source verification at their *actual recorded first receipt*. No source timestamps or receipt times were changed. Reducing subsequent delay might recover them, but they are not live success demonstrations. Reference failures at prediction/anchor observation cannot be repaired by processing execution faster.

## Repair and safety

Changed production files:

- `src/polybtc/shadow/runner_vnext.py`: constructor passes runtime reference allowance to strategy and executor; `evaluate` logs actual post-inference ages and strategy outcome.
- `src/polybtc/shadow/source_verification_vnext.py`: `SourceVerificationResult.provenance` records effective reference/book limits even on success.
- `src/polybtc/shadow/service_runtime_vnext.py`: optional configuration metadata and polling interval in status.
- `scripts/operations/run_vnext_shadow.py`: `build_runtime` provides resolved paths, limits, grace and execution wait to status.
- `scripts/operations/collect_vnext_local.py`: startup log records feed, paths and pause; no credentials logged.
- `src/polybtc/shadow/stream_driver_vnext.py`: obsolete 2,000 ms comment corrected only.
- `dashboard/backend/app/services.py`: historical reason explanation corrected.

Tests changed: runner and paper-mode regression coverage; verifier and executor stale fixtures now use 3,001 ms (3,000 is allowed); paper handoff fixture remains truly stale at 3,001 ms. Tests exercise the actual 3,000 boundary and reject beyond it rather than retaining obsolete 2,000 expectations.

No selector, feed interpretation, acquisition cadence, model, EV formula, entry thresholds, sizing, fee behavior, risk controls or live authorization changed. Provenance and causal cutoffs remain enforced. Books remain 500 ms, future times remain invalid, historical anchor choice remains the same, and the prospective runner still checks real time after inference. The temporary reference change was already authorized and applied in runner/executor; this repair carries it consistently through the final strategy gate.

## Retained real-input validation

All ten recorded strategy `stale_reference` decisions were reconstructed from the checkpoint-bound CSV, durable first receipts and exact raw acquisition records, then evaluated without access to any ledger or decision-journal mutation API. The actual frozen HGB3 model reproduced every recorded probability to 1e-12. Verification and cached fee descriptors passed for every pair. No source field or timestamp was altered.

At the **recorded source-verification deadline**, the old strategy default reproduced all ten stale-reference results. The corrected configuration produced nine `probability_gap_too_large` and one `price_ceiling_exceeded` results. Example 337776 at 21:11:03.781277: reference age 2,781.277 ms, YES 369.277 ms, NO 281.277 ms; model P(YES) 0.7005339527112011, market 0.625; result probability gap. Decision 337791 gives the price-ceiling result.

This is historical functional evaluation, not automatic replay into the operational journal. It does not reconstruct the unrecorded post-model wall-clock timestamp. The original journal independently proves all ten passed the real runner's final freshness gate before entering strategy, so the hidden strategy limit is the confirmed cause. Subsequent live observation is still required to verify the repaired running process. No actual trade is required.

Operational state remains 324 decisions (max 337811), 11,073 receipts reconstructed from CSV, zero duplicate market/observation timestamps, zero out-of-order observations, zero ledger entries. Checkpoint equals CSV length 35,565,749 bytes; complete CSV SHA256 matches the acknowledged prefix. Model SHA256 remains `42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`.

Machine-readable evidence: `PAPER_EVALUATION_REGRESSION_DETAIL.json` holds recorded-cohort counts, raw-gap checks, replay outcomes, later timing and preservation checks. `PAPER_EVALUATION_REGRESSION_EVIDENCE.json` holds all 84 reconstructed traces and horizon breakdowns. In the latter, `persisted_diagnostics` are historical facts; `diagnostics` and pass-at-receipt calculations are recomputed under current 3,000 ms configuration, so earlier 2,000 ms flags legitimately differ. The optional acquisition-floor counterfactual is not operational proof and is not used to claim success.

## Restart and capture

At inspection, no collector or runner process existed. The heartbeat still said running but was dated 21:40:03 on October 12; it is stale, not evidence of a currently healthy bot. Therefore old CLI intervals cannot be retrieved. Defaults remain collector 1 s and runtime 0.25 s; documented commands explicitly use 0.1 s and 0.05 s. No cadence defaults were changed. Lowering a pause may reduce waiting but cannot generate missing books, repair stale upstream events, or avoid disk/HTTP work. More aggressive acquisition can add request pressure; it is not recommended without measurements.

From `H:\PolyBTCv2`, use the existing `docs/PAPER_TRADING.md` commands with **the same CSV and state directory**, repeated below. If processes have since been started, stop their own terminals with Ctrl+C before restarting; do not start a second writer.

Terminal 1:

```powershell
.\.venv-execution\Scripts\python.exe scripts/collect_vnext_local.py --csv data/live/vnext_market_snapshots.csv --evidence-db data/live/paper_acquisition.sqlite3 --fee-cache data/live/paper_fees.sqlite3 --interval 0.1
```

Terminal 2:

```powershell
.\.venv-execution\Scripts\python.exe scripts/run_vnext_shadow.py --mode paper_execution --enable-paper-fills --csv data/live/vnext_market_snapshots.csv --evidence-db data/live/paper_acquisition.sqlite3 --fee-cache data/live/paper_fees.sqlite3 --state-dir data/paper/vnext_verified --model data/models/main/hgb3_expanded_v2.joblib --poll-interval 0.05
```

To preserve decisive logs, append `2>&1 | Tee-Object -FilePath data/live/collector-regression.log -Append` to terminal 1 and `2>&1 | Tee-Object -FilePath data/paper/vnext_verified/runtime-regression.log -Append` to terminal 2. These are diagnostic files only. Keep running through at least two complete markets after warmup. Inspect `acquisition_wait`, `execution_freshness`, and `strategy_evaluated`, along with journal provenance. New `runtime_status.json` exposes exact paths/polling/limits; new source provenance records 3000/500. Do not reset checkpoints to accelerate warmup or re-evaluate old decisions.

Outstanding evidence needs: collector skip logs around the next missing horizon; final execution ages for marginal quotes; live observation after this code restart; ongoing independent clock stability. The defect is repaired without pretending these operational uncertainties are solved.

## Validation results and stage status

Final pipeline/data/strategy regression command:

```powershell
.\.venv-execution\Scripts\python.exe -B -m pytest tests/shadow tests/data tests/trading/test_strategy_vnext.py -q --basetemp=.pytest_cache/evaluation-regression-release -p no:cacheprovider
```

Result: **298 passed in 164.79 seconds**. This includes causal horizon selection, late receipts, earlier eligible snapshots, raw evidence binding, future-source rejection, 500 ms books, 3,000 ms reference boundaries, paper provenance/risk gates, bounded handoff and restart recovery. Initial failures exposed seven stale test assumptions from the manual limit change; their fixtures now test just beyond the authorized boundary. No production guard was weakened to satisfy tests.

Dashboard: **25 passed**, using `dashboard/.venv/Scripts/python.exe` from `dashboard/backend` with `tests/test_monitor.py` and a writable unique pytest base under the repository `.pytest_cache`. A pre-existing Starlette/httpx deprecation warning remains. The execution environment lacks FastAPI, so dashboard tests were run in the existing dashboard environment; no dependency installations were needed.

| Stage | Status | Evidence / limitation |
|---|---|---|
| Reference acquisition and timestamp binding | PASS, intermittent freshness limits | Retained raw evidence; unchanged cache refresh after books |
| Market metadata / YES-NO identity | PASS for investigated evidence | No identity verification failures |
| Book acquisition coverage | BLOCKED for missing intervals | Zero raw snapshots for 29 horizon windows; precise skip reasons unavailable |
| Evidence → CSV → first receipt/checkpoint | PASS | 11,073 receipted rows, no duplicates/out-of-order rows, matching prefix hash |
| Prediction selection and causal history | PASS with legitimate unavailable-history rejection | Same selected snapshot as reconstruction, exact consumed anchor verified |
| Execution source and fee verification | PASS when evidence qualifies | 17/25 later attempts pass; eight source/missing-execution rejects remain valid |
| Actual execution-time recheck | PASS, marginal latency | Five correct post-verification book-age rejections; new logs expose actual ages |
| HGB3 inference → strategy configuration | FIXED | Ten real-input replays reach economic checks with unchanged probabilities |
| Risk and paper execution | PASS in regression tests; no real fill claimed | Zero operational ledger entries; no live authorization enabled |
| Live operation after patch | UNVERIFIED | Processes were not running; use state-preserving restart commands above |
