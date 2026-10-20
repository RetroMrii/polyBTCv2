"""P-EX-L audit regressions; passing tests are not live activation approval."""
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from polybtc.execution.clob_adapter import AdapterConfig, ClobAdapterError
from polybtc.execution.lifecycle import UNKNOWN
from polybtc.operations import model_identity
from polybtc.shadow.operating_mode_vnext import supported_mode
from tests.trading.test_clob_adapter import setup, submit, NOW


@pytest.mark.parametrize('delay', [.501, 31])
def test_expired_evidence_after_claim_must_not_reach_post(setup, delay):
    s=setup
    original=s.store.begin_submission
    def delayed_commit(*args,**kwargs):
        permit=original(*args,**kwargs)
        s.adapter.clock=lambda:NOW+timedelta(seconds=delay)
        return permit
    s.store.begin_submission=delayed_commit
    with pytest.raises(ClobAdapterError, match='reconcile without resubmitting'):
        submit(s)  # Entire exchange transport is the existing Mock fixture.
    s.client.post_order.assert_not_called()
    assert s.store.get(s.oid).state == UNKNOWN
    assert s.adapter.accounting.snapshot().reserved_cash['pUSD'] == 4
    assert s.adapter.config.kill_switch is True
    assert s.adapter._dispatch_permit is None
    assert s.adapter._dispatch_guard is None
    with pytest.raises(ClobAdapterError):
        submit(s)
    s.client.post_order.assert_not_called()


@pytest.mark.parametrize('field', ['account', 'yes_book_at', 'no_book_at', 'reference_at', 'selected_book'])
def test_dispatch_rechecks_each_market_and_account_timestamp(setup, field):
    s = setup
    context = s.authorization.risk_context
    earlier = NOW - timedelta(seconds=1.9 if field == 'reference_at' else .4)
    if field == 'account':
        context = replace(context, account=replace(context.account, observed_at=earlier))
    elif field == 'selected_book':
        s.client.get_order_book.return_value.timestamp = earlier
    else:
        context = replace(context, **{field: earlier})
    s.authorization = replace(s.authorization, risk_context=context)
    original = s.store.begin_submission
    def delayed_commit(*args, **kwargs):
        permit = original(*args, **kwargs)
        s.adapter.clock = lambda: NOW + timedelta(seconds=.2)
        return permit
    s.store.begin_submission = delayed_commit
    with pytest.raises(ClobAdapterError):
        submit(s)
    s.client.post_order.assert_not_called()
    assert s.store.get(s.oid).state == UNKNOWN
    assert s.adapter.accounting.snapshot().reserved_cash['pUSD'] == 4


def test_dispatch_check_occurs_after_lazy_client_initialization(setup):
    s = setup
    original = s.store.begin_submission
    def delayed_client(*args, **kwargs):
        permit = original(*args, **kwargs)
        s.adapter._client = None
        def factory():
            s.adapter.clock = lambda: NOW + timedelta(seconds=1)
            return s.client
        s.adapter._factory = factory
        return permit
    s.store.begin_submission = delayed_client
    with pytest.raises(ClobAdapterError):
        submit(s)
    s.client.post_order.assert_not_called()
    assert s.store.get(s.oid).state == UNKNOWN


def test_kill_switch_blocks_cancel_and_does_not_remove_resting_liability(setup):
    s=setup
    submit(s)
    s.adapter.config=replace(s.adapter.config,kill_switch=True)
    with pytest.raises(ClobAdapterError):
        s.adapter.cancel(s.oid,user_authorization='fixture:operator')
    s.client.cancel_order.assert_not_called()
    assert s.adapter.accounting.snapshot().reserved_cash['pUSD']==4


def test_selected_v2_identity_is_not_production_approval():
    path=Path('data/models/main/hgb3_expanded_v2.joblib')
    metadata=json.loads(path.with_suffix('.json').read_text())
    assert model_identity(path)['sha256']==metadata['frozen_model_sha256']
    assert model_identity(path)['identity_verified'] is True
    assert model_identity(path)['approval_scope'] == 'artifact_identity_only'
    assert model_identity(path)['production_approved'] is False
    assert metadata['model_version']=='hgb3_expanded_v2'
    assert metadata['production_approved'] is False
    assert metadata['full_data_refit'] is True


def test_operational_live_mode_and_default_adapter_remain_disabled():
    with pytest.raises(ValueError,match='unavailable'): supported_mode('live_execution')
    assert AdapterConfig()==AdapterConfig(False,False,True)


def test_paper_verified_sources_can_never_authorize_real_order(setup):
    setup.authorization.source_verification.execution_scope='paper'
    with pytest.raises(ClobAdapterError,match='Paper evidence'):
        submit(setup)
    setup.factory.assert_not_called()
    setup.client.post_order.assert_not_called()
