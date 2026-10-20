from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CLOB_BASE_URL = "https://clob.polymarket.com"

FEE_PROVIDER_VERSION = "polymarket_clob_fee_provider_v1"
EXPECTED_FEE_RATE = 0.07
EXPECTED_FEE_EXPONENT = 1
EXPECTED_FEE_FLAG = True

MAX_RESPONSE_BYTES = 1024 * 1024

CONDITION_ID_PATTERN = re.compile(r"0x[0-9a-fA-F]{64}")


class FeePolicyError(RuntimeError):
    """Fee policy could not be reliably established."""


@dataclass(frozen=True, slots=True)
class PolymarketFeePolicy:
    condition_id: str

    fee_rate: float
    fee_exponent: int
    fee_flag: bool

    source: str
    provider_version: str
    retrieved_at_utc: datetime

    descriptor_verified: bool
    research_formula_compatible: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_condition_id(condition_id: str) -> str:
    if not isinstance(condition_id, str):
        raise ValueError("Condition ID must be a string")

    condition_id = condition_id.strip().lower()

    if not CONDITION_ID_PATTERN.fullmatch(condition_id):
        raise ValueError("Invalid Polymarket condition ID")

    return condition_id


def _validate_fee_descriptor(raw: object) -> tuple[float, int, bool]:
    if not isinstance(raw, dict):
        raise FeePolicyError("Missing or invalid fee descriptor")

    required = {"r", "e", "to"}

    if not required.issubset(raw):
        raise FeePolicyError(f"Missing fee fields: {sorted(required - set(raw))}")

    rate = raw["r"]
    exponent = raw["e"]
    flag = raw["to"]

    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise FeePolicyError("Invalid fee rate type")

    rate = float(rate)

    if not math.isfinite(rate) or rate < 0:
        raise FeePolicyError("Invalid fee rate")

    if isinstance(exponent, bool) or not isinstance(exponent, int):
        raise FeePolicyError("Invalid fee exponent")

    if not isinstance(flag, bool):
        raise FeePolicyError("Invalid fee descriptor flag")

    return rate, exponent, flag


def fetch_market_fee_policy(
    condition_id: str,
    *,
    timeout_seconds: float = 15.0,
) -> PolymarketFeePolicy:
    """
    Retrieve the CLOB market fee descriptor.

    Read-only metadata request.

    This provider validates compatibility with the
    existing PolyBTC research fee formula. It does
    not authorize live trading or independently
    verify fee settlement accounting.
    """
    market = _validate_condition_id(condition_id)

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("Invalid request timeout")

    url = f"{CLOB_BASE_URL}/clob-markets/{market}"

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "PolyBTCv2/fee-provider-v1",
        },
        method="GET",
    )

    try:
        with urlopen(
            request,
            timeout=float(timeout_seconds),
        ) as response:
            payload_bytes = response.read(MAX_RESPONSE_BYTES + 1)

    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise FeePolicyError(f"CLOB fee request failed for {market}") from exc

    if len(payload_bytes) > MAX_RESPONSE_BYTES:
        raise FeePolicyError("CLOB fee response exceeds size limit")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise FeePolicyError("Invalid CLOB fee response JSON") from exc

    if not isinstance(payload, dict):
        raise FeePolicyError("Unexpected CLOB response structure")

    fee_rate, exponent, flag = _validate_fee_descriptor(payload.get("fd"))

    # Explicit compatibility gate.
    #
    # Do not automatically interpret other CLOB fee
    # descriptors as equivalent to research_fee_formula_v1.
    if not math.isclose(
        fee_rate,
        EXPECTED_FEE_RATE,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise FeePolicyError(f"Unsupported fee rate: {fee_rate}")

    if exponent != EXPECTED_FEE_EXPONENT:
        raise FeePolicyError(f"Unsupported fee exponent: {exponent}")

    if flag is not EXPECTED_FEE_FLAG:
        raise FeePolicyError(f"Unsupported fee descriptor flag: {flag}")

    return PolymarketFeePolicy(
        condition_id=market,
        fee_rate=fee_rate,
        fee_exponent=exponent,
        fee_flag=flag,
        source=url,
        provider_version=FEE_PROVIDER_VERSION,
        retrieved_at_utc=_utc_now(),
        descriptor_verified=True,
        research_formula_compatible=True,
    )
