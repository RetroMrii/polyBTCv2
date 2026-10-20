"""Build public research evidence/figures from frozen files, never operational stores."""
from pathlib import Path
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.publication-deps'))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.publication-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT=ROOT/'research'; SOURCES=OUT/'sources'; FIGURES=OUT/'figures'
for folder in [SOURCES,FIGURES]:folder.mkdir(parents=True,exist_ok=True)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def json_safe(d):
    if isinstance(d,float) and not math.isfinite(d):return None
    if isinstance(d,dict):return {k:json_safe(v) for k,v in d.items()}
    if isinstance(d,list):return [json_safe(v) for v in d]
    return d
def save(p,d):p.write_text(json.dumps(json_safe(d),indent=2,allow_nan=False)+'\n',encoding='utf-8')
def source(name,path,content):
    value={'source':path,'source_sha256':sha(ROOT/path),'classification':'Historical exposed research evidence; not a new independent experiment.',
           'serialization':'Nonfinite historical metadata values become JSON null; original source is unchanged.',**content}
    save(SOURCES/name,value);return value

s=load('docs/POLYBTC_S5_EVIDENCE.json');r=load('docs/POLYBTC_R1_EVIDENCE.json');f=load('docs/POLYBTC_DECISION_FUNNEL_EVIDENCE.json')
h=load('data/normalized/p115_market_anchored_walk_forward_report.json')
audit=load('docs/audit-20261019/workspace-evidence.json')
normal=load('data/research/publication_data_20261019_v1/manifest.json')
names={'market':'Market midpoint','raw':'Raw HGB3','platt':'Platt HGB3','isotonic':'Isotonic HGB3','combination':'Market / Platt blend'}
rows=s['prospective_rows']; test=[x for x in rows if x['partition']=='evaluation']; groups=Counter(x['condition_id'] for x in test)
checks={}
for key in names:
    bs=sum((x[key]-x['y'])**2/groups[x['condition_id']] for x in test)/len(groups)
    ll=0.
    for x in test:
        p=max(1e-15,min(1-1e-15,x[key]));ll+=-(x['y']*math.log(p)+(1-x['y'])*math.log1p(-p))/groups[x['condition_id']]/len(groups)
    expected=s['prospective']['overall'][key]
    assert abs(bs-expected['brier'])<1e-12 and abs(ll-expected['log_loss'])<1e-12
    checks[key]={'brier':bs,'log_loss':ll,'matches_saved':True}
forecast=source('forecast-evidence.json','docs/POLYBTC_S5_EVIDENCE.json',{'partitions':s['partitions'],'calibration':s['calibration'],'scores':s['prospective'],'recomputed_scores':checks,
    'limitations':['Exposed chronological holdout; not a preregistered final test.','Conditional intervals do not include model/calibrator selection uncertainty.','Retained registry labels lack full original raw-response/retrieval evidence.']})
source('data-evidence.json','docs/POLYBTC_R1_EVIDENCE.json',{'raw':audit['raw'],'normalization':normal,'inventory':r['inventory'],
    'verified_summary':r['verified_cohort']['summary'],'by_horizon':r['verified_cohort']['by_horizon'],'intersections':r['verified_cohort']['intersections']})
source('model-evidence.json','data/normalized/p115_market_anchored_walk_forward_report.json',{'design':h['design'],'overall':h['overall'],'folds':h['folds_detail'],'rows':h['rows'],'markets':h['markets'],
    'expanded_comparison':load('data/experiments/model_expansion/vm_expansion_v2/hgb3_xgb_v2_comparison.json'),
    'feature_retest':load('data/experiments/p13_model_improvement/p13_k2_model_feature_retest_report.json')['overall'],
    'later_block':load('data/experiments/p13_model_improvement/p13_block2_validation_report.json')['overall']})
source('timing-evidence.json','docs/POLYBTC_DECISION_FUNNEL_EVIDENCE.json',{'window':f['window'],'funnel':f['funnel'],'latency_ms':f['latency_ms'],
    'counterfactual':{k:v for k,v in f['forensic_summary']['counterfactual'].items() if not k.endswith('_ids')},'limitations':f['limitations']})
econ=s['economic_comparison']
economic_checks={}
for key,policy in econ['alternative_best_side_without_agreement_gap'].items():
    total=sum(t['hypothetical_pnl'] for t in policy['trades'])
    assert abs(total-policy['net_hypothetical_pnl'])<1e-10
    for t in policy['trades']:
        pnl=t['shares']*(t['won']-t['execution_price'])-t['fee']
        assert abs(pnl-t['hypothetical_pnl'])<1e-10
    economic_checks[key]={'entries':len(policy['trades']),'net_hypothetical_pnl':total,'accounting_recomputed':True}
