"""Retained collector inputs for paper simulation, never live authorization.

The local collector is the trusted HTTPS/WSS acquisition boundary. The sidecar
must have the same OS access protection as the trading state. Hashes detect
binding errors, not a malicious administrator replacing the complete database.
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from polybtc.data.snapshot_codec_vnext import _serialize
from polybtc.shadow.source_verification_vnext import SnapshotSourceEvidence, VNextSourceVerificationAdapter

PRODUCER = 'local_https_wss_paper_v1'
PAPER_FEE_MODEL = 'paper_cash_taker_full_precision_v1'


def binding(row):
    return _serialize(replace(row, snapshot_id='', source_file=None, ingested_at=row.observed_at))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def reference(event):
    p = event['payload']
    if event.get('topic') in ('crypto_prices_twap_sixty', 'prices.crypto.chainlink.twap'):
        if p['symbol'] != 'btc/usd' or int(p.get('window_s', p.get('window_seconds', 60))) != 60:
            raise ValueError('Invalid legacy reference')
        value = Decimal(str(p['full_accuracy_value'])) / Decimal(10**18) if 'full_accuracy_value' in p else Decimal(str(p['value']))
    elif event.get('channel') == 'price.crypto.twap':
        if p['symbol'] != 'btcusd' or p['window_seconds'] != 60 or p.get('source', '').lower() != 'chainlink':
            raise ValueError('Invalid PolyBolt reference')
        value = Decimal(str(p.get('full_accuracy_value', p['value'])))
    else:
        raise ValueError('Unexpected reference channel')
    if not value.is_finite() or value <= 0:
        raise ValueError('Invalid reference price')
    return float(value), datetime.fromtimestamp(int(p['timestamp'])/1000, timezone.utc)


def _list(value):
    return json.loads(value) if isinstance(value, str) else value


def attest(row, raw, evidence_id, captured):
    """Recompute identities and prices from retained upstream inputs."""
    from polybtc.data.market_values_vnext import best_bid_ask, timestamp_seconds
    m = raw['market']
    outcomes, tokens = _list(m['outcomes']), _list(m['clobTokenIds'])
    if m['conditionId'].lower() != row.condition_id or outcomes not in (['Up','Down'], ['Yes','No']):
        raise ValueError('Market mapping mismatch')
    if tokens != [row.yes_token_id, row.no_token_id] or tokens[0] == tokens[1]:
        raise ValueError('Token mapping mismatch')
    value, observed = reference(raw['reference'])
    strike, boundary = reference(raw['strike'])
    start = row.market_end_at.timestamp() - 300
    if datetime.fromisoformat(m['endDate'].replace('Z','+00:00')) != row.market_end_at:
        raise ValueError('Market expiry mismatch')
    if m['slug'] != 'btc-updown-5m-'+str(int(start)):
        raise ValueError('Market interval mismatch')
    if value != row.reference_price or observed != row.reference_timestamp or strike != row.strike:
        raise ValueError('Reference binding mismatch')
    if abs(boundary.timestamp()-start) > 5:
        raise ValueError('Strike outside preserved collector boundary rule')
    for side in ('yes', 'no'):
        book=raw[side]
        if book['market'].lower() != row.condition_id or str(book['asset_id']) != getattr(row,side+'_token_id'):
            raise ValueError('Book identity mismatch')
        if tuple(best_bid_ask(book)) != tuple(getattr(row,side+'_'+k) for k in ('bid','ask','bid_size','ask_size')):
            raise ValueError('Book prices/depth mismatch')
        if timestamp_seconds(book['timestamp']) != getattr(row,side+'_book_timestamp').timestamp():
            raise ValueError('Book timestamp mismatch')
        for key in ('tick_size','min_order_size'):
            if float(book[key]) != getattr(row,side+'_'+key):
                raise ValueError('Book constraints mismatch')
    polybolt=raw['reference'].get('channel') == 'price.crypto.twap'
    return SnapshotSourceEvidence(evidence_id, PRODUCER, row, captured,
        reference_endpoint='wss://ws-live-v2.polymarket.com/ws' if polybolt else 'wss://ws-live-data.polymarket.com',
        reference_topic='price.crypto.twap' if polybolt else raw['reference']['topic'],
        reference_symbol='btcusd' if polybolt else 'btc/usd',
        reference_window_seconds=60, strike_semantics_verified=True,
        metadata_endpoint='https://gamma-api.polymarket.com', metadata_condition_id=row.condition_id,
        outcome_tokens=tuple(zip(outcomes,tokens)),
        yes_book_endpoint='https://clob.polymarket.com/book',yes_book_condition_id=row.condition_id,yes_book_asset_id=tokens[0],
        no_book_endpoint='https://clob.polymarket.com/book',no_book_condition_id=row.condition_id,no_book_asset_id=tokens[1])


class AcquisitionEvidenceStore:
    def __init__(self, path, *, create=False, stream=False):
        self.path=Path(path).resolve()
        self.stream=stream
        self._wal_readers = None
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE IF NOT EXISTS acquisition (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, raw TEXT NOT NULL, captured TEXT NOT NULL)')
                for action in ('UPDATE','DELETE'):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{action} BEFORE {action} ON acquisition BEGIN SELECT RAISE(ABORT,'Immutable acquisition'); END")
            if stream:
                from uuid import uuid4
                with sqlite3.connect(self.path) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS input_metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL)")
                    db.execute("INSERT OR IGNORE INTO input_metadata VALUES ('identity',?)",(str(uuid4()),))
                    db.execute("CREATE TABLE IF NOT EXISTS input_observations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, acquisition_id TEXT NOT NULL UNIQUE REFERENCES acquisition(id), runtime_id TEXT NOT NULL UNIQUE, source_file TEXT, observed_at TEXT NOT NULL, condition_id TEXT NOT NULL)")
                    db.execute("CREATE INDEX IF NOT EXISTS input_observed ON input_observations(observed_at)")
                    for action in ('UPDATE','DELETE'):
                        db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_input_{action} BEFORE {action} ON input_observations BEGIN SELECT RAISE(ABORT,'Immutable input'); END")
            from polybtc.shadow.sqlite_wal_vnext import WALReaders
            self._wal_readers = WALReaders((self.path,))
        elif not self.path.is_file():
            raise ValueError('Acquisition evidence database missing')

    def close(self):
        if self._wal_readers is not None:
            self._wal_readers.close()

    def record(self,row,raw,at):
        payload=binding(row)
        key=digest(payload)
        encoded=json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False)
        attest(row,raw,key,at)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT snapshot,raw FROM acquisition WHERE id=?',(key,)).fetchone()
            if prior is not None:
                if prior != (payload,encoded): raise ValueError('Conflicting acquisition evidence')
            else:
                db.execute('INSERT INTO acquisition VALUES (?,?,?,?)',(key,payload,encoded,at.isoformat()))
            if self.stream:
                db.execute('INSERT OR IGNORE INTO input_observations(acquisition_id,runtime_id,source_file,observed_at,condition_id) VALUES (?,?,NULL,?,?)',(key,'acquisition:'+key,row.observed_at.isoformat(),row.condition_id))
        return key

    def lookup(self,row):
        payload=binding(row)
        key=digest(payload)
        with sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True) as db:
            item=db.execute('SELECT snapshot,raw,captured FROM acquisition WHERE id=?',(key,)).fetchone()
        if item is None: return None
        if item[0] != payload: raise ValueError('Canonical snapshot mismatch')
        return attest(row,json.loads(item[1]),key,datetime.fromisoformat(item[2]))


class PaperAcquisitionVerifier(VNextSourceVerificationAdapter):
    """Explicit simulated cash fees and retained acquisition, not venue receipts.

