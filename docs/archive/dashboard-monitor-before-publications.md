# PolyBTC v2 Trading Monitor

> Archived pre-transformation documentation. Statements about missing Git metadata describe that historical snapshot. A local Git repository now exists; see [current publication readiness](../PUBLICATION_READINESS.md).

Local, read-only monitoring of the current PolyBTC paper-execution pipeline. No trading module is imported, no model is run, and no bot process is started, stopped or reconfigured.

## Start on Windows

Dependencies are installed in `dashboard/.venv` and `dashboard/frontend/node_modules`. Python 3.11+ and Node 22.12+ are recommended. The implementation was verified with Python 3.14 and Node 26.

One command starts both dashboard services in hidden background windows, with logs inside `dashboard/logs`:

```powershell
Set-Location H:\PolyBTCv2
.\dashboard\scripts\start_dashboard.ps1
```

Open [the dashboard](http://localhost:3000). API documentation: [127.0.0.1:8001/api/docs](http://127.0.0.1:8001/api/docs). Both listeners bind exclusively to `127.0.0.1`. Occupied ports are not terminated or replaced.

For separate foreground terminals (recommended for easy Ctrl+C shutdown):

```powershell
# Terminal 1
Set-Location H:\PolyBTCv2
.\dashboard\scripts\start_dashboard.ps1 -Service backend
```

```powershell
# Terminal 2
Set-Location H:\PolyBTCv2
.\dashboard\scripts\start_dashboard.ps1 -Service frontend
```

To reproduce the separate dependency installation on a new checkout:

```powershell
Set-Location H:\PolyBTCv2
.\dashboard\scripts\setup.ps1
```

The launch scripts do not change machine execution policy. If organizational policy blocks scripts, use the equivalent foreground commands:

```powershell
# Backend
Set-Location H:\PolyBTCv2\dashboard\backend
..\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# Frontend, in a second terminal
Set-Location H:\PolyBTCv2\dashboard\frontend
npm.cmd run dev
```

## Pages

- **Overview:** realized P&L first, capital at risk, reserved capital, win rate, open positions, total fills and simulated entry fees; cumulative settlement P&L and recent positions; followed by market telemetry and decision context.
- **Live Market:** bid/ask/depth, normalized midpoint, condition ID, expiry, observed/source timestamps, signed collector ages and current source ages.
- **Predictions:** six scheduled horizons and same-cutoff HGB3 versus market comparison; historical search and filters.
- **Decisions:** searchable, sortable, paginated records; time, market, horizon, status, availability, probability, reason and outcome filters; expandable causal snapshot details.
- **Performance:** existing prospective report, model and market scores, paired comparisons, horizon charts, calibration, coverage, correlated-row/sample warnings and separate audited hypothetical portfolio metrics.
- **Resolutions:** registered YES/NO outcomes, evidence source and validation ID; verified and settled labels stay separate.
- **System Health:** runtime heartbeat state and freshness, source read availability, production rate and reason frequencies, missing telemetry. Heartbeat is not OS process inspection.
- **Settings:** refresh, page size, chart window, timezone, density, theme and motion preferences saved in browser local storage. Paths are startup-only configuration. Future trading controls are disabled and have no endpoints.

## Structure

```text
dashboard/
  backend/
    app/           # Configuration, typed schemas, bounded readers, services, GET API
    tests/         # Synthetic isolated SQLite/CSV tests
    requirements.txt
    requirements-lock.txt
    pytest.ini
    pyproject.toml
  frontend/
    src/           # React/TypeScript components, pages, polling, styles and contracts
    package.json
    package-lock.json
    vite.config.ts
  scripts/         # Setup, launch and read-only validation helpers
  audit/           # Initial inventory, integration and isolation evidence
  config.example.toml
  README.md
```

## Data contracts established from the repository

| Source | Contract / interpretation |
|---|---|
| `data/live/vnext_market_snapshots.csv` | `observed_at`, `market_id`, `btc_price`, `strike`, `market_end_at`, YES/NO bid/ask/depth and source timestamps/ages. The collector writes complete single-line CSV records. |
| `data/paper/vnext_verified/decisions.sqlite3` | `decisions`: unique condition/horizon, target and processed timestamps, causal snapshot fields, status/reason, `model_probability_yes`, **`prediction_market_probability_yes`**, `market_probability_yes`, execution price. |
| `data/paper/vnext_verified/trades.sqlite3` | `entries`, `entry_decision_context`, `entry_events`. A recorded fill alone is not enough for audited portfolio metrics. |
| `data/paper/vnext_verified/resolutions.sqlite3` | `resolutions`: binary registered label, evidence ID/source, resolved timestamp and VERIFIED/SETTLED state. |
| `data/paper/vnext_verified/prediction_report.json` | Validated `vnext_prospective_prediction_report_v2` snapshot. Read directly; never regenerated by this dashboard. |

The reader matches `src/polybtc/data/dataset/features.py`: current market probability is YES midpoint / (YES midpoint + NO midpoint). Prediction comparisons use only the journal's prediction-time field, never the later execution-time `market_probability_yes`. The frozen HGB3 model is never loaded or changed.

Runner thresholds verified in `runner_vnext.py`: reference age 2,000 ms, book age 500 ms. Dashboard observation freshness is a separate 5-second diagnostic; journal recency 300 seconds and report/last-resolution recency 900 seconds are dashboard display thresholds, not trading gates. Source ages at observation and at current wall clock are shown separately. Future timestamps remain signed. Collector observations do not establish provenance or process liveness.

## Safety and query bounds

- Every database connection uses URI `mode=ro`, `PRAGMA query_only=ON`, an authorizer allowing only read operations, a 200 ms busy timeout and a 100 ms query work deadline. Connections close in `finally`. `immutable=1` is deliberately not used; committed WAL changes remain visible.
- No SQL, arbitrary source path, command, migration, write, model, execution or process-control endpoint exists. CORS and Host allowlists are local. No remote runtime requests, external fonts or analytics.
- Telemetry reads at most the latest 2 MiB and ignores a partial trailing record. Charts use actual observations, at most 1,800 points; available windows are explicitly labeled. A current market must contain wall-clock time in its expiry-minus-five-minutes interval. Otherwise the last observed market is labeled inactive/expired.
- Decision reads use the primary key, newest 10,000 records, cached 1.5 seconds. Search/sort/pagination totals cover that bounded window. Registry reads cover newest 2,000 inserts, cached 15 seconds. CSV cache: 1 second; portfolio: 15 seconds; report: 30 seconds. Historical predictions poll every 10 seconds, resolutions 15 seconds and reports 60 seconds. Live views default to 2 seconds.
- A failed source refresh retains last successful values with an error/missing state. Browser API failure retains data with a prominent stale warning and last-success time. Source freshness is never equated with API connectivity.
- Portfolio metrics require a matching journal fill, immutable context, event sequence and (for settlements) registered reconciled outcome plus consistent fee-inclusive P&L. Missing or mismatched evidence withholds aggregate financial metrics. All values are hypothetical.
- No account balance, real exposure, real P&L or real orders are available here. Prediction quality is separate from profitability.

## Configuration

Default paths now follow `data/paper/vnext_verified` and the retained `data/live/vnext_market_snapshots.csv`. An existing `config.toml` overrides defaults: update it if it still points to the old shadow run. Historical files are preserved. Restart only the dashboard backend after changing paths or backend code; refresh the browser after deploying the frontend.

Copy `dashboard/config.example.toml` to `dashboard/config.toml`, edit the five approved path keys and restart the dashboard backend. Relative paths resolve from the repository root. Paths never come from HTTP query/body values. No trading configuration is written. Browser settings apply only to presentation and dashboard polling.

## Validation

```powershell
Set-Location H:\PolyBTCv2\dashboard\backend
..\.venv\Scripts\python.exe -m pytest -c pytest.ini --basetemp=..\.cache\pytest-local
..\.venv\Scripts\python.exe -m ruff check app tests --no-cache

Set-Location H:\PolyBTCv2\dashboard\frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Tests use only synthetic fixtures under the dashboard-local test directory. No production state is used by tests. Integration checks are separately documented in `audit/validation.json`.

## Known data limitations

An available empty paper ledger reports zero realized P&L, exposure, reserves and fees. Win rate stays unavailable until audited settlements exist. Missing or inconsistent ledgers withhold financial metrics. Capital at risk includes pending reservations and fee-inclusive open cost; no account balance or unrealized mark-to-market P&L is inferred. The cumulative curve steps through audited settlements in UTC. Portfolio audit scope remains bounded to 2,000 entries and 10,000 decisions; metrics are withheld if complete evidence falls outside those bounds. The existing report has old prediction rows without prediction-time market probabilities and initially no resolved paired scores. Those gaps remain explicit. Reports may be stale even while live data is fresh. Only an external report job can update the source report; the dashboard does not run it.

The dashboard reads `runtime_status.json` next to the selected trading ledger (64 KiB maximum, one-second cache). Heartbeats older than five seconds or future-dated are not treated as current running status. Settlement-worker liveness remains unavailable; only the latest registered resolution time is shown. Historical search is intentionally bounded, not a full-history warehouse. Signed source ages are retained even when the collector's clocks/timestamps disagree.

There is no Git repository in the supplied workspace. Isolation is checked using the initial file inventory and static-file hashes. Live `data/` files continue changing under the existing bot, so whole-file hash equality cannot distinguish legitimate concurrent bot writes; read-only enforcement, isolated mutation tests and runtime SQL traces provide the dashboard's non-mutation evidence.

Implementation references: [Vite documentation](https://vite.dev/guide/), [FastAPI typed responses](https://fastapi.tiangolo.com/tutorial/response-model/), [Recharts](https://recharts.github.io/en-US/api/LineChart/).
