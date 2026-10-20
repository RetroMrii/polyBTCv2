"""S5 research only. Capture read-only operational facts, then analyze frozen inputs.

No operational constructors, model training, network, or journal writes.
Run with -B from repository root; --capture refuses to replace its input artifact.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import socket
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/research/s5_v1'
INPUT = OUT / 'inputs.json'
SEED = 20261014
CUT = '2026-10-13T14:30:00+00:00'
END = '2026-10-13T21:20:00+00:00'


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ro(p):
    c = sqlite3.connect(Path(p).resolve().as_uri()+'?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    c.execute('BEGIN')
    return c


def dt(s):
    return datetime.fromisoformat(s)


def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, allow_nan=False, default=str)+'\n', encoding='utf-8')


def capture():
    from polybtc.shadow.converter_vnext import convert_v1_tail_row
    from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore, PaperAcquisitionVerifier
    from polybtc.data.causal_features_vnext import reference_anchor_30s, _reference_return_30s
    from polybtc.data.dataset.features import build_snapshot_features
    from polybtc.modeling.inference import FrozenProbabilityModel
    if INPUT.exists():
        raise FileExistsError('Frozen inputs already exist; rerun without --capture')
    base = ROOT/'data/paper/vnext_verified'
    with closing(ro(base/'decisions.sqlite3')) as c:
        decisions = [dict(r) for r in c.execute('SELECT * FROM decisions WHERE target_at_utc < ? ORDER BY id', (END,))]
    with closing(ro(base/'resolutions.sqlite3')) as c:
        labels = {r['condition_id']: dict(r) for r in c.execute('SELECT * FROM resolutions')}
    with closing(ro(base/'receipts.sqlite3')) as c:
        receipts = {r['snapshot_id']:r['first_received_at_utc'] for r in c.execute('SELECT * FROM receipts')}
    with closing(ro(base/'csv_tail.sqlite3')) as c:
        tail = dict(c.execute('SELECT * FROM tail_state').fetchone())
    csvpath = Path(tail['source_path'])
    wanted = {r['condition_id'] for r in decisions}
    byid = {}; markets = defaultdict(list); prefix_hash = hashlib.sha256()
    with csvpath.open('rb') as f:
        line = f.readline(); prefix_hash.update(line)
        headers = next(csv.reader([line.decode('utf-8-sig')]))
        while f.tell() < tail['offset_bytes']:
            off = f.tell(); line = f.readline(); prefix_hash.update(line)
            sid = hashlib.sha256((tail['source_identity']+':'+str(off)+':').encode()+line).hexdigest()
            if sid not in receipts:
                continue
            values = dict(zip(headers, next(csv.reader([line.decode()]))))
            if values['market_id'] not in wanted:
                continue
            row = convert_v1_tail_row(SimpleNamespace(row_id=sid,values=values), source_file=csvpath.name)
            row = replace(row, ingested_at=dt(receipts[sid]))
            byid[sid] = row; markets[row.condition_id].append(row)
    artifact = ROOT/'data/models/main/hgb3_expanded_v2.joblib'
    model = FrozenProbabilityModel(artifact)
    verifier = PaperAcquisitionVerifier(AcquisitionEvidenceStore(ROOT/'data/live/paper_acquisition.sqlite3'))
    rows = []
    economic_reasons = {'market_direction_neutral','model_direction_neutral','model_market_disagreement','probability_gap_too_large','price_ceiling_exceeded','insufficient_net_ev','insufficient_depth'}
    for d in decisions:
        p = byid.get(d['snapshot_id']); t = dt(d['target_at_utc'])
        r = {k:d[k] for k in ('id','condition_id','horizon_seconds','target_at_utc','reason','snapshot_id','model_probability_yes','prediction_market_probability_yes','market_probability_yes')}
        r['label'] = labels.get(d['condition_id'])
        v = json.loads(d['source_verification_json']) if d['source_verification_json'] else None
        r['original_verification'] = v
        r['strategy_reached'] = d['reason'] in economic_reasons
        r['reconstructed'] = False
        if p is not None:
            history = [x for x in markets[p.condition_id] if x.observed_at<=t and x.ingested_at<=t]
            anchor = reference_anchor_30s(history,p,decision_at=t)
            feature = build_snapshot_features(p)
            ret = _reference_return_30s(history,p,decision_at=t)
            if anchor is not None and ret is not None and feature.relative_distance_from_strike is not None:
                inputs = dict(relative_distance_from_strike=feature.relative_distance_from_strike,target_horizon_seconds=float(d['horizon_seconds']),reference_return_30s=ret)
                value = model.predict(inputs).probability_yes
                r.update(features=inputs,reconstructed=True,reconstructed_p=value,model_matches=d['model_probability_yes'] is not None and abs(value-d['model_probability_yes'])<1e-12)
                pe, pf = verifier._bound_result(p,t); ae, af = verifier._bound_result(anchor,t)
                r['prediction_reference_verified_now'] = bool(verifier._reference(p,pe,t) and verifier._reference(anchor,ae,anchor.observed_at) and anchor.market_end_at==p.market_end_at)
                r['binding_failures'] = [x for x in (pf,af) if x]
                r['causal'] = p.observed_at<=t and p.ingested_at<=t and anchor.observed_at<=t and anchor.ingested_at<=t
                r['prediction_market_p'] = feature.normalized_yes_mid
                r['prediction_book_ages_ms'] = [(t-getattr(p,s+'_book_timestamp')).total_seconds()*1000 for s in ('yes','no')]
                r['prediction_books_fresh'] = pe is not None and all(0<=a<=500 for a in r['prediction_book_ages_ms'])
                r['prediction_observed_at'] = p.observed_at.isoformat(); r['prediction_receipt_at'] = p.ingested_at.isoformat()
                r['anchor_observed_at'] = anchor.observed_at.isoformat(); r['anchor_receipt_at'] = anchor.ingested_at.isoformat()
                r['evidence_ids'] = [x.evidence_id for x in (pe,ae) if x]
        if v and (ex := byid.get(v['execution_snapshot_id'])) is not None:
            fee = json.loads(d['fee_provenance_json']) if d['fee_provenance_json'] else None
            r['fee'] = fee
            fields = ['observed_at','ingested_at','reference_timestamp','yes_book_timestamp','no_book_timestamp','yes_bid','no_bid','yes_ask','no_ask','yes_ask_size','no_ask_size','yes_tick_size','no_tick_size','yes_min_order_size','no_min_order_size','market_end_at']
            r['execution'] = {k:(getattr(ex,k).isoformat() if isinstance(getattr(ex,k),datetime) else getattr(ex,k)) for k in fields}
        rows.append(r)
    train = ROOT/'data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv'
    manifest = json.loads(artifact.with_suffix('.json').read_text())
    assert sha(artifact)==manifest['frozen_model_sha256']
    assert sha(train)==manifest['training_dataset_sha256']
    dump(INPUT,dict(version='s5_readonly_v1',captured_at=datetime.now(timezone.utc).isoformat(),calibration_evaluation_cutoff=CUT,exclusive_end=END,manifest=manifest,training_sha256=sha(train),model_sha256=sha(artifact),csv_prefix_sha256=prefix_hash.hexdigest(),checkpoint=tail,resolution_registry_rows=len(labels),resolution_registry=list(labels.values()),rows=rows))
    print('Captured',len(rows),'decisions; reconstructed',sum(r['reconstructed'] for r in rows),flush=True)


def clip(p):
    return np.clip(np.asarray(p,dtype=float),1e-15,1-1e-15)


def logit(p):
    p=clip(p); return np.log(p/(1-p))


def market_weights(df):
    return 1/df.groupby('condition_id')['condition_id'].transform('size').to_numpy(dtype=float)


def metrics(df, column, bin_count=10):
    if not len(df): return None
    y=df['y'].to_numpy(); p=clip(df[column]); w=market_weights(df); w=w/w.sum()
    bins=np.minimum((p*bin_count).astype(int),bin_count-1); curve=[]
    for b in range(bin_count):
        take=bins==b
        if not take.any(): continue
        wb=w[take]; curve.append(dict(bin=b,lower=b/bin_count,upper=(b+1)/bin_count,rows=int(take.sum()),markets=int(df.loc[take,'condition_id'].nunique()),weight=float(wb.sum()),predicted=float(np.average(p[take],weights=wb)),observed=float(np.average(y[take],weights=wb)),brier=float(np.average((p[take]-y[take])**2,weights=wb)),log_loss=float(np.average(-y[take]*np.log(p[take])-(1-y[take])*np.log1p(-p[take]),weights=wb))))
    return dict(rows=len(df),markets=int(df.condition_id.nunique()),brier=float(np.sum(w*(p-y)**2)),log_loss=float(np.sum(w*(-y*np.log(p)-(1-y)*np.log1p(-p)))),accuracy=float(np.sum(w*((p>=.5)==y))),ece=float(sum(b['weight']*abs(b['predicted']-b['observed']) for b in curve)),reliability=curve)


def paired_ci(df, column, repeats=2000):
    y=df.y.to_numpy(); p=clip(df[column]); m=clip(df.market)
    x=pd.DataFrame(dict(condition_id=df.condition_id.to_numpy(),brier=(p-y)**2-(m-y)**2,log_loss=-y*np.log(p)-(1-y)*np.log1p(-p)+y*np.log(m)+(1-y)*np.log1p(-m)))
    groups=x.groupby('condition_id',sort=True).mean(); a=groups.to_numpy(); n=len(a)
    rng=np.random.default_rng(SEED); draws=np.empty((repeats,2))
    for i in range(repeats): draws[i]=a[rng.integers(n,size=n)].mean(axis=0)
    order=df.groupby('condition_id')['target' if 'target' in df else 'prediction_timestamp'].min().sort_values().index
    ordered=groups.loc[order].to_numpy(); block_draws=np.empty((repeats,2)); block=min(6,n)
    for i in range(repeats):
        starts=rng.integers(n,size=int(np.ceil(n/block)))
        indices=np.concatenate([(start+np.arange(block))%n for start in starts])[:n]
        block_draws[i]=ordered[indices].mean(axis=0)
    return {k:dict(delta=float(a[:,j].mean()),ci95=np.quantile(draws[:,j],[.025,.975]).tolist(),six_market_block_ci95=np.quantile(block_draws[:,j],[.025,.975]).tolist(),market_delta_sd=float(np.std(a[:,j],ddof=1))) for j,k in enumerate(('brier','log_loss'))}


def evaluate(df, cols):
    return dict(overall={c:metrics(df,c) for c in cols},paired_deltas={c:paired_ci(df,c) for c in cols if c!='market'},by_horizon={str(h):{c:metrics(g,c) for c in cols} for h,g in df.groupby('horizon')})


def economics(rows, frame, platt, alpha):
    """Controlled EV substitution; legacy raw-HGB3 agreement/gap remain fixed.

    Hypothetical entries use conservative no-capital-release during this session.
    These are offline ledger-free scenarios, not observed executions.
    """
    from polybtc.execution.model import calculate_taker_fee
    eligible_ids=set(frame.loc[frame.target>=CUT,'id'])
    items=[]
    for r in rows:
        if not (r['id'] in eligible_ids and r['strategy_reached'] and r.get('execution') and r.get('fee')):continue
        ex=r['execution']; yp=(ex['yes_bid']+ex['yes_ask'])/2; np_=(ex['no_bid']+ex['no_ask'])/2
        m=yp/(yp+np_); p=r['reconstructed_p']; calibrated=float(platt.predict_proba([[float(logit([p])[0])]])[0,1])
        side='yes' if m>.5 else 'no'; ask=ex[side+'_ask']; tick=max(ex['yes_tick_size'],ex['no_tick_size'])
        fee=r['fee']['fee_descriptor_rate']; q=dict(A=m,B_raw_diagnostic=p,B_platt=calibrated,C=(1-alpha)*m+alpha*calibrated)
        items.append(dict(id=r['id'],condition_id=r['condition_id'],target=r['target_at_utc'],horizon=r['horizon_seconds'],label=r['label']['label_yes'],side=side,raw=p,market=m,probabilities=q,ask=ask,tick=tick,depth=ex[side+'_ask_size'],minimum_order_size=ex[side+'_min_order_size'],fee_rate=fee,spread=ex[side+'_ask']-ex[side+'_bid'],abs_reference_return=abs(r['features']['reference_return_30s']),execution=ex,verification_at=r['original_verification']['checked_at_utc']))
    def scenario(name, ticks=1, fee_multiplier=1, haircut=0, gap=.05, ceiling=.70, best_side=False):
        counts=Counter(); trades=[]; used=set(); capital=0.0
        for x in sorted(items,key=lambda x:(x['target'],x['id'])):
            counts['causal_fresh_strategy_inputs']+=1
            p=x['probabilities'][name]
            side=x['side'] if not best_side else ('yes' if p-x['execution']['yes_ask'] >= (1-p)-x['execution']['no_ask'] else 'no')
            prob=p if side=='yes' else 1-p
            price=x['execution'][side+'_ask']+ticks*x['tick']; allowance=x['fee_rate']*fee_multiplier/4+.00001
            ev=prob-haircut-price-allowance
            if ev<=0: counts['nonpositive_ev']+=1;continue
            counts['positive_ev']+=1
            if not best_side and (x['market']==.5 or (x['raw']>.5)!=(x['market']>.5) or x['raw']==.5):counts['direction_reject']+=1;continue
            if not best_side and abs(x['raw']-x['market'])>gap:counts['gap_reject']+=1;continue
            if price>ceiling:counts['price_reject']+=1;continue
            if x['execution'][side+'_ask_size']<5 or x['execution'][side+'_min_order_size']>5:counts['size_reject']+=1;continue
            counts['entry_constraints_pass']+=1
            fee=calculate_taker_fee(filled_size=5,execution_price=price,fee_rate=x['fee_rate']*fee_multiplier)
            cost=5*price+fee
            if x['condition_id'] in used:counts['one_entry_reject']+=1;continue
            if cost>7 or capital+cost>25:counts['capital_reject']+=1;continue
            used.add(x['condition_id']);capital+=cost
            won=int((side=='yes')==bool(x['label']))
            trades.append(dict(id=x['id'],condition_id=x['condition_id'],horizon=x['horizon'],side=side,estimated_probability=prob,estimated_ev=ev,execution_price=price,shares=5,fee=fee,maximum_loss=cost,won=won,hypothetical_pnl=5*won-cost))
        pnls=[t['hypothetical_pnl'] for t in trades]; equity=np.r_[0,np.cumsum(pnls)]
        return dict(counts=dict(counts),trades=trades,hypothetical_trades=len(trades),net_hypothetical_pnl=float(sum(pnls)),ex_post_entry_order_drawdown=float(np.max(np.maximum.accumulate(equity)-equity)),win_rate=float(np.mean([t['won'] for t in trades])) if trades else None,by_horizon=dict(Counter(t['horizon'] for t in trades)),trade_forecast_brier=float(np.mean([(t['estimated_probability']-t['won'])**2 for t in trades])) if trades else None,trade_forecast_log_loss=float(np.mean([-np.log(clip([t['estimated_probability'] if t['won'] else 1-t['estimated_probability']])[0]) for t in trades])) if trades else None)
    baseline={n:scenario(n) for n in ('A','B_raw_diagnostic','B_platt','C')}
    sensitivity={}
    for n in baseline:
        sensitivity[n]={label:scenario(n,**kwargs) for label,kwargs in [('zero_ticks',dict(ticks=0)),('two_ticks',dict(ticks=2)),('double_fee',dict(fee_multiplier=2)),('uncertainty_2pp',dict(haircut=.02)),('uncertainty_5pp',dict(haircut=.05)),('gap_10pp',dict(gap=.10)),('gap_unbounded',dict(gap=1)),('ceiling_80c_diagnostic',dict(ceiling=.8))]}
    latency={}
    for lag in (0,50,100,250,500):
        passed=0
        for x in items:
            at=dt(x['verification_at'])
            ages=[(at-dt(x['execution'][s+'_timestamp'])).total_seconds()*1000+lag for s in ('reference','yes_book','no_book')]
            passed+=all(0<=a<=limit for a,limit in zip(ages,(3000,500,500)))
        latency[str(lag)]=passed
    candidate={n:scenario(n,best_side=True) for n in ('B_platt','C')}
    candidate_stress={n:{label:scenario(n,best_side=True,**kw) for label,kw in [('two_ticks',dict(ticks=2)),('double_fee',dict(fee_multiplier=2)),('uncertainty_5pp',dict(haircut=.05))]} for n in candidate}
    return dict(eligible_observations=len(items),eligible_markets=len({x['condition_id'] for x in items}),rows=items,baseline=baseline,sensitivity=sensitivity,alternative_best_side_without_agreement_gap=candidate,alternative_stress=candidate_stress,verification_deadline_plus_ms_pass_counts=latency,no_trade_baseline=dict(trades=0,pnl=0,drawdown=0),risk_scenario='No release of capital during session; settlement receipt time is not retained. Ex-post labelled PnL and entry-order drawdown are not live equity or operational fills.')


def inventory():
    paths=['data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv','data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2_evaluation_predictions.csv','data/experiments/model_expansion/vm_expansion_v2/verified_resolutions.csv','data/normalized/p4_supervised_v1.csv','data/normalized/market_resolutions.csv','data/experiments/p13_model_improvement/p13_prospective_supervised.csv','data/normalized/p115_market_anchored_walk_forward_predictions.csv','data/experiments/p14_market_relative/p14_execution_abstention_rows.csv','data/raw/v1.1/btc_5m_market_snapshots_v1_4.csv','data/raw/p12/btc_5m_market_snapshots_p12.csv','data/raw/p13/btc_1m_ohlc.csv','data/external/bitcoin_history/btcusd_1-min_data.csv']
    results=[]
    for name in paths:
        p=ROOT/name
        if not p.exists():continue
        with p.open(encoding='utf-8-sig') as f: columns=next(csv.reader(f))
        use=[c for c in ('condition_id','market_id','prediction_timestamp','observed_at','timestamp','Timestamp','resolved_at','label_yes','validation_status') if c in columns]
        frame=pd.read_csv(p,usecols=use,low_memory=False)
        m=next((c for c in ('condition_id','market_id') if c in frame),None)
        time=next((c for c in ('prediction_timestamp','observed_at','timestamp','Timestamp','resolved_at') if c in frame),None)
        dates=frame[time].dropna() if time else pd.Series(dtype=str)
        results.append(dict(path=name,rows=len(frame),markets=int(frame[m].nunique()) if m else None,columns=columns,time_column=time,first=str(dates.min()) if len(dates) else None,last=str(dates.max()) if len(dates) else None,label_counts={str(k):int(v) for k,v in frame.label_yes.value_counts(dropna=False).items()} if 'label_yes' in frame else None,validation_counts=frame.validation_status.value_counts().to_dict() if 'validation_status' in frame else None,sha256=sha(p)))
    return results


def analyze():
    raw=json.loads(INPUT.read_text()); rows=raw['rows']
    train=pd.read_csv(ROOT/raw['manifest']['training_dataset'].replace('\\','/'))
    trainids=set(train.condition_id.str.strip().str.lower())
    assert not trainids.intersection(r['condition_id'] for r in rows)
    usable=[]
    for r in rows:
        if not (r.get('model_matches') and r.get('causal') and r.get('prediction_reference_verified_now') and r.get('prediction_books_fresh') and r['label']):continue
        if r['label']['settlement_status'] not in ('VERIFIED','SETTLED'):continue
        assert r['label']['evidence_source'].startswith('polymarket_gamma+data_api_v2:')
        assert dt(r['label']['resolved_at_utc'])>dt(r['target_at_utc'])
        usable.append(dict(id=r['id'],condition_id=r['condition_id'],target=r['target_at_utc'],horizon=r['horizon_seconds'],y=r['label']['label_yes'],raw=r['reconstructed_p'],market=r['prediction_market_p']))
    frame=pd.DataFrame(usable)
    cal=frame.loc[frame.target<CUT].copy(); test=frame.loc[frame.target>=CUT].copy()
    assert not set(cal.condition_id)&set(test.condition_id)
    calibration_ids=set(cal.id)
    assert all(dt(r['label']['resolved_at_utc'])<dt(CUT) for r in rows if r['id'] in calibration_ids)
    w=market_weights(cal)
    platt=LogisticRegression(C=1,solver='lbfgs',max_iter=2000,random_state=SEED).fit(logit(cal.raw).reshape(-1,1),cal.y,sample_weight=w)
    iso=IsotonicRegression(out_of_bounds='clip').fit(cal.raw,cal.y,sample_weight=w)
    calp=platt.predict_proba(logit(cal.raw).reshape(-1,1))[:,1]
    # Closed-form convex mixture minimizing market-weighted calibration Brier.
    m=cal.market.to_numpy(); z=calp-m
    alpha=float(np.clip(np.sum(w*z*(cal.y.to_numpy()-m))/np.sum(w*z*z),0,1))
    for part in (cal,test):
        part['platt']=platt.predict_proba(logit(part.raw).reshape(-1,1))[:,1]
        part['isotonic']=iso.predict(part.raw)
        part['combination']=(1-alpha)*part.market+alpha*part.platt
        part['half']=.5;part['equal_raw']=.5*part.market+.5*part.raw
    cols=['market','raw','platt','isotonic','combination','equal_raw','half']
    res=dict(version='s5_v1',inputs_sha256=sha(INPUT),model=raw['manifest'],membership_overlap=0,
        counts=dict(decisions=len(rows),markets=len({r['condition_id'] for r in rows}),reconstructed=sum(r['reconstructed'] for r in rows),model_matched=sum(r.get('model_matches',False) for r in rows),reference_verified=sum(r.get('prediction_reference_verified_now',False) for r in rows),fresh_prediction_books=sum(r.get('prediction_books_fresh',False) for r in rows),labelled_decisions=sum(r['label'] is not None for r in rows),usable_paired=len(frame),usable_markets=int(frame.condition_id.nunique())),
        partitions={name:dict(rows=len(p),markets=int(p.condition_id.nunique()),first=p.target.min(),last=p.target.max(),yes_markets=int(p.groupby('condition_id').y.first().sum())) for name,p in [('calibration',cal),('evaluation',test)]},
        calibration=dict(version='s5_exploratory_v1',platt_coefficient=float(platt.coef_[0,0]),platt_intercept=float(platt.intercept_[0]),isotonic_x=iso.X_thresholds_.tolist(),isotonic_y=iso.y_thresholds_.tolist(),combination_model_weight=alpha),
        prospective=evaluate(test,cols))
    # Existing predecessor predictions, never presented as independent full-refit scores.
    historical=pd.read_csv(ROOT/'data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2_evaluation_predictions.csv')
    hist=historical.rename(columns={'label_yes':'y','normalized_yes_mid':'market','target_horizon_seconds':'horizon','hgb3_raw':'raw','hgb3_platt':'platt','hgb3_isotonic':'isotonic'})
    paired=hist[hist.market.notna()].copy()
    res['historical_predecessor']=dict(total_rows=len(hist),paired_rows=len(paired),missing_market_rows=int(hist.market.isna().sum()),first=hist.prediction_timestamp.min(),last=hist.prediction_timestamp.max(),results=evaluate(paired,['market','raw','platt','isotonic']))
    res['archived_benchmarks']={}
    for path,probabilities in [('data/experiments/model_expansion/vm_expansion_v2/hgb3_xgb_v2_comparison.csv',['normalized_yes_mid','xgb_raw','xgb_platt','xgb_isotonic']),('data/normalized/p115_market_anchored_walk_forward_predictions.csv',['raw_market_probability','market_only_probability','market_plus_btc_probability','btc_only_walk_forward_probability'])]:
        archived=pd.read_csv(ROOT/path).rename(columns={'label_yes':'y'})
        archived=archived.dropna(subset=probabilities)
        res['archived_benchmarks'][path]={'sha256':sha(ROOT/path),'first':archived.prediction_timestamp.min(),'last':archived.prediction_timestamp.max(),'warning':'Existing development predictions; not an independent frozen-v2 or executable test.','metrics':{c:metrics(archived,c) for c in probabilities}}
    res['source_cohorts']=dict(Counter(train.source_dataset))
    res['inventory']=inventory()
    res['economic_comparison']=economics(rows,frame,platt,alpha)
    res['calibration_period_diagnostic']={c:metrics(cal,c) for c in cols}
    res['ece_bin_sensitivity']={str(n):{c:metrics(test,c,n)['ece'] for c in cols} for n in (5,10,20)}
    byid={r['id']:r for r in rows}
    regime_cut=float(np.median([abs(byid[i]['features']['reference_return_30s']) for i in cal.id]))
    regime=np.array([abs(byid[i]['features']['reference_return_30s']) for i in test.id])
    res['return_regimes']={'calibration_median_absolute_30s_return':regime_cut,'warning':'Absolute TWAP return proxy, not realized spot volatility; no regime tuning.', 'lower':{c:metrics(test.loc[regime<=regime_cut],c) for c in cols},'higher':{c:metrics(test.loc[regime>regime_cut],c) for c in cols}}
    res['exclusions']={}
    chain=list(rows)
    for name,criterion in [('no_matching_reconstructed_model',lambda r:r.get('model_matches')),('noncausal',lambda r:r.get('causal')),('prediction_reference_or_anchor_unverified',lambda r:r.get('prediction_reference_verified_now')),('prediction_books_not_fresh_or_unbound',lambda r:r.get('prediction_books_fresh')),('label_missing',lambda r:r['label'] is not None)]:
        keep=[r for r in chain if criterion(r)]
        res['exclusions'][name]=len(chain)-len(keep);chain=keep
    res['prospective_rows'] = pd.concat([cal.assign(partition='calibration'),test.assign(partition='evaluation')]).to_dict('records')
    import platform, sklearn
    res['reproducibility']=dict(script_sha256=sha(Path(__file__)),python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__,seed=SEED,cluster_resamples=2000,calibration_labels_resolved_before_evaluation=True,training_dataset_hash_verified=sha(ROOT/raw['manifest']['training_dataset'].replace('\\','/'))==raw['training_sha256'],model_hash_unchanged=sha(ROOT/'data/models/main/hgb3_expanded_v2.joblib')==raw['model_sha256'])
    dump(OUT/'calibration_s5_exploratory_v1.json',res['calibration'])
    dump(ROOT/'docs/POLYBTC_S5_EVIDENCE.json',res)
    print(json.dumps({k:res[k] for k in ('counts','partitions','calibration')},indent=2))
    print('Prospective',json.dumps({k:{j:v for j,v in x.items() if j!='reliability'} for k,x in res['prospective']['overall'].items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--capture',action='store_true');args=parser.parse_args()
    socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('S5 is offline'))
    if args.capture:capture()
    analyze()
