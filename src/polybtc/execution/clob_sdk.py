"""Pinned official SDK boundary; no credentials are loaded implicitly."""
from dataclasses import dataclass, field
from importlib.metadata import version
import re

SDK_VERSION = '0.13.0'
WALLET_SIGNATURE_TYPES = {'EOA': 0, 'POLY_PROXY': 1, 'GNOSIS_SAFE': 2, 'DEPOSIT_WALLET': 3}


@dataclass(frozen=True)
class ClobCredentials:
    private_key: str = field(repr=False)
    api_key: str = field(repr=False)
    secret: str = field(repr=False)
    passphrase: str = field(repr=False)
    wallet: str
    wallet_type: str = 'EOA'

    def validate(self):
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}', self.private_key):
            raise ValueError('Invalid private-key format')
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', self.wallet):
            raise ValueError('Invalid wallet format')
        if not all(isinstance(v, str) and v.strip() for v in (self.api_key, self.secret, self.passphrase)):
            raise ValueError('Existing API credentials are required')
        if self.wallet_type not in WALLET_SIGNATURE_TYPES:
            raise ValueError('Explicit supported wallet type required')


def connect_official(credentials: ClobCredentials):
    """Authenticated credential validation. Caller must authorize network access.

    Uses a reviewed, version-pinned SDK constructor seam: the public factory can
    create credentials when validation fails and can deploy a deposit wallet.
    Validate existing credentials using GET only instead. No place_* helpers.
    """
    client = None
    try:
        credentials.validate()
        if version('polymarket-client') != SDK_VERSION:
            raise ValueError('Unsupported SDK')
        from eth_account import Account
        from polymarket import SecureClient, ApiKeyCreds
        from polymarket._internal.environment import PRODUCTION_CONFIG
        from polymarket._internal.wallet import try_classify_wallet_type
        signer = Account.from_key(credentials.private_key).address
        # Do not use classify_account's unknown-address session-key fallback.
        # Only owner-derived wallets of the explicitly selected type are accepted.
        resolved_type = try_classify_wallet_type(signer=signer, wallet=credentials.wallet,
                                                config=PRODUCTION_CONFIG.wallet_derivation)
        if resolved_type != credentials.wallet_type:
            raise ValueError('Wallet type or owner derivation mismatch')
        client = SecureClient._create(
            private_key=credentials.private_key, wallet=credentials.wallet,
            credentials=ApiKeyCreds(apiKey=credentials.api_key, secret=credentials.secret,
                                    passphrase=credentials.passphrase), logger=None,
            validate_credentials=False,
        )
        if credentials.wallet_type != 'EOA' and (
            client.wallet_type != credentials.wallet_type or
            str(client.wallet).lower() != credentials.wallet.lower() or
            str(client.signer).lower() != signer.lower()
        ):
            raise ValueError('Resolved SDK account mismatch')
        if credentials.api_key not in client.fetch_api_keys():
            raise ValueError('Existing API credentials are not active')
        return client
    except Exception:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        # SDK exceptions can contain validation inputs; do not propagate them.
        raise RuntimeError('CLOB credential/client validation failed') from None
