# PolyBTC research transformation — review package

> Historical audit, October 19, 2026. The plan was subsequently approved and implemented. The owner initialized Git afterward; references below to an absent repository describe the audit-time state. See [current publication readiness](PUBLICATION_READINESS.md).

Audit date: 19 October 2026. **Proposal for review; structural implementation has not begun.** This document separates current inspection from historical reported results. No collection, training, operational replay, deployment, Git initialization or source relocation was performed. The audit adds its own evidence, test logs and isolated build/test outputs under `docs/audit-20261019/`.

## Recommendation

Build a five-paper research collection around the existing evidence, with a publication-first React website and a supporting read-only engine demonstration. Keep `src/polybtc`, grouped scripts, model paths, raw data and operational stores in place. First repair the already-broken reproduction interfaces, then establish canonical paper content and versioned evidence manifests. The evidence supports a provisional negative result for the tested methods, not a claim that all machine learning must fail.

The review gate is explicitly required by the supplied assignment: “Stop for review before performing major structural changes.” Approval of this plan would authorize local implementation; external publication remains a separate approval.

## What exists and what is currently verifiable

| Area | Inspected implementation/evidence | Assessment |
|---|---|---|
| Data engineering | `src/polybtc/data/`, snapshot schema/importers, causal horizons/history features, source and outcome validation; raw, normalized and receipt-bound stores | Substantial implemented pipeline. Event timestamps and receipt evidence have different evidential strength. Historical imports cannot recover original availability. |
| Modeling | `src/polybtc/modeling/`, six modeling scripts, historical baseline/calibration/walk-forward/ablation scripts and saved predictions | HGB, logistic, random-forest and XGBoost comparisons exist. Chronological market grouping exists. Source/model-selection exposure must accompany each result. |
| Execution engine | `src/polybtc/shadow/`, strategy, execution, risk, position and operations modules; paper runbooks and engineering reports | Collection, inference, verification, durable decisions, paper fills and settlement are implemented. This audit does not launch them or establish current process liveness. |
| Dashboard | React 19 / TypeScript / Vite, Recharts, existing light/dark preferences; FastAPI typed GET endpoints and bounded SQLite readers | Real application, not a mockup. Eight hash-navigation pages currently prioritize paper P&L. No publication renderer exists. |
| History | Development-stage document, `ToOrganize/` engineering reports, `docs/` audits, `research-OoD/` notebooks and saved experimental outputs | Documentary history is available, but Git history is not present in this workspace. Notebooks are supporting historical analyses, not the canonical papers. |
| Reproduction | Existing scripts and frozen inputs, main artifact and training manifest | Core regression collection is already broken by missing top-level launchers. Some documented raw sources and research outputs are missing. Fixed-output scripts can overwrite original evidence if run unchanged. |

The file inventory records approximately **2.254 GB in `data/`**, excluding environments and frontend dependencies. The acquisition SQLite database alone is approximately 1.036 GB. The cumulative CSV is 166 MB and external minute history 394 MB. These are local research assets, not an appropriate default Git add set. See [inventory and hashes](audit-20261019/workspace-evidence.json).

### Git, compatibility and documentation defects

