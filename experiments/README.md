# Experiment index

This index describes retained experiments without moving their outputs or treating overlapping studies as independent evidence.

| Investigation | Implementation | Original evidence |
|---|---|---|
| Predictive baselines and nonlinear families | `scripts/research/run_p5_baselines.py`, `run_p7_models.py` | `data/normalized/p5_baseline_report.json`, `p7_model_report.json` |
| Market-relative daily walk-forward | `scripts/research/run_p115_market_anchored_walk_forward.py` | `data/normalized/p115_market_anchored_walk_forward_*` |
| Feature/provider and model-family retests | `scripts/research/run_p13_*` | `data/experiments/p13_model_improvement/` |
| Expanded compact models | `scripts/modeling/` | `data/experiments/model_expansion/` |
| Strict paired calibration and economics | `scripts/research/audit_s5.py` | `docs/POLYBTC_S5_EVIDENCE.json`, frozen `data/research/s5_v1/` |
| Causal feature feasibility | `scripts/research/audit_r1_features.py` | `docs/POLYBTC_R1_EVIDENCE.json` |
| Publication consolidation | `scripts/research/normalize_publication_data.py`, `build_publications.py` | `data/research/publication_data_20261019_v1/`, `research/` |

Historical identifiers remain in paths for reproducibility. Public papers use descriptive titles. Existing experiment scripts often write fixed paths; run them in an isolated copy or first parameterize a new output ID. Do not overwrite originals or refit the deployed model in place. Publication consolidation performs no training and adds no new outcome evidence.