source('economics-evidence.json','docs/POLYBTC_S5_EVIDENCE.json',{'eligible_observations':econ['eligible_observations'],'eligible_markets':econ['eligible_markets'],
    'baseline':econ['baseline'],'alternative_summaries':{k:{a:b for a,b in v.items() if a!='trades'} for k,v in econ['alternative_best_side_without_agreement_gap'].items()},
    'accounting_checks':economic_checks,'risk_scenario':econ['risk_scenario'],'sensitivity':econ['sensitivity'],'alternative_stress':econ['alternative_stress']})
ids={key:f'market-{i+1:03}' for i,key in enumerate(sorted({x['condition_id'] for x in rows}))}
demo={'version':'frozen-forecast-demo-v1','as_of':'2026-10-13T21:13:00Z','mode':'Historical research snapshot',
    'source_sha256':sha(ROOT/'docs/POLYBTC_S5_EVIDENCE.json'),'description':'159 exposed forecast observations. These are predictions, not orders or fills. Market aliases replace source identifiers.',
    'rows':[{k:x[k] for k in ['target','horizon','y','raw','market','platt','isotonic','combination','partition']} | {'market_id':ids[x['condition_id']]} for x in rows]}
save(SOURCES/'demo.json',demo)

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#b9b7b0',
 'axes.labelcolor':'#353c3a','text.color':'#222d2a','xtick.color':'#535b57','ytick.color':'#535b57','figure.facecolor':'#faf9f5','axes.facecolor':'#faf9f5','svg.hashsalt':'polybtc-research-v1'})
teal='#147d72';orange='#bb6036';grey='#81928d'
def finish(fig,name):
    fig.tight_layout(pad=1.7);fig.savefig(FIGURES/(name+'.svg'),metadata={'Date':None},bbox_inches='tight');fig.savefig(FIGURES/(name+'.png'),dpi=160,bbox_inches='tight');plt.close(fig)
fig,ax=plt.subplots(figsize=(9,3.6)); dates=list(audit['raw']['rows_by_day']);ax.bar([d[5:] for d in dates],list(audit['raw']['rows_by_day'].values()),color=teal)
ax.tick_params(axis='x',rotation=45);ax.set(ylabel='Raw observations',xlabel='UTC date, October 2026',title='Cumulative export coverage — 256,449 observations / 4,616 markets');finish(fig,'data-coverage')
fig,ax=plt.subplots(figsize=(8,4)); labels=['Raw market','Market-only logistic','Market + BTC','BTC-only'];keys=['raw_market','market_only_logistic','market_plus_btc','btc_only_walk_forward']
values=[h['overall'][k]['brier_score'] for k in keys];ax.barh(labels,values,color=[teal,grey,grey,orange]);ax.invert_yaxis();ax.set_xlim(0,.21)
for i,v in enumerate(values):ax.text(v+.003,i,f'{v:.6f}',va='center')
ax.set(xlabel='Brier loss · lower is better',title='Historical walk-forward comparison — 8,914 matched rows');finish(fig,'historical-models')
fig,(ax,rel)=plt.subplots(1,2,figsize=(10,4));ks=list(names); vals=[s['prospective']['overall'][k]['brier'] for k in ks]
ax.barh([names[k] for k in ks],vals,color=[teal,orange,grey,grey,grey]);ax.invert_yaxis();ax.set(xlim=(0,.24),xlabel='Market-weighted Brier loss',title='93 later observations / 55 markets')
for i,v in enumerate(vals):ax.text(v+.004,i,f'{v:.4f}',va='center',fontsize=9)
rel.plot([0,1],[0,1],ls='--',color='#aaa',label='Perfect calibration')
for k,c in [('market',teal),('raw',orange),('combination',grey)]:
    bins=s['prospective']['overall'][k]['reliability'];rel.plot([x['predicted'] for x in bins],[x['observed'] for x in bins],marker='o',ms=4,color=c,label=names[k])
