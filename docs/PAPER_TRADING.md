# Operating paper trading

> **Research transition — 2026-10-14:** This is the preserved legacy paper-operation procedure. The primary project now follows the [research question](RESEARCH_QUESTION.md) and [research roadmap](RESEARCH_ROADMAP.md). R0 does not authorize starting, stopping or modifying any process or changing these operating settings. Paper fills are integration evidence, not proof of predictive or economic edge.

Run commands from `H:\PolyBTCv2`. The existing `.venv` remains the research
environment. `.venv-execution` combines the selected v2 inference libraries and
the pinned Polymarket SDK without changing research dependencies.

## Installation

The execution environment has been created locally. To reproduce it on Windows
with Python 3.14:

```powershell
python -m venv .venv-execution
.\.venv-execution\Scripts\python.exe -m pip install -r requirements-execution.lock
.\.venv-execution\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-execution\Scripts\python.exe -m pip check
```

## Start acquisition

In terminal 1:

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.collect_vnext_local --csv data/live/vnext_market_snapshots.csv --evidence-db data/live/paper_acquisition.sqlite3 --fee-cache data/live/paper_fees.sqlite3 --interval 0.1
```

This uses the public RTDS feed with a 0.1-second pause after acquisition work,
as exercised in the prospective pipeline validation. The script default remains
1 second for compatibility. It retains
upstream reference/strike messages, Gamma metadata and both books before publishing
each CSV row. Market fee refresh is explicitly performed in acquisition, outside
the decision loop. The quote used during a fee refresh is discarded; failed
refresh retries are bounded by a 30-second delay. The existing fee cache preserves
conflict handling.

Wait for snapshots before starting the next command. Starting midway through a
market may require waiting for the next five-minute boundary and feature warmup.
The collector will not invent a missing opening reference.

Polymarket has documented migration from RTDS to authenticated PolyBolt. To use
the implemented optional transport, append `--reference-feed polybolt`. Supply
existing CLOB API credentials to the collector process through securely managed
environment variables `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET` and
`POLYMARKET_API_PASSPHRASE`. Do not put secrets in command history, source files or
reports. No private key or wallet connection is used for price acquisition.
The default public RTDS command needs none of these variables. Never enable
websocket wire logging on an authenticated connection.

## Start the paper runtime

In terminal 2:

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --mode paper_execution --enable-paper-fills --csv data/live/vnext_market_snapshots.csv --evidence-db data/live/paper_acquisition.sqlite3 --fee-cache data/live/paper_fees.sqlite3 --state-dir data/paper/vnext_verified --model data/models/main/hgb3_expanded_v2.joblib --poll-interval 0.05
```

`--enable-paper-fills` arms only the simulator. Omitting it keeps the paper kill
switch on. Live runtime mode remains unavailable. All source, strategy, fee,
freshness, depth and risk checks still apply; an enabled simulator need not trade.
The first CSV checkpoint starts at EOF, so wait for new observations and at least
30 seconds of causal feature history. Restart with the same paths to resume.

Paper state must be separate from research and acquisition inputs. Do not reset
state to evade an existing reservation, loss limit or one-entry-per-market rule.
Only one runtime may own a state directory.
The existing `vnext_verified` checkpoint is bound to
`data/live/vnext_market_snapshots.csv`; the commands above preserve that binding.
A state directory name does not imply it is fresh. If resuming a different state
directory, use its original CSV path for both acquisition and the runtime.

### If startup reports `Configured source path changed`

The state directory already has a checkpoint for another CSV. The error includes
both paths. Stop the collector with Ctrl+C before changing its command, then
restart it with the checkpoint's original CSV and the evidence/fee options above.
Run only one collector writing that CSV. Restart the runtime with the same original
CSV and existing state directory; keep the settlement worker on that state too.
Do not copy the newer CSV over the original, delete the checkpoint, or change the
state directory just to bypass this check. Keep both CSVs for historical reference.
The tailer verifies the original file identity, header and consumed bytes before
resuming. If those checks fail too, recovery needs a reviewed migration.