1. `git status` reports no Git repository; no root `.git` exists. A remote, tracked-file set, branch history and historical diffs therefore cannot be inspected here. Do not invent a GitHub URL or initialize a replacement history before deciding whether this is an exported copy of an existing repository.
2. `docs/REPOSITORY_LAYOUT.md` says 93 original command launchers remain. Only `scripts/__init__.py` and `_entrypoint.py` remain at the scripts root. Tests import missing `scripts.collect_vnext_local`, `scripts.run_vnext_resolutions` and load missing `scripts/run_vnext_incremental_value.py`. The expanded-dataset builder also dynamically loads missing `scripts/build_p4_extension_from_p12.py`. Restoring compatibility is a prerequisite, not a new restructuring regression.
3. README links to missing `scripts/README.md`, `research/`, and engineering reports now located in `ToOrganize/`. It says feature auditing has not begun, despite current feature-inventory/coverage/evidence reports. Public navigation needs replacement without editing historical reports to erase their original context.
4. `tests/research/test_s5_audit.py`, referenced by reproduction instructions, is absent. The historical six-test claim cannot be represented as a current test result.
5. `HGB3_V3_DATA_AUDIT.md` names the cumulative CSV under an older path and references absent `data/research/hgb3_v3_r1_20261017_v2/` outputs, including its frozen labels. Preserve the report as history; do not claim its expanded dataset or trained artifact is currently available.
6. Dashboard documentation says the runner uses a 2,000 ms reference limit; current runner wiring and later economics/regression reports specify 3,000 ms. The standalone strategy default is a separate contract. Correct documentation, not thresholds.
7. Root ignore patterns cover raw/normalized data but do not comprehensively exclude live/paper/shadow databases, external data, or model artifacts under `data/`. A release allowlist and secret/path review must precede any Git staging. No secrets were opened for this audit.
8. Original `POLYBTC_V2_HARNESS.md` and `POLYBTC_V2_DEVELOPMENT.md`, cited by later reports, are absent. Their descriptions cannot substitute for inspecting the originals. The current document index records 34 existing historical/research Markdown documents and their unresolved relative links; see `docs/audit-20261019/document-index.json`.
9. `tests/data/test_v1_decisions.py` returns successfully when its original raw input is absent. A green test count therefore does not prove that importer was exercised against the historical source. The publication reproduction checklist must distinguish unavailable fixtures from executed validation.

## Evidence ledger and limits

| Research evidence | Supported result | Classification and limits |
|---|---|---|
| Historical baselines and nonlinear comparisons (`p5`, `p6`, `p7` reports under `data/normalized/`) | Forecasting models and matched market controls were tested; available matched comparisons often favor market | Retrospective development. Different feature tracks lose different observations; never compare unpaired headline scores. |
| Market-anchored walk-forward (`p115_market_anchored_walk_forward_report.json`) | On 8,914 common rows, raw-market Brier 0.137056, market-only logistic 0.137282, market-plus-BTC 0.137513 | Historical 8-fold evaluation, now exposed; these are saved report scores, not newly fitted models or evidence of equivalence. |
| Feature/provider and model-family studies under `data/experiments/p13_model_improvement/` | Some historical feature additions improve development scores; provider substitution and later block results can reverse the ranking | Selectively curate the hypothesis, matched comparison and later failure. Do not promote the best historical slice or add overlapping row counts. |
| Expanded-model comparison under `data/experiments/model_expansion/vm_expansion_v2/` | HGB3/XGBoost and calibrators have retained evaluation predictions | Predecessor models fitted on earlier partitions; evaluation markets later entered the frozen full refit. Not independent tests of that refit. |
| [Calibration report](POLYBTC_S5_CALIBRATION_REPORT.md) and JSON | Later paired sample: 93 observations / 55 markets. Market Brier 0.123156 vs raw HGB3 0.150580. Raw-minus-market interval [-0.006809, 0.064703] includes zero | Exploratory chronological holdout; now exposed development evidence. Only 42 earlier calibration markets. Cannot establish universal market superiority. |
| [Decision funnel](POLYBTC_DECISION_FUNNEL_REPORT.md) | 300 decisions: 143 stop at data/provenance gates, 60 expire after verification, 97 reach strategy, zero economically qualify | Historical observed decisions. The 68 idealized timing recoveries also fail unchanged economics; they are not missed trades. |
| [Strategy comparison](POLYBTC_S5_STRATEGY_COMPARISON.md) | 43 later executable-stage observations / 36 markets; controlled probability substitutions yield zero entries under unchanged rules | Conditional simulation. Post-hoc 23-entry calibrated basket totals +$0.03634; 13-entry blend totals -$6.38145. Neither is operational profit. |
| [Feature coverage](POLYBTC_R1_COVERAGE_REPORT.md) and inventory JSON | 159 eligible observations / 97 markets in the verified development cohort; incomplete receipt/label coverage limits expansion | Feasibility evidence, not a new model evaluation. Historical and strict verified cohorts must remain separate. |

