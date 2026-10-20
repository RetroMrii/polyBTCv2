from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


@dataclass(frozen=True, slots=True)
class PolymarketMarketMetadata:
    condition_id: str
    market_id: str | None
    slug: str | None
    question: str | None

    start_at: datetime | None
    end_at: datetime | None
    closed_at: datetime | None

    active: bool | None
    closed: bool | None

    yes_token_id: str | None
    no_token_id: str | None

    yes_price: float | None
    no_price: float | None

    resolution_source: str | None

    winning_outcome: str | None
    winning_token_id: str | None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _parse_json_list(value: object) -> list:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        decoded = json.loads(value)

        if not isinstance(decoded, list):
            raise ValueError(f"expected JSON list, got: {value!r}")

        return decoded

    raise TypeError(f"unsupported list value type: {type(value)!r}")


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def _bool_or_none(value: object) -> bool | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    raw = str(value).strip().lower()

    if raw == "true":
        return True

    if raw == "false":
        return False

    return None


def _parse_market(
    raw: dict,
) -> PolymarketMarketMetadata:
    outcomes = _parse_json_list(raw.get("outcomes"))

    token_ids = _parse_json_list(raw.get("clobTokenIds"))

    outcome_prices = _parse_json_list(raw.get("outcomePrices"))

    outcome_to_token: dict[str, str] = {}
    outcome_to_price: dict[str, float] = {}

    for index, outcome in enumerate(outcomes):
        normalized = str(outcome).strip().upper()

        if normalized == "UP":
            normalized = "YES"
        elif normalized == "DOWN":
            normalized = "NO"

        if index < len(token_ids):
            outcome_to_token[normalized] = str(token_ids[index])

        if index < len(outcome_prices):
            price = _float_or_none(outcome_prices[index])

            if price is not None:
                outcome_to_price[normalized] = price

    condition_id = str(raw.get("conditionId", "")).strip()

    if not condition_id:
        raise ValueError("Gamma market missing conditionId")

    winning_outcome = None
    winning_token_id = None

    yes_price = outcome_to_price.get("YES")
    no_price = outcome_to_price.get("NO")

    if yes_price == 1.0 and no_price == 0.0:
        winning_outcome = "YES"
        winning_token_id = outcome_to_token.get("YES")

    elif yes_price == 0.0 and no_price == 1.0:
        winning_outcome = "NO"
        winning_token_id = outcome_to_token.get("NO")

    return PolymarketMarketMetadata(
        condition_id=condition_id,
        market_id=(str(raw["id"]) if raw.get("id") is not None else None),
        slug=raw.get("slug"),
        question=raw.get("question"),
        start_at=_parse_datetime(raw.get("startDate")),
        end_at=_parse_datetime(raw.get("endDate")),
        closed_at=_parse_datetime(raw.get("closedTime")),
        active=_bool_or_none(raw.get("active")),
        closed=_bool_or_none(raw.get("closed")),
        yes_token_id=outcome_to_token.get("YES"),
        no_token_id=outcome_to_token.get("NO"),
        yes_price=outcome_to_price.get("YES"),
        no_price=outcome_to_price.get("NO"),
        resolution_source=raw.get("resolutionSource"),
        winning_outcome=winning_outcome,
        winning_token_id=winning_token_id,
    )


def fetch_market_metadata(
    condition_id: str,
    *,
    timeout_seconds: float = 15.0,
) -> PolymarketMarketMetadata | None:
    query = urlencode(
        {
            "condition_ids": condition_id,
            "closed": "true",
        }
    )

    url = f"{GAMMA_MARKETS_URL}?{query}"

    request = Request(
        url,
        headers={
            "User-Agent": "PolyBTCv2/0.1",
            "Accept": "application/json",
        },
    )

    with urlopen(
        request,
        timeout=timeout_seconds,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload:
        return None

    matching = [
        item
        for item in payload
        if str(item.get("conditionId", "")).lower() == condition_id.lower()
    ]

    if len(matching) == 0:
        return None

    if len(matching) > 1:
        raise ValueError(f"multiple Gamma markets returned for {condition_id}")

    return _parse_market(matching[0])
