"""Render research-only reports from the frozen v3/R1 evidence; no operational writes."""
import argparse, json
from pathlib import Path
import pandas as pd
import hgb3_v3_r1 as a

def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+''.join('| '+' | '.join(str(v) for v in row)+' |\n' for row in rows)

def write(name,text):
    p=a.ROOT/'docs'/name
    with p.open('x',encoding='utf-8') as f: f.write(text)

def data_report(out):
    x=json.loads((out/'audit.json').read_text()); o=pd.read_csv(out/'horizon_observations.csv'); d=pd.read_csv(out/'hgb3_expanded_v3_dataset.csv')
    s=json.loads((a.ROOT/'docs/POLYBTC_S5_EVIDENCE.json').read_text())
    rows=s['prospective_rows']; cutoff=pd.Timestamp('2026-10-13T14:30:00Z')
    # Preserve the original S5 membership instead of relabelling its test as untouched.
    s5groups={}
    for label in ['calibration','evaluation']:
        ids=set()
        for r in rows:
            t=r.get('prediction_timestamp') or r.get('target') or r.get('target_at_utc')
            if t and ((pd.Timestamp(t)<cutoff)==(label=='calibration')): ids.add(r['condition_id'])
        s5groups[label]={'markets':len(ids),'download_overlap':len(ids&set(o.condition_id)),'new_training_overlap':len(ids&set(d.loc[d.new_to_v2==True,'condition_id']))}
    raw=pd.read_csv(a.ROOT/x['file'],dtype=str,keep_default_na=False)
    baseids=set(pd.read_csv(a.BASE,usecols=['condition_id']).condition_id)
    newraw=raw[~raw.market_id.isin(baseids)]
    source_dates=pd.to_datetime(raw.observed_at,utc=True).dt.strftime('%Y-%m-%d')
    newlabelled=d[d.new_to_v2==True]
    labeldata=json.loads((out/'label_capture.json').read_text())
    newlabelids=set(newlabelled.condition_id)
    first_new=min(newlabelled.prediction_timestamp); last_new=max(newlabelled.prediction_timestamp)
    extras={'s5_partition_overlap':s5groups,'new_raw_rows':len(newraw),'first_added_prediction':first_new,'last_added_prediction':last_new,
       'actual_observation_range_intended_dates':{'rows':int((source_dates>='2026-10-11').sum()),'markets':raw.loc[source_dates>='2026-10-11','market_id'].nunique()},
       'added_label_record_sources':dict(pd.Series([r['source'] for r in labeldata['records'] if r['market'] in newlabelids]).value_counts()),
       'known_independent_vm_receipt_rows':0,'valid_label_capture_sha256':a.digest(out/'label_capture.json')}
    a.save(out/'audit_supplement.json',extras)
    provenance='''The CSV reports collector version 1.4. It contains repeated market observations, not precomputed labelled examples. Reference and book timestamps are original epoch milliseconds; `observed_at` is the collector's wall-clock observation. No independent CSV publication time, first receipt, immutable raw response or VM deployment-code hash is present. The exact VM collector build and its clock accuracy cannot be authenticated from this export. Current local collector code is not evidence of the deployed VM build. Reference-provider/strike semantics retain the historical RTDS/TWAP qualification; these are not newly authenticated official opening-strike records.

Existing official-source labels are accepted at their retained validation level: `polymarket_gamma+data_api_v2`, VALID/VERIFIED/SETTLED, binary outcome and recorded resolution time. CSV winning tokens are checked against the snapshot token mapping; registry-only records lack winning tokens/raw response/retrieval timestamps and inherit that limitation. They are not BTC-price proxies or independently re-fetched labels. Missing labels mean **no valid retained label**, not proof that the exchange still considers the market unresolved. No network collection or operational store update was performed.
'''
    overlaprows=[[r['path'],r.get('rows'),r.get('markets'),r.get('market_overlap'),r.get('identical_content_rows','not comparable')] for r in x['overlap']]
    dates=[[k,n,x['date_markets'][k]] for k,n in x['date_rows'].items()]
    missing=[[k,v] for k,v in x['missing_fields'].items() if v]
    newby=[[k,v['rows'],v['markets']] for k,v in x['added_by_date'].items()]
    ages=[[k,v['future'],v['stale'],round(v['quantiles_ms']['0.5'],2),round(v['quantiles_ms']['0.99'],2)] for k,v in x['source_ages'].items()]
    text=f'''# HGB3 v3: download and training-data audit

Research-only · 2026-10-17 · Successful evidence version `{out.name}`. Audit completed before model fitting. The original experiment card was recorded before new label inspection; the timestamp-parser failure in the preceding v1 attempt is explicitly marked invalid and had no model fit.

## Result

The cumulative download contains **{x['rows']:,} observations / {x['markets']:,} markets**. It adds 98,165 rows beyond the exact 158,284-row archived prefix. It contains **{x['not_in_v2_markets']:,} market IDs absent from v2**, but only **{x['added_markets']} new eligible labelled markets / {x['added_rows']:,} examples** can be added. Their predictions run **{first_new} through {last_new}**. The expanded dataset is **{x['expanded_rows']:,} rows / {x['expanded_markets']:,} markets**, preserving v2's original 33,366 examples and all 5,588 markets.

No October 14–17 market has a valid label in the inspected stores. This expansion therefore does **not** train through October 17. Those observations support unlabelled feature-feasibility counts only. Label procurement is the immediate data gap; it is not solved by assuming local BTC direction.

## File identity and schema

- Path: `{x['file']}`; {x['bytes']:,} bytes.
- SHA-256: `{x['sha256']}`.
- Actual observation UTC: {x['observation_min']} to {x['observation_max']}.
- Market expiry UTC: {x['expiry_min']} to {x['expiry_max']}.
- Derived eligible prediction targets UTC: {x['prediction_min']} to {x['prediction_max']}. There is no prediction timestamp column in the raw file; these are reconstructed as expiry minus registered horizon.
- Intended October 11–17 subset: {extras['actual_observation_range_intended_dates']['rows']:,} observations / {extras['actual_observation_range_intended_dates']['markets']:,} markets. This subset overlaps prior v2 training on October 11.
- Field count: {len(x['schema'])}; exact schema: `{', '.join(x['schema'])}`.

{provenance}
## Calendar coverage (raw observations)

{table(['UTC date','Rows','Distinct markets'],dates)}

## Exact overlap and deduplication

{table(['File','Rows','Markets','IDs shared with download','Identical full rows'],overlaprows)}

`old2` is an exact ordered content prefix, not merely a date overlap. Its hash `5c37788cba899ceed7f195c8161f28dd00ce1ea772cbc9bbc67e4369f8c443ea` matches v2's recorded original VM source hash. Other derivative research files inherit source membership and must not be pooled as new observations. The old transaction-history export has no stable condition ID and cannot prove ID overlap by market name.

S5 captured-market overlap: **{x['s5_market_overlap']}**; new training additions overlap **{x['added_s5_overlap']}** of those already exposed markets. Strict S5 partition membership overlap: `{s5groups}`. No S5 period is described as untouched.

Deduplication first protects the old training membership, then admits only wholly new market IDs, at most one selected observation per market/horizon. It never adds another copy of an old market/horizon from overlapping raw/P12 files. Selected snapshot and anchor line numbers and content fingerprints are retained in `horizon_observations.csv`; the raw source SHA authenticates those line references. The pandas content fingerprint is an identity aid, not a cryptographic provenance signature.

## Integrity and exclusions

Malformed CSV rows: {x['malformed_csv_rows']}; invalid observation/expiry timestamps: {x['invalid_timestamp_rows']}; malformed numeric cells: {sum(x['malformed_numeric'].values())}; identical duplicate rows: {x['identical_duplicate_rows']}; duplicate market/observation rows: {x['duplicate_market_observation_rows']}. Global backwards observations: {x['global_backward_observations']}; within-market backwards observations: {x['per_market_backward_observations']}. Market/expiry/token-map conflicts: {len(x['identity_conflict_markets'])}; conflicting label markets: {len(x['label_conflicts'])}. Complete per-field counts and token bindings remain in the machine evidence/raw source.

Missing quote fields (denominator {x['rows']:,}; other listed raw fields have no missing cells):

{table(['Field','Missing observations'],missing)}

There are {x['markets_with_retained_valid_label']:,} downloaded markets with retained valid labels and {x['markets_missing_retained_label']:,} without. {x['known_not_expired_at_last_observation']} market had not expired at the final recorded observation; the remaining missing-label markets are not assigned outcomes. For the 1,765 non-v2 markets there are 10,590 potential horizon examples: **1,517 admitted**, **8,940 missing-label exclusions**, **73 missing/late horizons**, **60 missing 30-second anchors**. These first-failure reasons are mutually exclusive at market/horizon level, not raw-row exclusions.

All downloaded markets: {x['horizon_candidates']:,} candidate horizons, {x['feature_eligible_horizons']:,} structurally feature-eligible, {x['exclusions']['missing_or_late_horizon']} missing/late horizons and {x['exclusions']['missing_30s_anchor']} missing anchors. Old overlapping examples are not re-added even if reconstructed.

{table(['Horizon seconds','Structurally eligible rows'],sorted(x['horizon_coverage'].items(),key=lambda z:-int(z[0])))}

## Training contract and freshness distinction

The research builder uses the same latest-at/before-target and 10-second maximum lag rule as `build_p4_extension_from_p12.py`. The 30-second reference anchor is the latest same-market observation at/before selected observation minus 30 seconds, with at most 10 seconds additional lag. Features are `(reference-strike)/strike`, horizon seconds and `reference/anchor_reference-1`. Positive finite inputs, market interval, token consistency, binary validated labels and no known future reference are required. New examples retain actual snapshot/anchor identities. Existing baseline rows retain their original features, labels, source cohorts and provenance qualification; no modern verification is retroactively asserted.

Raw ages recomputed from original source timestamps at observation (reference limit 3,000 ms; books 500 ms):

{table(['Source','Future','Stale observations','Median ms','p99 ms'],ages)}

Reported reference age can differ from age at final observation by up to {x['source_ages']['reference']['reported_age_max_absolute_difference_ms']:.2f} ms. Treat it as a different acquisition-stage measurement, not an authoritative final age. Book-age differences are at most about 9 ms. No source times were altered. The forecast development contract is broader than the operational execution freshness contract; stale-at-target rows are not called executable. Freshness subsets are reported separately in R1 and comparison evidence. Unknown receipt availability blocks fully verified causal/executable claims even where recorded source ages pass.

## Added training cohort

{table(['Prediction UTC date','Added rows','Added markets'],newby)}

Expanded dataset: `{out.relative_to(a.ROOT)}/hgb3_expanded_v3_dataset.csv`.

SHA-256: `{x['dataset_sha256']}`. Label capture SHA-256: `{extras['valid_label_capture_sha256']}`. Exact exclusions, membership, source hashes, field counts and feature coverage are in the same versioned directory. No reserved untouched final-test market is included: the entire download is explicitly development data, and new future observations require a separate frozen protocol.

## Reproduction

From `H:\\PolyBTCv2`, use a **new output directory**; outputs refuse overwrite. Reuse the frozen label capture to avoid dependence on a later changing registry. Input raw and v2 dataset hashes must match this report.

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
.\\.venv-execution\\Scripts\\python.exe -B scripts/research/hgb3_v3_r1.py audit --output data/research/hgb3_v3_r1_reproduction_01 --labels-capture data/research/{out.name}/label_capture.json
```

This command reads original data and writes only new offline research files. It does not run a collector, resolver, paper runtime or trading service.
'''
    write('HGB3_V3_DATA_AUDIT.md',text)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('phase',choices=['data']); p.add_argument('--output',type=Path,default=a.DEFAULT)
    args=p.parse_args(); data_report(args.output)
