from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
import sqlite3

import pytest

from polybtc.execution.lifecycle import (
    OrderIntent, OrderLifecycleStore, OrderState as S, UNKNOWN, acknowledgement,
)


def intent(key='decision:market:60'):
    return OrderIntent(key, 'market', 'token-yes', 'BUY', '5', '0.70', 'collateral')


def transition(target, **kw):
    return dict(kind='transition', target=target, evidence='fixture:authenticated', **kw)


def trade(status='CONFIRMED', trade_id='trade-1', quantity='2', **kw):
    return dict(kind='trade', evidence='fixture:authenticated', exchange_order_id='exchange-1',
                trade_id=trade_id, status=status, quantity=quantity, price='0.60',
                cash_fee='0.01', share_fee='0.02', fee_evidence='fixture:fee', **kw)


def reconcile(target, quantity='0', exchange='exchange-1'):
    return dict(kind='reconcile', target=target, confirmed_quantity=quantity,
                exchange_order_id=exchange, evidence='fixture:complete-order-and-trade-query')


def ready(tmp_path, acknowledge=True):
    store = OrderLifecycleStore(tmp_path / 'orders.sqlite3')
    oid = store.create(intent())
    store.append(oid, 'risk', transition(S.RISK_APPROVED))
    assert store.begin_submission(oid, payload_hash='a' * 64, evidence='risk+source+fees:fixture')
    if acknowledge:
        store.append(oid, 'ack', transition(S.ACKNOWLEDGED, exchange_order_id='exchange-1'))
    return store, oid


def test_stable_intent_and_single_dispatch_across_processes(tmp_path):
    store, oid = ready(tmp_path, False)
    reopened = OrderLifecycleStore(store.path)
    assert reopened.create(intent()) == oid
    assert not reopened.begin_submission(oid, payload_hash='a' * 64, evidence='risk+source+fees:fixture')
    with pytest.raises(ValueError):
        reopened.create(replace(intent(), quantity='4'))
    with pytest.raises(ValueError):
        reopened.begin_submission(oid, payload_hash='b' * 64, evidence='risk+source+fees:fixture')
    assert reopened.get(oid).state == S.SUBMISSION_PENDING


def test_concurrent_submission_has_one_winner(tmp_path):
    path = tmp_path / 'orders.sqlite3'
    store = OrderLifecycleStore(path)
    oid = store.create(intent())
    store.append(oid, 'risk', transition(S.RISK_APPROVED))
    def claim(_):
        return OrderLifecycleStore(path).begin_submission(oid, payload_hash='a'*64, evidence='fixture')
    with ThreadPoolExecutor(4) as workers:
        assert list(workers.map(claim, range(4))).count(True) == 1


def test_partial_fills_exact_fees_duplicates_and_restart(tmp_path):
    store, oid = ready(tmp_path)
    store.append(oid, 'matched', trade('MATCHED'))
    assert store.get(oid).provisional_quantity == 2
    assert store.get(oid).filled_quantity == 0
    store.append(oid, 'mined', trade('MINED'))
    store.append(oid, 'confirmed', trade())
    assert not store.append(oid, 'confirmed', trade())
    store.append(oid, 'duplicate-other-transport', trade())
    store.append(oid, 'duplicate-ack', transition(S.ACKNOWLEDGED, exchange_order_id='exchange-1'))
    view = OrderLifecycleStore(store.path).get(oid)
    assert view.state == S.PARTIALLY_FILLED
    assert view.filled_quantity == 2 and view.reserved_quantity == 3
    assert view.filled_notional == D('1.20')
    assert view.cash_delta == D('-1.21') and view.token_delta == D('1.98')
    store.append(oid, 'remaining-fill', trade(trade_id='trade-2', quantity='3'))
    assert store.get(oid).state == S.FILLED
    assert store.get(oid).reserved_quantity == 0


def test_timeout_blocks_all_new_dispatch_until_reconciled(tmp_path):
    store, oid = ready(tmp_path, False)
    store.append(oid, 'timeout', transition(UNKNOWN))
    second = store.create(intent('another'))
    store.append(second, 'risk', transition(S.RISK_APPROVED))
    with pytest.raises(ValueError, match='Unresolved'):
        store.begin_submission(second, payload_hash='b'*64, evidence='fixture')
    with pytest.raises(ValueError):
        store.append(oid, 'ack', transition(S.ACKNOWLEDGED, exchange_order_id='exchange-1'))
    assert store.get(oid).reserved_quantity == 5
    store.append(oid, 'resolved', reconcile(S.ACKNOWLEDGED))
    assert store.begin_submission(second, payload_hash='b'*64, evidence='fixture')


def test_recovery_is_repeatable_after_successful_reconciliation(tmp_path):
    store, oid = ready(tmp_path)
    assert store.recover_inflight('startup') == 1
    assert store.recover_inflight('startup') == 0
    store.append(oid, 'query', reconcile(S.ACKNOWLEDGED))
    assert store.recover_inflight('startup') == 1
    assert store.get(oid).state == UNKNOWN


def test_cancel_race_keeps_partial_exposure(tmp_path):
    store, oid = ready(tmp_path)
    store.append(oid, 'cancel', transition(S.CANCEL_REQUESTED))
    store.append(oid, 'late-match', trade('MATCHED'))
    assert store.get(oid).state == S.CANCEL_REQUESTED
    with pytest.raises(ValueError, match='Unsettled'):
        store.append(oid, 'cancelled', reconcile(S.CANCELLED))
    store.append(oid, 'late-confirm', trade())
    store.append(oid, 'cancelled', reconcile(S.CANCELLED, '2'))
    assert store.get(oid).filled_quantity == 2
    assert store.get(oid).reserved_quantity == 0
    store.append(oid, 'unexpected-late-fill', trade(trade_id='trade-2', quantity='1'))
    assert store.get(oid).state == UNKNOWN
    assert store.get(oid).filled_quantity == 3
    assert store.get(oid).reserved_quantity == 2