## Resolve and settle paper positions

After terminal 2 has initialized its databases, in terminal 3:

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_resolutions --state-dir data/paper/vnext_verified --settle-paper --interval 30
```

This uses the existing independent resolution providers and validation, then
applies validated outcomes to paper positions. Unresolved/conflicting outcomes do
not become losses or wins by assumption. Settlement is idempotent across restarts.
It does not redeem tokens, move funds or settle a live account.

## Inspect operation

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --mode paper_execution --state-dir data/paper/vnext_verified --fee-cache data/live/paper_fees.sqlite3 --status
```

`process` reports heartbeat health; `collector` and `sources` report freshness.
`paper` reports positions (including settled history), pending liabilities, open
cost, realized PnL, and the latest decision/rejection and verification provenance.
`model.identity_verified` checks the selected v2 hash; it is not production
approval. The top-level `status_scope=live_readiness`, `status=blocked` and
`live_ready=false` do **not** mean the paper process is broken.

### Diagnose source-verification rejections

New decisions retain `diagnostics_version=1` and a `diagnostics` array in their
`source_verification_json`. The same data appears under
`paper.latest_decision.verification` in the status command. Existing decisions
remain immutable; restart the runtime with the same command and paths to load
updated code for future decisions. No checkpoint reset or journal backfill is
needed.

Each failure identifies its `role` (`prediction`, `history`, or `execution`),
`snapshot_id`, `source`, and specific `reason`. Freshness failures also retain
`evidence_id`, `source_timestamp`, `evaluated_at_utc`, `age_ms`, and `limit_ms`.
`stale_source` means the source exceeded its unchanged limit;
`future_source_timestamp` means its computed age was negative. Prediction
reference ages use the prediction cutoff, historical reference ages use the consumed 30-second
anchor's observation time, and execution ages use evaluation time. A book fresh at
collection can therefore be stale when evaluated.

Binding failures have separate codes for missing evidence, untrusted producers,
snapshot/canonical mismatches, capture or ingestion deadlines, market/token
identity, raw reference/book mismatches, and malformed acquisition evidence.
`missing_evidence` means no evidence matched the requested canonical snapshot;
it does not mean the entire evidence database is empty. Diagnostics never include
raw upstream responses or arbitrary exception text. The legacy top-level
`unverified_input_provenance` and `unverified_*_evidence` reasons remain for
compatibility. No diagnostic overrides authorization or changes freshness limits.

At a one-second collection cadence, books can legitimately be older than the
500 ms threshold between updates. Such opportunities are rejected; do not increase
the threshold to force fills. Empty books, absent evidence, unavailable fees,
insufficient history, no strategy edge and exhausted risk capacity likewise mean
no fill. Consult the latest decision reason and acquisition/settlement logs.
Future-dated source timestamps are also rejected. Verify Windows time
synchronization before operation; a public validation sample had book timestamps
approximately 0.6–0.7 seconds ahead of the local clock. Correct host time rather
than relaxing freshness checks. No OS time settings are changed by the bot.

## Shutdown and recovery

Stop the paper runtime with Ctrl+C, then stop acquisition and the settlement
worker. Keep all databases and the CSV. On restart, run the same commands and
paths; the receipt/checkpoint, immutable decisions and ledger prevent duplicates.
Interrupted resolution settlement safely reconciles the registry with the ledger.
Unexpected processing or storage errors stop the runtime. Investigate the cause
before restarting; never delete claims or force a verified flag.

On Windows, heartbeat publication retries temporary access/sharing conflicts for
up to about 1.2 seconds, keeping the previous complete JSON visible until atomic
replacement succeeds. It never repeats the trading cycle for a heartbeat retry.
Persistent publication failures still stop processing. If `WinError 5`, `32` or
`33` persists on `runtime_status.json`, check directory write permissions and
programs holding the file open without delete sharing, then restart with the same
state and CSV. Do not delete the trading databases or disable monitoring.

