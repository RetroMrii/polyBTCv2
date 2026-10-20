# Validation baseline — 19 October 2026

This is a pre-transformation baseline. No application source, tests, strategy, thresholds, models or operational stores were edited. Commands run from `H:\PolyBTCv2` unless otherwise specified. Logs and synthetic test state belong to this audit; they are not publication data or operational fills.

| Check | Result | Log |
|---|---|---|
| Default core pytest discovery | Blocked: three collection errors, one skipped module | `core-tests.txt` |
| Core diagnostic excluding three broken modules | **499 passed, 3 failed, 1 skipped**, 419.16 s | `core-tests-partial.txt` |
| Dashboard backend initial attempt | 1 passed, 25 setup errors caused by denied temp-directory creation | `backend-tests.txt` |
| Dashboard backend retry | **26 passed**, 2 warnings, 22.64 s | `backend-tests-retry.txt` |
| Backend Ruff | **Pass** | `backend-lint.txt` |
| Frontend TypeScript | **Pass** | `frontend-typecheck.txt` |
| Frontend ESLint | **Pass** | `frontend-lint.txt` |
| Standard frontend production build | **Blocked by EPERM** writing `node_modules/.vite-temp` | `frontend-build.txt` |
| Alternate-loader isolated production build | **Pass**, 2,570 modules transformed, 12.27 s | `frontend-build-retry.txt` |
| Feature-audit self-test | **Pass**: timestamp units, causal selection, missing quotes, market denominator | Tool output; command below |
| Saved S5 scoring arithmetic | **Pass**: all five Brier/log-loss pairs agree within 1e-12 | `score-check.json` |
| Additional raw CSV | Full read-only scan completed; schema, counts, missingness, duplicates, time bounds and training overlap recorded | `workspace-evidence.json` |

The default collection failures are missing `scripts.collect_vnext_local`, `scripts/run_vnext_incremental_value.py`, and `scripts.run_vnext_resolutions`. Their grouped implementations exist. No test was altered or removed to make discovery pass. The diagnostic command excludes those modules only to measure the rest of the current baseline; it is not a passing full suite.

All three executed failures also concern missing legacy launchers: two tests import `run_vnext_shadow` and `refresh_vnext_fees`; the status-command test invokes absent `scripts/run_vnext_shadow.py`. The passing diagnostic run exercises model loading/inference, data/features, strategy/risk, execution/accounting and paper runtime tests that successfully collected. It does not prove the omitted modules or skipped SDK coverage pass. Restore launchers and rerun full discovery before claiming compatibility.

The five protected hashes (main artifact, full training CSV, frozen S5 inputs, S5 evidence and R1 evidence) match the inspection snapshot; see `preservation-check.json`. Current core and backend fixtures are confined to audit-owned temp directories. Some historical importer tests return without exercising absent input files; passing test counts are not a substitute for fixture availability.

## Exact commands

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=.pytest_cache/audit-20261019-core
.\.venv\Scripts\python.exe -B -m pytest -q --ignore=tests/shadow/test_collect_vnext_local.py --ignore=tests/shadow/test_vnext_incremental_value.py --ignore=tests/shadow/test_vnext_resolution_sync.py --basetemp=docs/audit-20261019/core-temp --tb=short
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_r1_features.py --self-test
.\.venv-execution\Scripts\python.exe -B docs/audit-20261019/inspect_workspace.py
.\.venv-execution\Scripts\python.exe -B docs/audit-20261019/check_saved_scores.py
```

From `dashboard/backend`:

```powershell
..\.venv\Scripts\python.exe -B -m pytest -c pytest.ini --basetemp=../.cache/audit-20261019
..\.venv\Scripts\python.exe -B -m pytest -c pytest.ini --basetemp=../../docs/audit-20261019/backend-temp
..\.venv\Scripts\python.exe -m ruff check app tests --no-cache
```

From `dashboard/frontend`:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
node node_modules/vite/bin/vite.js build --configLoader runner --outDir ../../docs/audit-20261019/frontend-dist
```

Use **new temporary/output paths** on subsequent runs. The alternate Vite loader avoided writing the denied bundled-config cache; the build did not replace the existing dashboard `dist`. It reports that the external output directory will not be emptied. No application configuration or permissions were changed.

Execution inspection environment: Python 3.14.5, NumPy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1, joblib 1.6.0, pytest 9.1.1; Node 26.3.0; installed Vite 6.4.4. These are local inspected versions, not a newly installed dependency set. Original environments and lock files remain unchanged.

Backend warnings concern TestClient dependency deprecation and an inaccessible existing pytest cache. The passing retry uses isolated synthetic SQLite/CSV fixtures. No dashboard server, collector, settlement job, operational replay, model training or live trading was started. Production build success does not establish browser behavior, public deployment or compatibility of every reproduction command.
