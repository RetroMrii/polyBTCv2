# PolyBTC Research — PolyBTC v2

**Can machine learning provide a statistically reliable and economically exploitable
edge in Polymarket's five-minute Bitcoin prediction markets?**

PolyBTC is a quantitative ML research project studying forecasting, prediction-market
efficiency, causal evaluation and executable economics. A negative result is a valid
research outcome. The project does not promise profitability.

The research-first transition began with **R0 on 2026-10-14**. The existing
`polybtc-v2` package, source tree, datasets, model artifacts, paper infrastructure and
disabled live adapter retain their identities. R0 changes documentation only; it
does not change process state, operational thresholds or trading authorization.

## Start here

- [Research question and hypotheses](docs/RESEARCH_QUESTION.md).
- [Research protocol](docs/RESEARCH_PROTOCOL.md): causal data, chronological splits,
  matched baselines, statistical tests and executable-cost evaluation.
- [R0–R4 roadmap](docs/RESEARCH_ROADMAP.md): deliverables and review gates.
- [S5 baseline](docs/RESEARCH_BASELINE_S5.md): existing evidence and reproduction.

**Predictive edge** means improved outcome forecasts against an uninformed baseline.
**Incremental edge** means improvement beyond contemporaneous market probabilities
on the same eligible observations. **Economic edge** requires that a frozen policy
convert that information into positive results after executable costs and uncertainty.
Accuracy, successful integration and paper fills alone establish none of these.

## Baseline and current phase

S5 found **no demonstrated incremental value from frozen HGB3 and no credible
after-cost trading advantage**. In its strict later cohort (93 observations across
55 markets), market Brier/log loss were **0.1232 / 0.3851**, versus raw HGB3
**0.1506 / 0.4651**. Raw HGB3's paired Brier confidence interval included equality;
the finding is provisional and does not rule out other models or features.
The [S5 baseline](docs/RESEARCH_BASELINE_S5.md) distinguishes prediction results,
small-sample calibration and hypothetical economic scenarios.

R0 is documentation only. **R1 has not begun.** Its first proposed investigation is
an audit of already available market-relative features and their causal eligibility,
before new collection requirements or model training. The S5 sample and inspected
historical evaluations are now exposed development evidence, not future final tests.

## Repository map

| Location | Contents |
| --- | --- |
| `src/polybtc/` | Reusable data/modeling/calibration/evaluation logic plus preserved operational code |
| [`scripts/`](scripts/README.md) | Stable command launchers and grouped implementations |
| [`tests/`](tests/README.md) | Tests grouped into data, modeling, trading and shadow |
| `data/` | Raw/normalized data, frozen models, versioned research outputs and separate legacy runtime state |
| `research/` | Existing analysis notebooks |
| `dashboard/` | Existing dashboard application |
| `docs/` | Current research protocol/roadmap and preserved engineering/evaluation history |

## Research workflow and reproduction

Collection supplies evidence; offline features and models consume versioned data;
chronological calibration/test partitions assess forecast quality; a separate
simulator assesses executable economics. Legacy paper trading is an integration
instrument, and live-execution code remains outside the research roadmap.
See the [responsibility map](docs/RESEARCH_QUESTION.md#research-and-operational-boundaries).

The [S5 reproduction procedure](docs/RESEARCH_BASELINE_S5.md#reproduction) uses the
existing `.venv-execution` environment and frozen research inputs. It regenerates
research outputs, so it is documented for reproduction and was **not run in R0**.
Do not overwrite the preserved S5 artifacts when creating a new experiment; use a
distinct experiment ID and output location. Dependencies and environments are unchanged.

Development tests, when code changes are authorized, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Passing tests validates implementation, not predictive value or profitability.
See [testing instructions](tests/README.md) for focused research tests and temporary data.

## Preserved operational infrastructure

The legacy shadow runtime's model default is
`data/models/main/hgb3_expanded_v2.joblib`; its directory name is not research
endorsement. Existing compatibility commands remain available, for example:

```powershell
.\.venv\Scripts\python.exe scripts/run_vnext_shadow.py --help
```

Grouped module invocation is also supported:

```powershell
.\.venv\Scripts\python.exe -m scripts.operations.run_vnext_shadow --help
```

CLI defaults remain non-executing, with the kill switch enabled. These defaults
do not describe the state of any already-running process.
The [paper operating procedure](docs/PAPER_TRADING.md) wires retained acquisition
evidence, an explicit simulation fee contract, durable fills and settlement.
Live source/charged-fee and account verification remain unresolved readiness gates.
Do not interpret model selection or passing tests as live-trading authorization.

## Historical development context

The research documents above govern the new objective. Earlier P0–P14 and
P-EX engineering plans remain historical records; their live-capital milestones
are not R0–R4 research requirements or authorization to trade. The S1–S4
architecture reports and S5 research files are preserved unchanged.

- [Development stages](docs/POLYBTC_V2_DEVELOPMENT_STAGES.md) — historical roadmap.
- [E8 completion report](POLYBTC_V2_P_EX_E8.md) — immutable fee evidence.
- [E9 completion report](POLYBTC_V2_P_EX_E9.md) — source verification and v2 selection.
- [F completion report](POLYBTC_V2_P_EX_F.md) — isolated, explicitly armed paper mode.
- [G completion report](POLYBTC_V2_P_EX_G.md) — durable order lifecycle and partial-fill accounting.
- [H completion report](POLYBTC_V2_P_EX_H.md) — disabled CLOB adapter and offline SDK validation.
- [I completion report](POLYBTC_V2_P_EX_I.md) — durable live fills, fee reconciliation, positions and settlement receipts.
- [J completion report](POLYBTC_V2_P_EX_J.md) — atomic live risk checks, balance constraints and submission reservations.
- [K completion report](POLYBTC_V2_P_EX_K.md) — read-only status, process health, controlled shutdown and recovery.
- [L readiness review](POLYBTC_V2_P_EX_L.md) and [first remediation](POLYBTC_V2_AUDIT_REMEDIATION.md) — historical audit and first fix pass.
- [Final readiness](POLYBTC_V2_FINAL_READINESS.md) — completed paper pipeline, validation and unresolved live risks.
- [Paper operation](docs/PAPER_TRADING.md) — acquisition, simulated fills, settlement and restart commands.
- [Operations runbook](docs/OPERATIONS.md) — status command and blocked-state recovery.
- [Layout and compatibility notes](docs/REPOSITORY_LAYOUT.md).
