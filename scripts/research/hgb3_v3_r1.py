"""Offline, versioned HGB3 expansion / R1 audit. Never opens an operational DB writable."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, platform, sqlite3
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'data/research/hgb3_v3_r1_20261017_v2'
BASE = ROOT / 'data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv'
MODEL = ROOT / 'data/models/main/hgb3_expanded_v2.joblib'
FEATURES = ['relative_distance_from_strike','target_horizon_seconds','reference_return_30s']
HORIZONS = [240,180,120,90,60,30]
LABEL_CAPTURE = None

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def save(p,obj):
    with Path(p).open('x',encoding='utf-8') as f:
        json.dump(obj,f,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))

def iso(x): return pd.Timestamp(x,unit='s',tz='UTC').isoformat()
def seconds(s): return pd.to_datetime(s,utc=True,errors='coerce').astype('datetime64[ns, UTC]').astype('int64')/1e9
def latest(t,cutoff):
    i=int(np.searchsorted(t,cutoff,side='right'))-1
    return i if i>=0 and 0<=cutoff-t[i]<=10 else None

def protected():
    paths=[MODEL,MODEL.with_suffix('.json'),BASE]
    paths+=list((ROOT/'docs').glob('POLYBTC_S5*'))
    paths+=list((ROOT/'data/research/s5_v1').rglob('*'))
    paths+=list((ROOT/'src').rglob('*.py'))
    paths+=list((ROOT/'scripts/operations').rglob('*'))
    paths+=list((ROOT/'data/raw/v1.1').glob('*.csv'))
    return {str(p.relative_to(ROOT)):digest(p) for p in paths if p.is_file()}

def get_labels(out):
    records=[]; inventory=[]
    if LABEL_CAPTURE is not None:
        captured=json.loads(Path(LABEL_CAPTURE).read_text())
        records=captured['records']; inventory=captured['sources']
        save(out/'label_capture.json',captured)
        return consolidate_labels(records), label_conflicts(records), inventory
    paths=[ROOT/'data/normalized/market_resolutions.csv', ROOT/'data/shadow/p12_market_resolutions.csv',
           BASE.parent/'verified_resolutions.csv']
    for p in paths:
        if not p.exists(): continue
        frame=pd.read_csv(p,dtype=str).fillna('')
        inventory.append({'path':str(p.relative_to(ROOT)),'sha256':digest(p),'rows':len(frame)})
        for r in frame.to_dict('records'):
            if r.get('label_yes') not in ('0','1'): continue
            if r.get('validation_status','VALID')!='VALID': continue
            if r.get('resolution_source')!='polymarket_gamma+data_api_v2': continue
            if not r.get('resolved_at') or not r.get('winning_token_id'): continue
            records.append(dict(market=r['condition_id'].lower(),label=int(r['label_yes']),resolved=r['resolved_at'],
                retrieved=r.get('retrieved_at',''),token=r['winning_token_id'],source=str(p.relative_to(ROOT)),
                evidence=r.get('evidence_id',''),status='VALID'))
    for p in [ROOT/'data/paper/vnext_verified/resolutions.sqlite3',ROOT/'data/shadow/vnext_local_live/resolutions.sqlite3']:
        if not p.exists(): continue
        with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as c:
            c.execute('PRAGMA query_only=ON')
            rows=pd.read_sql_query('SELECT * FROM resolutions',c).to_dict('records')
        inventory.append({'path':str(p.relative_to(ROOT)),'rows':len(rows),'mode':'read-only snapshot; captured records hashed separately'})
        for r in rows:
            if r['settlement_status'] not in ('VERIFIED','SETTLED') or not r['evidence_id']: continue
            if 'polymarket' not in r['evidence_source'].lower(): continue
            records.append(dict(market=r['condition_id'].lower(),label=int(r['label_yes']),resolved=r['resolved_at_utc'],
                retrieved='',token='',source=str(p.relative_to(ROOT)),evidence=r['evidence_id'],status=r['settlement_status']))
    save(out/'label_capture.json',{'sources':inventory,'records':records})
    return consolidate_labels(records),label_conflicts(records),inventory

def label_conflicts(records):
    by=defaultdict(list)
    for r in records: by[r['market']].append(r)
    conflicts=[]
    for m,rr in by.items():
        if len({r['label'] for r in rr})!=1 or len({r['token'] for r in rr if r['token']})>1:
            conflicts.append(m)
    return conflicts

def consolidate_labels(records):
    conflicts=set(label_conflicts(records)); good=defaultdict(list)
    for r in records:
        if r['market'] not in conflicts: good[r['market']].append(r)
    return dict(good)

def audit(out):
    out.mkdir(parents=True,exist_ok=True)
    if not (out/'preservation_before.json').exists(): save(out/'preservation_before.json',protected())
    assert digest(MODEL)=='42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4'
    # Discover the largest cumulative CSV by content; archive equality checked below.
    candidates=list((ROOT/'data/raw/v1.1').glob('*.csv'))
    source=max(candidates,key=lambda p:p.stat().st_size)
    raw=pd.read_csv(source,dtype=str,keep_default_na=False)
    original_fields=list(raw.columns)
    obs=pd.to_datetime(raw.observed_at,utc=True,errors='coerce')
    end=pd.to_datetime(raw.market_end_at,utc=True,errors='coerce')
    raw['market_id']=raw.market_id.str.lower()
    ids=set(raw.market_id)
    base=pd.read_csv(BASE,dtype=str,keep_default_na=False)
    baseids=set(base.condition_id)
    overlaps=[]
    fingerprints=set(pd.util.hash_pandas_object(raw[original_fields],index=False).tolist())
    for p in candidates:
        if p==source: continue
        df=pd.read_csv(p,dtype=str,keep_default_na=False)
        col=next((c for c in ['market_id','condition_id'] if c in df),None)
        record={'path':str(p.relative_to(ROOT)),'sha256':digest(p),'rows':len(df),'markets':df[col].nunique() if col else None,
                'market_overlap':len(set(df[col].str.lower())&ids) if col else None,'schema':list(df.columns)}
        if list(df.columns)==original_fields:
            record['identical_content_rows']=sum(int(v in fingerprints) for v in pd.util.hash_pandas_object(df,index=False))
            record['exact_prefix']=raw[original_fields].iloc[:len(df)].reset_index(drop=True).equals(df)
        overlaps.append(record)
    for p in [ROOT/'data/normalized/snapshots.csv',ROOT/'data/normalized/p4_supervised_v1.csv',
              BASE.parent.parent/'hgb3_expanded_v1.csv',ROOT/'data/raw/p12/btc_5m_market_snapshots_p12.csv',BASE]:
        if not p.exists(): continue
        head=pd.read_csv(p,nrows=0)
        col=next((c for c in ['condition_id','market_id'] if c in head),None)
        if col:
            df=pd.read_csv(p,usecols=[col],dtype=str)
            overlaps.append({'path':str(p.relative_to(ROOT)),'sha256':digest(p),'rows':len(df),
                             'markets':df[col].nunique(),'market_overlap':len(set(df[col].str.lower())&ids)})
    s5=json.loads((ROOT/'data/research/s5_v1/inputs.json').read_text())
    def find_ids(obj):
        found=set()
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k in ('condition_id','market_id') and isinstance(v,str): found.add(v.lower())
                found |= find_ids(v)
        elif isinstance(obj,list):
            for v in obj: found |= find_ids(v)
        return found
    s5ids=find_ids(s5)
    labels,conflicts,labelinv=get_labels(out)
    numcols=[c for c in original_fields if c not in ['observed_at','market_id','question','yes_token_id','no_token_id','market_end_at','collector_version']]
    numeric=raw[numcols].apply(pd.to_numeric,errors='coerce')
    malformed={c:int((raw[c].ne('')&numeric[c].isna()).sum()) for c in numcols}
    structural=0
    with source.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.reader(f); n=len(next(reader))
        structural=sum(len(r)!=n for r in reader)
    raw['t']=seconds(obs); raw['end']=seconds(end)
    for c in numcols: raw[c]=numeric[c]
    raw['line']=np.arange(len(raw))+2
    raw['content_id']=pd.util.hash_pandas_object(raw[original_fields],index=False).astype(str)
    duplicate_key=raw.duplicated(['market_id','observed_at'],keep=False)
    conflictobs=set(raw.loc[duplicate_key].groupby(['market_id','observed_at']).filter(lambda g:g.content_id.nunique()>1).market_id)
    identity_bad=set(raw.groupby('market_id').filter(lambda g:any(g[c].nunique()!=1 for c in ['market_end_at','yes_token_id','no_token_id'])).market_id)
    identity_bad |= set(raw.loc[~raw.market_id.str.fullmatch(r'0x[0-9a-f]{64}') | ~raw.yes_token_id.str.fullmatch(r'\d+') | ~raw.no_token_id.str.fullmatch(r'\d+') | raw.yes_token_id.eq(raw.no_token_id),'market_id'])
    quality={'rows':len(raw),'markets':len(ids),'schema':original_fields,'schema_type':'raw repeated observations, not supervised horizon examples',
      'file':str(source.relative_to(ROOT)),'bytes':source.stat().st_size,'sha256':digest(source),
      'observation_min':str(obs.min()),'observation_max':str(obs.max()),'expiry_min':str(end.min()),'expiry_max':str(end.max()),
      'date_rows':obs.dt.strftime('%Y-%m-%d').value_counts().sort_index().to_dict(),
      'date_markets':raw.assign(date=obs.dt.strftime('%Y-%m-%d')).groupby('date').market_id.nunique().to_dict(),
      'missing_fields':{c:int(raw[c].isna().sum() if c in numcols else raw[c].eq('').sum()) for c in original_fields},
      'malformed_numeric':malformed,'malformed_csv_rows':structural,'invalid_timestamp_rows':int((obs.isna()|end.isna()).sum()),
      'identical_duplicate_rows':int(pd.Series(list(pd.util.hash_pandas_object(raw[original_fields],index=False))).duplicated().sum()),
      'duplicate_market_observation_rows':int(duplicate_key.sum()),'conflicting_observation_markets':sorted(conflictobs),
      'identity_conflict_markets':sorted(identity_bad),'global_backward_observations':int((raw.t.diff()<0).sum()),
      'per_market_backward_observations':int((raw.groupby('market_id').t.diff()<0).sum()),
      'v2_market_overlap':len(ids&baseids),'not_in_v2_markets':len(ids-baseids),'s5_market_overlap':len(ids&s5ids),
      's5_captured_markets':len(s5ids),'overlap':overlaps,'labels':labelinv,'label_conflicts':conflicts,
      'markets_with_retained_valid_label':len(ids&set(labels)), 'markets_missing_retained_label':len(ids-set(labels)),
      'collector_versions':raw.collector_version.value_counts().to_dict(),'receipt_availability':'not recorded in VM CSV',
      'known_not_expired_at_last_observation':int(raw.groupby('market_id').end.first().gt(raw.t.max()).sum())}
    quality['source_ages']={}
    for name,limit in [('reference',3000),('yes_book',500),('no_book',500)]:
        age=raw.t*1000-raw[name+'_timestamp']
        quality['source_ages'][name]={'present':int(age.notna().sum()),'future':int((age<0).sum()),'stale':int((age>limit).sum()),
           'quantiles_ms':{str(k):float(v) for k,v in age.dropna().quantile([0,.5,.9,.99,1]).items()},
           'reported_age_max_absolute_difference_ms':float((age-raw[name+'_age_ms']).abs().max())}
    exclusion=[]; observations=[]; added=[]
    for m,g in raw.groupby('market_id',sort=True):
        g=g.sort_values(['t','line']).drop_duplicates('observed_at').reset_index(drop=True)
        t=g.t.to_numpy(); expiry=float(g.end.iloc[0]); new=m not in baseids
        for h in HORIZONS:
            target=expiry-h; reason=None; i=latest(t,target)
            if m in identity_bad or m in conflictobs: reason='identity_or_observation_conflict'
            elif i is None: reason='missing_or_late_horizon'
            if reason is None:
                r=g.iloc[i]; j=latest(t,float(r.t)-30)
                if j is None: reason='missing_30s_anchor'
                elif not all(np.isfinite(x) and x>0 for x in [r.btc_price,r.strike,g.iloc[j].btc_price]): reason='invalid_reference_or_strike'
                elif not (expiry-300<=r.t<=target<expiry): reason='outside_market_interval'
                elif r.reference_timestamp/1000>r.t or g.iloc[j].reference_timestamp/1000>g.iloc[j].t: reason='future_reference_at_observation'
            if reason:
                exclusion.append({'market':m,'horizon':h,'new_to_v2':new,'reason':reason}); continue
            a=g.iloc[j]; values={c:r[c] for c in ['yes_bid','yes_ask','no_bid','no_ask','yes_bid_size','yes_ask_size','no_bid_size','no_ask_size']}
            quote=all(np.isfinite(values[c]) for c in ['yes_bid','yes_ask','no_bid','no_ask']) and 0<=r.yes_bid<=r.yes_ask<=1 and 0<=r.no_bid<=r.no_ask<=1 and (r.yes_bid+r.yes_ask+r.no_bid+r.no_ask)>0
            quote=bool(quote and r.yes_book_timestamp/1000<=r.t and r.no_book_timestamp/1000<=r.t)
            mid=(r.yes_bid+r.yes_ask)/(r.yes_bid+r.yes_ask+r.no_bid+r.no_ask) if quote else np.nan
            rr=labels.get(m,[]); label_reason=None
            if m in conflicts: label_reason='conflicting_labels'
            elif not rr: label_reason='missing_valid_retained_label'
            elif any(z['token'] and z['token']!=(r.yes_token_id if z['label'] else r.no_token_id) for z in rr): label_reason='winner_token_mismatch'
            elif any(pd.Timestamp(z['resolved']).timestamp()<expiry for z in rr): label_reason='resolution_before_expiry'
            label=rr[0]['label'] if rr and label_reason is None else np.nan
            rec=dict(condition_id=m,target_horizon_seconds=h,prediction_timestamp=iso(target),snapshot_observed_at=r.observed_at,
              market_end_at=r.market_end_at,relative_distance_from_strike=r.btc_price/r.strike-1,reference_return_30s=r.btc_price/a.btc_price-1,
              normalized_yes_mid=mid,label_yes=label,label_version='p3_v1',source_dataset='vm_v3_development',reference_provider_status='unverified_VM_reported_reference',
              feature_version='hgb3_three_feature_v1',dataset_version='hgb3_expanded_v3_research_v1',anchor_observed_at=a.observed_at,
              source_line=int(r.line),anchor_line=int(a.line),observation_identity=r.content_id,anchor_identity=a.content_id,
              label_resolved_at=max((z['resolved'] for z in rr),default=''),label_retrieved_at=max((z['retrieved'] for z in rr),default=''),
              new_to_v2=new,provenance_quality='observation_time_only_no_receipt',label_eligible=label_reason is None,
              label_reason=label_reason or '',reference_timestamp=r.reference_timestamp,yes_book_timestamp=r.yes_book_timestamp,no_book_timestamp=r.no_book_timestamp,
              recorded_fresh=bool(0<=target*1000-r.reference_timestamp<=3000 and 0<=target*1000-r.yes_book_timestamp<=500 and 0<=target*1000-r.no_book_timestamp<=500 and 0<=a.t*1000-a.reference_timestamp<=3000),**values)
            sizes=np.array([r.yes_bid_size,r.yes_ask_size,r.no_bid_size,r.no_ask_size],float)
            depth=bool(np.isfinite(sizes).all() and (sizes>=0).all() and sizes[:2].sum()>0 and sizes[2:].sum()>0)
            rec['depth_available']=depth
            rec['yes_imbalance']=(sizes[0]-sizes[1])/sizes[:2].sum() if depth else np.nan
            rec['no_imbalance']=(sizes[2]-sizes[3])/sizes[2:].sum() if depth else np.nan
            for lag in [30,60]:
                k=latest(t,float(r.t)-lag); change=np.nan
                if k is not None:
                    z=g.iloc[k]; denom=z.yes_bid+z.yes_ask+z.no_bid+z.no_ask
                    if quote and 0<=z.yes_bid<=z.yes_ask<=1 and 0<=z.no_bid<=z.no_ask<=1 and denom>0 and z.yes_book_timestamp/1000<=z.t and z.no_book_timestamp/1000<=z.t:
                        change=mid-(z.yes_bid+z.yes_ask)/denom
                rec[f'mid_change_{lag}s']=change
            hist=g[(g.t>=r.t-60)&(g.t<=r.t)]
            validvol=len(hist)>=5 and hist.t.iloc[0]<=r.t-50 and hist.t.diff().dropna().max()<=10 and (hist.btc_price>0).all() and (hist.reference_timestamp/1000<=hist.t).all()
            vol=float(np.sqrt(np.square(np.diff(np.log(hist.btc_price.to_numpy()))).sum())) if validvol else np.nan
            rec['realized_volatility_60s']=vol
            rec['vol_adjusted_distance']=rec['relative_distance_from_strike']/vol if np.isfinite(vol) and vol>0 else np.nan
            observations.append(rec)
            if new:
                if label_reason: exclusion.append({'market':m,'horizon':h,'new_to_v2':True,'reason':label_reason})
                else: added.append(rec)
    obsdf=pd.DataFrame(observations); add=pd.DataFrame(added)
    obsdf.to_csv(out/'horizon_observations.csv',index=False,mode='x')
    pd.DataFrame(exclusion).to_csv(out/'exclusions.csv',index=False,mode='x')
    # Preserve every baseline value and cohort designation; extra provenance fields are unknown, not fabricated.
    base['provenance_quality']='legacy_training_provenance_no_modern_receipt_claim'
    base['new_to_v2']=False
    expanded=pd.concat([base,add],ignore_index=True)
    assert not expanded.duplicated(['condition_id','target_horizon_seconds']).any()
    assert set(add.condition_id).isdisjoint(baseids) if len(add) else True
    expanded.to_csv(out/'hgb3_expanded_v3_dataset.csv',index=False,mode='x')
    quality['horizon_candidates']=len(ids)*6
    quality['feature_eligible_horizons']=len(obsdf)
    quality['horizon_coverage']=obsdf.groupby('target_horizon_seconds').size().to_dict()
    quality['prediction_min']=obsdf.prediction_timestamp.min(); quality['prediction_max']=obsdf.prediction_timestamp.max()
    quality['exclusions']=dict(Counter(r['reason'] for r in exclusion))
    quality['new_exclusions']=dict(Counter(r['reason'] for r in exclusion if r['new_to_v2']))
    quality['added_rows']=len(add); quality['added_markets']=add.condition_id.nunique() if len(add) else 0
    quality['added_by_date']=add.groupby(add.prediction_timestamp.str[:10]).agg(rows=('condition_id','size'),markets=('condition_id','nunique')).to_dict('index') if len(add) else {}
    quality['expanded_rows']=len(expanded); quality['expanded_markets']=expanded.condition_id.nunique()
    quality['dataset_sha256']=digest(out/'hgb3_expanded_v3_dataset.csv')
    quality['added_s5_overlap']=len(set(add.condition_id)&s5ids) if len(add) else 0
    quality['feature_coverage']={}
    common=obsdf.normalized_yes_mid.notna()&obsdf.depth_available&obsdf.mid_change_30s.notna()&obsdf.mid_change_60s.notna()&obsdf.vol_adjusted_distance.notna()
    for name,mask in [('market_probability',obsdf.normalized_yes_mid.notna()),('depth',obsdf.depth_available),('mid_change_30s',obsdf.mid_change_30s.notna()),('mid_change_60s',obsdf.mid_change_60s.notna()),('volatility',obsdf.realized_volatility_60s.notna()),('vol_adjusted_distance',obsdf.vol_adjusted_distance.notna()),('common',common),('common_recorded_fresh',common&obsdf.recorded_fresh)]:
        quality['feature_coverage'][name]={'rows':int(mask.sum()),'markets':obsdf.loc[mask,'condition_id'].nunique(),
            'labelled_rows':int((mask&obsdf.label_eligible).sum()),'labelled_markets':obsdf.loc[mask&obsdf.label_eligible,'condition_id'].nunique(),
            'by_horizon':obsdf.loc[mask].groupby('target_horizon_seconds').size().to_dict()}
    save(out/'audit.json',quality)
    print(json.dumps({k:quality[k] for k in ['rows','markets','v2_market_overlap','not_in_v2_markets','markets_with_retained_valid_label','added_rows','added_markets','added_by_date','new_exclusions','expanded_rows','expanded_markets']},indent=2))

def score(df,p):
    y=df.label_yes.to_numpy(float); p=np.asarray(p,float); w=1/df.groupby('condition_id').condition_id.transform('size').to_numpy(); w=w/w.sum()
    q=np.clip(p,1e-15,1-1e-15)
    reliability=[]; bins=np.minimum((p*10).astype(int),9)
    for b in range(10):
        m=bins==b
        if m.any(): reliability.append(dict(bin=b,rows=int(m.sum()),weight=float(w[m].sum()),predicted=float(np.average(p[m],weights=w[m])),observed=float(np.average(y[m],weights=w[m]))))
    return dict(rows=len(df),markets=df.condition_id.nunique(),brier=float(np.sum(w*(p-y)**2)),log_loss=float(np.sum(w*(-y*np.log(q)-(1-y)*np.log(1-q)))),accuracy=float(np.sum(w*((p>=.5)==y))),ece=float(sum(r['weight']*abs(r['predicted']-r['observed']) for r in reliability)),reliability=reliability)

def paired(df,a,b):
    y=df.label_yes.to_numpy(float); a=np.asarray(a); b=np.asarray(b)
    outputs={}
    for metric in ['brier','log_loss']:
        if metric=='brier': d=(a-y)**2-(b-y)**2
        else:
            a=np.clip(a,1e-15,1-1e-15); b=np.clip(b,1e-15,1-1e-15)
            d=(-y*np.log(a)-(1-y)*np.log(1-a))-(-y*np.log(b)-(1-y)*np.log(1-b))
        x=df[['condition_id','prediction_timestamp']].assign(d=d).groupby('condition_id').agg(d=('d','mean'),t=('prediction_timestamp','min')).sort_values('t').d.to_numpy()
        result={'difference':float(x.mean()),'markets':len(x)}
        for block in [1,6]:
            rng=np.random.default_rng(20261017); means=[]
            for _ in range(2000):
                starts=rng.integers(0,len(x),math.ceil(len(x)/block)); ix=np.concatenate([(s+np.arange(block))%len(x) for s in starts])[:len(x)]
                means.append(x[ix].mean())
            result[f'ci95_block_{block}']=np.quantile(means,[.025,.975]).tolist()
        outputs[metric]=result
    return outputs

def train(out):
    import joblib, sklearn
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    if any((out/p).exists() for p in ['chronological_hgb3_candidate.joblib','comparison.json','hgb3_expanded_v3.joblib']):
        raise FileExistsError('Use a new versioned output directory; model outputs are immutable')
    audit=json.loads((out/'audit.json').read_text())
    if not audit['added_markets']: raise RuntimeError('No eligible new markets; no fit authorized by integrity gate')
    df=pd.read_csv(out/'hgb3_expanded_v3_dataset.csv',keep_default_na=True)
    df['expiry']=pd.to_datetime(df.prediction_timestamp,utc=True)+pd.to_timedelta(df.target_horizon_seconds,unit='s')
    start=pd.Timestamp('2026-10-12',tz='UTC'); cut=pd.Timestamp('2026-10-13',tz='UTC')
    df['partition']=np.where(df.expiry<start,'train',np.where(df.expiry<cut,'calibration','evaluation'))
    # Exact observed anchor dependencies for new rows. Legacy dependencies bounded by builder's 10+30+10s rule.
    dep=pd.to_datetime(df.anchor_observed_at,utc=True,errors='coerce')
    dep=dep.fillna(pd.to_datetime(df.prediction_timestamp,utc=True)-pd.Timedelta(seconds=50))
    marketdep=dep.groupby(df.condition_id).transform('min')
    purge=((df.partition=='calibration')&(marketdep<start))|((df.partition=='evaluation')&(marketdep<cut))
    resolved=pd.to_datetime(df.label_resolved_at,utc=True,errors='coerce')
    retrieved=pd.to_datetime(df.label_retrieved_at,utc=True,errors='coerce')
    purge|=((df.partition=='train')&((resolved>=start)|(retrieved>=start)))|((df.partition=='calibration')&((resolved>=cut)|(retrieved>=cut)))
    # Entire market removed if any dependency or label availability fails.
    purgedids=set(df.loc[purge,'condition_id']); use=df[~df.condition_id.isin(purgedids)].copy()
    membership=use[['condition_id','partition','expiry']].drop_duplicates()
    assert membership.groupby('condition_id').partition.nunique().max()==1
    membership.to_csv(out/'diagnostic_membership.csv',index=False,mode='x')
    trainset=use[use.partition=='train']; cal=use[use.partition=='calibration']; test=use[use.partition=='evaluation'].copy()
    params=json.loads(MODEL.with_suffix('.json').read_text())['model_params']
    candidate=HistGradientBoostingClassifier(**params).fit(trainset[FEATURES].astype(float),trainset.label_yes.astype(int))
    joblib.dump(candidate,out/'chronological_hgb3_candidate.joblib')
    test=test[test.normalized_yes_mid.notna()].copy()
    assert set(test.condition_id).isdisjoint(set(pd.read_csv(BASE,usecols=['condition_id']).condition_id))
    frozen=joblib.load(MODEL)
    if isinstance(frozen,dict): raise RuntimeError('Unexpected frozen artifact container')
    test['candidate']=candidate.predict_proba(test[FEATURES].astype(float))[:,1]
    test['v2']=frozen.predict_proba(test[FEATURES].astype(float))[:,1]
    test['market']=test.normalized_yes_mid
    test['constant']=.5; test['train_prior']=trainset.groupby('condition_id').label_yes.first().mean()
    names=['candidate','v2','market','constant','train_prior']; calibration={'fitted':False}
    if cal.condition_id.nunique()>=30 and cal.label_yes.nunique()==2:
        p=candidate.predict_proba(cal[FEATURES].astype(float))[:,1]
        logit=lambda p:np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
        weights=1/cal.groupby('condition_id').condition_id.transform('size').to_numpy()
        weights*=len(weights)/weights.sum()
        calibrator=LogisticRegression(C=1.,random_state=1337).fit(logit(p),cal.label_yes.astype(int),sample_weight=weights)
        test['platt']=calibrator.predict_proba(logit(test.candidate.to_numpy()))[:,1]; names.append('platt')
        calibration={'fitted':True,'coefficient':calibrator.coef_.tolist(),'intercept':calibrator.intercept_.tolist(),'C':1.,'clip':1e-6,'partition':'calibration only','final_refit_attached':False}
        save(out/'diagnostic_platt.json',calibration)
    metrics={n:score(test,test[n]) for n in names}
    pairs={n:paired(test,test.candidate,test[n]) for n in ['v2','market']}
    test.to_csv(out/'evaluation_predictions.csv',index=False,mode='x')
    report={'status':'exploratory chronological diagnostics; all download data designated development',
       'partitions':{n:{'rows':len(g),'markets':g.condition_id.nunique(),'min_prediction':g.prediction_timestamp.min(),'max_prediction':g.prediction_timestamp.max()} for n,g in use.groupby('partition')},
       'purged_markets':sorted(purgedids),'evaluation_matched_rows':len(test),'metrics':metrics,'paired':pairs,'calibration':calibration,
       'by_horizon':{str(h):{n:score(g,g[n]) for n in names} for h,g in test.groupby('target_horizon_seconds')},
       'by_date':{str(d):{n:score(g,g[n]) for n in names} for d,g in test.groupby(test.prediction_timestamp.str[:10])},
       'params':params,'candidate_iterations':candidate.n_iter_,'candidate_sha256':digest(out/'chronological_hgb3_candidate.joblib'),
       'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'joblib':joblib.__version__},
       'label_availability_limitation':'Resolution time is not first label receipt. Missing receipt evidence remains retrospective, not simulated as-of training.'}
    save(out/'comparison.json',report)
    # Only after diagnostic predictions and report are persisted: full development refit.
    final=HistGradientBoostingClassifier(**params).fit(df[FEATURES].astype(float),df.label_yes.astype(int))
    path=out/'hgb3_expanded_v3.joblib'
    if path.exists(): raise FileExistsError(path)
    joblib.dump(final,path)
    manifest={'model_version':'hgb3_expanded_v3','role':'research_main','production_approved':False,'deployment_authorized':False,
      'status':'research_only_full_development_refit','features':FEATURES,'feature_order_locked':True,'calibration_attached':False,
      'calibration_policy':{'method':'identity','fitted':False},'model_params':params,'seed':1337,'versions':report['versions'],
      'training_dataset':str((out/'hgb3_expanded_v3_dataset.csv').relative_to(ROOT)),'training_dataset_sha256':audit['dataset_sha256'],
      'training_rows':len(df),'training_markets':df.condition_id.nunique(),'first_training_timestamp':df.prediction_timestamp.min(),
      'last_training_timestamp':df.prediction_timestamp.max(),'frozen_model_sha256':digest(path),'iterations':final.n_iter_,
      'validation_reference':str((out/'comparison.json').relative_to(ROOT)),'evaluation_status':'No independent evaluation of full refit; exposed retrospective developmental diagnostics only',
      'provenance_limitations':['VM observations have no independently recorded receipt times','Existing validated official label records lack complete raw/retrieval evidence','Historical training provenance inherited without upgrade'],
      'v2_preserved_sha256':digest(MODEL)}
    save(out/'hgb3_expanded_v3.json',manifest)
    df[['condition_id','target_horizon_seconds','prediction_timestamp','source_dataset','provenance_quality']].to_csv(out/'final_training_membership.csv',index=False,mode='x')
    print(json.dumps({'partitions':report['partitions'],'metrics':{n:{k:v for k,v in m.items() if k!='reliability'} for n,m in metrics.items()},'paired':pairs,'final_manifest':manifest},indent=2))

def verify(out):
    before=json.loads((out/'preservation_before.json').read_text())
    changes={p:{'before':h,'after':digest(ROOT/p)} for p,h in before.items() if digest(ROOT/p)!=h}
    result={'protected_files':len(before),'changes':changes,'analysis_script_sha256':digest(Path(__file__))}
    save(out/'preservation_after.json',result)
    if changes: raise RuntimeError(changes)
    print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('phase',choices=['audit','train','verify']); parser.add_argument('--output',type=Path,default=DEFAULT)
    parser.add_argument('--labels-capture',type=Path,help='Replay frozen label capture instead of querying current registries')
    args=parser.parse_args(); LABEL_CAPTURE=args.labels_capture; globals()[args.phase](args.output.resolve())
