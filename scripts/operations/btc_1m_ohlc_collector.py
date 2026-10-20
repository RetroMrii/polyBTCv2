from __future__ import annotations

import csv
import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import websocket


OUTPUT_FILE = Path(
    os.getenv(
        "BTC_1M_OHLC_FILE",
        "/home/haytam_backup1/PolyBTC/btc_1m_ohlc.csv",
    )
)

WS_URL = os.getenv(
    "BTC_5M_CHAINLINK_WS_URL",
    "wss://ws-live-data.polymarket.com",
)

SYMBOL = (
    os.getenv(
        "BTC_5M_CHAINLINK_SYMBOL",
        "btc/usd",
    )
    .strip()
    .lower()
)

WINDOW_SECONDS = int(
    os.getenv(
        "BTC_5M_CHAINLINK_WINDOW_SECONDS",
        "60",
    )
)

RECONNECT_SECONDS = float(
    os.getenv(
        "BTC_5M_CHAINLINK_RECONNECT_SECONDS",
        "2",
    )
)

STALE_RECONNECT_SECONDS = float(
    os.getenv(
        "BTC_5M_CHAINLINK_STALE_RECONNECT_SECONDS",
        "15",
    )
)


CSV_FIELDS = (
    "Timestamp",
    "Open",
    "High",
    "Low",
    "Close",
)


logging.basicConfig(
    level=logging.INFO,
    format=("%(asctime)s %(levelname)s %(message)s"),
)

logger = logging.getLogger("btc_1m_ohlc")


def topic() -> str:
    if WINDOW_SECONDS == 30:
        return "crypto_prices_twap_thirty"

    if WINDOW_SECONDS == 60:
        return "crypto_prices_twap_sixty"

    raise RuntimeError("BTC_5M_CHAINLINK_WINDOW_SECONDS must be 30 or 60")


def subscription_frame() -> str:
    filters = json.dumps(
        {
            "symbol": SYMBOL,
        },
        separators=(",", ":"),
    )

    frame = {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": topic(),
                "type": "update",
                "filters": filters,
            }
        ],
    }

    return json.dumps(
        frame,
        separators=(",", ":"),
    )


def parse_price(
    payload: dict[str, Any],
) -> float:
    full_accuracy = payload.get("full_accuracy_value")

    if full_accuracy is not None:
        return float(Decimal(str(full_accuracy)) / Decimal(10**18))

    return float(payload["value"])


def ensure_output_file() -> None:
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_FILE.exists() and OUTPUT_FILE.stat().st_size > 0:
        return

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDS,
        )

        writer.writeheader()

        file.flush()

        os.fsync(file.fileno())


def load_last_written_minute() -> int | None:
    ensure_output_file()

    last_timestamp = None

    with OUTPUT_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            raw = (row.get("Timestamp") or "").strip()

            if not raw:
                continue

            last_timestamp = int(raw)

    return last_timestamp


def append_completed_candle(
    candle: dict[str, float | int],
    last_written_minute: int | None,
) -> int | None:
    minute = int(candle["Timestamp"])

    if last_written_minute is not None and minute <= last_written_minute:
        logger.warning(
            "skip duplicate/old candle minute=%s last_written=%s",
            minute,
            last_written_minute,
        )

        return last_written_minute

    with OUTPUT_FILE.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDS,
        )

        writer.writerow(
            {
                "Timestamp": minute,
                "Open": candle["Open"],
                "High": candle["High"],
                "Low": candle["Low"],
                "Close": candle["Close"],
            }
        )

        file.flush()

        os.fsync(file.fileno())

    logger.info(
        "finalized minute=%s open=%s high=%s low=%s close=%s",
        minute,
        candle["Open"],
        candle["High"],
        candle["Low"],
        candle["Close"],
    )

    return minute


def extract_events(
    decoded: Any,
) -> list[dict[str, Any]]:
    if isinstance(
        decoded,
        list,
    ):
        return [
            item
            for item in decoded
            if isinstance(
                item,
                dict,
            )
        ]

    if isinstance(
        decoded,
        dict,
    ):
        return [decoded]

    return []


def extract_sample(
    event: dict[str, Any],
) -> (
    tuple[
        int,
        float,
    ]
    | None
):
    if event.get("type") != "update":
        return None

    if event.get("topic") != topic():
        return None

    payload = event.get("payload")

    if not isinstance(
        payload,
        dict,
    ):
        return None

    symbol = (
        str(
            payload.get(
                "symbol",
                "",
            )
        )
        .strip()
        .lower()
    )

    if symbol != SYMBOL:
        return None

    timestamp_raw = payload.get("timestamp")

    if timestamp_raw is None:
        return None

    try:
        observed_ms = int(timestamp_raw)

        price = parse_price(payload)
    except (
        ValueError,
        TypeError,
        KeyError,
        ArithmeticError,
    ):
        logger.exception("invalid RTDS payload")

        return None

    if price <= 0.0:
        return None

    return (
        observed_ms,
        price,
    )