rel.set(xlim=(0,1),ylim=(0,1),xlabel='Mean forecast in occupied bin',ylabel='Weighted observed YES frequency',title='Reliability · sparse bins');rel.legend(fontsize=8);finish(fig,'calibration')
fig,ax=plt.subplots(figsize=(8,3.4));ks=['raw','platt','isotonic','combination'];d=[s['prospective']['paired_deltas'][k]['brier'] for k in ks]
for i,v in enumerate(d):ax.errorbar(v['delta'],i,xerr=[[v['delta']-v['ci95'][0]],[v['ci95'][1]-v['delta']]],fmt='o',color=orange,capsize=4)
ax.axvline(0,color=teal,ls='--');ax.set(yticks=range(4),yticklabels=[names[k] for k in ks],xlabel='Brier difference vs market · positive favors market',title='95% market-cluster intervals · 55 evaluation markets');ax.invert_yaxis();finish(fig,'paired-uncertainty')
fig,ax=plt.subplots(figsize=(8,4));labs=['Decisions','Causal horizon','Verification passes','Strategy reached','Economic qualification','Paper fills'];values=[300,222,157,97,0,0]
assert values==[f['funnel'][k] for k in ['decisions','horizon_selected','verification_pass','strategy_reached','economic_qualification','fills']]
ax.barh(labs,values,color=[grey,grey,teal,teal,orange,orange]);ax.invert_yaxis();ax.set(xlim=(0,340),xlabel='Decisions in the fixed 50-market cohort',title='Eligibility and economics — October 13, 2026')
for i,v in enumerate(values):ax.text(v+5,i,str(v),va='center')
finish(fig,'decision-funnel')
fig,ax=plt.subplots(figsize=(8,3.5));vals=[0,economic_checks['B_platt']['net_hypothetical_pnl'],economic_checks['C']['net_hypothetical_pnl']]
ax.barh(['Unchanged constraints','Post-hoc calibrated policy','Post-hoc blend policy'],vals,color=[grey,teal,orange]);ax.axvline(0,color='#777',lw=.8)
ax.set(xlim=(-8,2),xlabel='Total labelled hypothetical net P&L (USD)',title='Conditional simulation · 43 observations / 36 markets');ax.invert_yaxis()
for i,v in enumerate(vals):ax.text(v+(.15 if v>=0 else -.15),i,f'${v:+.5f}',va='center',ha='left' if v>=0 else 'right')
finish(fig,'strategy-economics')

claims=[]
for p in sorted(SOURCES.glob('*.json')):
    claims.append({'artifact':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p),'source':json.loads(p.read_text()).get('source','docs/POLYBTC_S5_EVIDENCE.json')})
parents=['docs/POLYBTC_S5_EVIDENCE.json','docs/POLYBTC_R1_EVIDENCE.json','docs/POLYBTC_DECISION_FUNNEL_EVIDENCE.json',
 'docs/audit-20261019/workspace-evidence.json','data/research/publication_data_20261019_v1/manifest.json',
 'data/normalized/p115_market_anchored_walk_forward_report.json',
 'data/experiments/model_expansion/vm_expansion_v2/hgb3_xgb_v2_comparison.json',
 'data/experiments/p13_model_improvement/p13_k2_model_feature_retest_report.json',
 'data/experiments/p13_model_improvement/p13_block2_validation_report.json']
save(OUT/'claims.json',{'version':'publication-evidence-v1','rule':'Numerical paper tables cite these source extracts; parent paths/hashes identify retained originals. Historical metrics are not silently redefined.','artifacts':claims,
 'parent_sources':{p:sha(ROOT/p) for p in parents},
 'paper_claim_map':{
  'market-data-provenance':['data-evidence.json:raw','data-evidence.json:inventory','data-evidence.json:verified_summary'],
  'models-versus-market':['model-evidence.json:overall','model-evidence.json:expanded_comparison','model-evidence.json:feature_retest','model-evidence.json:later_block'],
  'forecast-calibration':['forecast-evidence.json:partitions','forecast-evidence.json:calibration','forecast-evidence.json:scores','forecast-evidence.json:recomputed_scores'],
  'execution-timing':['timing-evidence.json:funnel','timing-evidence.json:latency_ms','timing-evidence.json:counterfactual'],
  'strategy-economics':['economics-evidence.json:baseline','economics-evidence.json:alternative_summaries','economics-evidence.json:accounting_checks']}})
save(OUT/'reproduction.json',{'version':'publication-evidence-v1','script_sha256':sha(Path(__file__)),'python':sys.version,'matplotlib':matplotlib.__version__,'numpy':np.__version__,
 'score_checks':checks,'accounting_checks':economic_checks,'normalization_source_unchanged':normal['source_unchanged'],
 'not_reproduced':['Model fitting','Raw resolution re-attestation','Historical bootstrapped intervals (shown from saved evidence)','Operational executions'],
 'public_demo_rows':len(demo['rows'])})
print('Built publication evidence, six figure pairs and 159-row historical demo. Saved scoring/accounting checks pass.')
