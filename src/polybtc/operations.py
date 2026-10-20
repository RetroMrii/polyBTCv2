"""Offline operations snapshots. Readers never initialize or migrate databases."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from polybtc.execution.lifecycle import OrderLifecycleStore
from polybtc.execution.live_accounting import project

MAIN_MODEL_SHA256 = '42647c6810f8ee01313aee24362e0c83e20b4240f951316d2d576160327752e4'


def atomic_status(path, payload):
    path=Path(path)
    temporary=path.with_name(path.name+'.'+str(uuid4())+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as handle:
            json.dump(payload,handle,sort_keys=True,allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows readers/scanners can briefly deny delete sharing, which also
        # blocks atomic replacement. Retry only publication of the already
        # flushed snapshot, never the trading cycle or a non-atomic overwrite.
        delays = iter((0.025, 0.05, 0.1, 0.2, 0.4, 0.4))
        while True:
            try:
                os.replace(temporary,path)
                break
            except OSError as exc:
                if getattr(exc, 'winerror', None) not in (5, 32, 33):
                    raise
                delay = next(delays, None)
                if delay is None:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)


def model_identity(path):
    path=Path(path)
    with path.open('rb') as handle:
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
    return dict(path=str(path.resolve()),sha256=digest,version='hgb3_expanded_v2' if digest==MAIN_MODEL_SHA256 else 'unapproved',
                approved=digest==MAIN_MODEL_SHA256,
                approval_scope='artifact_identity_only',
                identity_verified=digest==MAIN_MODEL_SHA256,
                production_approved=False)


@contextmanager
def readonly(path):
    path=Path(path).resolve()
    if not path.is_file(): raise FileNotFoundError()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def freshness(value, now, seconds):
    try:
        if isinstance(value,dict): value=value['__polybtc_datetime_utc__']
        stamp=datetime.fromisoformat(value)
        if stamp.utcoffset() is None: raise ValueError()
        age=(now-stamp).total_seconds()
        return dict(status='fresh' if 0<=age<=seconds else 'future' if age<0 else 'stale',age_seconds=age)
    except (ValueError,TypeError,KeyError):
        return dict(status='unknown',age_seconds=None)


def live_status(path, now):
    with readonly(path) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables!={'lifecycle_orders','lifecycle_events','live_accounting_events'} or db.execute('PRAGMA user_version').fetchone()[0]!=2:
            raise ValueError('Unsupported live ledger')
        store=object.__new__(OrderLifecycleStore)
        snapshot=project(store,db,at=now)
        orders=[store._view(db,oid) for oid, in db.execute('SELECT id FROM lifecycle_orders').fetchall()]
        events=[json.loads(p) for p, in db.execute('SELECT payload FROM live_accounting_events ORDER BY rowid')]
        operations=[e for e in events if e.get('kind')=='operation']
        last=operations[-1] if operations else None
        return dict(status='blocked' if snapshot.issues else 'accounted',
            orders=[dict(order_id=o.intent.order_id,state=o.state.value,filled_quantity=str(o.filled_quantity)) for o in orders],
            positions=[{k:str(v) if isinstance(v,Decimal) else v for k,v in asdict(p).items()} for p in snapshot.positions],
            pending_liabilities={k:str(v) for k,v in snapshot.reserved_cash.items()},
            open_cost_basis=None if any(p.cost_basis is None for p in snapshot.positions) else
                str(sum((p.cost_basis for p in snapshot.positions),Decimal(0))),
            realized_pnl=[dict(collateral=k[0],utc_date=k[1],value=str(v)) for k,v in snapshot.realized_by_day.items()],
            issues=list(snapshot.issues),unknown_orders=list(snapshot.unknown_orders),
            last_operation=last,failures=[e for e in operations if e.get('status')=='failed'][-20:],
            controls_current=False, # A persisted control value is not a current process attestation.
            recovery_required=bool(snapshot.unknown_orders))


def status_report(state_dir, model_path, *, live_ledger=None, fee_cache=None, now=None):
    now=now or datetime.now(timezone.utc)
    state_dir=Path(state_dir)
    layout=None
    if (state_dir/'paper_layout.json').is_file():
        layout=json.loads((state_dir/'paper_layout.json').read_text(encoding='utf-8'))
        if layout.get('status')!='complete': raise ValueError('Incomplete paper migration')
        if fee_cache is None:fee_cache=Path(layout['input_path'])
    result=dict(version='operations_v1',observed_at=now.isoformat(),live_ready=False,
                status_scope='live_readiness',
                blockers=['live_activation_not_implemented','source_and_fee_applicability_unverified'])
    try:
        heartbeat=json.loads((state_dir/'runtime_status.json').read_text(encoding='utf-8'))
        age=freshness(heartbeat['observed_at'],now,5)
        result['process']=dict(status='healthy' if age['status']=='fresh' and heartbeat['state']=='running' else
                               heartbeat['state'] if age['status']=='fresh' else 'unknown',heartbeat=heartbeat,freshness=age)
    except (OSError,ValueError,KeyError,TypeError): result['process']=dict(status='unknown')
    try: result['model']=model_identity(model_path)
    except (OSError,ValueError): result['model']=dict(approved=False,status='unavailable')
    try:
        if layout:
            with readonly(Path(layout['input_path'])) as db:
                row=db.execute('SELECT a.snapshot FROM input_observations o JOIN acquisition a ON a.id=o.acquisition_id ORDER BY o.sequence DESC LIMIT 1').fetchone()
        else:
            with readonly(state_dir/'snapshot_history.sqlite3') as db:
                row=db.execute('SELECT record_json FROM snapshots ORDER BY observed_at_utc DESC LIMIT 1').fetchone()
        data=json.loads(row[0]) if row else {}
        from polybtc.data.paper_policy_vnext import PAPER_POLICY
        result['sources']={name:freshness(data.get(field),now,limit) for name,field,limit in (
            ('reference','reference_timestamp',PAPER_POLICY.max_reference_age_ms/1000),('yes_book','yes_book_timestamp',.5),('no_book','no_book_timestamp',.5))}
        result['collector']=dict(status='processing' if all(v['status']=='fresh' for v in result['sources'].values()) else 'stale_or_unknown',
                                 last_snapshot_id=data.get('snapshot_id'))
    except (OSError,sqlite3.Error,ValueError,TypeError,AttributeError):
        result['sources']={}
        result['collector']=dict(status='unavailable')
    result['fees']=dict(status='unavailable',applicability_verified=False)
    if fee_cache is not None:
        try:
            with readonly(fee_cache) as db:
                rows=db.execute('SELECT condition_id,retrieved_at_utc FROM fee_policies').fetchall()
                conflicts=db.execute('SELECT COUNT(*) FROM fee_conflicts').fetchone()[0]
            result['fees']=dict(status='conflicted' if conflicts else 'observed' if rows else 'empty',
                applicability_verified=False,conflicts=conflicts,
                policies=[dict(condition_id=m,**freshness(t,now,86400)) for m,t in rows])
        except (OSError,sqlite3.Error,ValueError): pass
    result['live']=dict(status='not_configured')
    result['paper']=dict(status='not_configured')
    try:
        marker=json.loads((state_dir/'runtime_mode.json').read_text())
        if marker.get('mode')=='paper_execution' and marker.get('live_trading_enabled') is False:
            with readonly(state_dir/('paper.sqlite3' if layout else 'trades.sqlite3')) as db:
                db.row_factory=sqlite3.Row
                entries=[dict(r) for r in db.execute('SELECT condition_id,side,status,reserved_cost,filled_size,execution_price,entry_fee,realized_pnl FROM entries')]
            with readonly(state_dir/('paper.sqlite3' if layout else 'decisions.sqlite3')) as db:
                latest=db.execute('SELECT status,reason,source_verification_json FROM decisions ORDER BY id DESC LIMIT 1').fetchone()
            result['paper']=dict(status='observed',positions=entries,
                process_health=result['process']['status'],
                source_health=result['collector']['status'],
                pending_liabilities=sum(r['reserved_cost'] for r in entries if r['status']=='PENDING'),
                open_cost=sum(r['filled_size']*r['execution_price']+r['entry_fee'] for r in entries if r['status']=='FILLED'),
                realized_pnl=sum(r['realized_pnl'] or 0 for r in entries),
                latest_decision=dict(status=latest[0],reason=latest[1],verification=json.loads(latest[2]) if latest[2] else None) if latest else None,
                execution_scope='paper',live_authorization=False)
    except (OSError,ValueError,sqlite3.Error,TypeError,KeyError):
        result['paper']=dict(status='unavailable')
    if live_ledger is not None:
        try: result['live']=live_status(live_ledger,now)
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError): result['live']=dict(status='unavailable',issues=['live_ledger_unreadable'])
    if result['process']['status']!='healthy': result['blockers'].append('process_not_healthy')
    if not result['model']['approved']: result['blockers'].append('model_identity_unverified')
    if result['collector']['status']!='processing': result['blockers'].append('collector_stale_or_unavailable')
    if result['live']['status'] in {'blocked','unavailable'}: result['blockers'].append('live_accounting_unresolved')
    result['status']='blocked'
    return result