The main artifact hash is `42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4`. Its full refit uses 33,366 rows / 5,588 markets. This audit independently recalculated the saved later Brier and log-loss values for market, raw, Platt, isotonic and combination forecasts using equal total weight per market; results match the stored scores. See [score check](audit-20261019/score-check.json). This verifies arithmetic, not raw-source attestation, bootstrap intervals or inference reproduction.

Historical ingestion, label validation, position-policy, backtest, temporal-robustness, provider-substitution and execution-stress artifacts are retained. The proposed papers select technically consequential comparisons instead of giving every development step a publication. Earlier profitable-looking scenario results must retain their fee, fill and sample assumptions; later stricter evidence does not silently replace them.

## Additional raw dataset

The actual file is `data/raw/v1.1/btc_5m_market_snapshots_v1_4_O1-17.csv`, SHA-256 `71fb69ccaa1b4751c49fe37de8830607e1ff74c532a3c5614e8b5e9776d63aa3`.

Fresh inspection confirms **256,449 rows / 4,616 markets**, **34 fields**, observation timestamps **2026-10-01 17:15:08.609988 UTC–2026-10-17 18:21:43.175985 UTC**, and **2,851 market IDs overlapping frozen-model training**. The complete scan found no malformed rows, exact duplicates, duplicate market/observation keys, backwards observation sequence or conflicting market/token/expiry bindings. Missing quotes: YES bid 27,905; YES ask 28,386; NO bid 28,433; NO ask 27,946. Corresponding top sizes are missing on the same counts. Other raw fields contain no empty cells; presence alone does not establish semantic validity.

It contains BTC/reference and strike observations, both token IDs, top bid/ask and sizes, source reference/book timestamps and ages, timing telemetry, tick/minimum sizes and market expiry. It has no official outcome column, full-depth history, independent publication time or first-receipt timestamp. `observed_at` is collector wall time. Top size is not executable depth assurance. Source-clock discrepancies and provider/opening-strike semantics remain qualifications.

The existing current R1 audit establishes that the older 158,284-row October export is contained in this file, as are the 111,417 P12 rows. All 172 captured S5 markets overlap it. Its October 11–17 description is therefore not a new independent cohort. R1 recomputes source ages and reports selective missingness; this pass's full-file hash matches that inspected source. It does not authenticate the VM clock or collector binary.

Current retained labels match **3,023** cumulative-export markets, whereas the older v3 report claimed **3,104**, including 253 additional eligible training markets. R1 explains that the older label store and generated outputs are no longer present; current evidence supports 171 additional labelled markets beyond the archived October set. Neither inspected inventory provides October 14–17 official labels. Do not silently reconcile these numbers or infer labels from BTC direction.

**Valid role:** historical data-quality/feature-coverage analysis and explicitly retrospective reproduction on matched eligible observations. **Invalid role:** untouched evaluation, authenticated historical execution, or training through October 17 with invented outcomes. After review, write a versioned normalized derivative and provenance manifest preserving raw bytes, row identities, original times, exclusions and label-source membership. There is no need to refit a model merely to publish this audit.

## Publication plan

Five papers have distinct questions and evidence. The calibration paper owns the strict paired forecast result; the model paper references it without duplicating its analysis.

