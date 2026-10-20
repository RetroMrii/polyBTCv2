"""Run with the optional clob extra; all network calls are replaced or blocked."""
from decimal import Decimal as D
from types import SimpleNamespace as N
from unittest.mock import Mock
import socket

import pytest

sdk = pytest.importorskip('polymarket', reason='Optional pinned CLOB SDK not installed')
from eth_account import Account
from polymarket.clients.secure import SecureClient
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket.models.clob.api_key import ApiKeyCreds
from polybtc.execution.clob_sdk import ClobCredentials, connect_official


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('Network forbidden')))


@pytest.mark.parametrize('wallet_type,signature_type', [('EOA',0),('POLY_PROXY',1),('GNOSIS_SAFE',2),('DEPOSIT_WALLET',3)])
def test_official_signing_and_post_serialization_offline(wallet_type, signature_type):
    # Ephemeral synthetic identity, never a user key or funded wallet.
    signer = Account.create()
    wallet = signer.address if wallet_type == 'EOA' else '0x'+'2'*40
    transport = Mock()
    transport.post_json.return_value = dict(errorMsg='',makingAmount='0',takingAmount='0',
        orderID='0x'+'b'*64,status='live',success=True,tradeIDs=[],transactionsHashes=[])
    metadata = Mock()
    metadata.resolve_market.return_value=N(tick_size=D('.01'),neg_risk=False)
    client = object.__new__(SecureClient)
    client._ended=False
    client._ctx_inner=N(signer=signer, wallet=wallet, wallet_type=wallet_type, signer_type='OWNER',
        environment_config=PRODUCTION_CONFIG, order_metadata=metadata, secure_clob=transport,
        credentials=ApiKeyCreds(apiKey='fixture-only',secret='fixture-only',passphrase='fixture-only'))
    signed=client.create_limit_order(asset_id='101',side='BUY',price='0.60',size='5')
    assert signed.maker_amount==3000000 and signed.taker_amount==5000000
    assert signed.signature.startswith('0x')
    assert len(signed.signature) > 132 if wallet_type == 'DEPOSIT_WALLET' else len(signed.signature) == 132
    assert signed.maker == wallet
    assert signed.signer == (wallet if wallet_type == 'DEPOSIT_WALLET' else signer.address)
    assert signed.signature_type == signature_type
    response=client.post_order(signed)
    assert response.ok is True and response.status=='live'
    args=transport.post_json.call_args
    assert args.args==('/order',)
    assert args.kwargs['json']['order']['tokenId']=='101'
    assert transport.post_json.call_count==1


@pytest.mark.parametrize('wallet_type,derive_name', [
    ('POLY_PROXY','derive_proxy_wallet_address'),
    ('GNOSIS_SAFE','derive_safe_wallet_address'),
    ('DEPOSIT_WALLET','derive_beacon_deposit_wallet_address'),
    ('DEPOSIT_WALLET','derive_uups_deposit_wallet_address'),
])
def test_existing_owner_wallet_bootstrap_is_get_only(monkeypatch, wallet_type, derive_name):
    import httpx
    from dataclasses import replace
    from polymarket._internal import wallet as wallets
    calls=[]
    def handler(request):
        calls.append((request.method,request.url.path))
        assert request.method=='GET' and request.url.path=='/auth/api-keys'
        return httpx.Response(200,json={'apiKeys':['fixture']})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**(kw|{'transport':httpx.MockTransport(handler)})))
    signer=Account.create()
    wallet=getattr(wallets,derive_name)(signer.address,PRODUCTION_CONFIG.wallet_derivation)
    creds=ClobCredentials('0x'+signer.key.hex().removeprefix('0x'),'fixture','Zml4dHVyZQ==','fixture',wallet,wallet_type)
    client=connect_official(creds)
    assert client.wallet_type==wallet_type and client.signer==signer.address
    client.close()
    assert calls==[('GET','/auth/api-keys')]
    calls.clear()
    for invalid in (replace(creds,wallet_type='EOA'), replace(creds,wallet='0x'+'3'*40)):
        with pytest.raises(RuntimeError,match='validation failed'): connect_official(invalid)
    assert calls==[]


def test_factory_explicit_eoa_existing_credentials_no_implicit_setup(monkeypatch):
    signer=Account.create()
    fake=Mock()
    fake.fetch_api_keys.return_value=('fixture',)
    create=Mock(return_value=fake)
    monkeypatch.setattr(SecureClient,'_create',create)
    creds=ClobCredentials('0x'+signer.key.hex().removeprefix('0x'),'fixture','fixture','fixture',signer.address)
    assert connect_official(creds) is fake
    assert create.call_args.kwargs['wallet']==signer.address
    assert create.call_args.kwargs['credentials'].key=='fixture'
    assert create.call_args.kwargs['logger'] is None
    assert create.call_args.kwargs['validate_credentials'] is False
    create.reset_mock()
    from dataclasses import replace
    with pytest.raises(RuntimeError,match='validation failed'):
        connect_official(replace(creds,wallet='0x'+'2'*40))
    create.assert_not_called()


@pytest.mark.parametrize('status,keys',[(200,['fixture']),(200,[]),(401,[])])
def test_real_sdk_bootstrap_only_get_never_creates_credentials(monkeypatch,status,keys):
    import httpx
    calls=[]
    def handler(request):
        calls.append((request.method,request.url.path))
        assert request.method=='GET' and request.url.path=='/auth/api-keys'
        return httpx.Response(status,json={'apiKeys':keys})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**(kw|{'transport':httpx.MockTransport(handler)})))
    signer=Account.create()
    creds=ClobCredentials('0x'+signer.key.hex().removeprefix('0x'),'fixture','Zml4dHVyZQ==','fixture',signer.address)
    if status==200 and keys:
        client=connect_official(creds)
        assert client.wallet_type=='EOA'
        client.close()
    else:
        with pytest.raises(RuntimeError,match='validation failed'): connect_official(creds)
    assert calls==[('GET','/auth/api-keys')]


def test_sdk_unmatched_response_is_not_treated_as_fill():
    from polymarket._internal.actions.orders.post import parse_order_response
    response=parse_order_response(dict(errorMsg='',makingAmount='0',takingAmount='0',
        orderID='0x'+'b'*64,status='unmatched',success=True))
    assert response.ok is False


def test_sdk_pagination_normalization_and_order_types():
    from polymarket._internal.actions.account import parse_account_trades_page
    page=parse_account_trades_page({'data':[],'next_cursor':'LTE='})
    assert page.has_more is False and page.limit_reached is False
    from inspect import signature
    for method, parameter in [('get_order','order_id'),('get_market','id'),
                              ('get_order_book','asset_id'),('list_account_trades','market'),
                              ('cancel_order','order_id')]:
        assert parameter in signature(getattr(SecureClient,method)).parameters
