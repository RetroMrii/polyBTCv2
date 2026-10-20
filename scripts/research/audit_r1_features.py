"""R1 availability audit only: no fitting, scoring, network or operational writes.

Reads CSVs and SQLite mode=ro snapshots. Writes only POLYBTC_R1_EVIDENCE.json.
Frozen S5 decision membership is the receipt-attested cohort; outcomes are not
used to rank features. Historical field presence is not causal verification.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import sqlite3
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
HORIZONS = (240, 180, 120, 90, 60, 30)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ro(path):
    c = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    return c


def dt(s):
    return datetime.fromisoformat(s)


def stats(values):
    a = np.asarray([x for x in values if x is not None and math.isfinite(x)], dtype=float)
    return dict(n=len(a), **({k: float(v) for k, v in zip(('min','median','p90','p99','max'), np.quantile(a,[0,.5,.9,.99,1]))} if len(a) else {}))


def finite(v, positive=False):
    return v is not None and math.isfinite(float(v)) and (not positive or float(v) > 0)


def times(series):
    n = pd.to_numeric(series, errors='coerce')
    if n.notna().sum() > len(series) * .9:
        return pd.to_datetime(n, unit='ms' if n.median() > 1e11 else 's', utc=True, errors='coerce')
    return pd.to_datetime(series, format='mixed', utc=True, errors='coerce')


def inventory(frozen):
    paths = set((ROOT/'data/raw').rglob('*.csv'))
    for folder in ('data/experiments/p13_model_improvement','data/experiments/p14_market_relative','data/experiments/model_expansion/vm_expansion_v2'):
        paths.update((ROOT/folder).rglob('*.csv'))
    paths.update((ROOT/'data/normalized').glob('p115*.csv'))
    paths.update(ROOT/p for p in ('data/normalized/snapshots.csv','data/normalized/p4_supervised_v1.csv','data/normalized/market_resolutions.csv','data/normalized/labels.csv','data/shadow/p12_market_resolutions.csv','data/live/vnext_market_snapshots.csv','data/live/paper_market_snapshots.csv'))
    train = set(pd.read_csv(ROOT/'data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv',usecols=['condition_id']).condition_id)
    labels = {r['condition_id'] for r in frozen['resolution_registry']}
    for p in (ROOT/'data/normalized/market_resolutions.csv', ROOT/'data/shadow/p12_market_resolutions.csv', ROOT/'data/experiments/model_expansion/vm_expansion_v2/verified_resolutions.csv'):
        df = pd.read_csv(p,dtype=str)
        if 'validation_status' in df:
            df = df[df.validation_status.eq('VALID')]
        labels.update(df.loc[df.label_yes.isin(['0','1']), 'condition_id'])
    exposed = {r['condition_id'] for r in frozen['rows']}
    result = []; membership = {}; row_hashes = {}
    for p in sorted(paths):
        df = pd.read_csv(p,dtype=str,keep_default_na=True,low_memory=False)
        name = p.relative_to(ROOT).as_posix()
        market_col = next((k for k in ('condition_id','market_id') if k in df),None)
        ids = set(df[market_col].dropna()) if market_col else set()
        membership[name] = ids
        ts_col = next((k for k in ('prediction_timestamp','observed_at','Timestamp','timestamp','resolved_at') if k in df),None)
        ts = times(df[ts_col]) if ts_col and len(df) else pd.Series([],dtype='datetime64[ns, UTC]')
        item = dict(path=name,sha256=sha(p),bytes=p.stat().st_size,rows=len(df),markets=len(ids),schema=list(df.columns),missing={k:int(df[k].isna().sum()) for k in df},timestamp_field=ts_col,first=str(ts.min()) if ts.notna().any() else None,last=str(ts.max()) if ts.notna().any() else None,invalid_timestamps=int(ts.isna().sum()),by_date={str(k):int(v) for k,v in ts.dt.date.value_counts().sort_index().items()},training_overlap_markets=len(ids & train),s5_overlap_markets=len(ids & exposed),official_registry_matched_markets=len(ids & labels),unlabelled_markets=len(ids-labels))
        hcol = next((k for k in ('target_horizon_seconds','horizon_seconds','horizon') if k in df),None)
        if hcol:
            item['by_horizon'] = {str(k):int(v) for k,v in df[hcol].value_counts(dropna=False).items()}
        item['providers'] = {k:{str(a):int(b) for a,b in df[k].value_counts(dropna=False).items()} for k in ('source_name','collector_version','reference_provider_status','source_dataset','resolution_source') if k in df}
        family_cols = {'market':['normalized_yes_mid','market_probability'], 'distance':['relative_distance_from_strike'], 'return30':['reference_return_30s'], 'return60':['reference_return_60s'], 'volatility':['realized_volatility_60s','volatility_60s'], 'size':['yes_top_depth','yes_ask_size'], 'imbalance':['yes_book_imbalance'], 'context':['rtds_ohlc_return_1m','btc_return_1m']}
        item['field_present_rows_exploratory'] = {k:{c:int(pd.to_numeric(df[c],errors='coerce').notna().sum()) for c in cols if c in df} for k,cols in family_cols.items()}
        pcol=next((k for k in ('normalized_yes_mid','market_probability') if k in df),None)
        if market_col and pcol and 'relative_distance_from_strike' in df and 'reference_return_30s' in df:
            cols=[pcol,'relative_distance_from_strike','reference_return_30s']
            mask=np.isfinite(df[cols].apply(pd.to_numeric,errors='coerce')).all(axis=1)
            item['exploratory_common_ABC']=dict(rows=int(mask.sum()),markets=int(df.loc[mask,market_col].nunique()),by_horizon=df.loc[mask,hcol].value_counts().to_dict() if hcol else {},by_date={str(k):int(v) for k,v in ts.loc[mask].dt.date.value_counts().items()})
        if hcol:
            item['feature_presence_by_horizon']={str(h):{c:int(pd.to_numeric(g[c],errors='coerce').notna().sum()) for cols in family_cols.values() for c in cols if c in g} for h,g in df.groupby(hcol)}
        if market_col:
            item['rows_by_market']=df[market_col].value_counts().to_dict()
        # No labels are scored. Distinct market-horizon key counts expose policy replicas.
        if market_col and hcol:
            item['unique_market_horizon_pairs'] = int(df[[market_col,hcol]].drop_duplicates().shape[0])
        if name.startswith('data/raw/') and 'market_id' in df:
            row_hashes[name] = set(pd.util.hash_pandas_object(df,index=False).astype('uint64').tolist())
            item['exact_duplicate_rows'] = len(df)-len(row_hashes[name])
            item['raw_horizon_coverage'] = raw_horizons(df,labels)
        result.append(item)
        print('Inventoried',name,len(df),flush=True)
    overlaps=[]
    names=sorted(membership)
    for i,a in enumerate(names):
        for b in names[i+1:]:
            n=len(membership[a]&membership[b])
            if n:
                x=dict(a=a,b=b,shared_markets=n)
                if a in row_hashes and b in row_hashes:
                    x['identical_row_hashes']=len(row_hashes[a]&row_hashes[b])
                overlaps.append(x)
    return result,overlaps


def external_history():
    p=ROOT/'data/external/bitcoin_history/btcusd_1-min_data.csv'
    n=0;missing=Counter();first=None;last=None;schema=[]
    for chunk in pd.read_csv(p,chunksize=250000):
        schema=list(chunk.columns);n+=len(chunk)
        missing.update({k:int(v) for k,v in chunk.isna().sum().items()})
        ts=times(chunk.Timestamp)
        lo=ts.min();hi=ts.max()
        first=lo if first is None else min(first,lo);last=hi if last is None else max(last,hi)
    return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),rows=n,schema=schema,missing=dict(missing),first=str(first),last=str(last),markets=None,provenance='External minute OHLCV; no Polymarket market IDs, original receipt or settlement labels. Context only; minute availability is not authenticated by bar timestamp.')


def raw_horizons(df, labels):
    """Exploratory event-time coverage, NOT proof of first receipt availability."""
    # pandas may retain second/microsecond resolution. Normalize units before
    # integer conversion; dividing a non-nanosecond integer by 1e9 is incorrect.
    obs=times(df.observed_at).astype('datetime64[ns, UTC]').astype('int64').to_numpy()/1e9
    end=times(df.market_end_at).astype('datetime64[ns, UTC]').astype('int64').to_numpy()/1e9
    assert np.median(obs)>1e9 and np.median(end)>1e9
    z=df.copy();z['_obs']=obs;z['_end']=end
    out={str(h):Counter() for h in HORIZONS}
    for market,g in z.groupby('market_id',sort=False):
        g=g.sort_values('_obs'); a=g._obs.to_numpy(); expiry=float(g._end.iloc[-1])
        for h in HORIZONS:
            c=out[str(h)];c['market_opportunities']+=1
            ix=np.searchsorted(a,expiry-h,side='right')-1
            if ix<0 or not 0<=expiry-h-a[ix]<=10:continue
            r=g.iloc[ix];c['observed_within_10s']+=1
            c['official_label_match']+=int(market in labels)
            for key,cols in {'quotes':['yes_bid','yes_ask','no_bid','no_ask'],'sizes':['yes_bid_size','yes_ask_size','no_bid_size','no_ask_size'],'btc':['btc_price','strike'],'stored_momentum_volatility':['momentum_60s','volatility_60s']}.items():
                c[key]+=int(all(pd.notna(r[k]) and math.isfinite(float(r[k])) for k in cols))
    return out


def databases():
    out=[]
    paths=list((ROOT/'data/paper/vnext_verified').glob('*.sqlite3'))+[ROOT/'data/live/paper_acquisition.sqlite3',ROOT/'data/live/paper_fees.sqlite3']
    for p in paths:
        item=dict(path=p.relative_to(ROOT).as_posix(),tables={})
        with closing(ro(p)) as c:
            for row in c.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
                n=row['name']; quoted='"'+n.replace('"','""')+'"'
                cols=[x['name'] for x in c.execute('PRAGMA table_info('+quoted+')')]
                info=dict(schema=cols,ddl=row['sql'],rows=c.execute('SELECT count(*) FROM '+quoted).fetchone()[0])
                for col in ('observed_at_utc','first_received_at_utc','target_at_utc','captured','resolved_at_utc'):
                    if col in cols:
                        info[col+'_range']=list(c.execute(f'SELECT min({col}),max({col}) FROM '+quoted).fetchone())
                if 'condition_id' in cols:
                    info['markets']=c.execute('SELECT count(DISTINCT condition_id) FROM '+quoted).fetchone()[0]
                item['tables'][n]=info
        out.append(item)
    return out


def cohort(frozen, latest_received=False):
    from polybtc.shadow.converter_vnext import convert_v1_tail_row
    from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore, PaperAcquisitionVerifier, binding, digest, attest
    from polybtc.data.causal_features_vnext import reference_anchor_30s
    tail=frozen['checkpoint']; wanted={r['condition_id'] for r in frozen['rows']}
    with closing(ro(ROOT/'data/paper/vnext_verified/receipts.sqlite3')) as c:
        receipts={r['snapshot_id']:r['first_received_at_utc'] for r in c.execute('SELECT * FROM receipts')}
    byid={};markets=defaultdict(list);prefix=hashlib.sha256();raw_count=0
    with Path(tail['source_path']).open('rb') as f:
        line=f.readline();prefix.update(line);headers=next(csv.reader([line.decode('utf-8-sig')]))
        while f.tell()<tail['offset_bytes']:
            off=f.tell();line=f.readline();prefix.update(line)
            sid=hashlib.sha256((tail['source_identity']+':'+str(off)+':').encode()+line).hexdigest()
            v=dict(zip(headers,next(csv.reader([line.decode()]))))
            if v['market_id'] not in wanted:continue
            raw_count+=1
            if sid not in receipts:continue
            r=convert_v1_tail_row(SimpleNamespace(row_id=sid,values=v),source_file=Path(tail['source_path']).name)
            r=replace(r,ingested_at=dt(receipts[sid]));byid[sid]=r;markets[r.condition_id].append(r)
    assert prefix.hexdigest()==frozen['csv_prefix_sha256'],'Frozen CSV prefix changed'
    print('Rebuilt frozen CSV/receipt join',len(byid),flush=True)
    for rows in markets.values():rows.sort(key=lambda x:(x.observed_at,x.snapshot_id))
    observed={k:[r.observed_at for r in v] for k,v in markets.items()}
    # Cached read-only lookups; parent verifier still enforces each distinct cutoff.
    class CachedStore(AcquisitionEvidenceStore):
        def __init__(self,path):
            super().__init__(path);self.cache={};self.connection=ro(path)
        def lookup(self,row):
            if row.snapshot_id not in self.cache:
                payload=binding(row);key=digest(payload)
                item=self.connection.execute('SELECT snapshot,raw,captured FROM acquisition WHERE id=?',(key,)).fetchone()
                if item is None:self.cache[row.snapshot_id]=None
                else:
                    if item['snapshot']!=payload:raise ValueError('Canonical snapshot mismatch')
                    self.cache[row.snapshot_id]=attest(row,json.loads(item['raw']),key,dt(item['captured']))
            return self.cache[row.snapshot_id]
    verifier=PaperAcquisitionVerifier(CachedStore(ROOT/'data/live/paper_acquisition.sqlite3'))
    def bound(r,t):return verifier._bound_result(r,t)[0] if r else None
    def select(m,t):
        rows=markets[m]
        i=bisect_right(observed[m],t)-1
        while i>=0:
            r=rows[i]
            if (t-r.observed_at).total_seconds()>10:return None
            if r.ingested_at<=t:return r
            i-=1
        return None
    def books(r,t):
        ev=bound(r,t)
        return bool(r and ev and verifier._identity(r,ev) and all(finite(getattr(r,s+'_'+k)) for s in ('yes','no') for k in ('bid','ask')) and all(0<=getattr(r,s+'_bid')<=getattr(r,s+'_ask')<=1 and 0<=(t-getattr(r,s+'_book_timestamp')).total_seconds()*1000<=500 for s in ('yes','no')) and r.yes_bid+r.yes_ask+r.no_bid+r.no_ask>0)
    def ref(r,t):return bool(r and verifier._reference(r,bound(r,t),t) and finite(r.reference_price,True))
    records=[];binding_failures=Counter();topics=Counter()
    for d in frozen['rows']:
        t=dt(d['target_at_utc']);p=byid.get(d['snapshot_id']);m=d['condition_id'];g={}
        latest=select(m,t)
        if latest_received:p=latest
        g['horizon_available']=latest is not None
        g['selected']=bool(p and p.observed_at<=t and p.ingested_at<=t and 0<=(t-p.observed_at).total_seconds()<=10 and p.market_end_at==t+timedelta(seconds=d['horizon_seconds']))
        g['market']=g['selected'] and books(p,t)
        q=(p.yes_bid+p.yes_ask)/(p.yes_bid+p.yes_ask+p.no_bid+p.no_ask) if g['market'] else None
        g['log_odds']=bool(q is not None and 0<q<1)
        g['distance']=bool(g['selected'] and ref(p,t) and finite(p.strike,True))
        g['size_spread']=bool(g['market'] and all(finite(getattr(p,s+'_'+k)) and getattr(p,s+'_'+k)>=0 for s in ('yes','no') for k in ('bid_size','ask_size')) and all(getattr(p,s+'_bid_size')+getattr(p,s+'_ask_size')>0 for s in ('yes','no')) and p.yes_ask_size+p.no_ask_size>0)
        g['tick_cost']=bool(g['market'] and all(finite(getattr(p,s+'_tick_size'),True) and finite(getattr(p,s+'_min_order_size'),True) for s in ('yes','no')))
        anchor=reference_anchor_30s(markets[m],p,decision_at=t) if g['selected'] else None
        g['return30']=False
        # Bind the anchor at the decision cutoff; apply source freshness at its
        # own observation, matching the existing causal feature contract.
        if anchor:
            g['return30']=bool(g['distance'] and anchor.market_end_at==p.market_end_at and verifier._reference(anchor,bound(anchor,t),anchor.observed_at))
        for sec in (30,60):
            lag=select(m,t-timedelta(seconds=sec))
            g['market_change'+str(sec)]=bool(g['market'] and lag and lag.market_end_at==p.market_end_at and books(lag,t-timedelta(seconds=sec)))
        grid=[(t-timedelta(seconds=i),select(m,t-timedelta(seconds=i))) for i in range(60,-1,-10)]
        g['grid_vol60']=bool(g['distance'] and all(r and r.market_end_at==p.market_end_at and ref(r,deadline) for deadline,r in grid))
        g['common_ABC']=g['market'] and g['distance'] and g['return30']
        g['common_plus_sizes']=g['common_ABC'] and g['size_spread']
        g['common_plus_lag30']=g['common_plus_sizes'] and g['market_change30']
        g['common_plus_lag60']=g['common_plus_lag30'] and g['market_change60']
        g['common_plus_gridvol']=g['common_plus_lag60'] and g['grid_vol60']
        g['s5_original_strict']=bool(d.get('model_matches') and d.get('prediction_reference_verified_now') and d.get('prediction_books_fresh') and d.get('label'))
        g['strategy_stage_subset']=bool(g['common_ABC'] and p.snapshot_id==d['snapshot_id'] and d['strategy_reached'] and d.get('fee') and d.get('execution'))
        g['stored_momentum_vol_exploratory']=bool(p and finite(p.momentum_60s) and finite(p.volatility_60s))
        rec=dict(id=d['id'],condition_id=m,horizon=d['horizon_seconds'],target=t.isoformat(),label_available=d.get('label') is not None,flags=g,snapshot_id=p.snapshot_id if p else None,recorded_snapshot_id=d['snapshot_id'],latest_available_id=latest.snapshot_id if latest else None,anchor_id=anchor.snapshot_id if anchor else None)
        if g['common_ABC']:
            rec['candidate_values']=dict(market_probability=q,distance=(p.reference_price-p.strike)/p.strike,return30=p.reference_price/anchor.reference_price-1,yes_imbalance=(p.yes_bid_size-p.yes_ask_size)/(p.yes_bid_size+p.yes_ask_size),no_imbalance=(p.no_bid_size-p.no_ask_size)/(p.no_bid_size+p.no_ask_size))
        if p:
            ev,fail=verifier._bound_result(p,t)
            if fail:binding_failures[fail]+=1
            if ev:topics[ev.reference_topic]+=1
            rec['timing']=dict(observed_at=p.observed_at.isoformat(),received_at=p.ingested_at.isoformat(),capture_at=ev.captured_at_utc.isoformat() if ev else None,receipt_delay_ms=(p.ingested_at-p.observed_at).total_seconds()*1000,observation_to_target_ms=(t-p.observed_at).total_seconds()*1000,**{s+'_age_at_target_ms':(t-getattr(p,s+'_timestamp')).total_seconds()*1000 for s in ('reference','yes_book','no_book')})
        records.append(rec)
        if len(records)%200==0:print('Audited decisions',len(records),flush=True)
    verifier.store.connection.close()
    def coverage(rows):
        return dict(opportunities=len(rows),markets=len({r['condition_id'] for r in rows}),labelled=sum(r['label_available'] for r in rows),features={k:dict(rows=sum(r['flags'][k] for r in rows),markets=len({r['condition_id'] for r in rows if r['flags'][k]}),labelled_rows=sum(r['flags'][k] and r['label_available'] for r in rows)) for k in records[0]['flags']})
    keys=list(records[0]['flags'])
    return dict(frozen_prefix_sha256=prefix.hexdigest(),source_rows_in_cohort=raw_count,receipt_matched_rows=len(byid),summary=coverage(records),by_horizon={str(h):coverage([r for r in records if r['horizon']==h]) for h in HORIZONS},by_date={day:coverage([r for r in records if r['target'].startswith(day)]) for day in sorted({r['target'][:10] for r in records})},by_market={m:coverage([r for r in records if r['condition_id']==m]) for m in sorted(wanted)},intersections={a:{b:sum(r['flags'][a] and r['flags'][b] for r in records) for b in keys} for a in keys},timing={k:stats([r['timing'][k] for r in records if 'timing' in r]) for k in ('receipt_delay_ms','observation_to_target_ms','reference_age_at_target_ms','yes_book_age_at_target_ms','no_book_age_at_target_ms')},binding_failures=dict(binding_failures),reference_topics=dict(topics),rows=records)


def main():
    frozen_path=ROOT/'data/research/s5_v1/inputs.json'
    protected=[frozen_path,ROOT/'data/models/main/hgb3_expanded_v2.joblib']+list((ROOT/'docs').glob('POLYBTC_S5_*'))
    before={p.relative_to(ROOT).as_posix():sha(p) for p in protected}
    frozen=json.loads(frozen_path.read_text())
    inv,overlaps=inventory(frozen)
    evidence=dict(version='research_r1_feature_audit_v1',generated_at=datetime.now(timezone.utc).isoformat(),script_sha256=sha(Path(__file__)),scope='No model fitting or outcome scoring. Frozen S5 receipt cohort; historical event-time coverage is exploratory.',inventory=inv,overlaps=overlaps,external_history=external_history(),databases=databases(),verified_cohort=cohort(frozen),latest_received_reconstruction=cohort(frozen,latest_received=True),protected_hashes=before)
    assert all(sha(ROOT/p)==s for p,s in before.items()),'Protected input changed'
    c=evidence['verified_cohort']
    assert c['summary']['features']['s5_original_strict']['rows']==159
    assert {r['id'] for r in c['rows'] if r['flags']['common_ABC']}=={r['id'] for r in c['rows'] if r['flags']['s5_original_strict']}
    for r in c['rows']:
        if r['flags']['common_ABC']:
            assert dt(r['timing']['received_at'])<=dt(r['target'])
            assert all(0<=r['timing'][s+'_age_at_target_ms']<=limit for s,limit in [('reference',3000),('yes_book',500),('no_book',500)])
    evidence['validation']={'s5_membership_exact_match':True,'causal_deadlines_and_freshness_asserted':True,'protected_hashes_unchanged':True}
    output=ROOT/'docs/POLYBTC_R1_EVIDENCE.json'
    output.write_text(json.dumps(evidence,indent=2,allow_nan=False,default=str)+'\n',encoding='utf-8')
    print(json.dumps(evidence['verified_cohort']['summary'],indent=2))


def self_test():
    # Numeric event units and ISO timestamp resolution must agree.
    expected=pd.Timestamp('2026-10-13T00:01:00Z')
    assert times(pd.Series([str(int(expected.timestamp()*1000))])).iloc[0]==expected
    assert times(pd.Series([expected.isoformat()])).iloc[0]==expected
    rows=[]
    for market,stamp in [('a','00:00:55'),('a','00:01:01'),('b','00:01:01')]:
        r=dict(market_id=market,observed_at='2026-10-13T'+stamp+'Z',market_end_at='2026-10-13T00:05:00Z')
        r.update({k:'1' for k in ('yes_bid','yes_ask','no_bid','no_ask','yes_bid_size','yes_ask_size','no_bid_size','no_ask_size','btc_price','strike','momentum_60s','volatility_60s')})
        if stamp=='00:00:55':r['no_ask']=np.nan
        rows.append(r)
    c=raw_horizons(pd.DataFrame(rows),{'a'})['240']
    assert c['market_opportunities']==2 and c['observed_within_10s']==1
    assert c['quotes']==0 and c['official_label_match']==1
    print('R1 checks passed: timestamp units, no future selection, missing quote exclusion, market denominator.')


if __name__=='__main__':
    if '--self-test' in sys.argv:self_test()
    else:main()
