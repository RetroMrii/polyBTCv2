from datetime import datetime, timezone

import pytest

from polybtc.shadow.converter_vnext import (
    convert_v1_tail_row,
)
from polybtc.shadow.csv_tail_vnext import TailRow


def source_row():
    fields = {
        "observed_at": "2026-10-09T12:00:00Z",
        "market_id": "MARKET-A",
        "btc_price": "40010",
        "strike": "40000",
        "seconds_to_expiry": "60",
        "market_end_at": "2026-10-09T12:01:00Z",
        "yes_bid": "0.65",
        "yes_ask": "0.66",
        "no_bid": "0.34",
        "no_ask": "0.35",
        "yes_bid_size": "12",
        "yes_ask_size": "10",
        "no_bid_size": "12",
        "no_ask_size": "10",
        "yes_token_id": "yes-token",
        "no_token_id": "no-token",
        "reference_timestamp": "1791547200000",
        "reference_age_ms": "50",
        "reference_latency_ms": "0.05",
        "yes_book_timestamp": "1791547200000",
        "yes_book_age_ms": "40",
        "yes_book_latency_ms": "120",
        "no_book_timestamp": "1791547200000",
        "no_book_age_ms": "45",
        "no_book_latency_ms": "130",
        "yes_tick_size": "0.01",
        "yes_min_order_size": "5",
        "no_tick_size": "0.01",
        "no_min_order_size": "5",
        "snapshot_build_latency_ms": "270",
        "collector_version": "v1.1",
    }

    return TailRow(
        row_id="stable-tail-row-id",
        source_line_offset=100,
        values=fields,
    )


def convert(row):
    return convert_v1_tail_row(
        row,
        source_file="production.csv",
    )


def test_production_mapping():
    snapshot = convert(source_row())

    assert snapshot.snapshot_id == "stable-tail-row-id"
    assert snapshot.condition_id == "market-a"
    assert snapshot.reference_price == 40010.0
    assert snapshot.yes_ask == 0.66
    assert snapshot.no_ask == 0.35
    assert snapshot.yes_min_order_size == 5
    assert snapshot.source_file == "production.csv"
    assert snapshot.source_row_number is None


def test_millisecond_timestamp():
    snapshot = convert(source_row())

    assert snapshot.reference_timestamp == (
        datetime.fromtimestamp(
            1791547200,
            tz=timezone.utc,
        )
    )


def test_second_timestamp():
    row = source_row()
    row.values["reference_timestamp"] = "1791547200"

    snapshot = convert(row)

    assert snapshot.reference_timestamp == (
        datetime.fromtimestamp(
            1791547200,
            tz=timezone.utc,
        )
    )


def test_iso_timestamp():
    row = source_row()
    row.values["reference_timestamp"] = "2026-10-09T12:00:00Z"

    snapshot = convert(row)

    assert snapshot.reference_timestamp == (
        datetime(
            2026,
            10,
            9,
            12,
            tzinfo=timezone.utc,
        )
    )


def test_blank_book_timestamp_preserved():
    row = source_row()
    row.values["yes_book_timestamp"] = ""

    snapshot = convert(row)

    assert snapshot.yes_book_timestamp is None


def test_missing_required_column_rejected():
    row = source_row()
    del row.values["yes_book_timestamp"]

    with pytest.raises(ValueError, match="columns"):
        convert(row)


def test_nonfinite_value_rejected():
    row = source_row()
    row.values["yes_ask"] = "nan"

    with pytest.raises(ValueError, match="Nonfinite"):
        convert(row)


def test_stable_snapshot_identity():
    row = source_row()

    first = convert(row)
    second = convert(row)

    assert first.snapshot_id == second.snapshot_id
