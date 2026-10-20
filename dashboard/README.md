# PolyBTC research website and local monitor

The website presents five canonical papers, source-linked figures and an interactive historical prediction explorer. The existing eight-page local monitor remains available in development mode. Public builds need no backend and never access operational databases.

**Live website:** [polybtc-research.vercel.app](https://polybtc-research.vercel.app/). The commands below are for local development and preview.

## Research site

```powershell
Set-Location H:\PolyBTCv2\dashboard\frontend
npm ci
npm run dev
```

Open [the research website](http://127.0.0.1:3000/#/). For a static production preview use `npm run build` followed by `npm run preview`. Ports are strict; occupied ports are not terminated. `npm run content` compiles canonical `research/papers/` files, validates links and copies only allowlisted figures/evidence. Edit canonical papers, not `src/generated/` or `public/research/`.

## Existing local monitor

From the development website, choose System → Open local monitor. Original Overview, Live Market, Predictions, Decisions, Performance, Resolutions, System Health and Settings hash routes remain valid. Start the backend separately:

```powershell
Set-Location H:\PolyBTCv2\dashboard\backend
..\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

The existing `dashboard/scripts/start_dashboard.ps1` and setup script remain available. They do not start collectors or trading services. A local production build can explicitly set `VITE_ENABLE_LOCAL_MONITOR=true`; leave it unset for public deployment. Public builds give local-workflow guidance on old monitor routes instead of requesting operational APIs.

## Backend boundaries

FastAPI retains GET-only routes, loopback Host/CORS restrictions, typed responses and bounded read-only SQLite queries. Paths are startup configuration, never request parameters. There are no process-control, execution, training or database-write endpoints.

`dashboard/config.toml` optionally overrides telemetry, decisions, trades, resolutions and report paths. Relative paths resolve from the repository root. Defaults remain `data/live/vnext_market_snapshots.csv` and `data/paper/vnext_verified/`. Local `/api/settings` exposes source paths for diagnostics; do not expose this backend unchanged publicly. Public research uses frozen exports.

Prediction comparisons use `prediction_market_probability_yes`, not later execution quotes. Current paper reference/book limits are 3,000 / 500 ms; dashboard freshness indicators are separate diagnostics. No operational thresholds were changed. Portfolio metrics remain hypothetical and require audited fill/context/settlement evidence. Missing and stale sources remain explicit.

Original source contracts, query bounds and implementation evidence are preserved in [the archived monitor documentation](../docs/archive/dashboard-monitor-before-publications.md). Its dated descriptions do not establish present process liveness.

## Verification

```powershell
# dashboard/backend
..\.venv\Scripts\python.exe -B -m pytest -c pytest.ini --basetemp=../../reports/transformation/backend-check-unique
..\.venv\Scripts\python.exe -m ruff check app tests --no-cache
# dashboard/frontend
npm run typecheck
npm run lint
npm run build
```

The Vite runner config loader avoids the prior bundled-config cache issue. See [deployment and local development](../docs/DEPLOYMENT.md) for the live Vercel site, build instructions and local/public boundaries.
