from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace as N

import pytest

from polybtc.execution.lifecycle import OrderIntent, OrderState as S, OrderLifecycleStore
from polybtc.execution.live_accounting import AccountingSnapshot, Position
from polybtc.execution.clob_adapter import ClobAdapterError
from polybtc.risk.live import LiveRiskRequest, evaluate_live_risk, ledger_revision
from tests.trading.test_clob_adapter import setup, submit, NOW, MARKET, charge


def request(s):
    a=s.authorization
    return LiveRiskRequest(a.risk_context,a.source_verification,a.fee_policy,a.max_total_cost,
        a.wallet,True,False,'5',NOW,NOW,a.expires_at)


def empty():
    return AccountingSnapshot((),{}, {},(),())


def test_paper_evidence_cannot_reserve_live_risk(setup):
    setup.authorization.source_verification.execution_scope='paper'
    result=evaluate(setup)
    assert not result.approved
    assert result.reason=='paper_evidence_not_live_authorization'
    with pytest.raises(ValueError,match='paper_evidence_not_live_authorization'):
        setup.store.begin_submission(setup.oid,payload_hash='fixture',evidence='fixture',
            live_request=request(setup),clock=lambda:NOW)
    assert setup.store.get(setup.oid).state==S.RISK_APPROVED


def position(cost):
    return Position('other-market','other-token','pUSD',D('5'),True,D(cost),D(0),None,None,'OPEN')


def evaluate(s,r=None,snapshot=None,orders=()):
    return evaluate_live_risk(s.store.get(s.oid).intent,snapshot or empty(),orders,
        r or request(s),ledger_revision(s.store))


@pytest.mark.parametrize('cost,loss,approved', [('6','0',True),('6.00000001','0',False),
    ('5','-1',True),('5','-1.00000001',False),('7','100',False),('22','0',False)])
def test_exact_exposure_and_daily_worst_case_boundaries(setup,cost,loss,approved):
    snap=replace(empty(),positions=(position(cost),),realized_by_day={('pUSD','2026-10-12'):D(loss)})
    assert evaluate(setup,snapshot=snap).approved is approved


@pytest.mark.parametrize('change,reason', [
    ({'balance':'3.99999999'},'available_balance_or_allowance'),
    ({'allowance':'3.99'},'available_balance_or_allowance'),
    ({'inventory_reconciled':False},'account_inventory_unreconciled'),
    ({'wallet':'wrong'},'account_identity_mismatch'),
    ({'collateral_asset':'USDC'},'account_identity_mismatch'),
    ({'observed_at':NOW-timedelta(milliseconds=501)},'stale_account_evidence'),
    ({'observed_at':NOW+timedelta(microseconds=1)},'stale_account_evidence'),
    ({'ledger_revision':(0,0,0)},'account_ledger_changed'),
    ({'balance':'NaN'},'invalid_live_risk_evidence'),
])
def test_account_evidence_fails_closed(setup,change,reason):
    r=request(setup)
    r=replace(r,context=replace(r.context,account=replace(r.context.account,**change)))
    result=evaluate(setup,r)
    assert not result.approved and result.reason==reason


@pytest.mark.parametrize('field,age', [('yes_book_at',501),('no_book_at',501),('reference_at',2001)])
def test_market_freshness_enforced_independently(setup,field,age):
    r=request(setup)
    r=replace(r,context=replace(r.context,**{field:NOW-timedelta(milliseconds=age)}))
    assert evaluate(setup,r).reason=='stale_market_data'


def test_pending_capacity_and_balance_not_released_by_partial_fill(setup):
    s=setup
    submit(s)
    s.adapter.reconcile(s.oid,fee_evidence=charge)
    snap=s.adapter.accounting.snapshot()
    assert snap.positions[0].cost_basis+snap.reserved_cash['pUSD']==4
    r=request(s)
    r=replace(r,context=replace(r.context,account=replace(r.context.account,
        ledger_revision=ledger_revision(s.store),balance='6')))
    assert evaluate(s,r,snap).reason=='available_balance_or_allowance'


@pytest.mark.parametrize('state',[S.SUBMISSION_PENDING,S.ACKNOWLEDGED,S.FILLED,S.CANCELLED,S.REJECTED])
def test_market_entry_survives_terminal_outcome(setup,state):
    previous=OrderIntent('previous',MARKET,'101','BUY','5','0.60','pUSD')
    result=evaluate(setup,orders=(N(intent=previous,state=state),))
    assert result.reason=='market_already_entered'


def test_daily_loss_rollover_uses_utc_without_erasing_open_risk(setup):
    snap=replace(empty(),realized_by_day={('pUSD','2026-10-11'):D('-10')})
    assert evaluate(setup,snapshot=snap).approved
    snap=replace(snap,positions=(position('7'),))
    assert evaluate(setup,snapshot=snap).reason=='daily_worst_case_loss_limit'
    snap=replace(empty(),realized_by_day={('pUSD','2026-10-12'):D('-10')})
    assert evaluate(setup,snapshot=snap).reason=='daily_loss_limit_reached'


