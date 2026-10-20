from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

from polybtc.execution.clob_adapter import (
    AdapterConfig, ClobAdapter, ClobAdapterError, LiveOrderAuthorization,
    FillFeeEvidence, intent_hash,
)
from polybtc.execution.clob_sdk import ClobCredentials
from polybtc.execution.lifecycle import OrderLifecycleStore, OrderIntent, OrderState as S, UNKNOWN
from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy, CACHE_VERSION
from polybtc.data.polymarket_fees import FEE_PROVIDER_VERSION
from polybtc.risk.live import AccountRiskEvidence, LiveRiskContext, ledger_revision
from polybtc.strategy.vnext import Action, StrategyDecision

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
MARKET = '0x' + 'a'*64
WALLET = '0x' + '1'*40


@dataclass
class Signed:
    token_id: str = '101'
    side: str = 'BUY'
    order_type: str = 'GTC'
    expiration: int = 0
    maker: str = WALLET
    signer: str = WALLET
    maker_amount: int = 3000000
    taker_amount: int = 5000000
    signature_type: int = 0
    post_only: bool = False
    signature: str = 'SENSITIVE-SIGNATURE'


def trade(**kw):
    return N(**(dict(id='trade1', condition_id=MARKET, asset_id='101',
        side='BUY', maker_address=WALLET, taker_order_id='exchange1',
        size=D('2'), price=D('.60'), status='CONFIRMED', maker_orders=[],
        owner='SENSITIVE-API-KEY', matched_at=NOW) | kw))


def page(items, more=False):
    return N(items=items, limit_reached=False, has_more=more)


def charge(t):
    return FillFeeEvidence('exchange1', t['trade_id'], t['quantity'], t['price'],
                           '0.01', '0.02', 'fixture:charged-fees')


@pytest.fixture
def setup(tmp_path):
    store = OrderLifecycleStore(tmp_path / 'orders.sqlite3')
    intent = OrderIntent('entry1', MARKET, '101', 'BUY', '5', '0.60', 'pUSD')
    oid = store.create(intent)
    store.append(oid, 'risk', dict(kind='transition', target=S.RISK_APPROVED, evidence='fixture:risk'))
    client = Mock()
    client.wallet = WALLET
    client.get_market.return_value = N(condition_id=MARKET, version='v1',
        trading=N(fees_enabled=True, fee_schedule=N(rate=D('.07'),exponent=1,taker_only=True)),
        outcomes=N(yes=N(token_id='101'), no=N(token_id='202')),
        state=N(active=True, closed=False, accepting_orders=True, enable_order_book=True, neg_risk=False))
    client.get_order_book.return_value = N(condition_id=MARKET, asset_id='101', timestamp=NOW,
        tick_size=D('.01'), min_order_size=D('5'), neg_risk=False)
    client.create_limit_order.return_value = Signed()
    client.post_order.return_value = N(ok=True, order_id='exchange1', status='live')
    client.get_order.return_value = N(id='exchange1', condition_id=MARKET, asset_id='101',
        side='BUY', maker_address=WALLET, original_size=D('5'), price=D('.60'),
        size_matched=D('2'), status='LIVE', associate_trades=['trade1'])
    client.list_account_trades.return_value = [page([trade()])]
    config = AdapterConfig(True, True, False)
    factory = Mock(return_value=client)
    adapter = ClobAdapter(store=store, client_factory=factory, wallet=WALLET, config=config, clock=lambda:NOW, sleeper=Mock())
    verification = N(checked_at_utc=NOW, condition_id=MARKET, reasons=(), evidence_ids=('fixture',),
        sources=N(reference_source_verified=True, yes_book_source_verified=True,
                  no_book_source_verified=True, fee_policy_verified=True), fee_descriptor_verified=True)
    policy = CachedFeePolicy(condition_id=MARKET, fee_rate=.07, fee_exponent=1, fee_flag=True,
        source=f'https://clob.polymarket.com/clob-markets/{MARKET}', provider_version=FEE_PROVIDER_VERSION,
        retrieved_at_utc=NOW, cache_version=CACHE_VERSION)
    authorization = LiveOrderAuthorization(oid, intent_hash(intent), 'fixture:user-authorization',
        'fixture:risk', NOW+timedelta(seconds=30), verification, policy, '4', WALLET)
    decision=StrategyDecision('strategy_vnext_v1',MARKET,60,Action.BUY_YES,'positive_net_ev',
        .8,.6,.8,.6,.6,.01,.19)
    account=AccountRiskEvidence(WALLET,'pUSD','100','100',NOW,'fixture:account',ledger_revision(store),True)
    authorization=replace(authorization,risk_context=LiveRiskContext(account,decision,NOW,NOW,NOW))
    yield N(adapter=adapter, store=store, oid=oid, client=client, authorization=authorization, factory=factory)
    adapter.close()


def submit(s):
    return s.adapter.submit(s.oid, market_id='123', authorization=s.authorization)