For backup, stop all three processes first and copy the entire paper state plus
the acquisition CSV, evidence DB and fee DB, including any SQLite WAL/SHM sidecars.
Restore them together into the original layout, with original files retained until
the restored copy has been checked. Do not run both copies as the same deployment.
The tailer binds the CSV's file identity and consumed prefix. A copied/replaced
CSV can intentionally fail `SourceChanged`; do not edit its checkpoint to bypass
this. Recovery from restored copies needs a reviewed migration preserving receipt
and decision identities. Ordinary restart against the same files is supported.

## Simulation contract and limits

Each accepted paper decision records `execution_scope=paper`,
`fee_accounting_model=paper_cash_taker_full_precision_v1`, and
`strike_model=collector_nearest_boundary_twap_within_5s_v1`.

The fee contract deliberately preserves existing paper economics: cross the ask
plus one tick, require enough displayed depth for all five shares, retain five
shares, and charge `size * market_fee_rate * price * (1-price)` as a full-precision
simulated cash fee. The compatible, current market-specific fee descriptor is
still mandatory. This is an explicit simulation assumption, not a claim about
actual venue cash/share deductions, rounding, maker rebates or queue position.
The strike rule preserves the existing collector's nearest 60-second TWAP within
five seconds of the boundary; it is not certification of the official opening
strike. Resolution always uses independent venue evidence, never the model.

Limits remain five shares, $0.70 maximum execution price, $7 order cost, $25 open
exposure, $10 daily worst-case loss/capital-at-risk, one entry per market, 500 ms
books and 2 s reference freshness. Paper evidence is explicitly rejected by the
live adapter. No profitability claim follows from a successful test or paper run.

See [operations](OPERATIONS.md) for live-ledger inspection and
[final readiness](../POLYBTC_V2_FINAL_READINESS.md) for unresolved live risks.


## Pipeline recovery operation (2026-10-12)

The v2 consumed-anchor verifier uses the same `reference_anchor_30s` selection as
inference. It attests the prediction, the exact selected historical anchor and the
execution observation. An invalid selected anchor is rejected; verification does
not choose a different feature value to find a passing observation. Decisions
record `reference_anchor_snapshot_id` and the new verifier version. Older finalized
records retain their original provenance and are never replayed automatically.

The acquisition evidence store and snapshot history now use SQLite WAL with
`synchronous=FULL`. Idle read-only connections keep WAL files open during the
collector/runtime lifetime, avoiding a forced last-connection checkpoint on every
write. They hold no read transaction and do not prevent ordinary checkpoints;
normal shutdown closes them. Writer transactions remain separate and durable. Evidence still commits before CSV publication; receipts still commit before evaluation, and the replayable history cache commits
before CSV acknowledgement. A cache-write failure leaves the CSV unacknowledged;
restart recovers its original receipt without repeating a finalized decision. Keep SQLite WAL files with
their databases when making backups; use SQLite's backup API for a consistent
online backup. Do not delete WAL files to clear an error.

The runtime samples real processing time after durable intake and before source
verification. It checks freshness again after inference and at simulated execution.
A `stale_market_books` rejection after source verification can therefore indicate
that the quote expired during processing; it is not permission to raise a limit.

`--poll-interval` controls only runtime polling (default 0.25 seconds). A shorter
interval such as 0.05 seconds reduces idle delay but consumes more CPU and disk
bandwidth because the acknowledged CSV prefix is still integrity-checked. The
collector's `--interval` is its pause after acquisition/publication work, not a
promise of that total sample period. A 1-second pause cannot continuously satisfy
a 500 ms book budget. Cadence changes do not guarantee that any horizon is eligible.

