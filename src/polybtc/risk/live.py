"""Model-independent live entry constraints; no network or order submission.

Account evidence must come from a trusted authenticated account reconciler.
Balance means settled collateral before local pending reservations, with any
external commitments already excluded. No caller-supplied portfolio totals.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal as D

from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy, FeeCacheError
from polybtc.execution.lifecycle import amount, identity, OrderState as S
from polybtc.risk.vnext import (
    RiskConfig, VNextRiskGate, PortfolioRiskState, RiskRequest, RiskAction,
    canonical_market_id,
)
from polybtc.strategy.vnext import StrategyDecision


@dataclass(frozen=True)
class AccountRiskEvidence:
    wallet: str
    collateral_asset: str
    balance: str
    allowance: str
    observed_at: datetime
    evidence_id: str
    ledger_revision: tuple[int, int, int]
    inventory_reconciled: bool = False


@dataclass(frozen=True)
class LiveRiskContext:
    account: AccountRiskEvidence
    decision: StrategyDecision
    yes_book_at: datetime
    no_book_at: datetime
    reference_at: datetime


@dataclass(frozen=True)
class LiveRiskRequest:
    context: LiveRiskContext
    source_verification: object
    fee_policy: CachedFeePolicy
    max_total_cost: str
    wallet: str
    live_enabled: bool
    kill_switch: bool
    minimum_order_size: str
    selected_book_at: datetime
    evaluated_at: datetime
    authorization_expires_at: datetime


@dataclass(frozen=True)
class LiveRiskDecision:
    approved: bool
    reason: str
    reserved_cost: str = '0'


def ledger_revision(store, db=None):
    if db is None:
        with store._transaction() as connection:
            return ledger_revision(store, connection)
    return tuple(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in
        ('lifecycle_orders','lifecycle_events','live_accounting_events'))


def fresh(value, now, seconds):
    return (isinstance(value, datetime) and value.utcoffset() is not None and
            0 <= (now-value).total_seconds() <= seconds)


def evaluate_live_risk(intent, snapshot, orders, request, revision):
    """Pure decision. The store re-evaluates with its own snapshot under lock."""
    def reject(reason): return LiveRiskDecision(False, reason)
    try:
        if not isinstance(request, LiveRiskRequest): return reject('missing_live_risk_context')
        r, c = request, RiskConfig()
        now = r.evaluated_at
        if not fresh(now, now, 0): return reject('invalid_evaluation_time')
        now = now.astimezone(timezone.utc)
        if not 0 < (r.authorization_expires_at-now).total_seconds() <= 60:
            return reject('authorization_expired')
        if r.live_enabled is not True or r.kill_switch is not False: return reject('live_disabled')
        if not isinstance(r.context, LiveRiskContext): return reject('missing_live_risk_context')
        a, d = r.context.account, r.context.decision
        if not isinstance(a, AccountRiskEvidence) or a.inventory_reconciled is not True:
            return reject('account_inventory_unreconciled')
        identity(a.evidence_id)
        if a.wallet.lower()!=r.wallet.lower() or a.collateral_asset!=intent.collateral_asset:
            return reject('account_identity_mismatch')
        if a.ledger_revision!=revision: return reject('account_ledger_changed')
        if not fresh(a.observed_at,now,.5): return reject('stale_account_evidence')
        for value, seconds in ((r.context.yes_book_at,.5),(r.context.no_book_at,.5),
                               (r.context.reference_at,2),(r.selected_book_at,.5)):
            if not fresh(value,now,seconds): return reject('stale_market_data')
        v=r.source_verification
        if getattr(v,'execution_scope',None)=='paper':
            return reject('paper_evidence_not_live_authorization')
        if (not fresh(v.checked_at_utc,now,.5) or v.condition_id!=intent.condition_id or
            v.reasons or not v.evidence_ids or v.fee_descriptor_verified is not True or
            not all(getattr(v.sources,k) is True for k in ('reference_source_verified',
                'yes_book_source_verified','no_book_source_verified','fee_policy_verified'))):
            return reject('unverified_sources_or_fees')
        for evidence_id in v.evidence_ids: identity(evidence_id)
        if not isinstance(r.fee_policy,CachedFeePolicy): return reject('invalid_fee_policy')
        r.fee_policy.validate_for_decision(condition_id=intent.condition_id,
            fee_rate=r.fee_policy.fee_rate,at=now)
        if not snapshot.complete: return reject('portfolio_state_incomplete')
        if intent.side!='BUY' or intent.collateral_asset!='pUSD' or amount(intent.quantity)!=D(str(c.shares_per_entry)):
            return reject('unsupported_entry')
        if not isinstance(d,StrategyDecision) or d.condition_id!=intent.condition_id:
            return reject('strategy_identity_mismatch')
        if D(str(d.execution_price))!=amount(intent.limit_price): return reject('strategy_price_mismatch')
        cap=amount(r.max_total_cost)
        modeled=amount(intent.quantity)*(amount(intent.limit_price)+D(str(d.fee_per_share)))
        if not modeled<=cap<=D(str(c.max_order_value_usd)): return reject('order_value_limit')
        if any(p.collateral_asset!='pUSD' or p.cost_basis is None or p.cost_basis<0 for p in snapshot.positions):
            return reject('unsupported_portfolio')
        if any(asset!='pUSD' for asset in snapshot.reserved_cash): return reject('unsupported_portfolio')
        pending=snapshot.reserved_cash.get('pUSD',D(0))
        exposure=pending+sum((p.cost_basis for p in snapshot.positions),D(0))
        daily=snapshot.realized_by_day.get(('pUSD',now.date().isoformat()),D(0))
        entered=frozenset(canonical_market_id(o.intent.condition_id) for o in orders
            if o.intent.order_id!=intent.order_id and o.state not in {S.CREATED,S.RISK_APPROVED})
        # Reuse existing strategy/size/price/EV and portfolio risk semantics.
        state=PortfolioRiskState(True,now,now.date(),float(exposure),float(exposure),
                                 float(daily),entered,frozenset(),False)
        base=VNextRiskGate().evaluate(RiskRequest(d,state,float(amount(intent.quantity)),
            float(amount(r.minimum_order_size)),now))
        if base.action!=RiskAction.APPROVE_SHADOW: return reject(base.reason)
        # Exact Decimal bounds use the full approved envelope, not just modeled fees.
        if exposure+cap>D(str(c.max_open_exposure_usd)): return reject('portfolio_exposure_limit')
        if max(D(0),-daily)+exposure+cap>D(str(c.max_daily_realized_loss_usd)):
            return reject('daily_worst_case_loss_limit')
        if pending+cap>min(amount(a.balance),amount(a.allowance)):
            return reject('available_balance_or_allowance')
        return LiveRiskDecision(True,'live_risk_approved',str(cap))
    except (ValueError,TypeError,AttributeError,ArithmeticError,FeeCacheError):
        return reject('invalid_live_risk_evidence')