@pytest.mark.parametrize('wallet_type,signature_type', [('POLY_PROXY',1),('GNOSIS_SAFE',2),('DEPOSIT_WALLET',3)])
@pytest.mark.parametrize('invalid', [False, True])
def test_smart_wallet_owner_and_signed_terms(setup, wallet_type, signature_type, invalid):
    s=setup
    s.adapter.close()
    signer='0x'+'2'*40
    s.client.wallet_type=wallet_type
    s.client.signer=signer
    s.adapter=ClobAdapter(store=s.store,client_factory=s.factory,wallet=WALLET,
        signer=signer,wallet_type=wallet_type,config=AdapterConfig(True,True,False),clock=lambda:NOW)
    context=s.authorization.risk_context
    s.authorization=replace(s.authorization,risk_context=replace(context,
        account=replace(context.account,ledger_revision=ledger_revision(s.store))))
    signed_signer=WALLET if wallet_type=='DEPOSIT_WALLET' else signer
    s.client.create_limit_order.return_value=replace(Signed(),signer=signed_signer,
        signature_type=0 if invalid else signature_type)
    try:
        if invalid:
            with pytest.raises(ClobAdapterError,match='signed order'):
                submit(s)
            s.client.post_order.assert_not_called()
        else:
            assert submit(s).state==S.ACKNOWLEDGED
            s.client.post_order.assert_called_once()
    finally:
        s.adapter.close()


def test_default_blocks_all_access_before_factory(setup):
    s = setup
    s.adapter.config = AdapterConfig()
    for operation in (lambda: submit(s), lambda:s.adapter.order_status(s.oid),
                      lambda:s.adapter.fills(s.oid), lambda:s.adapter.cancel(s.oid,user_authorization='fixture')):
        with pytest.raises(ClobAdapterError): operation()
    s.factory.assert_not_called()


def test_submit_sign_once_and_redact_database(setup):
    s = setup
    assert submit(s).state == S.ACKNOWLEDGED
    with pytest.raises(ClobAdapterError): submit(s)
    s.client.post_order.assert_called_once()
    s.client.place_limit_order.assert_not_called()
    assert b'SENSITIVE' not in s.store.path.read_bytes()
    s.client.create_limit_order.assert_called_once_with(asset_id='101', side='BUY', price='0.60',size='5',expiration=None)


@pytest.mark.parametrize('change', ['kill','read_only','fee','expired','intent','source','size','tick','stale','signed'])
def test_preflight_failures_never_post(setup, change):
    s = setup
    if change=='kill': s.adapter.config=AdapterConfig(True,True,True)
    if change=='read_only': s.adapter.config=AdapterConfig(True,False,False)
    if change=='fee': s.authorization.source_verification.sources.fee_policy_verified=False
    if change=='source': s.authorization.source_verification.condition_id='wrong'
    if change=='expired': s.authorization=replace(s.authorization,expires_at=NOW)
    if change=='intent': s.authorization=replace(s.authorization,intent_hash='wrong')
    if change=='size': s.client.get_order_book.return_value.min_order_size=D('6')
    if change=='tick': s.client.get_order_book.return_value.tick_size=D('.07')
    if change=='stale': s.client.get_order_book.return_value.timestamp=NOW-timedelta(seconds=1)
    if change=='signed': s.client.create_limit_order.return_value=replace(Signed(),maker_amount=4000000)
    with pytest.raises((ClobAdapterError,ValueError)): submit(s)
    s.client.post_order.assert_not_called()
    assert s.store.get(s.oid).state==S.RISK_APPROVED


def test_timeout_is_unknown_no_retry_or_secret_output(setup,capsys):
    s=setup
    s.client.post_order.side_effect=TimeoutError('SENSITIVE-SECRET')
    with pytest.raises(ClobAdapterError,match='unknown') as error: submit(s)
    assert 'SENSITIVE' not in str(error.value)
    assert s.store.get(s.oid).state==UNKNOWN
    assert s.client.post_order.call_count==1
    assert 'SENSITIVE' not in capsys.readouterr().out
    assert b'SENSITIVE' not in s.store.path.read_bytes()


def test_reconcile_pages_duplicates_and_partial_fees(setup):
    s=setup
    submit(s)
    s.client.list_account_trades.return_value=[page([trade()],True),page([trade()])]
    v=s.adapter.reconcile(s.oid,fee_evidence=charge)
    assert v.state==S.PARTIALLY_FILLED and v.filled_quantity==2
    assert v.cash_delta==D('-1.21') and v.token_delta==D('1.98')
    assert s.adapter.reconcile(s.oid,fee_evidence=charge).filled_quantity==2
    assert b'SENSITIVE' not in s.store.path.read_bytes()


@pytest.mark.parametrize('problem',['fees','pagination','quantity','owner','missing','changing'])
def test_incomplete_reconciliation_stays_blocked(setup,problem):
    s=setup
    submit(s)
    fn=charge
    if problem=='fees': fn=lambda t:None
    if problem=='pagination': s.client.list_account_trades.return_value=[N(items=[trade()],has_more=False,limit_reached=True)]
    if problem=='quantity': s.client.get_order.return_value.size_matched=D('4')
    if problem=='owner': s.client.list_account_trades.return_value=[page([trade(maker_address='wrong')])]
    if problem=='missing': s.client.list_account_trades.return_value=[page([])]
    if problem=='changing':
        before=s.client.get_order.return_value
        s.client.get_order.side_effect=[before,N(**(vars(before)|{'status':'CANCELED'}))]
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=fn)
    assert s.store.get(s.oid).state==UNKNOWN