Collector logs now distinguish reference/strike/history warmup, missing market,
failed book requests, incomplete/crossed books, invalid timestamps and interval
expiry using `acquisition_wait reason=...`. Successful publication logs record the
actual local publication completion time separately from observation time. This
measures a previously unavailable component of the delay without editing CSV or
source timestamps.

See [the complete pipeline recovery report](PAPER_PIPELINE_RECOVERY_REPORT.md) for
bounded operational evidence, validation paths and remaining limitations. Resume
the original paper runtime using its original CSV, evidence, fee and state paths;
there is no state reset or migration command. Stop existing writers normally before
restarting them to load these changes.


Paper handoff keeps a selected prediction immutable while waiting at most one
second beyond the existing two-second finalization grace for transient execution
freshness/availability failures. This covers the measured one-second TWAP update
cadence. Waiting occurs before the durable evaluation claim; no model/strategy
attempt is repeated. Missing/tampered prediction or anchor evidence and invalid
fees do not enter this wait. At the first cycle at/after the fixed deadline, a
remaining failure is finalized normally. Restart preserves the same target and
selected prediction, so it cannot extend the wait. Research callers retain the
legacy immediate-attempt default. The wait never depends on a favorable model
probability, price or EV and never retries a strategy rejection.

## Temporary reference allowance and evaluation diagnostics (2026-10-13)

The vNext runner currently allows **3,000 ms** reference age, as temporarily
requested for paper evaluation. The verifier imports that limit, and the runner
explicitly passes it to both its strategy and shadow executor. The standalone
strategy research default remains 2,000 ms. YES/NO books remain limited to 500 ms;
negative ages remain invalid at verification/execution. No strategy economics or
risk controls changed.

New runtime status records the resolved CSV/evidence/fee/state paths, polling
interval, freshness limits, grace and execution wait. Source provenance records
the effective limits even on successful verification. Collector startup logs
record its interval and paths. `execution_freshness` logs record the actual final
runner freshness deadline and ages; `strategy_evaluated` identifies calls to the
strategy, including abstentions. A stale heartbeat saying `running` does not
establish that the process is still alive.

For the diagnosis, real retained-input replay, test results and exact commands
that preserve the existing state, see
[the evaluation regression report](PAPER_EVALUATION_REGRESSION_REPORT.md).

## Clock pause and recovery (S2)

The runtime now distinguishes a clock discontinuity from a collector failure.
`runtime_status.json` reports `state: clock_paused` and
`clock_health.incident.event_id`, with the actual UTC/monotonic samples and stage.
It keeps monitoring alive, but pauses new evaluation. Source timestamps and
historical first receipts are never clamped or rewritten.

1. Stop the paper runtime with Ctrl+C. Leave its state intact.
2. Independently verify/correct Windows time (the existing `w32tm` procedure).
   Local monotonic stability alone cannot establish UTC accuracy.
3. Read the current incident ID:

   ```powershell
   (Get-Content data/paper/vnext_verified/runtime_status.json -Raw | ConvertFrom-Json).clock_health.incident
   ```

4. Restart the **same command and state directory** with
   `--confirm-clock-event <the-current-event-id>` appended. This is an explicit
   assertion that you verified the clock, not an automatic time correction.

The runtime waits until genuine UTC reaches the durable high-water mark, the
next full five-minute market, and at least two seconds of monotonic stability.
Only observations/receipts/history in the new market epoch can be used. Further
clock adjustments create a new incident. Pending claims are not automatically
retried or cleared. Investigate them separately; never reset the state directory
as clock recovery.

## Optional consolidated paper path (S4)

The original commands above remain valid. The new transport is opt-in and uses
`input.sqlite3` for acquisition/evidence/fees/outcomes and `state/paper.sqlite3`
for paper receipts/cursor/decisions/positions/settlement. The collector is still
the only process making market or resolution requests. The paper process stays
offline and live execution remains unavailable.

