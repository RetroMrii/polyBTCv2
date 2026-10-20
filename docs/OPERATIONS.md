# Operations and recovery

> **R0 context — 2026-10-14:** These procedures remain available for legacy operational maintenance. The current [research roadmap](RESEARCH_ROADMAP.md) does not require operating or deploying a trading bot. R0 changes documentation only and makes no process/state changes; existing commands below are preserved.

Run from the repository root in the existing main environment:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --status
.\.venv\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --status --state-dir data/shadow/vnext_prospective
```

The equivalent grouped module command remains supported. Add `--fee-cache` with
the existing cache path and `--live-ledger` with the existing lifecycle database
path when those artifacts are available. These options only inspect state: they
do not construct SDK clients, start collection, refresh fees, claim orders,
initialize/migrate databases, or acquire the runtime's writer lock. `--csv` is
required for normal processing but unnecessary for status. Exit code zero means
the report was produced, not that live execution is ready.

## Reading the report

For the complete paper workflow, use [paper operation](PAPER_TRADING.md).
Top-level `status_scope=live_readiness` remains blocked; the separate `paper`
section reports simulated positions, pending liabilities, open cost, realized
PnL, process/source health and the latest decision verification.

| Field | Meaning |
| --- | --- |
| `process` | Latest runtime heartbeat and cycle counters; healthy requires a running heartbeat no older than five seconds. A stale heartbeat means unknown process health. |
| `process.heartbeat.kill_switch` | Runtime's recorded switch value; this runtime only supports collection, research and paper modes. |
| `collector` / `sources` | Latest cached snapshot and current reference/YES/NO timestamp ages. Limits are two seconds / 500 ms / 500 ms. Missing timestamps remain unknown; fresh data does not establish provenance. |
| `model` | `identity_verified` means the SHA256 matches the selected main v2 artifact. Legacy `approved` retains this same meaning for compatibility, with `approval_scope=artifact_identity_only`. `production_approved=false` is separate. No model deserialization is needed to inspect it. |
| `fees` | Per-market cache ages, conflict count and explicit unverified applicability. Cache age alone is not fee authorization. |
| `live.orders` | Durable lifecycle states and confirmed quantities, kept separate from shadow data. |
| `live.positions`, `open_cost_basis`, `realized_pnl` | Reconstructed inventory/cost, optional fresh-mark valuation and UTC realized results. Missing exact values remain null. |
| `live.pending_liabilities` | Unspent cash reservations, including unresolved submissions. |
| `live.issues`, `unknown_orders`, `failures` | Accounting discrepancies, unknown exchange outcomes and recent sanitized operational failures. |
| `live.last_operation` | Recorded adapter action and controls; `controls_current=false` means a database record is not a current process attestation. |
| `blockers`, `live_ready` | Readiness remains blocked. This segment does not implement or authorize activation. |

The five-second heartbeat threshold detects absent progress; it is not proof that
an OS process is alive. A source can be stale while its reader is healthy and
idle. The reader uses the most recent cached snapshot, not a claim that every
market is fresh. Existing dashboard views remain useful for shadow decisions and
collector monitoring; they are not presented as live-account reconciliation.

## Controlled shutdown

Use Ctrl+C in the existing runtime console or a handled SIGTERM. The current cycle
may finish its local transaction, then processing stops and the status file says
stopped. `--once` also records a final stop. An unexpected cycle error, changed
model artifact or failed heartbeat write stops further processing; the legacy
`stop_on_error=False` setting no longer permits continuing after such failures.

For an explicitly instantiated live adapter, call `close()`. It disables live
mutations, removes any in-memory dispatch permit, quarantines unresolved in-flight
orders, records shutdown, closes the SDK and releases process ownership. Repeated
close calls are harmless. Shutdown does not send cancellations or release pending
liabilities. SDK-close failure is sanitized and recorded while ownership is still
released. Hard process termination cannot write a final heartbeat: expect stale
health and perform restart recovery.

## Recovery

1. Inspect status and the existing logs. Preserve the SQLite databases and model
   artifact. Do not delete reservations, reset submission claims or relabel shadow
   fills as live fills.
2. After a runtime error, correct the source/storage/model cause, then restart the
   existing command with the same mode-bound state. It resumes existing CSV and
   journal checkpoints; it does not automatically reconcile exchange claims.
3. Adapter startup retains G/I restart quarantine. An unresolved submission cannot
   be resent, and risk evaluation rejects new claims while unknowns remain.
4. A failed submit/reconcile/cancel operation pauses live mutations for that adapter
   instance and quarantines in-flight claims. Account reads remain available only
   if previously authorized. Use authenticated order/trade/fee evidence to reconcile;
   an unknown exchange ID requires evidence-backed identity investigation first.
5. Successful reconciliation does not re-enable mutations. Any later activation
   requires explicit authorization, verified source/fee applicability and fresh
   account evidence matching the new ledger revision. Operational events themselves
   advance that revision. No activation or credentials are supplied by this runbook.

An unreadable or legacy live database is reported unavailable without migration.
Inspect it using the compatible lifecycle tooling and preserve its original state;
the status command intentionally cannot repair it. Disk/permission failures can
prevent a final status write: the process stops and the preceding heartbeat ages
out instead of being treated as current indefinitely.

## Explicit account binding for offline integration

The adapter defaults to EOA behavior for compatibility. Smart-wallet integration
must explicitly supply the funding account `wallet`, owner `signer`, and
`wallet_type` (`POLY_PROXY`, `GNOSIS_SAFE`, or `DEPOSIT_WALLET`). Supply that same
wallet type to `ClobCredentials`; bootstrap rejects a wallet that cannot be
derived from the owner under the pinned SDK configuration. The funding account,
not the owner's EOA, owns ledger inventory and cash liabilities.

This support does not provision or deploy a wallet, create credentials, verify
on-chain deployment, or accept session-key fallback. Existing credentials remain
explicit inputs and never belong in commands, reports or logs. Runtime live mode
is still unavailable; these interfaces are for separately authorized integration.
See the [audit remediation](../POLYBTC_V2_AUDIT_REMEDIATION.md) for remaining work.
