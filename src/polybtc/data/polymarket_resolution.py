from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DATA_API_RESOLUTIONS_URL = "https://data-api.polymarket.com/v2/resolutions"


@dataclass(frozen=True, slots=True)
class PolymarketResolution:
    condition_id: str
    resolved: bool
    resolved_at: datetime | None

    winning_outcome: str | None
    winning_token_id: str | None
    outcome_index: int | None

    source: str = "polymarket_data_api_v2"


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


def _normalize_outcome(
    value: object,
) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().upper()

    if normalized in {"YES", "UP"}:
        return "YES"

    if normalized in {"NO", "DOWN"}:
        return "NO"

    return None


def fetch_resolution(
    condition_id: str,
    *,
    timeout_seconds: float = 15.0,
) -> PolymarketResolution | None:
    query = urlencode(
        {
            "condition": condition_id,
        }
    )

    request = Request(
        f"{DATA_API_RESOLUTIONS_URL}?{query}",
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

    data = payload.get("data")

    if data is None:
        return None

    if isinstance(data, list):
        if len(data) == 0:
            return None

        if len(data) > 1:
            matching = [
                item
                for item in data
                if str(
                    item.get(
                        "condition_id",
                        item.get(
                            "conditionId",
                            "",
                        ),
                    )
                ).lower()
                == condition_id.lower()
            ]

            if len(matching) != 1:
                raise ValueError(
                    f"resolution lookup returned {len(data)} rows for {condition_id}"
                )

            data = matching[0]
        else:
            data = data[0]

    resolved_condition_id = str(
        data.get(
            "condition_id",
            data.get(
                "conditionId",
                condition_id,
            ),
        )
    ).strip()

    outcome_index = data.get(
        "outcome_index",
        data.get("outcomeIndex"),
    )

    if outcome_index is not None:
        outcome_index = int(outcome_index)

        if outcome_index == 999:
            outcome_index = None

    winning_outcome = _normalize_outcome(
        data.get(
            "outcome",
            data.get(
                "winning_outcome",
                data.get("winningOutcome"),
            ),
        )
    )

    winning_token_id = data.get(
        "token_id",
        data.get(
            "winning_token_id",
            data.get("winningTokenId"),
        ),
    )

    if winning_token_id is not None:
        winning_token_id = str(winning_token_id)

    resolved_at = _parse_datetime(
        data.get(
            "resolved_at",
            data.get("resolvedAt"),
        )
    )

    resolved = (
        winning_outcome is not None
        or winning_token_id is not None
        or resolved_at is not None
    )

    return PolymarketResolution(
        condition_id=resolved_condition_id,
        resolved=resolved,
        resolved_at=resolved_at,
        winning_outcome=winning_outcome,
        winning_token_id=winning_token_id,
        outcome_index=outcome_index,
    )
