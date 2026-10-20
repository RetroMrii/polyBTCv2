# Simplification stages S2–S4: implementation and validation

Date: 2026-10-13. Scope: prospective vNext paper operation. The production v1.1 runtime, research artifacts, model weights and economics are unchanged. This implements the stages proposed in `POLYBTC_SIMPLIFICATION_AUDIT.md`; it does not declare the audit's sustained live-operation acceptance windows complete.

## Result

S2 and S3 are available through the existing commands and storage layout. S4 is an explicit, copy-only migration and optional typed-input mode. Existing operational state was not switched, reset or rewritten. The consolidated path has two authoritative SQLite stores and two operating processes, excluding the optional dashboard.

Retained real observations reconstructed from the migrated input store passed source and fee verification and reached the unchanged strategy in **11 offline evaluations at their originally recorded deadlines**. Their model probabilities matched the original journal within 1e-12. Results: nine `probability_gap_too_large`, one `price_ceiling_exceeded`, and one `model_market_disagreement`. These are historical software-validation results, not new prospective decisions or evidence of current feed quality. No finalized decision was rerun in an operational journal.

Machine-readable evidence: [POLYBTC_SIMPLIFICATION_VALIDATION.json](POLYBTC_SIMPLIFICATION_VALIDATION.json).

## Implemented architecture

```text
Collector process
  reference feed + market/books + fee refresh
  background resolution requests -> bounded queue -> main acquisition writer
                    |
           input.sqlite3
  canonical snapshot + raw evidence, ordered publication, fees, verified outcomes
                    |
Paper process (no network)
  receipt + cursor transaction -> incremental causal history
  coordinator -> provenance / fees -> HGB3 -> strategy -> risk -> paper executor
  durable claim -> atomic outcome / ledger / context / journal completion
  offline outcome registration + settlement transaction
                    |
           paper.sqlite3
  receipts/cursor, claims/decisions, positions/events/context, resolutions, clock events
```

The existing driver, adapter and repository interfaces remain for historical callers. The operational coordinator owns scheduling and evaluation in one object and uses the existing domain checks. Compatibility code is retained deliberately; this is a reduction in runtime owners and durable copies, not a wholesale rewrite or a claim that every legacy class has disappeared.

## S2: clock safety and authoritative paper policy

`data/paper_policy_vnext.py` owns the operational reference/book limits, horizons, lag, finalization grace and execution wait. Runner, executor, verifier and runner-created strategy use 3,000 ms reference / 500 ms books. The independently usable research strategy retains its historical default; paper passes its explicit policy. Horizon selection accepts an explicit lag while its research default is unchanged.

`shadow/clock_vnext.py` brackets genuine UTC samples with monotonic readings. Negative UTC movement and material disagreement between UTC elapsed time and monotonic elapsed time cause a durable evaluation pause. It records the actual samples, process session, stage, detection budget and high-water mark. The 50 ms discontinuity detection budget is **not** permission for negative source age or any extension of freshness. Every observed negative UTC delta is rejected. Monotonic time never replaces market, source or receipt UTC.

The runtime publishes `clock_paused` instead of treating a detected clock adjustment as an ordinary collector failure. No ingestion/evaluation resumes until the current incident is explicitly acknowledged, actual UTC reaches its saved high-water mark, at least two monotonic seconds of stability are observed, and the next full five-minute market begins. History used after recovery must have observation, receipt and market start at or after that recovery boundary. Old receipts remain original; terminal decisions remain terminal. Unresolved claims remain unresolved and are not retried automatically.

Clock events detected inside a consolidated outcome transaction are flushed after that transaction rolls back. The durable PROCESSING claim already exists. A crash in this narrow interval leaves the claim for explicit recovery; it does not grant a second evaluation attempt. Failure to persist a clock incident remains fatal. A restart below the durable receipt/decision watermark also pauses.

Clock health is not absolute NTP accuracy. An operator must independently verify Windows time before acknowledgement. No NTP requests, synthetic offsets or timestamp clamping were introduced.

## S3: fewer transformations and clearer ownership

