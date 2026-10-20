"""Offline order lifecycle contract. No signing, network, or shadow-ledger writes.

An adapter must authenticate/normalize evidence before using this contract. A
True return from begin_submission is a single dispatch permit; never resend on
False, timeout, or restart. Reconciliation is an explicit evidence boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5


class OrderState(StrEnum):
    CREATED = 'CREATED'
    RISK_APPROVED = 'RISK_APPROVED'
    SUBMISSION_PENDING = 'SUBMISSION_PENDING'
    SUBMITTED = 'SUBMITTED'
    ACKNOWLEDGED = 'ACKNOWLEDGED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCEL_REQUESTED = 'CANCEL_REQUESTED'
    CANCELLED = 'CANCELLED'
    REJECTED = 'REJECTED'
    EXPIRED = 'EXPIRED'
    UNKNOWN_RECONCILIATION_REQUIRED = 'UNKNOWN_RECONCILIATION_REQUIRED'


S = OrderState
CONTRACT_VERSION = 'order_lifecycle_v3_live_risk'
UNKNOWN = S.UNKNOWN_RECONCILIATION_REQUIRED
TERMINAL = frozenset({S.FILLED, S.CANCELLED, S.REJECTED, S.EXPIRED})
TRANSITIONS = {
    S.CREATED: frozenset({S.RISK_APPROVED, S.REJECTED}),
    S.RISK_APPROVED: frozenset({S.SUBMISSION_PENDING, S.REJECTED}),
    S.SUBMISSION_PENDING: frozenset({S.SUBMITTED, S.ACKNOWLEDGED, S.REJECTED, UNKNOWN}),
    S.SUBMITTED: frozenset({S.ACKNOWLEDGED, S.REJECTED, UNKNOWN}),
    S.ACKNOWLEDGED: frozenset({S.CANCEL_REQUESTED, UNKNOWN}),
    S.PARTIALLY_FILLED: frozenset({S.CANCEL_REQUESTED, UNKNOWN}),
    S.CANCEL_REQUESTED: frozenset({UNKNOWN}),
    **{state: frozenset({UNKNOWN}) for state in TERMINAL},
    UNKNOWN: frozenset(),
}
TRADE_TRANSITIONS = {
    'MATCHED': {'MINED', 'RETRYING', 'CONFIRMED', 'FAILED'},
    'MATCHED_NOT_BROADCASTED': {'MATCHED', 'MINED', 'RETRYING', 'CONFIRMED', 'FAILED'},
    'MINED': {'RETRYING', 'CONFIRMED', 'FAILED'},
    'RETRYING': {'MINED', 'CONFIRMED', 'FAILED'},
    'CONFIRMED': set(), 'FAILED': set(),
}


def identity(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError('Nonempty canonical identifier required')
    return value


def amount(value: str) -> Decimal:
    # Bounded exact decimals keep all arithmetic within Decimal precision.
    if not isinstance(value, str):
        raise ValueError('Amounts must be decimal strings')
    try:
        result = Decimal(value)
    except Exception as exc:
        raise ValueError('Invalid amount') from exc
    if not result.is_finite() or result < 0 or result > Decimal('1000000') or result.as_tuple().exponent < -8:
        raise ValueError('Invalid amount or precision')
    return result


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def acknowledgement(*, exchange_order_id: str, venue_status: str, evidence: str) -> dict:
    """Normalize placement semantics, never infer a fill from 'matched'."""
    if venue_status not in {'live', 'matched', 'delayed', 'unmatched'}:
        raise ValueError('Unsupported placement status; reconciliation required')
    return dict(kind='transition', target=S.ACKNOWLEDGED,
                exchange_order_id=identity(exchange_order_id),
                venue_status=venue_status, evidence=identity(evidence))


@dataclass(frozen=True)
class OrderIntent:
    idempotency_key: str
    condition_id: str
    token_id: str
    side: str
    quantity: str
    limit_price: str
    collateral_asset: str
    order_type: str = 'GTC'
    expires_at: str | None = None

    def __post_init__(self):
        for value in (self.idempotency_key, self.condition_id, self.token_id, self.collateral_asset):
            identity(value)
        if self.side not in {'BUY', 'SELL'} or self.order_type not in {'GTC', 'GTD', 'FOK', 'FAK'}:
            raise ValueError('Unsupported side or order type')
        if not 0 < amount(self.quantity) or not 0 < amount(self.limit_price) <= 1:
            raise ValueError('Invalid quantity or price')
        if self.order_type == 'GTD':
            from datetime import datetime
            if not self.expires_at or datetime.fromisoformat(self.expires_at).utcoffset() is None:
                raise ValueError('GTD requires aware expiration')
        elif self.expires_at is not None:
            raise ValueError('Expiration only supported for GTD')

    @property
    def order_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, 'polybtc:order:v1:' + self.idempotency_key))


@dataclass
class OrderView:
    intent: OrderIntent
    state: OrderState = S.CREATED
    exchange_order_id: str | None = None
    venue_status: str | None = None
    trades: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    @property
    def filled_quantity(self) -> Decimal:
        return sum((amount(t['quantity']) for t in self.trades.values() if t['status'] == 'CONFIRMED'), Decimal(0))

    @property
    def provisional_quantity(self) -> Decimal:
        return sum((amount(t['quantity']) for t in self.trades.values() if t['status'] not in {'CONFIRMED', 'FAILED'}), Decimal(0))

    @property
    def filled_notional(self) -> Decimal:
        return sum((amount(t['quantity']) * amount(t['price']) for t in self.trades.values() if t['status'] == 'CONFIRMED'), Decimal(0))

    @property
    def cash_fees(self) -> Decimal:
        return sum((amount(t['cash_fee']) for t in self.trades.values() if t['status'] == 'CONFIRMED'), Decimal(0))

    @property
    def share_fees(self) -> Decimal:
        return sum((amount(t['share_fee']) for t in self.trades.values() if t['status'] == 'CONFIRMED'), Decimal(0))

    @property
    def token_delta(self) -> Decimal:
        return (self.filled_quantity if self.intent.side == 'BUY' else -self.filled_quantity) - self.share_fees

    @property
    def cash_delta(self) -> Decimal:
        return (-self.filled_notional if self.intent.side == 'BUY' else self.filled_notional) - self.cash_fees

    @property
    def reserved_quantity(self) -> Decimal:
        # Unknown state never releases the unresolved remainder.
        return Decimal(0) if self.state in TERMINAL else amount(self.intent.quantity) - self.filled_quantity


def reduce_event(view: OrderView, event: dict) -> None:
    kind = event['kind']
    evidence = identity(event['evidence'])
    if kind == 'transition':
        target = S(event['target'])
        if target == S.ACKNOWLEDGED and event.get('venue_status') not in {None, 'live', 'matched', 'delayed', 'unmatched'}:
            raise ValueError('Unknown placement status')
        if target == S.ACKNOWLEDGED and view.exchange_order_id == event.get('exchange_order_id') and view.state not in {S.CREATED, S.RISK_APPROVED, S.SUBMISSION_PENDING, S.SUBMITTED, UNKNOWN}:
            view.venue_status = event.get('venue_status', view.venue_status)
            return  # Duplicate placement cannot regress a filled order.
        if target not in TRANSITIONS[view.state]:
            raise ValueError(f'Invalid transition: {view.state} -> {target}')
        if target == S.REJECTED and view.trades:
            raise ValueError('Cannot reject an order with trade evidence')
        if target == S.CANCEL_REQUESTED and view.venue_status == 'delayed':
            raise ValueError('Delayed orders cannot yet be cancelled')
        if target == S.ACKNOWLEDGED:
            exchange = identity(event['exchange_order_id'])
            if view.exchange_order_id not in (None, exchange):
                raise ValueError('Conflicting exchange identity')
            view.exchange_order_id = exchange
            view.venue_status = event.get('venue_status')
        if target == S.SUBMISSION_PENDING:
            digest = event['payload_hash']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Submission requires a SHA-256 payload digest')
        view.state = target
    elif kind == 'exchange_identity':
        if view.state in {S.CREATED, S.RISK_APPROVED}:
            raise ValueError('Exchange identity before submission')
        exchange = identity(event['exchange_order_id'])
        if view.exchange_order_id not in (None, exchange):
            raise ValueError('Conflicting exchange identity')
        view.exchange_order_id = exchange
    elif kind == 'trade':
        if view.state in {S.CREATED, S.RISK_APPROVED, S.REJECTED}:
            raise ValueError('Trade before submission or after rejection')
        exchange = identity(event['exchange_order_id'])
        if view.exchange_order_id not in (None, exchange):
            raise ValueError('Wrong exchange order')
        trade_id = identity(event['trade_id'])
        status = event['status']
        if status not in TRADE_TRANSITIONS:
            raise ValueError('Unknown trade status')
        q, p = amount(event['quantity']), amount(event['price'])
        cash, shares = amount(event['cash_fee']), amount(event['share_fee'])
        identity(event['fee_evidence'])
        if q <= 0 or not 0 < p <= 1 or shares > q:
            raise ValueError('Invalid fill amounts')
        limit = amount(view.intent.limit_price)
        if (view.intent.side == 'BUY' and p > limit) or (view.intent.side == 'SELL' and p < limit):
            raise ValueError('Fill violates limit price')
        previous = view.trades.get(trade_id)
        terms = {k: event[k] for k in ('quantity', 'price', 'cash_fee', 'share_fee', 'fee_evidence')}
        if previous:
            if any(previous[k] != v for k, v in terms.items()):
                raise ValueError('Conflicting trade economics')
            if status == previous['status']:
                return
            if status not in TRADE_TRANSITIONS[previous['status']]:
                raise ValueError('Invalid trade status transition')
        view.exchange_order_id = exchange
        view.venue_status = 'matched'
        view.trades[trade_id] = dict(terms, status=status)
        total = sum((amount(t['quantity']) for t in view.trades.values() if t['status'] != 'FAILED'), Decimal(0))
        if total > amount(view.intent.quantity):
            raise ValueError('Overfill')
        if view.state == UNKNOWN or status == 'FAILED' or view.state in TERMINAL:
            view.state = UNKNOWN
        elif view.filled_quantity == amount(view.intent.quantity):
            view.state = S.FILLED
        elif view.state != S.CANCEL_REQUESTED:
            view.state = S.PARTIALLY_FILLED if view.filled_quantity else S.ACKNOWLEDGED
    elif kind == 'reconcile':
        if view.state != UNKNOWN and view.state != S.CANCEL_REQUESTED:
            raise ValueError('Reconciliation requires an unresolved order')
        target = S(event['target'])
        if target not in {S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.EXPIRED, S.REJECTED}:
            raise ValueError('Invalid reconciliation target')
        if view.provisional_quantity:
            raise ValueError('Unsettled trades still require reconciliation')
        if amount(event['confirmed_quantity']) != view.filled_quantity:
            raise ValueError('Missing or conflicting fill evidence')
        exchange = event['exchange_order_id']
        if target != S.REJECTED:
            identity(exchange)
        if view.exchange_order_id not in (None, exchange):
            raise ValueError('Exchange identity mismatch')
        size = amount(view.intent.quantity)
        if target == S.FILLED and view.filled_quantity != size:
            raise ValueError('Full fill requires complete confirmed trades')
        if target in {S.ACKNOWLEDGED, S.REJECTED} and view.filled_quantity:
            raise ValueError('State inconsistent with fills')
        if target == S.PARTIALLY_FILLED and not 0 < view.filled_quantity < size:
            raise ValueError('State inconsistent with partial fills')
        if target in {S.CANCELLED, S.EXPIRED} and view.filled_quantity == size:
            raise ValueError('Completely filled order cannot expire or cancel')
        view.exchange_order_id = exchange
        view.state = target
    else:
        raise ValueError('Unknown event kind')
    view.evidence.append(evidence)


class OrderLifecycleStore:
    """Serialized SQLite event journal, separate from the immutable shadow ledger."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {'lifecycle_orders', 'lifecycle_events', 'live_accounting_events'}:
                raise ValueError('Lifecycle requires its own database')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if (tables and version not in (1, 2)) or (not tables and version != 0):
                raise ValueError('Unsupported lifecycle schema version')
            db.execute("CREATE TABLE IF NOT EXISTS lifecycle_orders (id TEXT PRIMARY KEY, intent TEXT NOT NULL, exchange_id TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
            db.execute("CREATE TABLE IF NOT EXISTS lifecycle_events (order_id TEXT NOT NULL REFERENCES lifecycle_orders(id), event_id TEXT NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), PRIMARY KEY(order_id,event_id))")
            for operation in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS lifecycle_events_no_{operation} BEFORE {operation} ON lifecycle_events BEGIN SELECT RAISE(ABORT, 'Immutable lifecycle evidence'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS lifecycle_intent_no_update BEFORE UPDATE OF intent,id,created_at ON lifecycle_orders BEGIN SELECT RAISE(ABORT, 'Immutable intent'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS lifecycle_intent_no_delete BEFORE DELETE ON lifecycle_orders BEGIN SELECT RAISE(ABORT, 'Immutable intent'); END")
            db.execute("CREATE TABLE IF NOT EXISTS live_accounting_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
            for operation in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS live_accounting_no_{operation} BEFORE {operation} ON live_accounting_events BEGIN SELECT RAISE(ABORT, 'Immutable live accounting evidence'); END")
            db.execute('PRAGMA user_version=2')

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, intent: OrderIntent) -> str:
        payload = canonical(asdict(intent))
        with self._transaction() as db:
            old = db.execute('SELECT intent FROM lifecycle_orders WHERE id=?', (intent.order_id,)).fetchone()
            if old and old[0] != payload:
                raise ValueError('Idempotency key reused with different intent')
            db.execute('INSERT OR IGNORE INTO lifecycle_orders(id,intent) VALUES (?,?)', (intent.order_id, payload))
        return intent.order_id

    def _view(self, db, order_id):
        row = db.execute('SELECT intent FROM lifecycle_orders WHERE id=?', (order_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown internal order')
        view = OrderView(OrderIntent(**json.loads(row[0])))
        for payload, in db.execute('SELECT payload FROM lifecycle_events WHERE order_id=? ORDER BY rowid', (order_id,)):
            reduce_event(view, json.loads(payload))
        return view

    def get(self, order_id: str) -> OrderView:
        with self._transaction() as db:
            return self._view(db, order_id)

    def orders(self) -> tuple[OrderView, ...]:
        with self._transaction() as db:
            return tuple(self._view(db, row[0]) for row in db.execute('SELECT id FROM lifecycle_orders').fetchall())

    def _append(self, db, order_id, event_id, event):
        identity(event_id)
        payload = canonical(event)
        old = db.execute('SELECT payload FROM lifecycle_events WHERE order_id=? AND event_id=?', (order_id, event_id)).fetchone()
        if old:
            if old[0] != payload:
                raise ValueError('Event identity reused with conflicting payload')
            return False
        view = self._view(db, order_id)
        reduce_event(view, event)
        db.execute('UPDATE lifecycle_orders SET exchange_id=? WHERE id=?', (view.exchange_order_id, order_id))
        db.execute('INSERT INTO lifecycle_events(order_id,event_id,payload) VALUES (?,?,?)', (order_id, event_id, payload))
        return True

    def append(self, order_id: str, event_id: str, event: dict) -> bool:
        if event.get('target') == S.SUBMISSION_PENDING:
            raise ValueError('Use begin_submission for atomic dispatch claim')
        error = None
        with self._transaction() as db:
            db.execute('SAVEPOINT incoming')
            try:
                result = self._append(db, order_id, event_id, event)
            except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
                db.execute('ROLLBACK TO incoming')
                view = self._view(db, order_id)
                # Preserve economics, but block future dispatch if submitted
                # evidence conflicts. Commit quarantine before propagating error.
                if UNKNOWN in TRANSITIONS[view.state]:
                    self._append(db, order_id, 'quarantine:' + str(uuid4()), dict(
                        kind='transition', target=UNKNOWN,
                        evidence='invalid-event:' + hashlib.sha256(str(event_id).encode()).hexdigest(),
                        reason=str(exc)))
                error = exc
        if error is not None:
            raise error
        return result

    def _live_risk(self, db, order_id, request, clock):
        from dataclasses import replace
        from datetime import datetime, timezone
        from polybtc.execution.live_accounting import project
        from polybtc.risk.live import evaluate_live_risk, ledger_revision, LiveRiskRequest
        if not isinstance(request, LiveRiskRequest):
            raise ValueError('Live accounting requires authoritative risk evidence')
        binding = db.execute("SELECT payload FROM live_accounting_events WHERE id='account'").fetchone()
        if binding is None or json.loads(binding[0])['wallet'] != request.wallet.lower():
            raise ValueError('Live account binding mismatch')
        view = self._view(db, order_id)
        if view.state != S.RISK_APPROVED:
            raise ValueError('Order is not eligible for submission')
        now = clock() if clock is not None else datetime.now(timezone.utc)
        request = replace(request, evaluated_at=now)
        snapshot = project(self, db, exclude_order_id=order_id)
        orders = tuple(self._view(db, oid) for oid, in db.execute('SELECT id FROM lifecycle_orders').fetchall())
        decision = evaluate_live_risk(view.intent, snapshot, orders, request, ledger_revision(self, db))
        if not decision.approved:
            raise ValueError('Live risk rejected: ' + decision.reason)
        return decision, request

    def check_live_risk(self, order_id, request, *, clock=None):
        with self._transaction() as db:
            return self._live_risk(db, order_id, request, clock)[0]

    def begin_submission(self, order_id: str, *, payload_hash: str, evidence: str,
                         live_request=None, clock=None) -> bool:
        event = dict(kind='transition', target=S.SUBMISSION_PENDING, payload_hash=payload_hash, evidence=evidence)
        with self._transaction() as db:
            # Existing permit is consumed forever, including after a crash.
            old = db.execute("SELECT payload FROM lifecycle_events WHERE order_id=? AND event_id='submission-intent'", (order_id,)).fetchone()
            if old:
                if old[0] != canonical(event):
                    raise ValueError('Conflicting submission intent')
                return False
            for other, in db.execute('SELECT id FROM lifecycle_orders'):
                if self._view(db, other).state == UNKNOWN:
                    raise ValueError('Unresolved exchange outcome blocks new submission')
            if db.execute("SELECT 1 FROM live_accounting_events WHERE id='account'").fetchone():
                from polybtc.execution.live_accounting import LiveAccounting, stamp
                decision, request = self._live_risk(db, order_id, live_request, clock)
                # Risk evaluation, reservation and dispatch claim share one transaction.
                LiveAccounting._insert(db,'reserve:'+order_id,dict(kind='reserve',order_id=order_id,
                    max_cost=decision.reserved_cost,evidence=evidence))
                LiveAccounting._insert(db,'risk:'+order_id,dict(kind='live_risk',version='live_risk_v1',
                    order_id=order_id,reason=decision.reason,max_cost=decision.reserved_cost,
                    account_evidence=request.context.account.evidence_id,
                    account_balance=request.context.account.balance,
                    account_allowance=request.context.account.allowance,
                    account_observed_at=stamp(request.context.account.observed_at),
                    ledger_revision=list(request.context.account.ledger_revision),
                    source_evidence_ids=list(request.source_verification.evidence_ids),
                    source_checked_at=stamp(request.source_verification.checked_at_utc),
                    fee_policy=request.fee_policy.provenance(),
                    yes_book_at=stamp(request.context.yes_book_at),
                    no_book_at=stamp(request.context.no_book_at),
                    reference_at=stamp(request.context.reference_at),
                    evaluated_at=stamp(request.evaluated_at)))
            return self._append(db, order_id, 'submission-intent', event)

    def recover_inflight(self, evidence: str) -> int:
        """Call once under exclusive process ownership before any adapter dispatch."""
        identity(evidence)
        count = 0
        with self._transaction() as db:
            for order_id, in db.execute('SELECT id FROM lifecycle_orders').fetchall():
                view = self._view(db, order_id)
                if view.state in {S.SUBMISSION_PENDING, S.SUBMITTED, S.ACKNOWLEDGED, S.PARTIALLY_FILLED, S.CANCEL_REQUESTED}:
                    event = dict(kind='transition', target=UNKNOWN, evidence=evidence)
                    event_id = 'recovery:' + str(uuid4())
                    count += self._append(db, order_id, event_id, event)
        return count
