# Tests

The [research protocol](../docs/RESEARCH_PROTOCOL.md) defines evidential acceptance;
tests validate implementation and reproducibility, not market inefficiency or
profitability. The publication transformation restores legacy script entry points and validates the static research site separately; it does not rerun model training.

| Folder | Scope |
| --- | --- |
| `data/` | Importers, schema validation and causal feature/horizon construction |
| `modeling/` | Inference, metrics and chronological splits |
| `research/` | Offline research arithmetic, dependence-aware metrics and read-only access checks |
| `trading/` | Strategy, independent risk and execution calculations |
| `shadow/` | Collector intake, verification, runtime, ledger, settlement and reports |

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/shadow
.\.venv\Scripts\python.exe -m pytest -q tests/data/test_validation.py
```

Test filenames and test-function names are unchanged. Individual file selectors
now include their subsystem folder; default discovery remains `tests/`.
Test packages use explicit imports, so running a single module does not depend on
the order in which pytest happened to collect other modules.

Integration tests use existing local datasets and the main HGB3 v2 artifact.
For the preserved S5 calculation tests, see the [S5 reproduction procedure](../docs/RESEARCH_BASELINE_S5.md#reproduction).
Generated databases belong in pytest temporary directories, never in production
state directories. If the Windows default temp directory is inaccessible, supply
a fresh `--basetemp=.pytest_cache/<unique-name>`.

The collector implementation is in `scripts/operations/`; pytest does not collect
it. Root script launchers were removed intentionally; tests import grouped modules
directly. The misplaced roadmap is now in `docs/`, and the historical export formerly
beside tests is in `data/raw/reference/`, with its contents preserved.
