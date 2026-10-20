from datetime import timedelta
from decimal import Decimal as D
import sqlite3

import pytest

from polybtc.execution.lifecycle import OrderLifecycleStore, OrderIntent, OrderState as S, UNKNOWN
from polybtc.execution.live_accounting import LiveAccounting
from polybtc.execution.clob_adapter import ClobAdapterError
from tests.trading.test_clob_adapter import setup, submit, charge, trade, page, NOW, WALLET, MARKET


def closed_partial(s):
    submit(s)
    s.client.get_order.return_value.status = 'CANCELED'
    s.adapter.reconcile(s.oid, fee_evidence=charge)
    return s.adapter.accounting


def receipt(**kw):
    return dict(settlement_id='receipt:transaction:log', condition_id=MARKET, token_id='101',
        collateral_asset='pUSD', quantity='1.98', payout_per_share='1', cash_received='1.98',
        cash_fee='0.01', status='CONFIRMED', occurred_at=NOW+timedelta(days=1), evidence='fixture:receipt') | kw


def test_missing_fees_preserve_fills_and_reservation_across_restart(setup):
    s = setup
    submit(s)
    with pytest.raises(ClobAdapterError):
        s.adapter.reconcile(s.oid, fee_evidence=lambda t: None)
    a = LiveAccounting(OrderLifecycleStore(s.store.path), WALLET)
    snap = a.snapshot()
    assert not snap.complete and snap.unknown_orders == (s.oid,)
    p, = snap.positions
    assert p.quantity_after_known_fees == 2 and p.cost_basis is None
    assert not p.fees_complete and snap.reserved_cash == {'pUSD': D('2.8')}
    assert any(i.startswith('unreconciled_fee:') for i in snap.issues)
    s.adapter.reconcile(s.oid, fee_evidence=charge)
    snap = a.snapshot()
    p, = snap.positions
    assert snap.complete and p.quantity_after_known_fees == D('1.98')
    assert p.cost_basis == D('1.21') and snap.reserved_cash['pUSD'] == D('2.79')


def test_unacknowledged_submission_retains_full_liability(setup):
    s = setup
    s.client.post_order.side_effect = TimeoutError()
    with pytest.raises(ClobAdapterError): submit(s)
    a = LiveAccounting(OrderLifecycleStore(s.store.path), WALLET)
    assert a.snapshot().reserved_cash == {'pUSD': D('4')}
    a.investigate(s.oid, exchange_order_id='exchange1', evidence='fixture:authenticated-lookup')
    assert s.store.get(s.oid).state == UNKNOWN
    assert a.snapshot().reserved_cash['pUSD'] == 4
    s.adapter.reconcile(s.oid, fee_evidence=charge)
    assert s.store.get(s.oid).state == S.PARTIALLY_FILLED


def test_partial_page_facts_persist_even_when_later_read_fails(setup):
    s = setup
    submit(s)
    s.client.list_account_trades.return_value = [page([trade()], True)]
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid, fee_evidence=charge)
    assert s.adapter.accounting.snapshot().positions[0].quantity_after_known_fees == 2


def test_disappearing_exchange_history_cannot_clear_unknown(setup):
    s=setup
    closed_partial(s)
    s.client.list_account_trades.return_value=[page([])]
    s.client.get_order.return_value.associate_trades=[]
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=charge)
    snap=s.adapter.accounting.snapshot()
    assert snap.unknown_orders==(s.oid,)
    assert snap.positions[0].quantity_after_known_fees==D('1.98')


def test_duplicate_reads_and_restart_do_not_double_count(setup):
    s = setup
    submit(s)
    for _ in range(2): s.adapter.reconcile(s.oid, fee_evidence=charge)
    before = s.adapter.accounting.snapshot()
    other = OrderLifecycleStore(s.store.path)
    other.recover_inflight('fixture:restart')
    after = LiveAccounting(other, WALLET).snapshot()
    assert before.positions == after.positions
    assert before.reserved_cash == after.reserved_cash
    assert after.unknown_orders == (s.oid,)