Uses the existing full-precision fee formula and nearest-boundary strike rule.
Both assumptions are labeled in durable decision provenance, not silently
presented as authenticated live charged fees or an official opening strike.
"""
    def __init__(self, store):
        super().__init__(trusted_producers=frozenset({PRODUCER}))
        self.store=store

    def _bound_result(self,row,at):
        try:
            ev=self.store.lookup(row)
            self._evidence={row.snapshot_id:ev}
            return super()._bound_result(row,at)
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            # Only fixed internal codes are persisted, never upstream exception
            # text or retained raw responses. Rejection behavior is unchanged.
            code = {
                'Canonical snapshot mismatch': 'canonical_snapshot_mismatch',
                'Market mapping mismatch': 'market_token_binding_mismatch',
                'Token mapping mismatch': 'market_token_binding_mismatch',
                'Market expiry mismatch': 'market_interval_mismatch',
                'Market interval mismatch': 'market_interval_mismatch',
                'Reference binding mismatch': 'raw_reference_binding_mismatch',
                'Strike outside preserved collector boundary rule': 'strike_boundary_mismatch',
                'Book identity mismatch': 'book_identity_mismatch',
                'Book prices/depth mismatch': 'raw_book_values_mismatch',
                'Book timestamp mismatch': 'raw_book_timestamp_mismatch',
                'Book constraints mismatch': 'raw_book_constraints_mismatch',
                'Invalid legacy reference': 'reference_semantics_mismatch',
                'Invalid PolyBolt reference': 'reference_semantics_mismatch',
                'Unexpected reference channel': 'reference_semantics_mismatch',
                'Invalid reference price': 'invalid_reference_price',
            }.get(str(exc), 'malformed_acquisition_evidence')
            return None, code

    def verify(self,**kwargs):
        result=super().verify(**kwargs)
        reasons=tuple(r for r in result.reasons if r!='fee_applicability_and_accounting_unverified')
        return replace(result,sources=replace(result.sources,fee_policy_verified=result.fee_descriptor_verified),
            reasons=reasons,execution_scope='paper',fee_accounting_model=PAPER_FEE_MODEL,
            strike_model='collector_nearest_boundary_twap_within_5s_v1')
