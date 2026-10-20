# R1 — Market-relative feature feasibility

2026-10-19. No feature was selected using outcome scores. Counts below use the 1,032 frozen opportunities and the **recorded prediction** branch; the separate latest-received branch gives the same 159-row matched intersection. See [coverage](POLYBTC_R1_COVERAGE_REPORT.md) and [evidence](POLYBTC_R1_EVIDENCE.json).

## Cutoffs and verification vocabulary

Let expiry be E, requested horizon H in {240,180,120,90,60,30}, and prediction cutoff T=E−H. Select the latest observation with `observed_at<=T`, first receipt `<=T`, observation lag at most 10 seconds, matching condition/tokens/expiry. Never select on later receipt or interpolate future values. The recorded branch additionally retains the original selected snapshot ID; the availability branch recomputes this selection offline without writing decisions.

“Available and causally verified” means raw inputs bind under the existing local acquisition trust contract, capture and receipt meet the cutoff, and source ages are nonnegative and within 500 ms for books / 3,000 ms for reference. It does **not** authenticate historical Windows clock accuracy or the official opening strike. “Reconstructable with verified availability” additionally requires every consumed history row to satisfy its stated deadline. Historical VM/normalized sources without receipts remain exploratory even when all numeric columns exist. All counts remain conditional on the retained official-label and strike limitations.

Write Y=(Ybid+Yask)/2, N=(Nbid+Nask)/2, q=Y/(Y+N), R=reference price, K=collector opening reference, B_s/A_s=best bid/ask size. Reject invalid/crossed quotes, nonfinite fields, and nonpositive denominators. Do not impute missing inputs in the primary paired comparison.

## Feature definitions and measured support

| Family / exact proposed definition | Fields and window | Deadline / missing behavior | Classification; supported rows / markets |
|---|---|---|---|
| Market probability q; log odds `ln(q/(1−q))`; H=E−T | Four bids/asks, expiry; current observation | Both books bound/fresh at T. Log odds requires 0<q<1; exclude endpoints unless a clipping rule is registered in R2 | Available and causally verified: **166 / 102**; all 166 have finite log odds |
| Spread `ask_s−bid_s`; relative spread `spread_s/mid_s` | Four quotes; current | Same deadline; positive midpoint for relative version | Available: **166 / 102** for absolute spreads; relative version must retain denominator check |
| Quote cost `c_s=ask_s+max(tick_Y,tick_N)` | Asks, ticks, min-order fields; current | Bound/fresh at T; this is a one-tick paper quote estimate, not a fill | Available quote inputs: **166 / 102** |
| Fee-inclusive allowance `c_s+rate/4+0.00001`; five-share paper cash fee `round(5*rate*c_s*(1−c_s),5)` | Above plus applicable cached descriptor and its receipt/effective time | Fee must be available/valid at actual evaluation deadline. Do not project later execution fee capture back to T | Exploratory cost calculation until that deadline-specific join; **49 / 41** common rows reached original execution/fee/strategy stage, not 49 assured fills |
| Top size B_s, A_s; imbalance `I_s=(B_s−A_s)/(B_s+A_s)` | Four top sizes; current | Bound with same book response at T; sizes >=0, sums >0 | Available: **166 / 102**; adds no loss to 159-row common sample |
| Liquidity asymmetry `(A_Y−A_N)/(A_Y+A_N)`; two-sided asymmetry `((B_Y+A_Y)−(B_N+A_N))/(B_Y+A_Y+B_N+A_N)` | Same four sizes; current | Same deadline; positive denominators | Available: **166 / 102** |
| Market change `q(T)−q(T−w)`, w=30 or 60 sec | Current and latest observation received by T−w, lag <=10 sec | Historical books must be fresh at **T−w**, with capture/receipt by that cutoff; same market/expiry; missing lag stays missing | Reconstructable: **48 / 34** for 30 sec; **40 / 31** for 60 sec; both plus core features **16 / 14** |
| Reference displacement `D=(R−K)/K` (also R−K in USD) | `btc_price`/`reference_price`, `strike`, reference raw event and boundary event | Reference fresh at T, K>0; boundary event within preserved ±5 sec collector rule | Available as **distance from collector TWAP proxy**, **596 / 159**; not authenticated distance from official strike |
| Existing causal 30-sec return `r30=R_current/R_anchor−1` | Anchor latest observation <=current.observed_at−30 sec, <=10 sec older; same market | Anchor received/captured by T; its source fresh at its own observation; current source fresh at T. Matches `reference_anchor_30s` exactly | Reconstructable: **564 / 159**, 560 rows labelled; with market **159 / 97**, all labelled |
| Sampled TWAP variation `V60=sqrt(sum_{j=1..6} ln(R_j/R_{j−1})²)` | Seven grid deadlines T−60,T−50,...,T; latest received observation within 10 sec at each | Each source 0–3,000 ms at its own grid deadline; bind/receive by that deadline; no cross-market borrowing or interpolation | Reconstructable **296 / 129** before market intersection. This is sampled smoothed-reference variation, not tick-level or spot realized volatility |
| Interactions `(q−0.5)*D`, `(q−0.5)*r30`, optionally H*D | Above common inputs | Union of parent requirements; no extra history | Reconstructable **159 / 97**; availability does not establish predictive value |
| Quality: `T−reference_timestamp`, `T−book_timestamp_s`, `received_at−observed_at`, `T−observed_at` | Source, collector and first-receipt times | Available by T; source-age validity enforced, not used to waive gates | Available for the corresponding verified parent; **159 / 97** jointly. May encode collection regime and selective eligibility |
| Stored `momentum_60s`, `volatility_60s` | Collector's cached feed events over a 60-sec source window | Full contributing event cache and event availability not retained | Exploratory only: **759** recorded snapshots have both values; none independently reconstructed from the complete original event cache |
| Minute BTC returns/volatility/volume context | P13 RTDS OHLC or external OHLCV, 1–30 min windows | `bar_start+60s` is an assumed completion time, not measured delivery; provider identity differs | Exploratory only; no verified first-delivery cohort established |
| True order flow, queue position, trade imbalance, continuous full-depth liquidity; authenticated official opening strike | Required event/strike evidence absent | Cannot infer from snapshots or approximate TWAP | Unavailable at the required verification level |