def test_cancel_never_releases_until_reconciled(setup):
    s=setup
    submit(s)
    s.client.cancel_order.return_value=N(canceled=['exchange1'],not_canceled={})
    assert s.adapter.cancel(s.oid,user_authorization='fixture:cancel')
    assert s.store.get(s.oid).state==UNKNOWN
    assert s.store.get(s.oid).reserved_quantity==5
    s.client.get_order.return_value.status='CANCELED'
    v=s.adapter.reconcile(s.oid,fee_evidence=charge)
    assert v.state==S.CANCELLED and v.filled_quantity==2 and v.reserved_quantity==0


def test_read_rate_limit_bounded_retry(setup):
    s=setup
    submit(s)
    error=RuntimeError('SENSITIVE')
    error.status=429
    error.retry_after=1
    s.client.get_order.side_effect=[error,s.client.get_order.return_value]
    assert s.adapter.order_status(s.oid).id=='exchange1'
    s.adapter.sleeper.assert_called_once_with(1)


def test_exclusive_owner_and_restart_quarantine(setup):
    s=setup
    submit(s)
    with pytest.raises(ClobAdapterError,match='owns'):
        ClobAdapter(store=s.store,client_factory=s.factory,wallet=WALLET)
    s.adapter.close()
    reopened=ClobAdapter(store=s.store,client_factory=s.factory,wallet=WALLET)
    try: assert s.store.get(s.oid).state==UNKNOWN
    finally: reopened.close()


def test_credentials_repr_redacts():
    creds=ClobCredentials('SENSITIVE-KEY','SENSITIVE-ID','SENSITIVE-SECRET','SENSITIVE-PASS',WALLET)
    assert 'SENSITIVE' not in repr(creds)


def test_maker_fill_uses_only_own_leg(setup):
    s=setup
    submit(s)
    maker=N(order_id='exchange1',asset_id='101',side='BUY',maker_address=WALLET,
            matched_amount=D('2'),price=D('.60'),owner='SENSITIVE')
    s.client.list_account_trades.return_value=[page([trade(taker_order_id='another',
        size=D('50'),asset_id='202',side='SELL',maker_orders=[maker])])]
    assert s.adapter.reconcile(s.oid,fee_evidence=charge).filled_quantity==2


@pytest.mark.parametrize('failure',['rate_limit','malformed','unmatched'])
def test_placement_uncertainty_is_not_rejection(setup,failure):
    s=setup
    if failure=='rate_limit':
        error=RuntimeError('SENSITIVE')
        error.status=429
        error.retry_after=1
        s.client.post_order.side_effect=error
    elif failure=='malformed': s.client.post_order.return_value=N(ok=True,status='invented',order_id='exchange1')
    else: s.client.post_order.return_value=N(ok=False,code='unmatched')
    try: submit(s)
    except ClobAdapterError: pass
    assert s.store.get(s.oid).state==UNKNOWN
    assert s.client.post_order.call_count==1
    s.adapter.sleeper.assert_not_called()
    if failure=='malformed': assert s.store.get(s.oid).exchange_order_id=='exchange1'


def test_cancel_timeout_preserves_reservation(setup):
    s=setup
    submit(s)
    s.client.cancel_order.side_effect=TimeoutError('SENSITIVE')
    with pytest.raises(ClobAdapterError): s.adapter.cancel(s.oid,user_authorization='fixture')
    assert s.store.get(s.oid).state==UNKNOWN
    assert s.store.get(s.oid).reserved_quantity==5
    assert s.client.cancel_order.call_count==1


def test_current_fee_conflict_blocks_signing(setup):
    s=setup
    s.client.get_market.return_value.trading.fee_schedule.rate=D('.08')
    with pytest.raises(ClobAdapterError,match='fee descriptor'): submit(s)
    s.client.create_limit_order.assert_not_called()


def test_unsettled_trade_is_persisted_but_not_confirmed(setup):
    s=setup
    submit(s)
    s.client.list_account_trades.return_value=[page([trade(status='MINED')])]
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=charge)
    v=s.store.get(s.oid)
    assert v.state==UNKNOWN and v.provisional_quantity==2 and v.filled_quantity==0
    assert v.reserved_quantity==5


def test_wrong_account_never_reaches_signing(setup):
    s=setup
    s.client.wallet='0x'+'2'*40
    with pytest.raises(ClobAdapterError): submit(s)
    s.client.create_limit_order.assert_not_called()


def test_order_status_cannot_expose_api_key_owner(setup):
    s=setup
    submit(s)
    s.client.get_order.return_value.owner='SENSITIVE-API-KEY'
    snapshot=s.adapter.order_status(s.oid)
    assert 'SENSITIVE' not in repr(snapshot)
    assert not hasattr(snapshot,'owner')
