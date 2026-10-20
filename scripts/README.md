# Research and operational scripts

Scripts are grouped by purpose. Root-level duplicate launchers were intentionally removed; use the paths below. Run commands from the repository root so relative data paths resolve consistently.

| Directory | Purpose | Examples |
|---|---|---|
| [research/](research/) | Historical evaluations, dataset construction, publication evidence and figures | `build_publications.py`, `verify_publications.py`, `normalize_publication_data.py`, `audit_s5.py` |
| [modeling/](modeling/) | Model-training datasets, fitting, comparisons and candidate freezing | `build_hgb3_expanded_v2_dataset.py`, `train_hgb3_expanded_v2.py`, `freeze_expanded_model_candidates.py` |
| [operations/](operations/) | Collection, paper-engine execution, resolution synchronization and diagnostics | `collect_vnext_local.py`, `run_vnext_shadow.py`, `run_vnext_resolutions.py`, `run_vnext_incremental_value.py` |

## Publication reproduction

With the documented execution environment and local source artifacts installed:

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.research.build_publications
.\.venv-execution\Scripts\python.exe -B -m scripts.research.verify_publications
```

These commands recalculate retained evidence and render publication assets; they do not collect new market data or retrain the deployed model. See [reproduction prerequisites](../docs/REPRODUCTION.md) and [dataset availability](../datasets/README.md). A public checkout can build the website from curated sources without the excluded raw files, but cannot regenerate unavailable historical inputs.

## Operational commands

Use the grouped paths in [paper operation](../docs/PAPER_TRADING.md) and [operations](../docs/OPERATIONS.md). For command help:

```powershell
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.run_vnext_shadow --help
.\.venv-execution\Scripts\python.exe -B -m scripts.operations.collect_vnext_local --help
```

Collection and resolution commands can contact external services; runtime commands can write local state. They are not part of website building or publication checks. Historical research and training scripts may write fixed paths: reproduce them in an isolated workspace or use their explicit output options where supported. Preserve original datasets, models and frozen evidence.

## Imports and historical references

Import operational helpers as `from scripts.operations import run_vnext_resolutions`, for example. Earlier reports may cite old `scripts/<name>.py` paths; locate the matching implementation in the table above. Historical evidence documents remain dated records rather than current command guides. `scripts/__init__.py` uses the path setup in `scripts/_entrypoint.py` so module invocation can locate `src/polybtc` from the repository root. New callers should use grouped modules directly.
