# R1 — Data inventory

Audit date: 2026-10-19. Read-only research; no training, outcome scoring, process changes or operational writes. [Machine-readable inventory](POLYBTC_R1_EVIDENCE.json) contains per-file SHA-256, exact column names, null counts, UTC bounds, rows by date/market/horizon, field-presence counts, training/label overlap and pairwise market overlap. A populated field is not proof of causal availability.

## Available sources

Paths below are relative to the repository. Dates are UTC; exact endpoints are in the evidence. Counts describe the current filesystem, not the older reports' file listings.

| Source | Rows / distinct markets | Coverage | Provenance and use |
|---|---:|---|---|
| `data/live/vnext_market_snapshots.csv` | 122,340 / 383 | Oct 9–13 | Local collector telemetry; only the receipt/evidence-bound subset supports verified availability |
| `data/live/paper_market_snapshots.csv` | 281 / 2 | Oct 12 14:30–14:37 | Earlier local acquisition file, not the active S5 CSV; do not combine checkpoint identities |
| `data/raw/v1.1/btc_5m_market_snapshots_v1_4.csv` | 158,284 / 2,852 | Oct 1–11 | Archived VM telemetry; original receipts/raw acquisition sidecar unavailable |
| `data/raw/v1.1/btc_5m_market_snapshots_v1_4_O1-17.csv` | 256,449 / 4,616 | Oct 1–17 | Cumulative VM export, not independent of the preceding file |
| `data/raw/v1.1/btc_5m_market_snapshots_v1_4_S17-27.csv` | 91,140 / 1,620 | Sep 17–27 | Earlier telemetry; same historical provenance limitations |
| `data/raw/p12/btc_5m_market_snapshots_p12.csv` | 111,417 / 2,000 | Oct 1–8 | Exact row subset of the October VM exports |
| `data/normalized/snapshots.csv` | 10,844 / 280 | Sep 15–16 | v1.1 decision-derived snapshots; original v1 raw files are absent from the current raw tree |
| `data/normalized/p4_supervised_v1.csv` | 16,388 / 2,737 | Sep 17–Oct 1 | Historical horizon features and labels; event-time research |
| `data/normalized/p115_residual_dataset.csv` | 11,931 / 1,994 | Sep 24–Oct 1 | P11.5 features plus exposed predictions/errors; 8,914 matched market rows |
| `data/normalized/p115_market_anchored_walk_forward_predictions.csv` | 8,914 / 1,994 | Sep 24–Oct 1 | Derived predictions, not additional observations |
| `data/experiments/p13_model_improvement/p13_enriched_supervised.csv` | 16,388 / 2,737 | Sep 17–Oct 1 | P4 plus external minute context |
| Same directory: `p13_continuous_reference_supervised.csv` | 16,388 / 2,737 | Sep 17–Oct 1 | Same rows plus continuous-reference anchors |
| Same directory: `p13_prospective_supervised.csv` | 11,935 / 1,995 | Oct 1–8 | Historical quote/BTC features plus RTDS minute context; “prospective” does not mean untouched today |
| `data/experiments/p14_market_relative/p14_execution_abstention_rows.csv` | 14,238 / 678 | Oct 6–8 | Only **678 distinct market/horizon keys** repeated across policies and costs; historical simulation |
| Same directory: `p14_execution_abstention_before_price_ceiling.csv` | 8,136 / 678 | Oct 6–8 | Earlier variants of those same 678 keys |
| Same directory: `p14_p12_price_ceiling_trades.csv` | 351 / 117 | Oct 1–8 | Repeated cost scenarios; not venue trades |
| `data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv` | 33,366 / 5,588 | Sep 17–Oct 11 | Full training membership of frozen HGB3; 8,245 missing market probabilities |
| Same directory: `hgb3_expanded_v2_evaluation_predictions.csv` | 6,662 / 1,118 | Oct 7–11 | Predecessor evaluation, subsequently included in full refit; not untouched for frozen HGB3 |
| `data/research/s5_v1/inputs.json` | 1,032 / 172 | Targets Oct 12 14:41–Oct 13 21:19:30 | Frozen decisions, receipts/evidence linkage and exposed labels; R1's verified-availability development cohort |
| `data/raw/p13/btc_1m_ohlc.csv` | 19,837 / N/A | Oct 3–17 | Reported RTDS OHLC, no first delivery receipts or market IDs |
| `data/experiments/p13_model_improvement/rtds_1m_context_features.csv` | 6,866 / N/A | Oct 3–8 | Older derivative of the OHLC source; 56 missing minute returns |
| Same directory: `btc_1m_research_slice.csv`, `btc_1m_context_features.csv` | 24,661 each / N/A | Sep 15–Oct 2 | External OHLCV slice/context; context is derived, not a second feed sample |
| `data/external/bitcoin_history/btcusd_1-min_data.csv` | 7,758,900 / N/A | Jan 2012–Oct 2 2026 | External OHLCV; no Polymarket labels, first receipts or authenticated settlement-reference equivalence |

Additional P13 prediction, ablation, pre-refresh and development CSVs are individually enumerated in the JSON. Their market IDs overlap the sources above; none is automatically a fresh evaluation partition.

## Field and provenance map

**Current/raw telemetry schema (34 fields):** `observed_at, market_id, question, btc_price, strike, seconds_to_expiry, yes_bid, yes_ask, no_bid, no_ask, yes_bid_size, yes_ask_size, no_bid_size, no_ask_size, yes_token_id, no_token_id, momentum_60s, volatility_60s, reference_timestamp, reference_age_ms, reference_latency_ms, yes_book_timestamp, yes_book_age_ms, yes_book_latency_ms, no_book_timestamp, no_book_age_ms, no_book_latency_ms, yes_tick_size, yes_min_order_size, no_tick_size, no_min_order_size, snapshot_build_latency_ms, market_end_at, collector_version`.