- Canonical snapshot codec, raw-market value parsing, verified-source value type and causal anchor selection moved to neutral modules. Old public imports remain available.
- Acquisition evidence no longer imports a collector command or the service to parse or serialize data.
- The collector can pass numeric values directly through the converter; optional CSV exports produce the same canonical evidence binding.
- Runtime uses `VNextEvaluationCoordinator`, preserving the tested scheduling/claim/reconciliation algorithms.
- Snapshot history loads once, then updates incrementally. Pending markets retain their causal rows. The typed path rebuilds from immutable input plus original first receipts instead of storing a third normalized snapshot copy.
- Model features are constructed once for the prediction path. Distinct checks at prediction, verification and final execution remain because their deadlines differ.
- Identical runtime heartbeat states publish at most once per second using monotonic elapsed time. State transitions and failures publish immediately. A durable-status failure still stops the process.

## S4: optional consolidated ownership

`shadow/paper_store_vnext.py` gives repositories a single thread-owned SQLite connection. Component leases translate existing nested transactions into savepoints and preserve independent schema versions. FULL durability, WAL, foreign keys, conflict rules and immutable history remain enforced.

The claim commits before the one permitted evaluation. The outcome transaction covers reservation, hypothetical fill/reject, context, ledger events and journal completion. A failure rolls back the outcome while retaining PROCESSING. Actual execution time is still sampled after work/lock waits, and the executor still rejects expired quotes. Model loading and network requests are outside this transaction; synchronous inference remains inside the outcome scope.

`shadow/input_stream_vnext.py` consumes committed acquisition records in sequence, checks canonical hashes, preserves identity and writes first receipt plus cursor atomically. Restart history uses those receipts; capture time is never substituted for arrival time. On this transport, the compatibility status field `checkpoint_bytes` contains an input sequence; `operating_configuration.checkpoint_unit` explicitly identifies `input_sequence` versus `csv_bytes`.

`data/resolution_handoff_vnext.py` runs existing official resolution validation in a bounded background acquisition worker. Only acquisition main commits the resulting input records. `shadow/settlement_handoff_vnext.py` applies them without network access in the sole paper writer. The old resolution command refuses a consolidated layout, preventing accidental creation of a second trading ledger there. Resolution fetching remains subject to real network/provider availability; no outcome is inferred from price or model prediction.

CSV transport remains supported. In consolidated acquisition, CSV is an optional export and not the runner input. An export failure stops collection clearly; no uncommitted observation is advertised as available.

## Files and compatibility

| Responsibility | Main files |
|---|---|
| Shared policy/types/codec/parsing/features | `src/polybtc/data/{paper_policy,verified_sources,snapshot_codec,market_values,causal_features}_vnext.py` |
| Clock pause/recovery | `src/polybtc/shadow/clock_vnext.py`, `service_runtime_vnext.py`, `collector_service_vnext.py`, `scripts/operations/run_vnext_shadow.py` |
| Coordinator and history | `coordinator_vnext.py`, `collector_service_vnext.py`, `runner_vnext.py`, `source_verification_vnext.py` |
| Consolidated transactions | `paper_store_vnext.py`, `adapter_vnext.py`, `orchestrator_vnext.py`, `ledger_vnext.py`, `reconciler_vnext.py`, `collector_bridge_vnext.py`, `settlement_vnext.py` |
| Typed acquisition | `input_stream_vnext.py`, `acquisition_evidence.py`, `converter_vnext.py`, `data/fee_policy_cache_vnext.py`, `scripts/operations/collect_vnext_local.py` |
| Outcome handoff | `data/resolution_sync_vnext.py`, `data/resolution_handoff_vnext.py`, `shadow/settlement_handoff_vnext.py`, `scripts/operations/run_vnext_resolutions.py` |
| Migration and ownership | `shadow/migration_vnext.py`, `shadow/writer_lock_vnext.py`, `scripts/operations/migrate_vnext_paper.py`, root compatibility launcher |
| Read-only operations/UI | `src/polybtc/operations.py`, `dashboard/backend/app/data.py` |
| Focused validation | `tests/shadow/test_clock_vnext.py`, `test_simplification_vnext.py` and existing suites |

