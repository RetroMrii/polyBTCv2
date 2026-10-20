"""Pure upstream value parsing; no acquisition or runtime dependencies."""

import math
import json
from datetime import datetime
from typing import Any


def timestamp_seconds(value: Any) -> float | None:
    if value is None:
        return None

    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        if number > 100_000_000_000:
            return number / 1000.0
        if number > 1_000_000_000:
            return number
    except (TypeError, ValueError, OverflowError):
        pass

    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return None
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def source_age_ms(value: Any, *, now: float) -> float | None:
    seconds = timestamp_seconds(value)
    if seconds is None:
        return None
    return (now - seconds) * 1000.0


def parse_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def field(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite market data")
    return result


def best_bid_ask(book: Any) -> tuple:
    bids = field(book, "bids", []) or []
    asks = field(book, "asks", []) or []

    def parse_levels(levels):
        parsed = []
        for level in levels:
            try:
                price = number(field(level, "price"))
                size_raw = field(level, "size")
                size = None if size_raw is None else number(size_raw)
                if not 0 < price <= 1:
                    continue
                if size is not None and size < 0:
                    continue
                parsed.append((price, size))
            except (ValueError, TypeError):
                continue
        return parsed

    parsed_bids = parse_levels(bids)
    parsed_asks = parse_levels(asks)

    bid = max(parsed_bids, key=lambda x: x[0], default=None)
    ask = min(parsed_asks, key=lambda x: x[0], default=None)

    return (
        bid[0] if bid else None,
        ask[0] if ask else None,
        bid[1] if bid else None,
        ask[1] if ask else None,
    )
