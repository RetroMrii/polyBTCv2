# Public repository readiness — October 20, 2026

The local Git repository is initialized and `origin` is configured as `https://github.com/RetroMrii/polyBTCv2.git`. The website now uses the matching GitHub link by default, with an optional `VITE_GITHUB_URL` override. A hosted website URL has not been supplied or verified.

The owner selected MIT licensing and frontend-only deployment. The root `LICENSE` covers original project code and authored documentation, papers and figures, subject to file-specific notices. Dependencies and upstream data retain their own terms. No hosted backend is needed for this release.

## Grouped scripts: intentional migration

The owner confirmed removal of the 100 root launchers because their implementations already live in `scripts/research/`, `scripts/modeling/` and `scripts/operations/`. They should not be restored as duplicates. The accidentally deleted [scripts README](../scripts/README.md) has been recreated for the grouped layout.

Tests now import grouped modules; the CLI subprocess test and active operations guides use grouped command paths. The expanded-dataset builder's dynamic helper lookup now points to `scripts/research/build_p4_extension_from_p12.py`. Test assertions and operational strategy/risk settings were not changed. Historical migration records are labelled as historical; old commands in archived evidence are not current launch instructions.

## Validation

- Frontend production build and lint passed with the configured GitHub backlink.
- Publication verification passed: five papers, 17 paper links, source hashes, exact demonstration predictions, disjoint partitions and weighted scores, 256,449 normalized rows, and unchanged protected artifact hashes.
- Grouped runtime and collector `--help` commands passed without starting their services.
- The grouped dataset helper loads and resolves the correct repository root.
- Full core run: **522 passed, 1 skipped, 1 failed** in 361.86 seconds. The remaining failure was a direct-file CLI invocation bypassing source-path setup. Commands now use `python -m scripts.operations...`; the five affected test modules then passed **83 tests** in 22.74 seconds, including the failing case. The entire suite was not repeated after this invocation-only correction.
- Updated documentation links, Python syntax parsing and `git diff --check` passed.

## Final public-file check

The final review used Git's non-ignored candidate file list, with no staging changes. It contained **383 files, approximately 22.96 MB**, with the 100 deleted launchers absent. The index is empty and `main` has no commits. `origin` matches the intended GitHub repository.

An isolated export under local `reports/final-public-export/` contained only those candidate files, without datasets, model artifacts, existing `node_modules` or generated frontend content. A fresh `npm ci`, production build and lint succeeded there. This is a clean-file build on Windows, not verification of Vercel's Linux deployment.

The comparison exposed environment-dependent Tailwind class detection. `src/style.css` now explicitly scans the frontend TypeScript/TSX and HTML files, following [Tailwind's source configuration](https://tailwindcss.com/docs/detecting-classes-in-source-files). After rebuilding both locations, CSS hashes and emitted asset names match. No published evidence or operational behavior was changed.

MIT metadata is consistent across the root license, Python package and frontend package/lock file. Current entry-point documentation links resolve to included files. A renewed targeted credential scan found only the existing synthetic test fixture. No ignored operational data, local environment files or old research folders appeared in the candidate list.

Installation reported an ESLint deprecation notice and an esbuild install-script approval warning in the local npm version; install, build and lint still completed successfully. Those warnings are recorded in local logs and are not represented as failures or silently resolved by dependency upgrades.

## Remaining before release

1. **Stage the reviewed release.** The final check found an empty index and no commits on `main`; all proposed project files are currently untracked. The stale staged launchers are no longer present. Stage the current reviewed files, inspect the staged diff, then make the intended initial commit. This review has not staged or committed anything.
2. **Review third-party redistribution terms.** MIT is now selected and the license file is present. Confirm the public evidence extracts may be redistributed under their source terms; the project's license does not relicense upstream material. See [dataset notes](../datasets/README.md).
3. **Approve the public file set.** The targeted credential scan found only a synthetic test fixture, not an actual credential. An older collector has a personal home-directory output default, and historical audit logs include local workspace paths. Review whether those should be public. The collector default and hashed evidence were preserved rather than silently changed. Recheck the exact final staged content for secrets and excluded local assets.
4. **Keep the commit aligned with the checked files.** The clean-export install/build/lint checks have passed. Review the staged snapshot against the current files before committing. Full historical reproduction and model-dependent tests require excluded local artifacts; do not describe them as self-contained in a public clone.
5. **Publish and verify approved destinations.** The GitHub remote is configured, but this review has not pushed or verified public visibility. If publishing the website too, select/confirm hosting, verify navigation/downloads at the deployed URL, then add that URL to the README. No public deployment is claimed.

## Scope of the prior content review

The initial reviewed index contained 481 paths. Existing tracked working files totalled approximately 22.94 MB; the largest evidence file was 8.96 MB. No bulk evidence removal was justified by size. Raw datasets, model binaries, environments, generated frontend content, runtime databases and old local folders are ignored. No indexed files matched the ignore rules at review time.

The targeted credential review examined working files and the original reachable commit's blobs for private-key headers, GitHub/AWS token formats and quoted credential assignments. It found an explicit synthetic fixture in `tests/trading/test_clob_sdk_contract.py`, whose network calls are blocked. This limited pattern review is not an exhaustive security guarantee and must be repeated on any newly added release content. Local detailed logs remain under ignored `reports/`.
