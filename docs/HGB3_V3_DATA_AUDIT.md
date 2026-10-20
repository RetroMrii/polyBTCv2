# HGB3 v3: download and training-data audit

Research-only · 2026-10-17 · Successful evidence version `hgb3_v3_r1_20261017_v2`. Audit completed before model fitting. The original experiment card was recorded before new label inspection; the timestamp-parser failure in the preceding v1 attempt is explicitly marked invalid and had no model fit.

## Result

The cumulative download contains **256,449 observations / 4,616 markets**. It adds 98,165 rows beyond the exact 158,284-row archived prefix. It contains **1,765 market IDs absent from v2**, but only **253 new eligible labelled markets / 1,517 examples** can be added. Their predictions run **2026-10-11T15:06:00+00:00 through 2026-10-13T21:14:30+00:00**. The expanded dataset is **34,883 rows / 5,841 markets**, preserving v2's original 33,366 examples and all 5,588 markets.

No October 14–17 market has a valid label in the inspected stores. This expansion therefore does **not** train through October 17. Those observations support unlabelled feature-feasibility counts only. Label procurement is the immediate data gap; it is not solved by assuming local BTC direction.

## File identity and schema

- Path: `data\raw\v1.1\btc_5m_market_snapshots_v1_4.csv`; 166,128,026 bytes.
- SHA-256: `71fb69ccaa1b4751c49fe37de8830607e1ff74c532a3c5614e8b5e9776d63aa3`.
- Actual observation UTC: 2026-10-01 17:15:08.609988+00:00 to 2026-10-17 18:21:43.175985+00:00.
- Market expiry UTC: 2026-10-01 17:20:00+00:00 to 2026-10-17 18:25:00+00:00.
- Derived eligible prediction targets UTC: 2026-10-01T17:16:00+00:00 to 2026-10-17T18:21:00+00:00. There is no prediction timestamp column in the raw file; these are reconstructed as expiry minus registered horizon.
- Intended October 11–17 subset: 108,222 observations / 1,946 markets. This subset overlaps prior v2 training on October 11.
- Field count: 34; exact schema: `observed_at, market_id, question, btc_price, strike, seconds_to_expiry, yes_bid, yes_ask, no_bid, no_ask, yes_bid_size, yes_ask_size, no_bid_size, no_ask_size, yes_token_id, no_token_id, momentum_60s, volatility_60s, reference_timestamp, reference_age_ms, reference_latency_ms, yes_book_timestamp, yes_book_age_ms, yes_book_latency_ms, no_book_timestamp, no_book_age_ms, no_book_latency_ms, yes_tick_size, yes_min_order_size, no_tick_size, no_min_order_size, snapshot_build_latency_ms, market_end_at, collector_version`.

The CSV reports collector version 1.4. It contains repeated market observations, not precomputed labelled examples. Reference and book timestamps are original epoch milliseconds; `observed_at` is the collector's wall-clock observation. No independent CSV publication time, first receipt, immutable raw response or VM deployment-code hash is present. The exact VM collector build and its clock accuracy cannot be authenticated from this export. Current local collector code is not evidence of the deployed VM build. Reference-provider/strike semantics retain the historical RTDS/TWAP qualification; these are not newly authenticated official opening-strike records.

Existing official-source labels are accepted at their retained validation level: `polymarket_gamma+data_api_v2`, VALID/VERIFIED/SETTLED, binary outcome and recorded resolution time. CSV winning tokens are checked against the snapshot token mapping; registry-only records lack winning tokens/raw response/retrieval timestamps and inherit that limitation. They are not BTC-price proxies or independently re-fetched labels. Missing labels mean **no valid retained label**, not proof that the exchange still considers the market unresolved. No network collection or operational store update was performed.

## Calendar coverage (raw observations)