def test_failed_settlement_remains_unknown_until_evidence(tmp_path):
    store, oid = ready(tmp_path)
    for status in ('MATCHED', 'MINED', 'RETRYING', 'FAILED'):
        store.append(oid, status, trade(status))
    view = store.get(oid)
    assert view.state == UNKNOWN and view.filled_quantity == 0
    assert view.reserved_quantity == 5 and view.cash_fees == 0
    store.append(oid, 'reconciled-cancel', reconcile(S.CANCELLED))
    assert store.get(oid).reserved_quantity == 0


@pytest.mark.parametrize('event', [
    transition(S.FILLED), transition(S.EXPIRED), transition(S.RISK_APPROVED),
    dict(trade(), quantity='6'), dict(trade(), price='0.71'),
    dict(trade(), cash_fee='NaN'), dict(trade(), share_fee='3'),
    dict(trade(), fee_evidence=''), dict(trade(), exchange_order_id='wrong'),
    dict(trade(), quantity=2), dict(trade(), status='unexpected'),
])
def test_invalid_events_are_atomic(tmp_path, event):
    store, oid = ready(tmp_path)
    before = store.get(oid)
    with pytest.raises(ValueError):
        store.append(oid, 'bad', event)
    after = store.get(oid)
    assert after.intent == before.intent and after.trades == before.trades
    assert after.state == UNKNOWN


def test_conflicting_duplicate_fill_and_ack_are_rejected(tmp_path):
    store, oid = ready(tmp_path)
    store.append(oid, 'fill', trade())
    for key in ('fill', 'another-event'):
        with pytest.raises(ValueError):
            store.append(oid, key, dict(trade(), quantity='3'))
    with pytest.raises(ValueError):
        store.append(oid, 'wrong-ack', transition(S.ACKNOWLEDGED, exchange_order_id='wrong'))
    assert store.get(oid).filled_quantity == 2


def test_evidence_and_intent_immutable_and_shadow_database_rejected(tmp_path):
    store, oid = ready(tmp_path)
    for sql in ('DELETE FROM lifecycle_events', "UPDATE lifecycle_events SET payload='{}'",
                'DELETE FROM lifecycle_orders', "UPDATE lifecycle_orders SET intent='{}'"):
        with sqlite3.connect(store.path) as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    foreign = tmp_path / 'shadow.sqlite3'
    with sqlite3.connect(foreign) as db:
        db.execute('CREATE TABLE positions (id TEXT)')
    with pytest.raises(ValueError, match='own database'):
        OrderLifecycleStore(foreign)


def test_exchange_ids_unique_across_internal_orders(tmp_path):
    store, oid = ready(tmp_path)
    second = store.create(intent('second'))
    store.append(second, 'risk', transition(S.RISK_APPROVED))
    store.begin_submission(second, payload_hash='a'*64, evidence='fixture')
    with pytest.raises(sqlite3.IntegrityError):
        store.append(second, 'ack', transition(S.ACKNOWLEDGED, exchange_order_id='exchange-1'))
    assert store.get(second).state == UNKNOWN


def test_reconciliation_cannot_invent_fills(tmp_path):
    store, oid = ready(tmp_path)
    store.append(oid, 'timeout', transition(UNKNOWN))
    with pytest.raises(ValueError):
        store.append(oid, 'query', reconcile(S.FILLED, '5'))
    store.append(oid, 'recovered-trade', trade(quantity='5'))
    assert store.get(oid).state == UNKNOWN
    store.append(oid, 'complete-query', reconcile(S.FILLED, '5'))
    assert store.get(oid).state == S.FILLED


@pytest.mark.parametrize('status', ['live', 'matched', 'delayed', 'unmatched'])
def test_placement_status_is_not_a_fill(tmp_path, status):
    store, oid = ready(tmp_path, False)
    store.append(oid, 'placement', acknowledgement(exchange_order_id='exchange-1',
        venue_status=status, evidence='fixture'))
    assert store.get(oid).filled_quantity == 0
    assert store.get(oid).reserved_quantity == 5
    if status == 'delayed':
        with pytest.raises(ValueError, match='Delayed'):
            store.append(oid, 'cancel', transition(S.CANCEL_REQUESTED))


def test_sell_accounting_and_expiration(tmp_path):
    store = OrderLifecycleStore(tmp_path / 'orders.sqlite3')
    oid = store.create(replace(intent(), side='SELL', limit_price='0.50',
                               order_type='GTD', expires_at='2026-10-12T00:00:00+00:00'))
    store.append(oid, 'risk', transition(S.RISK_APPROVED))
    store.begin_submission(oid, payload_hash='a'*64, evidence='fixture')
    store.append(oid, 'fill', trade())
    assert store.get(oid).cash_delta == D('1.19')
    assert store.get(oid).token_delta == D('-2.02')
    store.append(oid, 'expiry-observed', transition(UNKNOWN))
    store.append(oid, 'expiry-confirmed', reconcile(S.EXPIRED, '2'))
    assert store.get(oid).reserved_quantity == 0


def test_rejection_and_no_automatic_resubmit(tmp_path):
    store, oid = ready(tmp_path, False)
    store.append(oid, 'response', transition(S.REJECTED))
    assert store.get(oid).reserved_quantity == 0
    assert not store.begin_submission(oid, payload_hash='a'*64, evidence='risk+source+fees:fixture')


def test_schema_version_fails_closed(tmp_path):
    store, _ = ready(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError, match='schema'):
        OrderLifecycleStore(store.path)