| Proposed title / slug | Question and defensible conclusion | Sources, figures and reproduction |
|---|---|---|
| **From Market Snapshots to Causal Research Data** / `market-data-provenance` | Which observations support historical features versus receipt-verified forecasts? Raw size does not establish causal or labelled coverage. | Schema/importer/feature code, R1 inventory and current CSV audit. Coverage-by-date/horizon heatmaps, overlap diagram, eligibility waterfall. Reproduce manifest/overlap/exclusion counts in a new output directory; disclose missing receipts, official strike authentication and labels. |
| **Machine Learning versus Market-Implied Bitcoin Probabilities** / `models-versus-market` | Do BTC models or market-relative features improve matched forecasts? Historical selected comparisons do not establish a durable incremental edge. | Baselines, nonlinear families, market-anchored walk-forward, selected feature/provider retests and expanded-model predictions. Matched Brier/log-loss tables, fold deltas, cohort lineage. Rescore saved predictions first; retrain only if a material discrepancy remains. Historical selection and provider drift limit inference. |
| **Probability Calibration under Limited Independent Data** / `forecast-calibration` | Can calibration improve a frozen model beyond contemporaneous market probabilities? Small-sample calibrators and the fitted blend did not improve the later proper scores. | Frozen S5 rows, calibration parameters and report, historical calibration as context. Reliability plots with counts, paired-score intervals and horizon coverage. Reproduce weighted scoring and declared resampling from frozen inputs in a separate output; 42 fitting / 55 later markets and conditional intervals limit claims. |
| **Execution Timing and Data Freshness in Five-Minute Markets** / `execution-timing` | Where do technically valid forecasts lose execution eligibility? Coverage, provenance and processing delays all matter; faster processing alone did not produce qualifying trades. | Timing, recovery, regression and funnel reports plus retained benchmarks. Stage funnel, deadline timeline and age distributions. Recalculate from frozen forensic evidence without operational replay; separate measured timestamps from inferred bounds and counterfactuals. |
| **Expected Value, Costs and the Limits of Paper Trading** / `strategy-economics` | Can forecast information survive prices, fees and constraints? No credible after-cost advantage is demonstrated for the tested policies. | Strategy/risk/execution code, historical execution stress and S5 economics. EV decomposition, controlled-policy table, cost/capital sensitivity. Replay pure accounting into new research files only; retain paper fee assumptions, unknown executor/settlement availability and post-hoc policy limitations. |

Each paper will have an abstract, question, methods, cohort/eligibility table, findings, limitations, reproduction instructions and precise source references. Captions will name the denominator, time period, units and evidence class. Publication claims will map to artifact path/hash, JSON field or calculation. Public titles/navigation will use descriptive names; internal identifiers remain only in source references and compatibility paths.

## Concrete migration map

| Current location | Proposed treatment | Compatibility/verification |
|---|---|---|
| `src/polybtc/` and `pyproject.toml` | Retain package paths and identity | Imports, inference, strategy/risk, execution and data tests. No threshold/model changes. |
| `scripts/{research,modeling,operations}/` | Retain implementations; restore documented legacy launchers through existing `_entrypoint.py`; add a real script index | Old command imports/help and grouped invocation; dynamic helper loading. No collector or trading launch. |
| `data/{raw,normalized,experiments,models,live,paper,shadow}/` | Retain all existing paths | Hash immutable sources/models; do not rename or copy active databases as a migration technique. |
| New `research/papers/` | Canonical Markdown papers with descriptive filenames | Website consumes the same sources at build time; no independently edited website copies. |
| New `research/figures/`, `research/catalog.json`, `research/claims.json` | Generated figures, catalogue metadata and claim provenance | Figure scripts consume retained/versioned inputs; validate links, cohort counts and hashes. |
| New `datasets/` | Small schemas, availability notes and manifests; raw data remains in `data/` | Record exclusions, licensing/redistribution status and local artifact requirements. No bulk staging. |
| New `experiments/README.md` and experiment cards | Curated index to existing `data/experiments/` and new `data/research/<version>/` outputs | Explicitly permit small documentation in ignore rules; generated results keep separate IDs. |
| `docs/`, `ToOrganize/`, `research-OoD/` | Preserve historical files initially; add descriptive archive index and repair incoming links | Avoid moving evidence referenced by scripts. Optional later moves require an exact caller/link map. |
| `dashboard/frontend/`, `dashboard/backend/` | Preserve application roots and API contracts; add publication shell and safe export adapter | Existing engine pages, filters, charts, preferences and API tests remain. |
| README | Replace entry narrative with question, findings, paper catalogue, engine/reproduction entry points | GitHub and website links only when actual destinations are known. |

### Website and deployment boundary

