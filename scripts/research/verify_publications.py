"""Validate canonical publications, frozen demo and local normalization without writes to sources."""
from pathlib import Path
import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def verify():
    results={}
    catalog=read('research/catalog.json');assert len(catalog)==5
    links=0
    for paper in catalog:
        p=ROOT/'research'/paper['file'];text=p.read_text(encoding='utf-8')
        assert len(text.split())>700 and '## Abstract' in text and '## Reproduction' in text
        for target in re.findall(r'\]\(([^)]+)\)',text):
            if target.startswith(('http:','https:','#')):continue
            assert (p.parent/target.split('#')[0]).is_file(),(p,target)
            links+=1
    results['papers']=len(catalog);results['paper_links']=links
    claims=read('research/claims.json')
    for artifact in claims['artifacts']:
        assert sha(ROOT/artifact['artifact'])==artifact['sha256']
    for path,expected_hash in claims['parent_sources'].items():
        assert sha(ROOT/path)==expected_hash
    results['source_extract_hashes']='pass'
    demo=read('research/sources/demo.json');original=read('docs/POLYBTC_S5_EVIDENCE.json')
    assert len(demo['rows'])==159 and demo['source_sha256']==sha(ROOT/'docs/POLYBTC_S5_EVIDENCE.json')
    expected=[{k:r[k] for k in ['target','horizon','y','raw','market','platt','isotonic','combination','partition']} for r in original['prospective_rows']]
    actual=[{k:v for k,v in r.items() if k!='market_id'} for r in demo['rows']]
    assert actual==expected
    assert len({(r['market_id'],r['target']) for r in demo['rows']})==159
    assert not ({r['market_id'] for r in demo['rows'] if r['partition']=='calibration'} & {r['market_id'] for r in demo['rows'] if r['partition']=='evaluation'})
    results['demo_exact_values_and_disjoint_partitions']='pass'
    for partition,n,m in [('calibration',66,42),('evaluation',93,55)]:
        rows=[r for r in demo['rows'] if r['partition']==partition];counts=Counter(r['market_id'] for r in rows)
        assert len(rows)==n and len(counts)==m
        if partition=='evaluation':
            for key in ['market','raw','platt','isotonic','combination']:
                score=sum((r[key]-r['y'])**2/counts[r['market_id']] for r in rows)/len(counts)
                assert math.isclose(score,original['prospective']['overall'][key]['brier'],abs_tol=1e-12)
    results['demo_weighted_scores']='pass'
    manifest=read('data/research/publication_data_20261019_v1/manifest.json')
    assert sha(ROOT/manifest['source'])==manifest['source_sha256']
    compressed=ROOT/'data/research/publication_data_20261019_v1'/manifest['output']
    assert sha(compressed)==manifest['output_sha256']
    count=0;invalid=0
    with gzip.open(compressed,'rt',encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            count+=1
            assert row['official_label']=='' and row['availability_class']=='historical_event_time_only'
            assert row['source_record']==f"{manifest['source_sha256']}:{count+1}"
            if row['quote_eligible']=='0':assert row['normalized_yes_mid']=='';invalid+=1
            elif row['normalized_yes_mid']:
                y=(float(row['yes_bid'])+float(row['yes_ask']))/2
                n=(float(row['no_bid'])+float(row['no_ask']))/2
                assert math.isclose(float(row['normalized_yes_mid']),y/(y+n),abs_tol=1e-12)
    assert count==256449==manifest['counts']['rows']
    results['normalized_rows']=count;results['withheld_market_probability_rows']=invalid
    for path,before in read('docs/audit-20261019/workspace-evidence.json')['protected_hashes'].items():
        assert sha(ROOT/path)==before,path
    results['protected_artifacts_unchanged']='pass'
    private=re.compile(r'[A-Za-z]:\\|private_key|api_secret',re.I)
    for p in (ROOT/'research/sources').glob('*.json'):
        assert not private.search(p.read_text(encoding='utf-8')),p
    results['public_source_private_markers']='none'
    out=ROOT/'reports/transformation/publication-validation.json';out.parent.mkdir(exist_ok=True,parents=True)
    out.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8');print(json.dumps(results,indent=2))

if __name__=='__main__':verify()
