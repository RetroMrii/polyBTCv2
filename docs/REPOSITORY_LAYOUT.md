# Repository organization — 2026-10-12

> Historical migration record. On October 20 the owner intentionally removed the root compatibility launchers. Current callers use grouped paths, documented in [scripts/README.md](../scripts/README.md). The launcher-retention statements and test results below describe the October 12 snapshot.

This is a modest layout change within PolyBTC v2, not a new project or an
architecture rewrite. `src/polybtc`, package metadata, the virtual environment,
dashboard, notebooks, existing data/model locations and runtime defaults retain
their identities.

## Moves

- 93 script implementations moved into `scripts/operations`, `scripts/modeling`,
  and `scripts/research`. All 93 old command paths remain compatibility launchers.
- Tests moved into `tests/data`, `tests/modeling`, `tests/trading`, and
  `tests/shadow`. Filenames/functions are unchanged; imports and repository-root
  calculations were updated together.
- `tests/btc_1m_ohlc_collector.py` implementation moved unchanged to
  `scripts/operations/btc_1m_ohlc_collector.py`; the old command has a launcher.
- `tests/POLYBTC_V2_DEVELOPMENT_STAGES.md` moved into `docs/`; its test-file
  reference was updated to the grouped location.
- `tests/Polymarket-History-2026-09-17.csv` moved unchanged to
  `data/raw/reference/`. It is a historical raw export, not a pytest fixture.

Script bodies were checked against pre-move SHA-256 hashes after reversing only
the necessary `Path(__file__).resolve().parents[1]` to `parents[2]` root adjustment.
The moved standalone collector and CSV were checked byte-for-byte. Roadmap
content is preserved apart from its updated test-file reference.
Original datasets, model artifacts, reports and state DBs elsewhere were not moved.

The top-level launcher files are intentionally retained at the user's request.
They preserve command and import compatibility while keeping implementation edits
in the grouped directories. Direct grouped-file invocation is not required for
compatibility; use the original command or `python -m scripts.<group>.<name>`.

## Compatibility repairs found during validation

Baseline pytest collection was blocked by two stale `data.*` imports; those now
use the package's existing `polybtc.data.*` namespace. Re-enabling those tests
revealed that the legacy snapshot validator referenced removed shared book/fee
fields. It now validates the existing YES/NO timestamps, ages, tick sizes and
minimum quantities. Fees remain validated at their actual cache/execution
boundaries; SnapshotRecord does not contain a fee-rate field. Both sides have
targeted regression checks. No strategy, risk limit or execution gate was changed.

Three baseline settlement-test failures came from an outdated fake ledger and
an assertion expecting a Boolean instead of the current integer label contract.
The fake now supplies persisted settlement evidence through the service's existing
ledger interface, including restart recovery. Production settlement logic was
not changed, and the tests still assert idempotence and recovery.

## Validation

Verification covers full pytest discovery/execution, compilation, old and grouped
script imports with network access blocked, repository-root resolution, the
dynamic P4 helper loader, and safe CLI help commands through both invocation forms.
Collectors, training runs, historical experiments and real orders were not executed.

Results: **282 passed in 103.71 seconds** with
`.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_cache/reorg-final-01 --tb=short`.
Both `python -m pytest` and the virtual environment's `pytest.exe` collect all
282 tests. All 93 legacy and grouped script imports pass with network access
blocked; the dynamic research helper resolves the original repository root.
Legacy and grouped shadow-runtime/fee-refresh help expose identical options
(their usage prefixes correctly reflect the different invocation forms).
An absolute legacy launcher also runs from a different working directory.
Compilation passes, and the main v2 artifact SHA-256 remains
`42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`.

Main model remains `data/models/main/hgb3_expanded_v2.joblib`. Runtime kill switch,
source/fee gates, risk limits and 250 ms cadence remain unchanged. No Git commits,
deployment changes, dependency upgrades or scheduled tasks were created.
