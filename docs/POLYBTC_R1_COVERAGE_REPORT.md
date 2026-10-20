# R1 — Coverage and selection audit

2026-10-19. **Recommendation: collect additional data before modeling.** Useful features exist, but only 159 matched, receipt-backed observations across 97 already-exposed markets support the proposed core comparison. Historical datasets offer larger exploratory samples without equivalent availability evidence. No R2 fitting or operational change was performed.

## Denominators and reconstruction

Primary window: frozen S5 targets **2026-10-12 14:41:00 through 2026-10-13 21:19:30 UTC**, 1,032 opportunities, six horizons per 172 markets. It is development evidence, not untouched evaluation. Source CSV prefix hash was checked against the frozen checkpoint. Of 81,451 prefix rows belonging to these markets, 81,417 join durable first receipts; 34 unmatched rows are not assigned synthetic receipts.

The current journal has 1,036 decisions / 173 markets. Four post-window decisions belong to an additional market without a retained official label. Pre-October-12 CSV history has no matching receipts in this state directory. The strict counts below are a measured cohort, not an assertion that every row in every historical file has been independently re-attested.

The recorded branch finds 759 selected snapshot IDs in the frozen CSV/receipt join. Of these, 46 were received after their historical cutoff; **713** pass selection timing. A separate offline reconstruction selects the latest observation actually received by each cutoff: **751** horizons have such a snapshot (within ten seconds), but its fresh market/BTC intersection is still **the same 159 decision IDs**. This is availability analysis, not replay or rewriting of finalized decisions.

## Predictive feature funnel

All percentages in this table use **1,032 opportunities**. Individual feature rows overlap; do not add them.

| Gate / feature | Rows | Markets | % of opportunities | Rows with retained official-source label |
|---|---:|---:|---:|---:|
| Latest causal observation exists | 751 | 165 | 72.77% | 745 |
| Recorded selection is causal | 713 | 165 | 69.09% | 707 |
| Bound, fresh contemporaneous market probability | 166 | 102 | 16.09% | 166 |
| Current reference/collector-strike distance | 596 | 159 | 57.75% | 592 |
| Current reference plus verified r30 anchor | 564 | 159 | 54.65% | 560 |
| Common market + distance + r30 | **159** | **97** | **15.41%** | **159** |
| Common plus top sizes/imbalance/asymmetry | 159 | 97 | 15.41% | 159 |
| Common plus fresh market change at 30 sec | 48 | 34 | 4.65% | 48 |
| Common plus both 30/60-sec market changes | 16 | 14 | 1.55% | 16 |
| Above plus sampled 60-sec TWAP variation | 16 | 14 | 1.55% | 16 |
| Common rows also reaching original execution-fee/strategy stage | 49 | 41 | 4.75% | 49 |

Incremental loss in that declared order: 166 → 159 (**7 lost** on BTC dependencies), →159 (**0** on sizes), →48 (**111** on 30-sec market history), →16 (**32** on additional 60-sec market history), →16 (**0** on grid variation after those prior exclusions). These are order-dependent losses. Individually adding only 60-sec market history to the 159 core rows leaves **39**; adding only grid variation leaves **94**. The JSON intersection matrix supports other fair comparisons without fitting or looking at outcome performance.

The latest-received branch increases reference-distance availability to 618 and r30 to 586, but does not increase the paired market sample. All 159 common rows reproduce the **membership**, not a new model-score claim, of the frozen S5 strict cohort. The 49 strategy-stage rows span the whole window; S5's 43 rows / 36 markets describe only its later evaluation partition. Neither count proves executor freshness at a newly simulated fill. Fully observed fill/settlement paths remain unavailable; actual paper entries are zero.

## By horizon and date

Each horizon has 172 opportunities. “Market” and “core” use recorded selections; “available” searches all receipts. One row per market/horizon, so each horizon count is also its market count.

| H seconds | Available | Causal recorded | Fresh market | Reference+r30 | Common core | Core + market Δ30 | Core + Δ30 + Δ60 | Original strategy subset |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 240 | 165 | 161 | 36 | 135 | 34 | 13 | 0 | 7 |
| 180 | 163 | 154 | 39 | 130 | 37 | 12 | 7 | 18 |
| 120 | 150 | 141 | 33 | 113 | 32 | 11 | 3 | 13 |
| 90 | 135 | 124 | 23 | 97 | 22 | 5 | 3 | 6 |
| 60 | 104 | 100 | 27 | 72 | 27 | 4 | 2 | 4 |
| 30 | 34 | 33 | 8 | 17 | 7 | 3 | 1 | 1 |

Core coverage: October 12 **44 rows / 26 markets**; October 13 **115 / 71**. These are only two calendar days, not 159 independent observations. All per-market flags, selected/anchor IDs, deadlines, per-date and per-horizon feature counts are retained in JSON. Lack of 30-second-horizon coverage is severe: 138/172 have no eligible recent receipt, and only 7/172 enter the matched core. Eligibility is not missing at random.

## Historical exploratory coverage

These counts require finite market probability, displacement and r30 **fields**, not modern source/receipt verification. They cannot be promoted to verified execution data.

