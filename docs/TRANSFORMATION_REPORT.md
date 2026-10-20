# Research transformation report

Completed locally on October 19, 2026, following approval of the [audit and migration plan](RESEARCH_TRANSFORMATION_REVIEW.md). The approved website boundary is a public historical snapshot explorer plus the preserved local monitor. Git initialization was deferred during that work; the owner has since initialized the local repository. The configured remote is now `https://github.com/RetroMrii/polyBTCv2.git`. See the [current publication-readiness review](PUBLICATION_READINESS.md); the validation results below describe the October 19 snapshot, before the subsequent intentional migration to grouped script paths.

## Delivered publications and evidence

Five canonical engineering papers live in [research/papers](../research/papers), catalogued in [research/catalog.json](../research/catalog.json):

1. **From Market Snapshots to Causal Research Data** — provenance, timestamp semantics, coverage and eligibility.
2. **Machine Learning versus Market-Implied Bitcoin Probabilities** — historical model comparisons, lineage and matched baselines.
3. **Probability Calibration under Limited Independent Data** — calibration, chronological partitions, matched scoring and uncertainty.
4. **Execution Timing and Data Freshness in Five-Minute Markets** — decision funnel, latency and counterfactual eligibility.
5. **Expected Value, Costs and the Limits of Paper Trading** — controlled substitutions, simulated costs and limits of return claims.

Six reproducible figures have both SVG and PNG exports. Source extracts, parent artifact hashes, output hashes and claim-to-evidence mappings are in [research/claims.json](../research/claims.json). The [reproduction record](../research/reproduction.json) distinguishes recalculated results from retained historical findings.

The defensible conclusion remains that these experiments do not demonstrate an incremental predictive or after-cost trading edge. On the exposed later cohort, market Brier loss is 0.123156 versus 0.150580 for the raw frozen model, across 93 observations and 55 markets. The retained paired uncertainty interval crosses zero. Favorable hypothetical outcomes are not presented as realized profits.

## Additional dataset

The supplied cumulative file actually covers October 1–17, rather than only October 11–17: 256,449 snapshots across 4,616 markets. A separate versioned derivative resides at `data/research/publication_data_20261019_v1/`, with transformation manifest and source-record identities. All rows and original columns are retained; no outcomes or receipt times were synthesized. Missing or invalid quotes withhold normalized market probability on 56,398 rows.

The derivative is suitable for historical coverage and data-quality analysis, not independent model evaluation. It overlaps 2,851 training markets and all 172 markets in the retained calibration-study cohort. Missing official outcomes and receipt-time evidence prevent stronger claims. See [datasets](../datasets/README.md).

## Repository and software

The [README](../README.md) now leads with the research question, findings, papers and reproduction. Publications, figures, source extracts, dataset manifests and experiment documentation have explicit homes. Original README documents are archived in `docs/archive/`; historical datasets, reports, models and databases remain in place. Stable `src/polybtc` imports and grouped script locations are retained. One hundred root compatibility launchers were restored during the October 19 transformation, then intentionally removed by the owner on October 20. Active callers now use grouped modules, with source-path setup provided by `scripts/__init__.py` and `scripts/_entrypoint.py`. See [current script commands](../scripts/README.md).

The React/Vite website builds directly from canonical Markdown papers, with validated relative links and an allowlisted public export. It provides paper navigation, section anchors, tables, figures, source downloads, architecture documentation and an interactive historical forecast explorer. Filters recalculate matched, equal-market-weight scores; observation details expose the actual recorded forecasts. Light/dark and mobile layouts are supported.

The original eight-route local monitor remains available in development mode or an explicitly enabled local build. The default production site uses frozen public data and does not mount that monitor or connect to its APIs. The backend remains local and read-only; it must not be publicly exposed because some responses include local configuration paths. The background launcher now generates publication content before starting Vite, matching the foreground workflow.

## Verification

| Check | Result |
|---|---|
| Core regression suite | 523 passed, 1 skipped; 392.95 seconds |
| Dashboard backend suite | 26 passed; one existing Starlette/httpx deprecation warning |
| Frontend production build | Passed, including TypeScript and all five paper link checks |
| Frontend lint | Passed |
| Publication validation | Passed: five papers, 17 relative links, source/output hashes, exact demo predictions, disjoint partitions and weighted scores |
| Normalized data validation | All 256,449 source identities checked; probability calculations and withheld rows verified |
| Protected artifacts | Five audited artifact hashes unchanged, including raw input and frozen model |
| Browser checks | Paper reading and section navigation, figures, explorer filtering, inspection, pagination/empty states, light/dark and mobile layouts |
| Mobile overflow | Home, paper and explorer checked at 390px; explorer page width matches its client width after correction |
| Local monitor | Original eight-route shell renders; backend disconnected state verified |

Logs are retained under `reports/transformation/`. The final dependency audit returned zero known vulnerabilities after updating Markdown-It. One intermediate attempt encountered a registry socket error; the retry succeeded and its result is saved in `npm-audit.json`. The updated PowerShell launcher also passed syntax parsing.

Backend behavior is covered by isolated tests; a live end-to-end operational monitor session was not claimed or required. Existing collectors and paper-trading processes were not started, stopped or reset. No operational strategy/risk parameter or deployed model was changed. The temporary preview serves the production build on loopback port 4173.

## Reproduction limits and deployment

Recalculated work includes paired forecast Brier/log loss, hypothetical trade arithmetic and basket totals, the normalized dataset and publication figures. No model was retrained. Retained historical bootstrap intervals were not regenerated. The missing historical v3 dataset and older label capture prevent exact reproduction of some earlier experiments; current labels are not substituted silently. Some legacy tests have conditional fixture availability, so passing totals do not prove that every historical artifact exists.

The public site supports a static host; see [deployment instructions](DEPLOYMENT.md) and [reproduction instructions](REPRODUCTION.md). The local repository and GitHub remote are configured, and the site links to `https://github.com/RetroMrii/polyBTCv2`. The owner subsequently deployed the frontend to [polybtc-research.vercel.app](https://polybtc-research.vercel.app/). The live homepage and GitHub backlink were verified in a browser on October 20, 2026. The historical validation results above describe the transformation snapshot, not a complete post-deployment regression run.