No new service, framework or dependency was added. Root command paths remain usable. Legacy separate-file constructors still reject accidental path overlap; sharing requires the explicit store owner.

## Real-state preservation and validation

Originals were opened read-only for migration and comparison. The successful validation copy is `data/validation/simplification_copy_20261013_2`; it is a test destination, **not the active paper state**. An interrupted first attempt remains incomplete and cannot start; restarting a migration uses a new destination and never overwrites originals.

| Preserved table | Rows |
|---|---:|
| decisions | 540 |
| receipts | 32,354 |
| acquisition | 32,671 |
| resolutions | 89 |
| fee_policies | 92 |
| fee_conflicts | 0 |
| entries / entry_events / entry_decision_context | 0 / 0 / 0 |

Logical SHA-256 digests of every listed table matched between originals and copy. All 32,354 CSV receipt identities/fingerprints mapped back to retained acquisition, preserving original arrival times. Cutover input sequence is 32,671. Unreceipted legacy acquisition remains retained but is not manufactured into past arrivals. Two clean runtime starts on the copy consumed zero new records, created zero decisions and preserved all table digests.

CSV size remains 50,259,204 bytes and SHA-256 `dcf89c08308fcfb8353a7ae82d7e1e8f28ee3bcb405bc66b63d05bc65b2c6720`.
Frozen HGB3 v2 SHA-256 remains `42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`.

The 11 historical evaluations include decisions 337776, 337779, 337790, 337791, 337792, 337795, 337796, 337801, 337808, 337809 and 337849. The validation report records each original deadline, source verification and strategy outcome. No operational decision or fill was inserted for these evaluations. A deliberately unusable ledger object prevents the pure evaluation harness from trading.

Tests additionally exercise synthetic acquisition through actual HGB3, source/fee verification, paper fill, settlement and restart; receipt/cursor rollback; outcome rollback retaining a claim; paused-clock restart; explicit recovery; incident persistence failure; and migration of filled/settled accounting. Fixture timestamps are test inputs, not evidence of present upstream eligibility.

## Test results

- Broad existing shadow/data/trading suite: **511 passed** (481.68 seconds).
- Follow-up clock, consolidation, acquisition, runtime, mode, resolution and horizon suite: **69 passed** (74.00 seconds).
- Final storage/clock/service regression checks after cursor and resolution-conflict hardening: **25 passed** (47.81 seconds). These runs overlap; counts are not additive.
- Dashboard suite, including read-only typed telemetry: **26 passed**; one existing Starlette/httpx deprecation warning.
- New-module static undefined/unused-symbol checks passed. Collector, runner and migration compatibility launchers passed CLI smoke checks; consolidated read-only status reported paper state observed and the model identity approved.
- Local UTC-sampling brackets over 2,000 pairs: median 0.0004 ms, p99 0.0005 ms, maximum 0.0064 ms. This measures call-pair uncertainty only, not absolute clock error or long-run Windows synchronization. The 50 ms discontinuity budget remains separate from strict source-age checks.

Reproduce the broad suite with `.\.venv-execution\Scripts\python.exe -B -m pytest tests/shadow tests/data tests/trading -q -p no:cacheprovider --basetemp <new-test-directory>`. Run dashboard tests from `dashboard/backend` with its own `../.venv/Scripts/python.exe`. Always select a new scratch directory; never use operational state for tests.

## Acceptance still required before declaring sustained reliability

Implementation and offline validation are complete only to the extent described above. The audit's 12/24-market prospective windows, real clock-slew behavior over those windows, and resolution-provider/network contention under live acquisition have not been demonstrated in this change. No collector or trading runtime was launched against live markets for this validation. Current upstream cadence can still produce legitimate stale references/books or missing horizons; nothing here changes those contracts.

Use the procedures in [PAPER_TRADING.md](PAPER_TRADING.md) for conservative clock recovery and explicit S4 cutover. Monitor at least 24 full markets and two clean operational restarts, retain all rejected opportunities in the denominator, and compare observed source age with internal delay. A strategy SKIP is valid; a provenance failure is not proof of successful evaluation. Do not automatically revert to the old state after the new state has made decisions: that requires reconciliation or a tested reverse migration to avoid a second entry.