def test_marks_are_explicit_fresh_and_out_of_order_safe(setup):
    a = closed_partial(setup)
    assert a.snapshot(at=NOW).positions[0].market_value is None
    args = dict(condition_id=MARKET,token_id='101',collateral_asset='pUSD',evidence='fixture:book')
    a.record_mark(**args,price='0.65',observed_at=NOW)
    a.record_mark(**args,price='0.10',observed_at=NOW-timedelta(seconds=1))
    p = a.snapshot(at=NOW).positions[0]
    assert p.market_value == D('1.287') and p.unrealized_pnl == D('0.077')
    assert a.snapshot(at=NOW+timedelta(milliseconds=501)).positions[0].market_value is None


@pytest.mark.parametrize('payout,cash,realized', [('1','1.98','0.76'),('0','0','-1.22'),('0.5','0.99','-0.23')])
def test_settlement_receipt_pending_confirmed_and_duplicate(setup,payout,cash,realized):
    a = closed_partial(setup)
    args = receipt(payout_per_share=payout,cash_received=cash)
    a.record_settlement(**(args | {'status':'PENDING'}))
    p = a.snapshot().positions[0]
    assert p.quantity_after_known_fees == D('1.98') and p.settlement_status == 'SETTLEMENT_PENDING'
    assert a.record_settlement(**args)
    assert not a.record_settlement(**args)
    snap = LiveAccounting(OrderLifecycleStore(setup.store.path), WALLET).snapshot()
    p = snap.positions[0]
    assert p.quantity_after_known_fees == 0 and p.cost_basis == 0
    assert p.realized_pnl == D(realized) and p.settlement_status == 'SETTLED'
    assert snap.realized_by_day == {('pUSD','2026-10-13'):D(realized)}
    assert snap.reserved_cash == {} and snap.complete


def test_invalid_settlement_cannot_release_inventory(setup):
    a = closed_partial(setup)
    for change in ({'quantity':'2','cash_received':'2'}, {'occurred_at':NOW-timedelta(days=1)},
                   {'cash_received':'2'}, {'token_id':'wrong'}):
        with pytest.raises(ValueError): a.record_settlement(**receipt(**change))
    assert a.snapshot().positions[0].quantity_after_known_fees == D('1.98')


def test_conflicting_exchange_economics_are_durable_and_block_new_claims(setup):
    s = setup
    a = closed_partial(s)
    with pytest.raises(ValueError, match='discrepancy'):
        a.observe_fill(s.oid, exchange_order_id='exchange1', trade_id='trade1', quantity='3',
            price='0.60', status='CONFIRMED', executed_at=NOW,evidence='fixture:conflict')
    a = LiveAccounting(OrderLifecycleStore(s.store.path), WALLET)
    assert any(i.startswith('discrepancy:') for i in a.snapshot().issues)
    assert a.snapshot().positions[0].quantity_after_known_fees == D('1.98')
    oid=s.store.create(OrderIntent('second',MARKET,'101','BUY','5','0.60','pUSD'))
    s.store.append(oid,'risk',dict(kind='transition',target=S.RISK_APPROVED,evidence='fixture:risk'))
    a.reserve(oid,'4','fixture:risk')
    with pytest.raises(ValueError, match='accounting'):
        s.store.begin_submission(oid,payload_hash='a'*64,evidence='fixture:risk')


def test_wallet_binding_and_immutable_evidence(setup):
    a = closed_partial(setup)
    with pytest.raises(ValueError): LiveAccounting(setup.store,'0x'+'2'*40)
    with sqlite3.connect(setup.store.path) as db:
        for sql in ('DELETE FROM live_accounting_events',"UPDATE live_accounting_events SET payload='{}'"):
            with pytest.raises(sqlite3.IntegrityError): db.execute(sql)
    assert a.snapshot().complete