Use the existing Vite/React stack. Proposed navigation: **Research**, **Papers**, **Evidence**, **System**, **Engine**. The landing page explains the question and links to papers; the engine retains the current functional monitoring pages. Research pages must render without API connectivity; today the app gates almost every page on the overview API. Preserve existing hash links as aliases when adding descriptive paper routes.

Use a small Markdown pipeline with table support, safe code rendering and math support if needed; figures are generated SVG/PNG with captions and text summaries. Build-time ingestion from `research/papers/` gives one canonical source, a table of contents and reproducible asset links. Preserve theme settings and test long-form widths, keyboard navigation, mobile layouts and tables. No new service framework is needed.

Current API inspection confirms GET routes, method blocking, local Host/CORS restrictions, read-only SQLite connections, bounded queries and no process-control endpoints. However, **`/api/settings` exposes absolute local source paths**. The local backend is not ready to expose unchanged on the public internet. The frontend also hardcodes localhost API-documentation links.

Recommended public deployment: static papers plus a timestamped, sanitized research snapshot feeding existing read-only engine views. Public demo labels must clearly say historical snapshot, with no live/process implication. Keep the local FastAPI monitor and its actual files available for local operation. An export must strip local paths, operational identifiers not needed for interpretation, and private configuration. If a genuinely live hosted monitor is desired, hosting, authentication, source access and isolation need separate design approval; do not merely widen CORS/Host lists.

No hosting configuration, configured repository remote or confirmed public URL was found. Deployment preparation will document build/base-path requirements and verify local production navigation first. No account, domain, paid service, public repository or deployment will be created in this review pass.

Historical account-history exports and reconstructed fills need a separate privacy/redistribution review; they are not necessary for the public model-comparison demo. Public manifests should describe availability without embedding private account activity. This is separate from the official-outcome and market-data evidence requirements.

## Execution sequence after approval

1. Restore documented compatibility entry points and missing documentation links; classify absent fixtures/artifacts separately from defects. Establish a clean or explicitly qualified regression baseline without changing strategy behavior.
2. Create source/claim/cohort manifests and the cumulative-data derivative with bounded offline processing. Preserve labels at their retained provenance level. Rescore key saved predictions; record differences instead of replacing old reports.
3. Write the five canonical papers and deterministic figures, with a source-linked catalogue. No broad training sweep is needed. Any expensive retraining receives a separate resource estimate and approval.
4. Transform the existing website around those papers and a functioning local/read-only snapshot engine. Verify rendering, charts, math, links, navigation and existing API contracts.
5. Update README and release/deployment instructions; audit the proposed publication file set. Stop for approval before any external publication.

## Decisions required

1. **Approve this publication collection, migration map and local implementation sequence?** The assignment explicitly requires review first.
2. **Is this folder an export of an existing Git repository?** If so, supply its location or URL so history and tracked-file configuration can be retained. Otherwise approve initializing this existing project later; no replacement history will be invented.
3. **Approve a public historical-snapshot engine demo alongside the full local monitor, or is a hosted live monitor required?** The snapshot option fits the current evidence and avoids exposing local files; a live requirement changes deployment scope.

Hosting provider/domain and dataset/model redistribution permissions can remain deferred while local implementation proceeds. They must be settled before publication. Missing historical v3 outputs and label captures may be supplied if available; otherwise the papers will explicitly mark them unavailable and will not claim successful reproduction.

## Current validation baseline

Detailed commands/results are recorded in [the baseline log](audit-20261019/BASELINE.md). Core default discovery has three existing missing-launcher errors. Excluding those three modules for diagnosis yields **499 passed, 3 failed, 1 skipped** in 419.16 seconds; all three failures also involve missing legacy launchers. This diagnostic cannot substitute for full discovery. Backend: **26 passed** using a fresh isolated temp path; Ruff passes. Frontend typechecking/lint pass; default build hits a local cache-permission error, while an alternate config-loader production build passes. Feature-audit self-checks and saved-score arithmetic checks pass. Five protected artifact/evidence hashes are unchanged. No public deployment or browser interaction is claimed.
