# Datasets and artifact availability

Source data remain in their original `data/` locations. The public repository should contain manifests and curated evidence, not operational databases, private account exports or large raw datasets. No new external data was acquired for the publication transformation.

| Local path | Role | Availability / qualification |
|---|---|---|
| `data/raw/v1.1/btc_5m_market_snapshots_v1_4_O1-17.csv` | Cumulative October telemetry | Local, 166,128,026 bytes; overlaps training and inspected outcomes; no first receipts or labels |
| `data/research/publication_data_20261019_v1/` | New normalized historical derivative | Local compressed CSV plus manifest; every raw row retained; no assigned labels |
| `data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv` | Frozen artifact training membership | Local; 33,366 rows / 5,588 markets |
| `data/models/main/hgb3_expanded_v2.joblib` | Preserved frozen model | Local; SHA-256 in `manifests.json`; not retrained or replaced |
| `data/research/s5_v1/inputs.json` | Frozen eligibility and calibration inputs | Local; exposed research evidence, not a new untouched test |
| `data/live/`, `data/paper/`, `data/shadow/` | Acquisition and operational state | Local only; never required by the public static site |
| `research/sources/` | Publication extracts and aliased frozen predictions | Included in local static build; parent source hashes and limitations retained |

## Normalized schema

The new compressed CSV retains all 34 raw fields and adds `source_record` (source SHA-256 and CSV record number), normalized `condition_id`, UTC observation/reference/book times, recomputed ages, reference price, relative displacement, normalized YES midpoint, spreads, quality flags and observation-time eligibility flags. `availability_class` is always `historical_event_time_only`; `official_label` is deliberately empty.

The normalized midpoint requires complete, finite, uncrossed quotes between zero and one. Rejected quotes remain in the original columns and receive flags. No imputation, row deletion, receipt synthesis or deduplication was needed for this source. Observation-age checks do not establish original delivery by a prediction deadline. A future label join must record its own immutable label-source membership and conflicts.

The manifest records source/output/script hashes, counts, UTC-date coverage, exclusion policy and dependency context. Gzip container bytes can vary by build timestamp; compare decompressed CSV content when assessing deterministic row reproduction. The raw source hash must match the registered input, and the command refuses an existing output directory.

```powershell
.\.venv-execution\Scripts\python.exe -B scripts/research/normalize_publication_data.py --output data/research/publication_data_reproduction_01
```

## Evidence availability is not licensing permission

No redistribution license for upstream market data, third-party history or original model inputs has been established here. Keep raw files local until permissions are resolved. Historical account exports are excluded from the public demo. A fresh checkout can build the paper website from committed canonical papers, figures and curated extracts; regenerating figures/extracts from originals requires the local research files. Runtime/model tests also require their documented local artifacts.

Missing historical v3 outputs and the older label capture have not been recreated or claimed available. Current label counts and the older report's differing count remain explicitly documented in the data paper.