The top-size sum called `yes_top_depth` in historical code is **bid size plus ask size**, not executable ask quantity or full order-book depth. Quote changes are not trades. YES/NO books are sampled at different upstream times, not an atomic two-book snapshot.

The collector's stored momentum chooses the nearest feed sample to source time minus 60 sec within 8 sec; stored volatility is the population standard deviation of successive fractional returns from unique source timestamps in that window. Neither equals the proposed grid V60. Do not reuse names or claim numerical equivalence. Sixty-second same-market windows fail structurally near the first 240-sec horizon when the required market-start observation was unavailable; cross-market context would be a separate audited feature definition.

## Implementation references and limitations

- `src/polybtc/data/dataset/features.py`: midpoint, spread, size sum, imbalance and displacement calculations.
- `src/polybtc/data/causal_features_vnext.py:reference_anchor_30s`: exact existing anchor dependency and ten-second lag.
- `src/polybtc/shadow/acquisition_evidence.py:binding, attest, reference`: canonical/raw binding, reference-provider scale conversion and approximate boundary-strike rule.
- `src/polybtc/shadow/source_verification_vnext.py:_bound_result, _reference, _identity`: capture/receipt, reference semantics and token checks. Policy remains 500/3,000 ms in `data/paper_policy_vnext.py`.
- `scripts/operations/collect_vnext_local.py`: reference refreshed after sequential book requests; latest/strike evidence retained, full rolling reference cache absent.
- `scripts/research/ingest_p13_rtds_ohlc.py` and `build_p13_enriched_dataset.py`: derive minute availability as start+60 sec. This guards bar completion but cannot establish original delivery latency.
- `scripts/modeling/build_hgb3_expanded_v2_dataset.py`: some historical provider status is assigned `RTDS` by the builder; that string alone is not upstream attestation. The training CSV has 28,280 `unverified` and 5,086 `RTDS` rows.

Provider/strike and wall-clock limitations cannot be repaired by renaming fields or assigning synthetic receipt times. A future research sample can retain stronger metadata and official-resolution responses, but it cannot reconstruct genuinely unrecorded historical availability. No new feed or framework is needed merely to use top quotes, displacement and r30 already supported by the local acquisition path.
