"""Disabled-by-default CLOB integration; separate authorization for every order.

No runtime wires this adapter in. The official SDK is loaded only through an
explicitly supplied client factory after access gates pass. Evidence references
must be nonsecret opaque IDs, never credentials or raw exchange responses.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
import time
import threading
from functools import wraps
from uuid import uuid4

from polybtc.execution.lifecycle import (
    OrderLifecycleStore, OrderIntent, OrderState as S, UNKNOWN,
    acknowledgement, amount, canonical, identity,
)
from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy
from polybtc.execution.live_accounting import LiveAccounting, stamp
from polybtc.risk.live import LiveRiskContext, LiveRiskRequest
from polybtc.strategy.vnext import Action
from polybtc.execution.clob_sdk import WALLET_SIGNATURE_TYPES


class ClobAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    allow_account_reads: bool = False
    live_enabled: bool = False
    kill_switch: bool = True

    def __post_init__(self):
        if any(type(v) is not bool for v in (self.allow_account_reads, self.live_enabled, self.kill_switch)):
            raise ValueError('Adapter controls must be booleans')


@dataclass(frozen=True)
class LiveOrderAuthorization:
    """Supplied by a future authorized controller, never by the shadow risk gate."""
    order_id: str
    intent_hash: str
    user_authorization: str
    risk_evidence: str
    expires_at: datetime
    source_verification: object
    fee_policy: object
    max_total_cost: str
    wallet: str
    risk_context: LiveRiskContext | None = None


@dataclass(frozen=True)
class FillFeeEvidence:
    exchange_order_id: str
    trade_id: str
    quantity: str
    price: str
    cash_fee: str
    share_fee: str
    evidence_id: str


@dataclass(frozen=True)
class OrderSnapshot:
    """Safe query result: deliberately excludes API-key owner and raw payload."""
    id: str
    status: str
    size_matched: str
    associate_trades: tuple[str, ...]


def intent_hash(intent: OrderIntent) -> str:
    return hashlib.sha256(canonical(asdict(intent)).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc)


def _fresh(timestamp, now, seconds):
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise ValueError('Missing aware timestamp')
    if not 0 <= (now - timestamp).total_seconds() <= seconds:
        raise ValueError('Stale or future evidence')


def _serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._mutex:
            if self._lock.closed or method.__name__ not in {'submit','reconcile','cancel'}:
                return method(self, *args, **kwargs)
            try:
                result=method(self, *args, **kwargs)
                if ((method.__name__=='submit' and result.state==UNKNOWN) or
                        (method.__name__=='cancel' and result is False)):
                    self.config=replace(self.config,kill_switch=True,live_enabled=False)
                    self._operation(method.__name__,'failed')
                    return result
                self._operation(method.__name__,'completed')
                return result
            except (Exception, KeyboardInterrupt):
                self.config=replace(self.config,kill_switch=True,live_enabled=False)
                self._dispatch_permit=None
                self._dispatch_guard=None
                self.store.recover_inflight('operation-failure')
                self._operation(method.__name__,'failed')
                raise
    return run


class ClobAdapter:
    def __init__(self, *, store: OrderLifecycleStore, client_factory, wallet: str,
                 config: AdapterConfig | None = None, clock=_now, sleeper=time.sleep,
                 signer: str | None = None, wallet_type: str = 'EOA'):
        if wallet_type not in WALLET_SIGNATURE_TYPES or (wallet_type != 'EOA' and not signer):
            raise ValueError('Explicit wallet type and owner signer required')
        self.wallet_type = wallet_type
        self.signer = (signer or wallet).lower()
        if wallet_type == 'EOA' and self.signer != wallet.lower():
            raise ValueError('EOA signer must equal wallet')
        self.store, self.config = store, config or AdapterConfig()
        self.wallet, self.clock, self.sleeper = wallet.lower(), clock, sleeper
        self._factory, self._client = client_factory, None
        self._dispatch_permit = None
        self._dispatch_guard = None
        self._mutex = threading.RLock()
        self._lock = (store.path.parent / (store.path.name + '.adapter.lock')).open('a+b')
        self._lock.seek(0)
        self._lock.write(b'0')
        self._lock.flush()
        self._lock.seek(0)
        try:
            import msvcrt
            msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
        except Exception:
            self._lock.close()
            raise ClobAdapterError('Another adapter owns this state, or locking unavailable') from None
        try:
            self.accounting = LiveAccounting(store, self.wallet)
            self.store.recover_inflight('adapter-startup')
            self._operation('startup','completed')
        except Exception:
            self._lock.close()
            raise

    @_serialized
    def close(self):
        if self._lock.closed: return
        self.config=replace(self.config,kill_switch=True,live_enabled=False)
        self._dispatch_permit=None
        self._dispatch_guard=None
        try:
            self.store.recover_inflight('controlled-shutdown')
            try:
                if self._client is not None: self._client.close()
            except Exception:
                self._operation('shutdown','failed')
                raise ClobAdapterError('SDK shutdown failed; live methods disabled') from None
            self._operation('shutdown','completed')
        finally:
            self._lock.close()

    def _operation(self, action, status):
        with self.store._transaction() as db:
            LiveAccounting._insert(db,'operation:'+str(uuid4()),dict(kind='operation',
                action=action,status=status,observed_at=stamp(self.clock()),
                kill_switch=self.config.kill_switch,live_enabled=self.config.live_enabled))

    def _access(self, *, mutation=False):
        if self._lock.closed:
            raise ClobAdapterError('Adapter closed')
        if not self.config.allow_account_reads:
            raise ClobAdapterError('Exchange access disabled')
        if mutation and (not self.config.live_enabled or self.config.kill_switch):
            raise ClobAdapterError('Live methods disabled')

    def _call(self, method, *, mutation=False, _dispatch_permit=None, **kwargs):
        dispatch_guard = None
        allowed = {'get_market':False,'get_order_book':False,'get_order':False,
                   'list_account_trades':False,'create_limit_order':True,
                   'post_order':True,'cancel_order':True}
        if method not in allowed or mutation is not allowed[method]:
            raise ClobAdapterError('Unsupported CLOB operation')
        if method == 'post_order':
            if _dispatch_permit is None or _dispatch_permit is not self._dispatch_permit:
                raise ClobAdapterError('Risk-approved one-time dispatch required')
            self._dispatch_permit = None
            dispatch_guard, self._dispatch_guard = self._dispatch_guard, None
            if dispatch_guard is None:
                raise ClobAdapterError('Final dispatch validation required')
        self._access(mutation=mutation)
        for attempt in range(3 if not mutation else 1):
            retry = None
            try:
                if self._client is None:
                    self._client = self._factory()
                    if str(self._client.wallet).lower() != self.wallet or (
                        self.wallet_type != 'EOA' and (
                            self._client.wallet_type != self.wallet_type or
                            str(self._client.signer).lower() != self.signer)):
                        self._client.close()
                        self._client = None
                        raise ValueError('Account mismatch')
                operation = getattr(self._client, method)
                if dispatch_guard is not None:
                    dispatch_guard()
                return operation(**kwargs)
            except Exception as error:
                if not mutation and getattr(error, 'status', None) == 429 and attempt < 2:
                    delay = getattr(error, 'retry_after', None)
                    if isinstance(delay, (int, float)) and math.isfinite(delay) and 0 <= delay <= 30:
                        retry = delay
            if retry is None:
                raise ClobAdapterError('CLOB request failed; response details suppressed') from None
            self.sleeper(retry)

    def _unknown(self, oid, reason):
        if self.store.get(oid).state != UNKNOWN:
            self.store.append(oid, 'unknown:' + str(uuid4()), dict(
                kind='transition', target=UNKNOWN, evidence=reason))

    def _authorize(self, oid, authorization):
        self._access(mutation=True)
        intent = self.store.get(oid).intent
        now = self.clock()
        a = authorization
        if not isinstance(a, LiveOrderAuthorization) or a.order_id != oid or a.intent_hash != intent_hash(intent) or a.wallet.lower() != self.wallet:
            raise ClobAdapterError('Explicit order-bound live authorization required')
        identity(a.user_authorization)
        identity(a.risk_evidence)
        if a.expires_at.utcoffset() is None or not 0 < (a.expires_at - now).total_seconds() <= 60:
            raise ClobAdapterError('Live authorization expired or invalid')
        verification = a.source_verification
        if getattr(verification, 'execution_scope', None) == 'paper':
            raise ClobAdapterError('Paper evidence cannot authorize live execution')
        _fresh(verification.checked_at_utc, now, 0.5)
        if verification.condition_id != intent.condition_id or verification.reasons or not verification.evidence_ids:
            raise ClobAdapterError('Source evidence mismatch')
        if not all(getattr(verification.sources, name) is True for name in (
            'reference_source_verified', 'yes_book_source_verified',
            'no_book_source_verified', 'fee_policy_verified',
        )) or verification.fee_descriptor_verified is not True:
            raise ClobAdapterError('Source or fee applicability unverified')
        if not isinstance(a.fee_policy, CachedFeePolicy):
            raise ClobAdapterError('Verified fee descriptor required')
        a.fee_policy.validate_for_decision(condition_id=intent.condition_id,
                                           fee_rate=a.fee_policy.fee_rate, at=now)
        if intent.collateral_asset != 'pUSD' or intent.side != 'BUY' or amount(intent.quantity) != 5 or amount(intent.limit_price) > Decimal('0.70'):
            raise ClobAdapterError('Existing entry limits required')
        if not amount(intent.quantity) * amount(intent.limit_price) <= amount(a.max_total_cost) <= 7:
            raise ClobAdapterError('Invalid risk-approved cost envelope')
        return intent

    @_serialized
    def market_context(self, oid, *, market_id):
        self._access()
        intent = self.store.get(oid).intent
        market = self._call('get_market', id=market_id)
        book = self._call('get_order_book', asset_id=intent.token_id)
        try:
            if market.condition_id != intent.condition_id or book.condition_id != intent.condition_id or book.asset_id != intent.token_id:
                raise ValueError('Market/token mismatch')
            if market.version not in {'v1', 'v2'}:
                raise ValueError('Unverified market protocol')
            assets = [getattr(o, 'position_id' if market.version == 'v2' else 'token_id')
                      for o in (market.outcomes.yes, market.outcomes.no)]
            if len(set(assets)) != 2 or intent.token_id not in assets:
                raise ValueError('Invalid binary outcome mapping')
            if market.state.active is not True or market.state.closed is not False or market.state.accepting_orders is not True or market.state.enable_order_book is not True:
                raise ValueError('Market is not accepting orders')
            if market.state.neg_risk is not book.neg_risk:
                raise ValueError('Exchange type mismatch')
            _fresh(book.timestamp, self.clock(), 0.5)
            tick, minimum = amount(str(book.tick_size)), amount(str(book.min_order_size))
            if tick <= 0 or minimum <= 0 or amount(intent.limit_price) % tick or amount(intent.quantity) < minimum:
                raise ValueError('Tick or size constraint failed')
        except Exception:
            raise ClobAdapterError('Market, asset or order constraints unverified') from None
        return market, book

    @_serialized
    def submit(self, oid, *, market_id, authorization):
        intent = self._authorize(oid, authorization)
        if self.store.get(oid).state != S.RISK_APPROVED:
            raise ClobAdapterError('Order is not eligible for a new submission')
        market, book = self.market_context(oid, market_id=market_id)
        def risk_request():
            return LiveRiskRequest(authorization.risk_context, authorization.source_verification,
                authorization.fee_policy, authorization.max_total_cost, self.wallet,
                self.config.live_enabled,self.config.kill_switch,str(book.min_order_size),
                book.timestamp,self.clock(),authorization.expires_at)
        self.store.check_live_risk(oid,risk_request(),clock=self.clock)
        chosen = market.outcomes.yes if authorization.risk_context.decision.action == Action.BUY_YES else market.outcomes.no
        if getattr(chosen, 'position_id' if market.version=='v2' else 'token_id') != intent.token_id:
            raise ClobAdapterError('Strategy outcome does not match order token')
        try:
            fees = market.trading.fee_schedule
            policy = authorization.fee_policy
            if (market.trading.fees_enabled is not True or fees is None or
                amount(str(fees.rate)) != amount(str(policy.fee_rate)) or
                fees.exponent != policy.fee_exponent or fees.taker_only is not policy.fee_flag):
                raise ValueError('Fee evidence conflict')
        except Exception:
            raise ClobAdapterError('Current market fee descriptor conflicts with verified policy') from None
        if intent.order_type not in {'GTC', 'GTD'}:
            raise ClobAdapterError('Only explicit limit GTC/GTD entries supported')
        expiration = None
        if intent.expires_at:
            expiration = int(datetime.fromisoformat(intent.expires_at).timestamp())
            if expiration - self.clock().timestamp() < 180:
                raise ClobAdapterError('GTD expiration requires at least three minutes')
        signed = self._call('create_limit_order', mutation=True, asset_id=intent.token_id,
                            side=intent.side, price=intent.limit_price, size=intent.quantity,
                            expiration=expiration)
        try:
            if (signed.token_id != intent.token_id or signed.side != intent.side or
                signed.order_type != intent.order_type or signed.expiration != (expiration or 0) or
                str(signed.maker).lower() != self.wallet or
                str(signed.signer).lower() != (self.wallet if self.wallet_type == 'DEPOSIT_WALLET' else self.signer) or
                signed.signature_type != WALLET_SIGNATURE_TYPES[self.wallet_type] or signed.post_only is not False or
                Decimal(signed.maker_amount) != amount(intent.quantity) * amount(intent.limit_price) * 1000000 or
                Decimal(signed.taker_amount) != amount(intent.quantity) * 1000000):
                raise ValueError('Signed terms mismatch')
            digest = hashlib.sha256(canonical(asdict(signed)).encode()).hexdigest()
        except Exception:
            raise ClobAdapterError('SDK signed order does not match approved intent') from None
        # Recheck expiring gates after metadata/signing latency.
        self._authorize(oid, authorization)
        _fresh(book.timestamp, self.clock(), 0.5)
        if not self.store.begin_submission(oid, payload_hash=digest, evidence=authorization.risk_evidence,
                                          live_request=risk_request(),clock=self.clock):
            raise ClobAdapterError('Submission permit already consumed')
        self._dispatch_permit = object()
        def validate_dispatch():
            # The claim advances the ledger revision; do not reuse the pre-claim
            # revision gate. Revalidate all expiring inputs after durable I/O and
            # SDK initialization, immediately before the one-shot POST.
            self._authorize(oid, authorization)
            now = self.clock()
            if not 0 < (authorization.expires_at - now).total_seconds() <= 60:
                raise ClobAdapterError('Live authorization expired before dispatch')
            context = authorization.risk_context
            for timestamp, seconds in (
                (authorization.source_verification.checked_at_utc, .5),
                (context.account.observed_at, .5), (context.yes_book_at, .5),
                (context.no_book_at, .5), (context.reference_at, 2),
                (book.timestamp, .5),
            ):
                _fresh(timestamp, now, seconds)
            authorization.fee_policy.validate_for_decision(
                condition_id=intent.condition_id,
                fee_rate=authorization.fee_policy.fee_rate, at=now)
            self._access(mutation=True)
        self._dispatch_guard = validate_dispatch
        try:
            response = self._call('post_order', mutation=True, signed_order=signed,
                                  _dispatch_permit=self._dispatch_permit)
            if response.ok is not True:
                # Includes ambiguous SDK 'unmatched' normalization: never guess rejection.
                self._unknown(oid, 'placement-not-accepted')
                return self.store.get(oid)
            self.store.append(oid, 'placement-identity', dict(kind='exchange_identity',
                exchange_order_id=response.order_id, evidence='sdk-placement-identity'))
            event = acknowledgement(exchange_order_id=response.order_id,
                                    venue_status=response.status, evidence='sdk-placement')
            self.store.append(oid, 'placement', event)
        except Exception:
            self._unknown(oid, 'placement-outcome-unknown')
            raise ClobAdapterError('Submission outcome unknown; reconcile without resubmitting') from None
        return self.store.get(oid)

    @_serialized
    def order_status(self, oid):
        self._access()
        view = self.store.get(oid)
        if not view.exchange_order_id:
            raise ClobAdapterError('Unknown exchange identity requires investigation')
        order = self._call('get_order', order_id=view.exchange_order_id)
        try:
            if (order.id != view.exchange_order_id or order.condition_id != view.intent.condition_id or
                order.asset_id != view.intent.token_id or order.side != view.intent.side or
                str(order.maker_address).lower() != self.wallet or
                amount(str(order.original_size)) != amount(view.intent.quantity) or
                amount(str(order.price)) != amount(view.intent.limit_price)):
                raise ValueError('Order identity mismatch')
        except Exception:
            self._unknown(oid, 'order-identity-mismatch')
            raise ClobAdapterError('Order identity mismatch') from None
        return OrderSnapshot(order.id, order.status, str(order.size_matched), tuple(order.associate_trades))

    @_serialized
    def fills(self, oid):
        self._access()
        view = self.store.get(oid)
        if not view.exchange_order_id:
            raise ClobAdapterError('Fill lookup requires a known exchange identity')
        pages = self._call('list_account_trades', market=view.intent.condition_id)
        selected = {}
        try:
            complete = False
            for index, page in enumerate(pages):
                if index >= 100 or page.limit_reached:
                    raise ValueError('Incomplete trade pagination')
                for trade in page.items:
                    if trade.taker_order_id == view.exchange_order_id:
                        leg = trade
                        quantity = trade.size
                    else:
                        matches = [m for m in trade.maker_orders if m.order_id == view.exchange_order_id]
                        if not matches:
                            continue
                        if len(matches) != 1:
                            raise ValueError('Ambiguous maker allocation')
                        leg, = matches
                        quantity = leg.matched_amount
                    if (trade.condition_id != view.intent.condition_id or leg.asset_id != view.intent.token_id or
                        leg.side != view.intent.side or str(leg.maker_address).lower() != self.wallet):
                        raise ValueError('Fill identity mismatch')
                    # Strip owner/API-key and raw response fields before persistence.
                    normalized = dict(trade_id=identity(trade.id), quantity=str(quantity),
                                      price=str(leg.price), status=trade.status,
                                      executed_at=stamp(trade.matched_at))
                    # Persist authenticated facts even if later pages/fees fail.
                    self.accounting.observe_fill(oid, exchange_order_id=view.exchange_order_id,
                        **normalized, evidence='sdk-trade-history')
                    if trade.id in selected and selected[trade.id] != normalized:
                        raise ValueError('Conflicting paginated fill')
                    selected[trade.id] = normalized
                complete = page.has_more is False
            if not complete:
                raise ValueError('Incomplete pagination')
            return tuple(selected.values())
        except Exception:
            self._unknown(oid, 'fill-history-incomplete')
            raise ClobAdapterError('Fill history incomplete or inconsistent') from None

    @_serialized
    def reconcile(self, oid, *, fee_evidence):
        self._access()
        self._unknown(oid, 'reconciliation-start')
        try:
            before = self.order_status(oid)
            trades = self.fills(oid)
            after = self.order_status(oid)
            if (before.status, before.size_matched, before.associate_trades) != (after.status, after.size_matched, after.associate_trades):
                raise ValueError('Order changed during reconciliation')
            if not set(after.associate_trades).issubset({t['trade_id'] for t in trades}):
                raise ValueError('Missing associated trades')
            recorded = self.store.get(oid).trades
            if not {tid for tid, t in recorded.items() if t['status'] != 'FAILED'}.issubset(
                    {t['trade_id'] for t in trades}):
                raise ValueError('Exchange history omitted previously recorded fills')
            for trade in trades:
                charge = fee_evidence(trade.copy())
                if not isinstance(charge, FillFeeEvidence) or any(getattr(charge, k) != trade[k] for k in ('trade_id', 'quantity', 'price')) or charge.exchange_order_id != after.id:
                    raise ValueError('Missing bound fee accounting')
                event = dict(kind='trade', evidence='sdk-trade-history', exchange_order_id=after.id,
                             **trade, cash_fee=charge.cash_fee, share_fee=charge.share_fee,
                             fee_evidence=charge.evidence_id)
                eid = 'trade:' + hashlib.sha256(canonical(event).encode()).hexdigest()
                self.store.append(oid, eid, event)
            view = self.store.get(oid)
            if view.provisional_quantity or view.filled_quantity != amount(str(after.size_matched)):
                raise ValueError('Unsettled or missing trade quantities')
            if any(not issue.startswith('unknown_order:') for issue in self.accounting.snapshot().issues):
                raise ValueError('Unresolved accounting evidence')
            size = amount(view.intent.quantity)
            if after.status == 'MATCHED' and view.filled_quantity == size:
                target = S.FILLED
            elif after.status in {'LIVE', 'UNMATCHED'} and view.filled_quantity < size:
                target = S.PARTIALLY_FILLED if view.filled_quantity else S.ACKNOWLEDGED
            elif after.status == 'CANCELED' and view.filled_quantity < size:
                target = S.CANCELLED
            else:
                raise ValueError('Unresolved order status')
            self.store.append(oid, 'reconcile:' + str(uuid4()), dict(kind='reconcile', target=target,
                confirmed_quantity=str(view.filled_quantity), exchange_order_id=after.id,
                evidence='sdk-complete-order-and-trades'))
            return self.store.get(oid)
        except Exception:
            raise ClobAdapterError('Reconciliation incomplete; order remains blocked') from None

    @_serialized
    def cancel(self, oid, *, user_authorization):
        self._access(mutation=True)
        identity(user_authorization)
        order = self.order_status(oid)
        view = self.store.get(oid)
        if order.status not in {'LIVE', 'UNMATCHED'} or view.state not in {S.ACKNOWLEDGED, S.PARTIALLY_FILLED}:
            raise ClobAdapterError('Cancellation requires a reconciled resting order')
        self.store.append(oid, 'cancel:' + str(uuid4()), dict(kind='transition',
            target=S.CANCEL_REQUESTED, evidence=user_authorization))
        try:
            response = self._call('cancel_order', mutation=True, order_id=order.id)
            success = order.id in response.canceled and order.id not in response.not_canceled
        except Exception:
            self._unknown(oid, 'cancel-outcome-unknown')
            raise ClobAdapterError('Cancellation outcome unknown; reconcile') from None
        self._unknown(oid, 'cancel-requires-fill-reconciliation')
        return success  # Never release fills/reservations solely on cancel response.
