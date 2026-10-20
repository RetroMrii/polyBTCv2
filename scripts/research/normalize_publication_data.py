"""Versioned, offline derivative of the cumulative VM export; never assigns labels."""
from pathlib import Path
import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from polybtc.data.dataset.features import build_snapshot_features

SOURCE = ROOT / 'data/raw/v1.1/btc_5m_market_snapshots_v1_4_O1-17.csv'
EXPECTED = '71fb69ccaa1b4751c49fe37de8830607e1ff74c532a3c5614e8b5e9776d63aa3'

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()

def normalize(output):
    if output.exists(): raise FileExistsError('Choose a new version directory; existing evidence is never overwritten.')
    source_hash = digest(SOURCE)
    if source_hash != EXPECTED: raise ValueError('Source changed; audit and register the new input first.')
    output.mkdir(parents=True)
    totals = Counter(); days = Counter(); markets = set(); seen = set()
    numeric = ['yes_bid','yes_ask','no_bid','no_ask','yes_bid_size','yes_ask_size','no_bid_size','no_ask_size',
        'reference_age_ms','yes_book_age_ms','no_book_age_ms','yes_book_latency_ms','no_book_latency_ms','snapshot_build_latency_ms']
    target = output / 'snapshots.csv.gz'
    with SOURCE.open(newline='',encoding='utf-8-sig') as source, gzip.open(target,'wt',newline='',encoding='utf-8') as dest:
        reader=csv.DictReader(source)
        extra=['source_record','condition_id','observed_at_utc','reference_price','reference_at_utc','yes_book_at_utc','no_book_at_utc',
            'reference_age_at_observation_ms','yes_age_at_observation_ms','no_age_at_observation_ms','relative_distance_from_strike',
            'normalized_yes_mid','yes_spread','no_spread','quote_eligible','reference_fresh_at_observation','books_fresh_at_observation',
            'quality_flags','availability_class','official_label']
        writer=csv.DictWriter(dest,fieldnames=list(reader.fieldnames)+extra);writer.writeheader()
        for line,row in enumerate(reader,2):
            obs=datetime.fromisoformat(row['observed_at']).astimezone(timezone.utc)
            fields={k:float(row[k]) if row[k] else None for k in numeric}
            fields.update(reference_price=float(row['btc_price']),strike=float(row['strike']))
            feature=build_snapshot_features(SimpleNamespace(**fields))
            flags=[]
            for side in ['yes','no']:
                bid,ask=fields[side+'_bid'],fields[side+'_ask']
                if bid is None or ask is None:flags.append(side+'_missing_quote')
                elif not (math.isfinite(bid) and math.isfinite(ask) and 0 <= bid <= ask <= 1):flags.append(side+'_invalid_quote')
            quote_ok=not flags
            times={key:datetime.fromtimestamp(int(row[col])/1000,tz=timezone.utc) for key,col in
                   [('reference','reference_timestamp'),('yes','yes_book_timestamp'),('no','no_book_timestamp')]}
            ages={k:(obs-v).total_seconds()*1000 for k,v in times.items()}
            ref_ok=0 <= ages['reference'] <= 3000
            books_ok=all(0 <= ages[k] <= 500 for k in ['yes','no'])
            if not ref_ok:flags.append('reference_age_outside_research_limit')
            if not books_ok:flags.append('book_age_outside_research_limit')
            key=(row['market_id'],row['observed_at'])
            if key in seen:raise ValueError('Duplicate observation identity; requires explicit policy review.')
            seen.add(key);markets.add(row['market_id']);days[str(obs.date())]+=1
            totals['rows']+=1;totals['complete_valid_quotes']+=quote_ok;totals['reference_fresh_at_observation']+=ref_ok
            totals['books_fresh_at_observation']+=books_ok;totals.update(flags)
            row.update(source_record=f'{source_hash}:{line}',condition_id=row['market_id'].lower(),observed_at_utc=obs.isoformat(),
                reference_price=fields['reference_price'],reference_at_utc=times['reference'].isoformat(),yes_book_at_utc=times['yes'].isoformat(),no_book_at_utc=times['no'].isoformat(),
                reference_age_at_observation_ms=ages['reference'],yes_age_at_observation_ms=ages['yes'],no_age_at_observation_ms=ages['no'],
                relative_distance_from_strike=feature.relative_distance_from_strike,normalized_yes_mid=feature.normalized_yes_mid if quote_ok else None,
                yes_spread=feature.yes_spread,no_spread=feature.no_spread,quote_eligible=int(quote_ok),reference_fresh_at_observation=int(ref_ok),books_fresh_at_observation=int(books_ok),
                quality_flags=';'.join(flags),availability_class='historical_event_time_only',official_label='')
            writer.writerow(row)
    manifest={'version':output.name,'source':str(SOURCE.relative_to(ROOT)).replace('\\','/'),'source_sha256':source_hash,
      'output':'snapshots.csv.gz','output_sha256':digest(target),'script_sha256':digest(Path(__file__)),
      'counts':dict(totals),'markets':len(markets),'rows_by_day':dict(days),'excluded_rows':0,'deduplicated_rows':0,
      'rules':['Preserve every raw column and row; source_record is SHA256:CSV record number (header=1).',
        'Parse original epoch milliseconds to UTC; recompute source ages at observed_at without clock correction.',
        'Reuse polybtc.data.dataset.features; withhold normalized midpoint when quotes are missing/invalid/crossed.',
        'Keep rejected rows and flags. Observation-age checks do not establish receipt by a prediction deadline.',
        'No imputation, receipt synthesis, label assignment, model training or operational writes.'],
      'research_role':'Exposed historical quality/feature analysis; not independent evaluation or executable evidence.',
      'label_policy':'official_label intentionally empty. Retained official labels require a separate versioned provenance join; no BTC proxies.',
      'python':sys.version,'source_unchanged':digest(SOURCE)==source_hash}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    normalize(parser.parse_args().output)