@pytest.mark.parametrize('change',[{'kill_switch':True},{'live_enabled':False},
    {'max_total_cost':'7.00000001'},{'max_total_cost':'3'}, {'authorization_expires_at':NOW}])
def test_fixed_controls(setup,change):
    assert not evaluate(setup,replace(request(setup),**change)).approved


def test_missing_context_cannot_bypass_bound_store_or_adapter(setup):
    s=setup
    with pytest.raises(ValueError,match='risk evidence'):
        s.store.begin_submission(s.oid,payload_hash='a'*64,evidence='forged-label')
    s.authorization=replace(s.authorization,risk_context=None)
    with pytest.raises(ValueError): submit(s)
    s.client.post_order.assert_not_called()
    assert s.adapter.accounting.snapshot().reserved_cash=={}


def test_low_level_post_requires_one_time_dispatch_and_helpers_are_rejected(setup):
    s=setup
    for method in ('post_order','place_limit_order','place_order'):
        with pytest.raises(ClobAdapterError): s.adapter._call(method,mutation=True)
    s.factory.assert_not_called()
    submit(s)
    with pytest.raises(ClobAdapterError): s.adapter._call('post_order',mutation=True)
    s.client.post_order.assert_called_once()


def test_changed_ledger_during_signing_blocks_post_and_rolls_back_reservation(setup):
    s=setup
    signed=s.client.create_limit_order.return_value
    def sign(**kwargs):
        s.store.create(OrderIntent('another','another-market','202','BUY','5','0.60','pUSD'))
        return signed
    s.client.create_limit_order.side_effect=sign
    with pytest.raises(ValueError,match='account_ledger_changed'): submit(s)
    s.client.post_order.assert_not_called()
    assert s.store.get(s.oid).state==S.RISK_APPROVED
    assert s.adapter.accounting.snapshot().reserved_cash=={}


def test_kill_switch_change_during_signing_prevents_dispatch(setup):
    s=setup
    signed=s.client.create_limit_order.return_value
    def sign(**kwargs):
        s.adapter.config=replace(s.adapter.config,kill_switch=True)
        return signed
    s.client.create_limit_order.side_effect=sign
    with pytest.raises(ClobAdapterError): submit(s)
    s.client.post_order.assert_not_called()
    assert s.adapter.accounting.snapshot().reserved_cash=={}


def test_clock_rechecked_after_transaction_wait(setup):
    s=setup
    with pytest.raises(ValueError,match='stale_account_evidence'):
        s.store.begin_submission(s.oid,payload_hash='a'*64,evidence='fixture:risk',
            live_request=request(s),clock=lambda:NOW+timedelta(seconds=1))
    assert s.adapter.accounting.snapshot().reserved_cash=={}


def test_competing_claims_use_one_atomic_account_revision(setup):
    s=setup
    market='0x'+'b'*64
    second=s.store.create(OrderIntent('second',market,'202','BUY','5','0.60','pUSD'))
    s.store.append(second,'risk',dict(kind='transition',target=S.RISK_APPROVED,evidence='fixture:risk'))
    r=request(s)
    r=replace(r,context=replace(r.context,account=replace(r.context.account,
        ledger_revision=ledger_revision(s.store),balance='6')))
    other=replace(r,context=replace(r.context,decision=replace(r.context.decision,condition_id=market)),
        source_verification=N(**(vars(r.source_verification)|{'condition_id':market})),
        fee_policy=replace(r.fee_policy,condition_id=market,
            source=f'https://clob.polymarket.com/clob-markets/{market}'))
    assert s.store.check_live_risk(s.oid,r,clock=lambda:NOW).approved
    assert s.store.check_live_risk(second,other,clock=lambda:NOW).approved
    def claim(pair):
        oid,req=pair
        try:
            return s.store.begin_submission(oid,payload_hash='a'*64,evidence='fixture:risk',live_request=req,clock=lambda:NOW)
        except ValueError: return False
    with ThreadPoolExecutor(2) as workers:
        results=list(workers.map(claim,[(s.oid,r),(second,other)]))
    assert results.count(True)==1
    assert s.adapter.accounting.snapshot().reserved_cash=={'pUSD':D('4')}
    reopened=OrderLifecycleStore(s.store.path)
    reopened.recover_inflight('fixture:restart')
    with pytest.raises(ValueError,match='Unresolved'):
        reopened.begin_submission(s.oid if not results[0] else second,payload_hash='a'*64,
            evidence='fixture:risk',live_request=r,clock=lambda:NOW)


def test_balance_exact_boundary_and_source_rejection(setup):
    s=setup
    r=request(s)
    r=replace(r,context=replace(r.context,account=replace(r.context.account,balance='4',allowance='4')))
    assert evaluate(s,r).approved
    r.source_verification.sources.fee_policy_verified=False
    assert evaluate(s,r).reason=='unverified_sources_or_fees'


def test_bad_fee_cache_and_nonpositive_ev_rejected(setup):
    s=setup
    r=request(s)
    assert not evaluate(s,replace(r,fee_policy=replace(r.fee_policy,source='wrong'))).approved
    r=replace(r,context=replace(r.context,decision=replace(r.context.decision,net_ev_per_share=0)))
    assert evaluate(s,r).reason=='nonpositive_expected_value'