Do not use `data/validation/simplification_copy_20261013_2` for operation: it is
an isolated validation copy. Create a fresh operational migration at cutover.

1. Stop the collector. Let the current runner drain the CSV, then stop the
   runner and the old resolution worker. All original writers must be stopped.
   Preserve original files, including WAL contents. Do not copy only SQLite
   main files by hand or delete an undrained trailing CSV record.
2. Run the copy-only migration into a destination that does not yet exist:

   ```powershell
   .\.venv-execution\Scripts\python.exe -B -m scripts.operations.migrate_vnext_paper --state-dir data/paper/vnext_verified --evidence-db data/live/paper_acquisition.sqlite3 --fee-cache data/live/paper_fees.sqlite3 --destination data/paper_consolidated --writers-stopped
   ```

   The command requires the CSV to match its fully acknowledged prefix, checks
   every receipt fingerprint against retained acquisition, preserves all IDs and
   times, and validates SQLite integrity. It writes a completed layout manifest
   only on success. Source changes during migration invalidate the copy. A
   failed/interrupted destination remains incomplete; retain it for diagnosis
   and retry with a new destination. No original database is opened writable.
   The command holds the original runtime process lock while copying.
3. In terminal 1, start acquisition against the new input store:

   ```powershell
   .\.venv-execution\Scripts\python.exe -B -m scripts.operations.collect_vnext_local --input-db data/paper_consolidated/input.sqlite3 --paper-state data/paper_consolidated/state --interval 0.1
   ```

   This retains the already documented 0.1-second inter-cycle pause; it does not
   make network work take 0.1 seconds. The default remains 1 second if omitted.
   Append `--reference-feed polybolt` only when using the already supported feed
   and its existing credentials. Optional `--csv <new-export-path>` produces a
   compatibility export; the new runner does not consume that CSV. A background
   worker discovers resolutions; acquisition main commits its verified results.
4. In terminal 2, start the new paper owner:

   ```powershell
   .\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --mode paper_execution --enable-paper-fills --input-db data/paper_consolidated/input.sqlite3 --state-dir data/paper_consolidated/state --model data/models/main/hgb3_expanded_v2.joblib --poll-interval 0.05
   ```

   The input store supplies acquisition and fee evidence. Do not run the old
   separate resolution writer against this state: settlement is now applied by
   the runner. Omitting `--enable-paper-fills` leaves simulation disabled.
   The runner CLI default remains 0.25 seconds when the poll option is omitted.
5. Inspect read-only status with the same state directory:

   ```powershell
   .\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --mode paper_execution --state-dir data/paper_consolidated/state --status
   ```

   For the optional dashboard, set these startup-only paths in
   `dashboard/config.toml` and restart only the dashboard:

   ```toml
   [paths]
   telemetry = "data/paper_consolidated/input.sqlite3"
   decisions = "data/paper_consolidated/state/paper.sqlite3"
   trades = "data/paper_consolidated/state/paper.sqlite3"
   resolutions = "data/paper_consolidated/state/paper.sqlite3"
   report = "data/paper_consolidated/state/prediction_report.json"
   ```

   The dashboard reads typed observations without importing trading code or
   writing to the input store. Its model report remains optional. Consolidated
   `checkpoint_bytes` is a compatibility field containing an input sequence;
   `operating_configuration.checkpoint_unit` makes that distinction explicit.

Retain the original CSV and stores. Before the new layout makes decisions,
rollback can resume the original stopped workflow. After new decisions or
positions exist, **do not reopen the old state as the active trader** without
reconciling those writes: it could forget already-entered markets. There is no
automatic reverse migration. Validate at least 24 complete markets and two clean
restarts before declaring sustained reliability. External reference/book gaps
still produce valid safety rejections.

Implementation and retained-input evidence are in
[POLYBTC_SIMPLIFICATION_IMPLEMENTATION.md](POLYBTC_SIMPLIFICATION_IMPLEMENTATION.md).
