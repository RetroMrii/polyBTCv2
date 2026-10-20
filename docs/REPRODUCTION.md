# Reproducing the research presentation

There are three levels of reproduction. Keep them separate: building the website from retained publication content, recalculating publication evidence from local originals, and rerunning historical fitting/simulation. Only the first two were performed in the transformation. No new model was trained.

## Website from canonical content

Use Node 22.12+ and the committed frontend lock file:

```powershell
Set-Location dashboard/frontend
npm ci
npm run build
npm run preview
```

The build compiles `research/papers/*.md` through Markdown-It with raw HTML disabled, validates relative links, copies only allowlisted publication files, runs TypeScript and emits Vite assets. Papers render without a backend. Generated frontend content is disposable; edit the canonical papers, not generated copies. Relative asset paths support static hosting under a repository subpath. Hash navigation requires no server rewrites.

## Evidence and figures from local research files

The existing execution environment supplies the established research packages. Plotting dependencies are isolated from it:

```powershell
.\.venv-execution\Scripts\python.exe -m pip install --target .publication-deps -r requirements-publications.lock
.\.venv-execution\Scripts\python.exe -B scripts/research/build_publications.py
.\.venv-execution\Scripts\python.exe -B scripts/research/verify_publications.py
```

The builder reads fixed research JSON/CSV artifacts, not operational databases. It recalculates later Brier/log loss with equal total market weight, checks hypothetical trade arithmetic and basket sums, generates SVG/PNG figures and exports an aliased 159-observation demonstration. It records versions and source hashes in `research/reproduction.json` and source extracts. Nonfinite historical model metadata is represented as JSON null in extracts; originals remain unchanged.

The cumulative raw-data derivative uses a separate command and must receive a fresh version path. See [dataset documentation](../datasets/README.md). Local raw/model files are not bundled with the public website. If originals are absent, report regeneration as unavailable rather than inventing replacements.

## Historical experiments

The chronological split, cohort membership, weighting and model lineage are part of a result. Earlier predecessor evaluations are not independent tests of the full refit. The calibration readout is already exposed; rerunning it does not restore independence.

`audit_s5.py`, historical training scripts and many walk-forward scripts write fixed output paths. Run them only in an isolated copied workspace preserving the original source tree and artifacts, or add a reviewed distinct output parameter first. Do not invoke `--capture` to replace a frozen cohort. The missing historical v3 dataset and label capture cannot be reconstructed exactly from the current evidence. Original bootstrap intervals are retained and labelled; this publication does not claim to regenerate them.

## Regression commands

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q --basetemp=reports/transformation/<new-test-directory>
Set-Location dashboard/backend
..\.venv\Scripts\python.exe -B -m pytest -c pytest.ini --basetemp=../../reports/transformation/<new-backend-directory>
Set-Location ../frontend
npm run typecheck
npm run lint
npm run build
```

Use a new temporary directory each time. Some legacy importer tests return early if a historical source is absent; test counts alone do not establish fixture completeness. SDK tests may be skipped when the SDK is unavailable. The public build does not enable local monitor routes unless explicitly built with `VITE_ENABLE_LOCAL_MONITOR=true`; normal development mode retains them.
