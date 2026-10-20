"""Live-only accounting projection over immutable exchange evidence.

No network, order execution, resolution oracle or redemption operation. External
evidence must be authenticated before calling these APIs. Unknown fees are never
zero fees; unknown orders retain their approved maximum cash reservation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import re
from uuid import uuid4

from polybtc.execution.lifecycle import (
    OrderLifecycleStore, OrderState as S, UNKNOWN, TERMINAL,
    TRADE_TRANSITIONS, amount, canonical, identity,
)

ZERO = Decimal(0)


def stamp(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('Aware exchange timestamp required')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


@dataclass(frozen=True)
class Position:
    condition_id: str
    token_id: str
    collateral_asset: str
    quantity_after_known_fees: Decimal
    fees_complete: bool
    cost_basis: Decimal | None
    realized_pnl: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    settlement_status: str


@dataclass(frozen=True)
class AccountingSnapshot:
    positions: tuple[Position, ...]
    reserved_cash: dict[str, Decimal]
    realized_by_day: dict[tuple[str, str], Decimal]
    issues: tuple[str, ...]
    unknown_orders: tuple[str, ...]

    @property
    def complete(self):
        return not self.issues


def project(store, db, *, at=None, exclude_order_id=None):
    """One SQLite snapshot; no checkpoint or separately mutable position totals."""
    orders = {oid: store._view(db, oid) for oid, in db.execute('SELECT id FROM lifecycle_orders').fetchall()}
    if exclude_order_id is not None:
        if orders[exclude_order_id].state != S.RISK_APPROVED:
            raise ValueError('Only an unsubmitted candidate may be excluded')
        del orders[exclude_order_id]
    events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM live_accounting_events ORDER BY rowid')]
    issues, facts, reservations, marks, settlements = [], {}, {}, {}, {}
    for event in events:
        kind = event['kind']
        if kind == 'observation':
            facts[(event['order_id'], event['trade_id'])] = event
        elif kind == 'reserve':
            reservations[event['order_id']] = amount(event['max_cost'])
        elif kind == 'mark':
            key = (event['condition_id'],event['token_id'],event['collateral_asset'])
            if key not in marks or event['observed_at'] > marks[key]['observed_at']:
                marks[key] = event
        elif kind == 'settlement':
            settlements[event['settlement_id']] = event
        elif kind == 'discrepancy':
            issues.append('discrepancy:' + event['reference'])

    unknown = tuple(oid for oid,v in orders.items() if v.state == UNKNOWN)
    issues.extend('unknown_order:' + oid for oid in unknown)
    timeline, reserved = [], {}
    for oid, view in orders.items():
        # Import already recorded G/H fills without deleting or fabricating data.
        for tid, trade in view.trades.items():
            if (oid, tid) not in facts:
                facts[(oid,tid)] = dict(trade, order_id=oid, trade_id=tid, executed_at=None)
        spent = ZERO
        confirmed_gross = ZERO
        for (owner, tid), fact in facts.items():
            if owner != oid:
                continue
            if fact['status'] not in {'CONFIRMED','FAILED'}:
                issues.append('unsettled_trade:' + oid + ':' + tid)
            if fact['status'] != 'CONFIRMED':
                continue
            quantity, price = amount(fact['quantity']), amount(fact['price'])
            confirmed_gross += quantity
            fee = view.trades.get(tid)
            known = bool(fee and fee['status']=='CONFIRMED' and
                         amount(fee['quantity'])==quantity and amount(fee['price'])==price)
            cash = amount(fee['cash_fee']) if known else ZERO
            shares = amount(fee['share_fee']) if known else ZERO
            if not known:
                issues.append('unreconciled_fee:' + oid + ':' + tid)
            if not fact.get('executed_at'):
                issues.append('missing_exchange_time:' + oid + ':' + tid)
            spent += quantity * price + cash
            timeline.append((fact.get('executed_at') or '0001', oid+':'+tid,
                'fill', (view.intent, quantity, price, cash, shares, known)))
        if confirmed_gross > amount(view.intent.quantity):
            issues.append('exchange_overfill:' + oid)
        pending = (view.state not in TERMINAL and view.state not in {S.CREATED,S.RISK_APPROVED}) or (
            view.state == S.RISK_APPROVED and oid in reservations)
        if pending:
            ceiling = reservations.get(oid)
            if ceiling is None:
                issues.append('missing_reservation:' + oid)
                # Preserve a known notional lower bound, never declare it complete.
                ceiling = amount(view.intent.quantity)*amount(view.intent.limit_price)
            reserved[view.intent.collateral_asset] = reserved.get(view.intent.collateral_asset,ZERO) + max(ZERO, ceiling-spent)

    for event in settlements.values():
        key = (event['condition_id'],event['token_id'],event['collateral_asset'])
        if event['status']=='CONFIRMED':
            timeline.append((event['occurred_at'],event['settlement_id'],'settlement',event))
        else:
            issues.append('settlement_pending:' + event['settlement_id'])

    positions, daily = {}, {}
    # Weighted average cost; chronological exchange times, deterministic tie order.
    # Missing fees/time render the position inexact and block new submissions.
    for occurred, _, kind, data in sorted(timeline, key=lambda row:(row[0],row[1])):
        if kind=='fill':
            intent,q,p,cash,shares,known = data
            key=(intent.condition_id,intent.token_id,intent.collateral_asset)
        else:
            key=(data['condition_id'],data['token_id'],data['collateral_asset'])
        pos=positions.setdefault(key,dict(q=ZERO,cost=ZERO,realized=ZERO,known=True,status='OPEN'))
        realized=ZERO
        if kind=='fill' and intent.side=='BUY':
            pos['q'] += q-shares
            pos['cost'] += q*p+cash
            pos['known'] &= known and occurred!='0001'
            if pos['status']=='SETTLED':
                issues.append('fill_after_settlement:' + key[1])
                pos['status']='OPEN'
        else:
            removed = q+shares if kind=='fill' else amount(data['quantity'])
            proceeds = q*p-cash if kind=='fill' else amount(data['cash_received'])-amount(data['cash_fee'])
            if removed > pos['q'] or pos['q'] <= 0:
                issues.append('inventory_shortfall:' + key[1])
                pos['known']=False
                allocated=ZERO
            else:
                with localcontext() as context:
                    context.prec=40
                    allocated=pos['cost'] if removed==pos['q'] else pos['cost']*removed/pos['q']
            pos['q']-=removed
            pos['cost']-=allocated
            realized=proceeds-allocated
            pos['realized']+=realized
            if kind=='fill': pos['known'] &= known and occurred!='0001'
            elif pos['q']==0: pos['status']='SETTLED'
        if realized and pos['known']:
            daykey=(key[2],occurred[:10])
            daily[daykey]=daily.get(daykey,ZERO)+realized

    output=[]
    for key,p in positions.items():
        mark=marks.get(key)
        value=None
        if p['q']==0: value=ZERO
        elif mark is not None and at is not None:
            age=(datetime.fromisoformat(stamp(at))-datetime.fromisoformat(mark['observed_at'])).total_seconds()
            if 0<=age<=0.5: value=p['q']*amount(mark['price'])
        for settlement in settlements.values():
            if (settlement['condition_id'],settlement['token_id'],settlement['collateral_asset'])==key and settlement['status']=='PENDING':
                p['status']='SETTLEMENT_PENDING'
        if not p['known']: issues.append('inexact_position:' + key[1])
        output.append(Position(*key,p['q'],p['known'],p['cost'] if p['known'] else None,
            p['realized'] if p['known'] else None,value if p['known'] else None,
            value-p['cost'] if value is not None and p['known'] else None,p['status']))
    # Never expose a partial aggregate as an exact daily loss total.
    inexact_assets = {p.collateral_asset for p in output if not p.fees_complete}
    daily = {k:v for k,v in daily.items() if k[0] not in inexact_assets}
    return AccountingSnapshot(tuple(output),reserved,daily,tuple(sorted(set(issues))),unknown)


class LiveAccounting:
    def __init__(self, store: OrderLifecycleStore, wallet: str):
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}',wallet):
            raise ValueError('Explicit account wallet required')
        self.store=store
        with store._transaction() as db:
            self._insert(db,'account',dict(kind='account',wallet=wallet.lower(),version=1))

    @staticmethod
    def _insert(db, eid, event):
        payload=canonical(event)
        old=db.execute('SELECT payload FROM live_accounting_events WHERE id=?',(eid,)).fetchone()
        if old:
            if old[0]!=payload: raise ValueError('Conflicting accounting identity')
            return False
        db.execute('INSERT INTO live_accounting_events(id,payload) VALUES (?,?)',(eid,payload))
        return True

    def snapshot(self, *, at=None):
        with self.store._transaction() as db:
            return project(self.store,db,at=at)

    def reserve(self, oid, max_cost, evidence):
        identity(evidence)
        cap=amount(max_cost)
        with self.store._transaction() as db:
            view=self.store._view(db,oid)
            if view.state!=S.RISK_APPROVED or cap < amount(view.intent.quantity)*amount(view.intent.limit_price):
                raise ValueError('Risk-approved cost envelope required')
            return self._insert(db,'reserve:'+oid,dict(kind='reserve',order_id=oid,max_cost=max_cost,evidence=evidence))

    def observe_fill(self, oid, *, exchange_order_id, trade_id, quantity, price, status, executed_at, evidence):
        for v in (exchange_order_id,trade_id,evidence): identity(v)
        if amount(quantity)<=0 or not 0<amount(price)<=1 or status not in TRADE_TRANSITIONS:
            raise ValueError('Invalid exchange fill')
        event=dict(kind='observation',order_id=oid,exchange_order_id=exchange_order_id,
            trade_id=trade_id,quantity=quantity,price=price,status=status,
            executed_at=stamp(executed_at),evidence=evidence)
        eid='fill:'+hashlib.sha256(canonical([oid,trade_id,status]).encode()).hexdigest()
        conflict=False
        with self.store._transaction() as db:
            view=self.store._view(db,oid)
            if view.exchange_order_id!=exchange_order_id or view.state in {S.CREATED,S.RISK_APPROVED}:
                raise ValueError('Unbound exchange fill')
            prior=None
            for payload, in db.execute('SELECT payload FROM live_accounting_events ORDER BY rowid'):
                row=json.loads(payload)
                if row.get('kind')=='observation' and row['order_id']==oid and row['trade_id']==trade_id: prior=row
            if prior:
                conflict = any(prior[k]!=event[k] for k in ('quantity','price','executed_at')) or (
                    status!=prior['status'] and status not in TRADE_TRANSITIONS[prior['status']])
            if conflict:
                self._insert(db,'discrepancy:'+str(uuid4()),dict(kind='discrepancy',reference=eid,
                    reason='conflicting_exchange_fill',order_id=oid,
                    previous=prior, incoming=event))
            else:
                # Evidence IDs may differ between transports; identity is trade+status.
                if not db.execute('SELECT 1 FROM live_accounting_events WHERE id=?',(eid,)).fetchone():
                    self._insert(db,eid,event)
        if conflict: raise ValueError('Exchange fill discrepancy requires investigation')

    def record_mark(self, *, condition_id, token_id, collateral_asset, price, observed_at, evidence):
        for v in (condition_id,token_id,collateral_asset,evidence): identity(v)
        if amount(price)>1: raise ValueError('Invalid mark')
        event=dict(kind='mark',condition_id=condition_id,token_id=token_id,collateral_asset=collateral_asset,
            price=price,observed_at=stamp(observed_at),evidence=evidence)
        with self.store._transaction() as db:
            self._insert(db,'mark:'+hashlib.sha256(canonical(event).encode()).hexdigest(),event)

    def investigate(self, oid, *, evidence, exchange_order_id=None):
        identity(evidence)
        with self.store._transaction() as db:
            view=self.store._view(db,oid)
            if view.state!=UNKNOWN: raise ValueError('Order is not awaiting investigation')
            if exchange_order_id is not None:
                self.store._append(db,oid,'investigate:'+str(uuid4()),dict(kind='exchange_identity',
                    exchange_order_id=identity(exchange_order_id),evidence=evidence))
            self._insert(db,'investigation:'+str(uuid4()),dict(kind='investigation',order_id=oid,evidence=evidence))

    def record_settlement(self, *, settlement_id, condition_id, token_id, collateral_asset,
                          quantity, payout_per_share, cash_received, cash_fee, status,
                          occurred_at, evidence):
        for v in (settlement_id,condition_id,token_id,collateral_asset,evidence): identity(v)
        q,p,c,f=map(amount,(quantity,payout_per_share,cash_received,cash_fee))
        if q<=0 or p>1 or c!=q*p or status not in {'PENDING','CONFIRMED'}:
            raise ValueError('Invalid settlement receipt')
        event=dict(kind='settlement',settlement_id=settlement_id,condition_id=condition_id,
            token_id=token_id,collateral_asset=collateral_asset,quantity=quantity,payout_per_share=payout_per_share,
            cash_received=cash_received,cash_fee=cash_fee,status=status,occurred_at=stamp(occurred_at),evidence=evidence)
        with self.store._transaction() as db:
            previous=[json.loads(p) for p, in db.execute('SELECT payload FROM live_accounting_events')
                      if json.loads(p).get('settlement_id')==settlement_id]
            for prior in previous:
                if any(prior[k]!=event[k] for k in ('condition_id','token_id','collateral_asset','quantity','payout_per_share','cash_received','cash_fee')):
                    raise ValueError('Conflicting settlement terms')
                if prior['status']=='CONFIRMED' and status!='CONFIRMED':
                    raise ValueError('Cannot regress confirmed settlement')
                if prior['status']==status and prior['occurred_at']!=event['occurred_at']:
                    raise ValueError('Conflicting settlement timestamp')
            eid='settlement:'+settlement_id+':'+status
            if db.execute('SELECT 1 FROM live_accounting_events WHERE id=?',(eid,)).fetchone():
                return False
            snapshot=project(self.store,db)
            if any(i for i in snapshot.issues if not i.startswith('settlement_pending:')):
                raise ValueError('Resolve accounting before recording settlement')
            pos=next((p for p in snapshot.positions if (p.condition_id,p.token_id,p.collateral_asset)==(condition_id,token_id,collateral_asset)),None)
            if pos is None or not pos.fees_complete or q>pos.quantity_after_known_fees:
                raise ValueError('Settlement exceeds confirmed holdings')
            inserted = self._insert(db,eid,event)
            after = project(self.store,db)
            if any(i not in snapshot.issues and not i.startswith('settlement_pending:') for i in after.issues):
                raise ValueError('Settlement conflicts with chronological holdings')
            return inserted
