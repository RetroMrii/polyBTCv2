"""Read-only source inspection; writes only this audit's JSON evidence."""
from pathlib import Path
import csv
import hashlib
import json
import platform
from collections import Counter
from datetime import datetime
from importlib.metadata import version, PackageNotFoundError

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

files = []
for base in ['src', 'scripts', 'tests', 'docs', 'ToOrganize', 'research-OoD', 'data', 'dashboard']:
    for p in (ROOT/base).rglob('*'):
        if not p.is_file() or any(x in p.parts for x in ['node_modules','.venv','__pycache__','.cache','.pytest_cache','dist','audit-20261019']):
            continue
        files.append({'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size})

raw = ROOT/'data/raw/v1.1/btc_5m_market_snapshots_v1_4_O1-17.csv'
nulls, days = Counter(), Counter()
markets, seen, keys, bindings = set(), set(), set(), {}
duplicates = key_duplicates = backwards = binding_conflicts = malformed = 0
first = last = previous = None
with raw.open(encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    fields = reader.fieldnames
    for n, row in enumerate(reader, 1):
        if None in row or None in row.values(): malformed += 1
        stamp = datetime.fromisoformat(row['observed_at'])
        first = min(first,stamp) if first else stamp
        last = max(last,stamp) if last else stamp
        backwards += bool(previous and stamp < previous)
        previous = stamp
        days[str(stamp.date())] += 1
        market = row['market_id']; markets.add(market)
        fingerprint = hashlib.sha256(json.dumps(row,sort_keys=True).encode()).digest()
        duplicates += fingerprint in seen; seen.add(fingerprint)
        key = (market,row['observed_at'])
        key_duplicates += key in keys; keys.add(key)
        binding = tuple(row[k] for k in ['yes_token_id','no_token_id','market_end_at'])
        binding_conflicts += market in bindings and bindings[market] != binding
        bindings[market] = binding
        nulls.update(k for k,v in row.items() if not v)

training = ROOT/'data/experiments/model_expansion/vm_expansion_v2/hgb3_expanded_v2.csv'
with training.open(newline='',encoding='utf-8-sig') as f:
    training_markets = {r['condition_id'] for r in csv.DictReader(f)}
r1 = json.loads((ROOT/'docs/POLYBTC_R1_EVIDENCE.json').read_text())
versions = {'python':platform.python_version()}
for p in ['numpy','pandas','scikit-learn','pytest','joblib']:
    try: versions[p]=version(p)
    except PackageNotFoundError: versions[p]=None
result = {'scope':'Read-only audit; no normalization, fitting, collection or operational writes.',
 'files':files, 'bytes_by_root':dict((base,sum(x['bytes'] for x in files if x['path'].startswith(base+'/'))) for base in ['data','src','scripts','tests','docs','dashboard','research-OoD','ToOrganize']),
 'versions':versions, 'raw':{'path':raw.relative_to(ROOT).as_posix(),'sha256':sha(raw),'bytes':raw.stat().st_size,'rows':n,'markets':len(markets),'columns':fields,'observed_first':str(first),'observed_last':str(last),'rows_by_day':dict(days),'missing':dict(nulls),'exact_duplicates':duplicates,'duplicate_market_observation':key_duplicates,'backward_observations':backwards,'binding_conflicts':binding_conflicts,'malformed_rows':malformed,'training_market_overlap':len(markets & training_markets)},
 'protected_hashes':{str(p.relative_to(ROOT)):sha(p) for p in [training,ROOT/'data/models/main/hgb3_expanded_v2.joblib',ROOT/'data/research/s5_v1/inputs.json',ROOT/'docs/POLYBTC_S5_EVIDENCE.json',ROOT/'docs/POLYBTC_R1_EVIDENCE.json']},
 'existing_r1_generated_at':r1['generated_at']}
(OUT/'workspace-evidence.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['files']},indent=2))