def new_candle(
    minute_start: int,
    price: float,
    observed_ms: int,
) -> dict[str, float | int]:
    return {
        "Timestamp": (minute_start),
        "Open": price,
        "High": price,
        "Low": price,
        "Close": price,
        "_first_ms": (observed_ms),
        "_last_ms": (observed_ms),
    }


def update_candle(
    candle: dict[str, float | int],
    price: float,
    observed_ms: int,
) -> None:
    candle["High"] = max(
        float(candle["High"]),
        price,
    )

    candle["Low"] = min(
        float(candle["Low"]),
        price,
    )

    # RTDS events are expected in temporal
    # order, but use the source timestamp
    # explicitly for Open/Close semantics.
    if observed_ms < int(candle["_first_ms"]):
        candle["_first_ms"] = observed_ms

        candle["Open"] = price

    if observed_ms >= int(candle["_last_ms"]):
        candle["_last_ms"] = observed_ms

        candle["Close"] = price


def run_connection(
    last_written_minute: int | None,
) -> int | None:
    logger.info(
        "connecting url=%s topic=%s symbol=%s",
        WS_URL,
        topic(),
        SYMBOL,
    )

    ws = websocket.create_connection(
        WS_URL,
        timeout=10,
    )

    try:
        ws.send(subscription_frame())

        logger.info("RTDS subscription active")

        current_candle = None

        last_valid_receive_monotonic = time.monotonic()

        while True:
            try:
                raw_message = ws.recv()
            except websocket.WebSocketTimeoutException:
                age = time.monotonic() - last_valid_receive_monotonic

                if age >= STALE_RECONNECT_SECONDS:
                    raise RuntimeError(f"RTDS feed stale for {age:.1f}s")

                continue

            if not raw_message:
                continue

            try:
                decoded = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning("received non-JSON RTDS message")

                continue

            for event in extract_events(decoded):
                sample = extract_sample(event)

                if sample is None:
                    continue

                observed_ms, price = sample

                last_valid_receive_monotonic = time.monotonic()

                source_seconds = observed_ms // 1000

                minute_start = source_seconds // 60 * 60

                if (
                    last_written_minute is not None
                    and minute_start <= last_written_minute
                ):
                    continue

                if current_candle is None:
                    current_candle = new_candle(
                        minute_start,
                        price,
                        observed_ms,
                    )

                    logger.info(
                        "started minute=%s",
                        minute_start,
                    )

                    continue

                current_minute = int(current_candle["Timestamp"])

                if minute_start == current_minute:
                    update_candle(
                        current_candle,
                        price,
                        observed_ms,
                    )

                    continue

                if minute_start < current_minute:
                    logger.warning(
                        "discard out-of-order old event "
                        "event_minute=%s "
                        "current_minute=%s",
                        minute_start,
                        current_minute,
                    )

                    continue

                # We have observed a later minute.
                # Therefore the current minute is
                # complete and may now be persisted.
                last_written_minute = append_completed_candle(
                    current_candle,
                    last_written_minute,
                )

                # If one or more entire minutes were
                # missed, do NOT synthesize candles.
                if minute_start > current_minute + 60:
                    missing = (minute_start - current_minute) // 60 - 1

                    logger.warning(
                        "minute gap detected previous=%s next=%s missing_minutes=%s",
                        current_minute,
                        minute_start,
                        missing,
                    )

                current_candle = new_candle(
                    minute_start,
                    price,
                    observed_ms,
                )

                logger.info(
                    "started minute=%s",
                    minute_start,
                )

    finally:
        try:
            ws.close()
        except Exception:
            pass

    return last_written_minute


def main() -> None:
    ensure_output_file()

    last_written_minute = load_last_written_minute()

    logger.info(
        "collector starting output=%s last_written_minute=%s",
        OUTPUT_FILE,
        last_written_minute,
    )

    while True:
        try:
            last_written_minute = run_connection(last_written_minute)

        except KeyboardInterrupt:
            logger.info("collector stopped")

            return

        except Exception:
            logger.exception("collector connection failed")

        logger.info(
            "reconnecting in %.1fs",
            RECONNECT_SECONDS,
        )

        time.sleep(RECONNECT_SECONDS)


if __name__ == "__main__":
    main()