def test_schema_one_migration_preserves_intent_and_evidence(setup):
    s = setup
    closed_partial(s)
    before=s.store.get(s.oid)
    with sqlite3.connect(s.store.path) as db:
        db.execute('DROP TABLE live_accounting_events')
        db.execute('PRAGMA user_version=1')
    reopened=OrderLifecycleStore(s.store.path)
    assert reopened.get(s.oid)==before
    snap=LiveAccounting(reopened,WALLET).snapshot()
    assert snap.positions[0].quantity_after_known_fees==D('1.98')
    assert any(i.startswith('missing_exchange_time:') for i in snap.issues)


def record_order(store, accounting, key, side, quantity, price, cash, when):
    oid=store.create(OrderIntent(key,MARKET,'101',side,quantity,price,'pUSD'))
    store.append(oid,'risk',dict(kind='transition',target=S.RISK_APPROVED,evidence='fixture:risk'))
    accounting.reserve(oid,str(D(quantity)*D(price)+D(cash)),'fixture:risk')
    # Import historical synthetic fills directly; this helper is not a live dispatch path.
    with store._transaction() as db:
        store._append(db,oid,'submission-intent',dict(kind='transition',target=S.SUBMISSION_PENDING,
            payload_hash='a'*64,evidence='fixture:historical-import'))
    store.append(oid,'ack',dict(kind='transition',target=S.ACKNOWLEDGED,
        exchange_order_id=key,evidence='fixture:ack'))
    fill=dict(exchange_order_id=key,trade_id=key,quantity=quantity,price=price,
        status='CONFIRMED',evidence='fixture:trade')
    accounting.observe_fill(oid,**fill,executed_at=when)
    store.append(oid,'fill',dict(kind='trade',**fill,cash_fee=cash,share_fee='0',fee_evidence='fixture:fee'))
    return oid


def test_weighted_cost_partial_sell_daily_realized_and_restart(tmp_path):
    store=OrderLifecycleStore(tmp_path/'orders.sqlite3')
    a=LiveAccounting(store,WALLET)
    record_order(store,a,'buy','BUY','5','0.60','0.05',NOW)
    record_order(store,a,'sell','SELL','2','0.70','0.02',NOW+timedelta(seconds=1))
    snap=LiveAccounting(OrderLifecycleStore(store.path),WALLET).snapshot()
    p,=snap.positions
    assert snap.complete and p.quantity_after_known_fees==3
    assert p.cost_basis==D('1.83') and p.realized_pnl==D('0.16')
    assert snap.realized_by_day=={('pUSD','2026-10-12'):D('0.16')}


def test_confirmed_overfill_remains_visible_and_blocked(setup):
    s=setup
    submit(s)
    s.client.list_account_trades.return_value=[page([trade(size=D('6'))])]
    s.client.get_order.return_value.size_matched=D('6')
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=charge)
    snap=s.adapter.accounting.snapshot()
    assert snap.positions[0].quantity_after_known_fees==6
    assert 'exchange_overfill:'+s.oid in snap.issues and snap.unknown_orders==(s.oid,)


def test_provisional_fill_does_not_release_cash_or_create_position(setup):
    s=setup
    submit(s)
    s.client.list_account_trades.return_value=[page([trade(status='MATCHED')])]
    with pytest.raises(ClobAdapterError): s.adapter.reconcile(s.oid,fee_evidence=charge)
    snap=s.adapter.accounting.snapshot()
    assert snap.positions==() and snap.reserved_cash=={'pUSD':D('4')}
    assert any(i.startswith('unsettled_trade:') for i in snap.issues)
    s.client.list_account_trades.return_value=[page([trade()])]
    s.adapter.reconcile(s.oid,fee_evidence=charge)
    assert s.adapter.accounting.snapshot().positions[0].quantity_after_known_fees==D('1.98')
