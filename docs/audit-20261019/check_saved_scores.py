"""Recalculate saved forecast scores; does not refit or replay inference."""
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = json.loads((ROOT/'docs/POLYBTC_S5_EVIDENCE.json').read_text())
rows = [r for r in source['prospective_rows'] if r['partition'] == 'evaluation']
counts = Counter(r['condition_id'] for r in rows)
scores = {}
for key in ['market', 'raw', 'platt', 'isotonic', 'combination']:
    brier = sum((r[key]-r['y'])**2/counts[r['condition_id']] for r in rows)/len(counts)
    log_loss = 0
    for row in rows:
        p = max(1e-15, min(1-1e-15, row[key]))
        log_loss += -(row['y']*math.log(p)+(1-row['y'])*math.log1p(-p))/counts[row['condition_id']]/len(counts)
    saved = source['prospective']['overall'][key]
    scores[key] = {'brier':brier,'log_loss':log_loss,
        'matches_saved':abs(brier-saved['brier']) < 1e-12 and abs(log_loss-saved['log_loss']) < 1e-12}
    assert scores[key]['matches_saved']
out = {'source':'docs/POLYBTC_S5_EVIDENCE.json','scope':'Saved-prediction arithmetic only; no model fitting or source re-attestation.',
       'rows':len(rows),'markets':len(counts),'scores':scores}
Path(__file__).with_name('score-check.json').write_text(json.dumps(out,indent=2)+'\n')
print('All five Brier/log-loss pairs match within 1e-12.')
