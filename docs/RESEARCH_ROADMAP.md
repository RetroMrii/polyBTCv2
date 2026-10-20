# PolyBTC Research roadmap: R0–R4

Version 1 · 2026-10-14. **R0 is documentation only; R1–R4 are proposals requiring stage review.** These research phases replace the primary integration-first queue, not the historical P0–P14 record. Live execution is outside this roadmap.

## Stages and gates

| Stage | Small coherent deliverable | Acceptance criterion / stop condition |
|---|---|---|
| **R0 — Research identity and protocol** | README, research question, hypotheses, protocol, roadmap and faithful S5 baseline | Documentation agrees with evidence; protected history/artifacts remain intact; no experiments, process or trading changes. Review before R1 |
| **R1 — Existing market-relative feature audit** | Field/feature catalogue, causal eligibility matrix, coverage/exclusion report and bounded experiment card using existing development data | Every proposed input has source, formula, availability/dependency proof, missingness and validation status; identify a feasible matched comparison or conclude data insufficient. No new collector requirement or model training before this audit is reviewed |
| **R2 — Bounded model and calibration development** | Versioned feature dataset and small predeclared baseline/ablation study using chronological development folds; one frozen candidate or a documented negative result | Matched raw/fitted market baselines, standalone BTC and market-relative comparisons; calibration/selection confined to earlier data; full search record and reproducible membership/hashes. No candidate is an acceptable outcome |
| **R3 — Frozen chronological forecast and economic evaluation** | One final readout under the registered statistical and executable-cost protocol, with labelled sensitivity results | Test genuinely unused by training/selection; sufficient independent markets/days; report predictive, incremental and economic conclusions separately. Missing timing/fees/labels block executable claims. An exposed test becomes development data after readout |
| **R4 — Prospective replication and research conclusion** | Forward observations from the unchanged frozen candidate and independent settlement evidence; replication report or reproducible negative result | Same candidate/analysis plan, new periods and adequate coverage; compare with market and no-trade under real availability/cost constraints. Conclude support, predictive-only improvement, no demonstrated benefit or insufficient data; do not automatically deploy |

R2 can use existing pure calculations and ordinary Python research scripts. R3/R4 need neither a new service layer nor an application rebuild. Any collector change, runtime integration or source restructuring is a separately reviewed implementation proposal. A research approval never enables real-money trading or implicitly changes legacy paper economics.

## First R1 investigation: market-relative feature feasibility

**Question:** Which signals already retained by PolyBTC could support a causal test of incremental information beyond contemporaneous market prices?

Use only exposed development evidence for exploration: S5 frozen inputs, the overlapping historical snapshot/feature datasets and existing P11.5/P13/P14 work. Inventory other files without assuming they are independent tests. Do not read unused final-period labels for exploratory feature ranking.

| Candidate feature family | First audit question |
|---|---|
| Market probability / log odds and remaining horizon | Is the normalized two-book midpoint available and fresh at the target? How are endpoint logits and inconsistent book sums handled? |
| YES/NO spread, ask-to-mid costs and midpoint-sum deviation | Are both sides from identifiable, contemporaneously available books? Is a feature a signal or merely a transaction-cost estimate? |
| Top-of-book depth/imbalance and YES/NO asymmetry | Are sizes present, comparable and causally timed? Top-of-book size must not be described as full depth or trade flow |
| Market-probability changes over past windows | Does receipt history support every lag, with no interpolation through missing/future observations or across market IDs? |
| Reference-to-strike distance, causal returns and interactions with market odds | Are TWAP provider, strike semantics and consumed anchor consistent? Does the feature contribute information not already in price? |
| Volatility/context and latency/data-quality indicators | Are enough earlier observations available to calculate them? Distinguish smoothed-return proxies from realized volatility and availability selection from genuine information |

Do not claim order-flow imbalance, queue position, trade intensity or full-depth features unless the existing records actually contain the required events. Audit reference-provider/strike drift, clock alignment, token mapping, official labels, training membership and overlapping derivatives alongside feature coverage.

Deliver a catalogue with `available / reconstructable with verified availability / exploratory only / unavailable`, exact source paths, proposed formulas, dependency cutoffs and missingness by horizon/time/source. Quantify the common eligible sample without fitting a model or tuning entry thresholds. Identify the smallest informative ablation, such as a market-only probability model versus that same model augmented with a small set of verified BTC/book features; also specify its standalone BTC comparator.

**R1 review decision:** approve a concrete R2 card, request a narrowly justified collection/provenance repair, or stop for insufficient data. Any collection proposal must identify the missing field, hypothesis served, impact on existing collection and validation plan. Do not add data feeds simply because a model family could consume them.

## Experiments and evaluation ownership

R1 chooses what is causally testable, not which signal wins. R2 chooses models/calibrators/policy using development and calibration periods only. R3 measures a frozen decision once on its final period. R4 checks whether that result replicates after freeze. A changed feature, model, calibrator or policy cannot inherit a predecessor's untouched-test status.

Use the [protocol](RESEARCH_PROTOCOL.md) experiment card and decision rules before R2 fitting and before any R3 final readout. Separate forecast eligibility from execution eligibility and keep both denominators. Declare effect sizes, dependence model and power before seeing final outcomes. The S5 planning counts are minimum planning inputs, not stage-completion evidence by themselves.

## Preservation and scope

Keep frozen HGB3, S5 scripts/data/reports, research notebooks, model-selection history, raw snapshots and official label records. Never reset or rewrite journal, receipt, checkpoint or position state to improve a result. Existing script paths and package identity remain stable. Preserve production v1.1 behavior, legacy paper trading, risk/freshness/fee constraints and live authorization gates.

R0 does not run a collector, stop a process, train/calibrate a model, regenerate S5, simulate new trades or begin R1. The next action is review of this transition and the bounded first R1 investigation above.