| UTC date | Rows | Distinct markets |
|---|---|---|
| 2026-10-01 | 4483 | 80 |
| 2026-10-02 | 16011 | 287 |
| 2026-10-03 | 16178 | 288 |
| 2026-10-04 | 16060 | 287 |
| 2026-10-05 | 16031 | 288 |
| 2026-10-06 | 15988 | 288 |
| 2026-10-07 | 15898 | 288 |
| 2026-10-08 | 15996 | 288 |
| 2026-10-09 | 15857 | 288 |
| 2026-10-10 | 15725 | 288 |
| 2026-10-11 | 16075 | 288 |
| 2026-10-12 | 16176 | 288 |
| 2026-10-13 | 16100 | 288 |
| 2026-10-14 | 16032 | 288 |
| 2026-10-15 | 15751 | 286 |
| 2026-10-16 | 15866 | 287 |
| 2026-10-17 | 12222 | 221 |


## Exact overlap and deduplication

| File | Rows | Markets | IDs shared with download | Identical full rows |
|---|---|---|---|---|
| data\raw\v1.1\btc_5m_decisions_v1_1.csv | 10844 | 280 | 0 | not comparable |
| data\raw\v1.1\btc_5m_market_snapshots_v1_2.csv | 759 | 15 | 0 | 0 |
| data\raw\v1.1\btc_5m_market_snapshots_v1_3.csv | 41726 | 743 | 0 | 0 |
| data\raw\v1.1\btc_5m_market_snapshots_v1_4_old.csv | 91140 | 1620 | 0 | 0 |
| data\raw\v1.1\btc_5m_market_snapshots_v1_4_old1.csv | 153942 | 2737 | 0 | 0 |
| data\raw\v1.1\btc_5m_market_snapshots_v1_4_old2.csv | 158284 | 2852 | 2852 | 158284 |
| data\raw\v1.1\btc_5m_trades_v1_1.csv | 82 | 18 | 0 | not comparable |
| data\raw\v1.1\Polymarket-History-2026-09-16.csv | 966 | None | None | not comparable |
| data\normalized\snapshots.csv | 10844 | 280 | 0 | not comparable |
| data\normalized\p4_supervised_v1.csv | 16388 | 2737 | 0 | not comparable |
| data\experiments\model_expansion\hgb3_expanded_v1.csv | 28280 | 4732 | 1995 | not comparable |
| data\raw\p12\btc_5m_market_snapshots_p12.csv | 111417 | 2000 | 2000 | not comparable |
| data\experiments\model_expansion\vm_expansion_v2\hgb3_expanded_v2.csv | 33366 | 5588 | 2851 | not comparable |


`old2` is an exact ordered content prefix, not merely a date overlap. Its hash `5c37788cba899ceed7f195c8161f28dd00ce1ea772cbc9bbc67e4369f8c443ea` matches v2's recorded original VM source hash. Other derivative research files inherit source membership and must not be pooled as new observations. The old transaction-history export has no stable condition ID and cannot prove ID overlap by market name.

S5 captured-market overlap: **172**; new training additions overlap **171** of those already exposed markets. Strict S5 partition membership overlap: `{'calibration': {'markets': 42, 'download_overlap': 42, 'new_training_overlap': 42}, 'evaluation': {'markets': 55, 'download_overlap': 55, 'new_training_overlap': 55}}`. No S5 period is described as untouched.

Deduplication first protects the old training membership, then admits only wholly new market IDs, at most one selected observation per market/horizon. It never adds another copy of an old market/horizon from overlapping raw/P12 files. Selected snapshot and anchor line numbers and content fingerprints are retained in `horizon_observations.csv`; the raw source SHA authenticates those line references. The pandas content fingerprint is an identity aid, not a cryptographic provenance signature.

## Integrity and exclusions

Malformed CSV rows: 0; invalid observation/expiry timestamps: 0; malformed numeric cells: 0; identical duplicate rows: 0; duplicate market/observation rows: 0. Global backwards observations: 0; within-market backwards observations: 0. Market/expiry/token-map conflicts: 0; conflicting label markets: 0. Complete per-field counts and token bindings remain in the machine evidence/raw source.

Missing quote fields (denominator 256,449; other listed raw fields have no missing cells):