| Source | Total rows | Common numeric A/B/C rows | Common markets | Incremental loss |
|---|---:|---:|---:|---:|
| Frozen v2 training CSV | 33,366 | 25,121 | 5,587 | 8,245 missing market probability |
| P4 / P13 enriched / P13 continuous, each | 16,388 | 12,325 | 2,737 | 4,049 missing market probability, then 14 additional missing r30 |
| P11.5 residual dataset | 11,931 | 8,914 | 1,994 | 3,017 missing market probability |
| P13 prospective supervised | 11,935 | 8,869 | 1,995 | 3,040 missing market probability, then 26 additional missing r30 |

These sets overlap extensively; the 25,121 are not additional to P4/P13. Historical training membership is known for v2, but original receipt availability is not. Labelled historical rows can support explicitly qualified development exercises, not a causal/untouched claim about this frozen model.

For the cumulative Oct 1–17 raw export, there are **4,616 opportunities per horizon**. Select by observation time only, within ten seconds; the table counts finite fields before freshness/provenance tests:

| H | Observation available by event time | All four quotes and sizes present | Retained label match among observed rows |
|---:|---:|---:|---:|
| 240 | 4,594 | 4,594 | 3,010 |
| 180 | 4,588 | 4,552 | 3,011 |
| 120 | 4,596 | 4,254 | 3,012 |
| 90 | 4,595 | 3,762 | 3,014 |
| 60 | 4,592 | 2,589 | 3,012 |
| 30 | 4,591 | 859 | 3,012 |

The label column is not the intersection with complete quotes. This event-time coverage is an upper bound for availability, not a causal pass count. At 30 seconds, 3,732 of 4,591 observed candidates lack a complete two-book quote; simply obtaining more labels cannot recover those books. Per-source versions of this table, column missingness and historical feature coverage by horizon/date are in JSON. No future interpolation is used.

## Timing and bias

Measured across the **759 recorded selected snapshots**, including rejected ones:

| Milliseconds | Median | p90 | p99 | Maximum |
|---|---:|---:|---:|---:|
| First receipt − observation | 342.8 | 580.6 | 22,154.5 | 1,350,057.5 |
| Cutoff − observation | 648.4 | 1,744.5 | 9,157.9 | 9,935.9 |
| Reference age at cutoff | 3,000 | 4,000 | 11,000 | 12,000 |
| YES book age at cutoff | 666 | 1,728.4 | 9,105.4 | 9,909 |
| NO book age at cutoff | 589 | 1,627 | 9,023.8 | 9,826 |

Minimum book ages are −825 ms YES / −901 ms NO. Negative ages fail; no offset correction is applied. These are recorded cross-clock differences, not proof that the source actually arrived from the future. Receipt delay includes publication/transport/ingestion and possible clock discontinuity; independent CSV publication time is absent, so these components cannot be separately attributed. Bound raw evidence proves field consistency, not UTC clock calibration.

The paired sample selects for tight timing and complete two-sided books. Missingness changes sharply with horizon and may depend on market extremity/liquidity, feed cadence and acquisition regime. The protocol must report coverage and abstentions, preserve identical eligible A/B/C rows and avoid generalizing conditional performance to all markets. No outcome-based feature ranking or volatility-regime optimization was done here.

## Reproduction and checks

From `H:\PolyBTCv2`:

```powershell
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_r1_features.py --self-test
.\.venv-execution\Scripts\python.exe -B scripts/research/audit_r1_features.py
```

The second command overwrites **only** `docs/POLYBTC_R1_EVIDENCE.json`. It performs no training, scoring, network calls or operational journal writes. SQLite connections use `mode=ro`, `query_only=ON` and read transactions; acquisition lookup uses the existing canonical attestation logic with a read-only connection. The frozen CSV prefix is checked before cohort analysis. S5 files and frozen model hashes are checked unchanged before/after.

Self-checks passed for epoch/ISO timestamp units, no future event-time selection, missing quote exclusion and market denominators. Integrated assertions passed for exact S5 common membership and source/receipt deadline limits. Each final run records the analysis script hash. No broad operational test suite is claimed: this change adds an offline audit, not a runtime correction.

## Missing information and next action

Unrecoverable from present exports: historical first receipts, discarded full reference event caches and independent publication times. Potentially resolvable prospectively: raw official resolution/retrieval retention, explicit provider/build/clock provenance, measured execution deadlines and longer coherent observation coverage. Existing VM labels can be supplemented only through separately authorized official evidence retrieval; even then the missing historical receipts remain missing.

The newer VM file is larger but adds no demonstrably independent, receipt-backed labelled comparison period beyond the exposed local cohort. There are no retained official labels for Oct 14–17. Current stores match 171 additional October VM markets beyond the archived Oct 1–11 set; the older v3 report's 253-new-labelled-market result depended on sources/artifacts no longer present at their referenced paths, including `data/shadow/vnext_local_live/resolutions.sqlite3`. Do not silently substitute that report for current evidence.

Collect a longer, coherent receipt/evidence-backed development sample with retained official resolution provenance before fitting the proposed R2 comparison. Do not start a new collector or alter an existing process under R1 authorization. The [R2 card](POLYBTC_R1_R2_EXPERIMENT_PROPOSAL.md) specifies the review and registration gate.