CSV `observed_at` is collection wall time, not publication or receipt. Source reference/book timestamps are separately reported. The converter accepts epoch milliseconds/seconds and ISO time without replacing absent timestamps. All 122,340 current local CSV rows have these fields populated; that does not make all rows fresh or received in time. The cumulative VM export has 27,905 missing YES bids, 28,386 missing YES asks, 28,433 missing NO bids and 27,946 missing NO asks; corresponding sizes are also missing.

**Normalized v1.1:** exact schema is recorded in JSON. All 10,844 rows lack reference source time, book source time, received time, sizes, ticks and fee rate. `v1_decisions.iter_v1_decisions` and `v1_market_snapshots.import_v1_market_snapshots` assign ingestion at import; those timestamps must not be substituted for original receipts.

**P4/P11.5/P13:** retain normalized midpoint, relative distance, some historical returns, spreads, top sizes/imbalances and derived context. Each derivative's exact schema and missingness are in JSON. P11.5 `model_error`, `market_error`, residual/error-derived columns and labels are outcomes or exposed model diagnostics, never candidate causal predictors. P14 contains policy and simulated-result columns, not an independent quote feed.

**S5:** top-level manifest, model/training hashes, CSV-prefix hash/checkpoint, resolution registry and decision `rows`; per-row fields include condition/horizon/target, selected snapshot, probabilities, reason, label, original verification, strategy-stage flag, reconstructed features, reference/book validation, prediction/anchor observations and receipts, evidence IDs, execution quote and fee provenance where available. Missing optional sections represent an unreached/unreconstructable stage, not zero-valued data. R1 does not rerun inference or calibration.

## Retained stores and official outcomes

| Store | Current contents | Evidence limitation |
|---|---|---|
| `data/live/paper_acquisition.sqlite3` | 82,302 `acquisition(id,snapshot,raw,captured)` records, Oct 12 14:30–Oct 13 21:23 | Raw metadata, latest reference, opening reference and YES/NO book responses retained; full reference event cache is not |
| `data/paper/vnext_verified/receipts.sqlite3` | 81,984 first receipts, Oct 12 14:41–Oct 13 21:23 | Snapshot ID, source fingerprint and first receipt; real causal availability evidence |
| Same directory: `decisions.sqlite3` | 1,036 decisions / 173 markets | Four later decisions in one additional, unlabelled market lie beyond frozen S5; excluded from paired labelled research |
| Same directory: `snapshot_history.sqlite3` | 2,134 rows / 4 markets | Retention window, not full historical corpus; reconstruct from preserved CSV plus receipts |
| Same directory: `csv_tail.sqlite3` | One durable checkpoint | Source identity and acknowledged byte-prefix hash; no independent per-row publication timestamp |
| Same directory: `resolutions.sqlite3` | 171 VERIFIED registry labels | Official-source validation status/hash, but no raw resolution response, winning token or first retrieval time in this schema |
| `data/live/paper_fees.sqlite3` | 175 policies, zero conflicts | Applicable fee evidence must be joined at its actual deadline; not a price feature implied by a market ID |
| `data/normalized/market_resolutions.csv` | 3,017 markets | Gamma + Data API, VALID status, outcome/token, resolution and retrieval time |
| `data/shadow/p12_market_resolutions.csv` | 1,995 markets | Same official-source fields; Oct 1–8 source labels |
| `data/experiments/model_expansion/vm_expansion_v2/verified_resolutions.csv` | 857 markets | Official source/version, winning token and evidence ID; no retrieval field |

The source-resolution CSVs and registry support **retained official-source label availability**, not complete independent re-attestation. No raw response was fetched and no local BTC proxy substituted. All 5,588 training markets match these label sources; 171 of 172 S5 markets do. Only 3,023 of 4,616 cumulative October VM markets match retained labels. “Missing” means absent from these stores, not necessarily unresolved at the exchange. No inspected source provides Oct 14–17 official labels.

Acquisition attestation binds prices, source times, market/Up–Down tokens, expiry and top quotes to raw responses. It trusts the local HTTPS/WSS acquisition boundary; it does not cryptographically attest remote time or resist an administrator rewriting the whole store. Raw book arrays are retained sampled responses, not a continuous full-depth/order-event history. The 713 deadline-bound recorded predictions all identify `crypto_prices_twap_sixty`; supported PolyBolt code is not evidence of PolyBolt observations in this cohort.

## Overlap, drift and preservation

The cumulative October export shares all 158,284 archived October rows and all 111,417 P12 rows (full-row hashes). Its 4,616 markets overlap frozen v2 training on 2,851 IDs and S5 on all 172. The September export's 1,620 markets are already in v2 training. P4/enriched/continuous files share their 2,737 markets; P14's 678 markets are in P13 and v2 training. Do not concatenate these counts.

The separate October 17 `HGB3_V3_DATA_AUDIT.md` refers to the cumulative file under an older name; the current `_O1-17.csv` hash is `71fb69ccaa1b4751c49fe37de8830607e1ff74c532a3c5614e8b5e9776d63aa3`. Its referenced `data/research/hgb3_v3_r1_20261017_v2` outputs and some older raw filenames are absent now. That report is retained history, not proof those training artifacts currently exist. Its modeling scripts were not run. Current OHLC has 19,837 rows, versus S5's older 11,086-row inventory; the 6,866-row derivative has not automatically expanded with it.

Reproduce measurements with the [coverage report command](POLYBTC_R1_COVERAGE_REPORT.md#reproduction-and-checks). The script writes only the R1 evidence file; operational sources and frozen S5/model hashes are preserved.