| Field | Missing observations |
|---|---|
| yes_bid | 27905 |
| yes_ask | 28386 |
| no_bid | 28433 |
| no_ask | 27946 |
| yes_bid_size | 27905 |
| yes_ask_size | 28386 |
| no_bid_size | 28433 |
| no_ask_size | 27946 |


There are 3,104 downloaded markets with retained valid labels and 1,512 without. 1 market had not expired at the final recorded observation; the remaining missing-label markets are not assigned outcomes. For the 1,765 non-v2 markets there are 10,590 potential horizon examples: **1,517 admitted**, **8,940 missing-label exclusions**, **73 missing/late horizons**, **60 missing 30-second anchors**. These first-failure reasons are mutually exclusive at market/horizon level, not raw-row exclusions.

All downloaded markets: 27,696 candidate horizons, 27,450 structurally feature-eligible, 140 missing/late horizons and 106 missing anchors. Old overlapping examples are not re-added even if reconstructed.

| Horizon seconds | Structurally eligible rows |
|---|---|
| 240 | 4576 |
| 180 | 4568 |
| 120 | 4580 |
| 90 | 4581 |
| 60 | 4573 |
| 30 | 4572 |


## Training contract and freshness distinction

The research builder uses the same latest-at/before-target and 10-second maximum lag rule as `build_p4_extension_from_p12.py`. The 30-second reference anchor is the latest same-market observation at/before selected observation minus 30 seconds, with at most 10 seconds additional lag. Features are `(reference-strike)/strike`, horizon seconds and `reference/anchor_reference-1`. Positive finite inputs, market interval, token consistency, binary validated labels and no known future reference are required. New examples retain actual snapshot/anchor identities. Existing baseline rows retain their original features, labels, source cohorts and provenance qualification; no modern verification is retroactively asserted.

Raw ages recomputed from original source timestamps at observation (reference limit 3,000 ms; books 500 ms):

| Source | Future | Stale observations | Median ms | p99 ms |
|---|---|---|---|---|
| reference | 0 | 19399 | 2322.95 | 3556.48 |
| yes_book | 0 | 4088 | 125.71 | 691.15 |
| no_book | 0 | 3355 | 43.95 | 611.38 |


Reported reference age can differ from age at final observation by up to 10931.94 ms. Treat it as a different acquisition-stage measurement, not an authoritative final age. Book-age differences are at most about 9 ms. No source times were altered. The forecast development contract is broader than the operational execution freshness contract; stale-at-target rows are not called executable. Freshness subsets are reported separately in R1 and comparison evidence. Unknown receipt availability blocks fully verified causal/executable claims even where recorded source ages pass.

## Added training cohort

| Prediction UTC date | Added rows | Added markets |
|---|---|---|
| 2026-10-11 | 492 | 82 |
| 2026-10-12 | 324 | 54 |
| 2026-10-13 | 701 | 117 |


Expanded dataset: `data\research\hgb3_v3_r1_20261017_v2/hgb3_expanded_v3_dataset.csv`.

SHA-256: `6fc110449ea311aa3f1fc9ef958705501e4f07753b840510e0c47e088293f40c`. Label capture SHA-256: `04099f79b552b94a8b73792675804f76e261ec2cb59cd89fd7ead4d0c51f1631`. Exact exclusions, membership, source hashes, field counts and feature coverage are in the same versioned directory. No reserved untouched final-test market is included: the entire download is explicitly development data, and new future observations require a separate frozen protocol.

## Reproduction

From `H:\PolyBTCv2`, use a **new output directory**; outputs refuse overwrite. Reuse the frozen label capture to avoid dependence on a later changing registry. Input raw and v2 dataset hashes must match this report.

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\.venv-execution\Scripts\python.exe -B scripts/research/hgb3_v3_r1.py audit --output data/research/hgb3_v3_r1_reproduction_01 --labels-capture data/research/hgb3_v3_r1_20261017_v2/label_capture.json
```

This command reads original data and writes only new offline research files. It does not run a collector, resolver, paper runtime or trading service.
