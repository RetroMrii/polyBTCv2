import csv
import time

import pytest

from scripts.operations.collect_vnext_local import (
    COLUMNS,
    ReferenceFeed,
    append_snapshot,
    best_bid_ask,
    source_age_ms,
    timestamp_seconds,
)


def test_timestamp_seconds_and_milliseconds():
    assert timestamp_seconds(1_790_000_000) == 1_790_000_000

    assert timestamp_seconds(1_790_000_000_000) == 1_790_000_000


def test_reference_age():
    assert source_age_ms(
        1_790_000_000_000,
        now=1_790_000_000.25,
    ) == pytest.approx(250)


def test_order_book_selects_true_best_prices():
    book = {
        "bids": [
            {"price": "0.30", "size": "8"},
            {"price": "0.45", "size": "3"},
        ],
        "asks": [
            {"price": "0.70", "size": "2"},
            {"price": "0.60", "size": "5"},
        ],
    }

    assert best_bid_ask(book) == (0.45, 0.60, 3.0, 5.0)


def test_reference_feed_rejects_wrong_topic():
    feed = ReferenceFeed()

    feed.ingest(
        {
            "type": "update",
            "topic": "unrelated",
            "payload": {
                "symbol": "btc/usd",
                "timestamp": int(time.time() * 1000),
                "value": 60000,
            },
        }
    )

    assert feed.samples() == []


def test_reference_feed_retains_source_timestamp():
    feed = ReferenceFeed()
    now_ms = int(time.time() * 1000)

    feed.ingest(
        {
            "type": "update",
            "topic": "crypto_prices_twap_sixty",
            "payload": {
                "symbol": "btc/usd",
                "window_s": 60,
                "timestamp": now_ms,
                "value": "60000",
            },
        }
    )

    assert feed.latest()["observed_ms"] == now_ms
    assert feed.latest()["value"] == 60000


def test_csv_exact_header(tmp_path):
    path = tmp_path / "snapshots.csv"

    row = {name: "" for name in COLUMNS}
    row["observed_at"] = "2026-10-09T15:04:00+00:00"

    append_snapshot(path, row)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(COLUMNS)
        assert len(list(reader)) == 1


def test_csv_wrong_header_rejected(tmp_path):
    path = tmp_path / "snapshots.csv"
    path.write_text(
        "wrong,header\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="header"):
        append_snapshot(
            path,
            {name: "" for name in COLUMNS},
        )


@pytest.mark.parametrize("refresh_available,features_available", [(True, True), (False, True), (True, False)])
def test_collector_refreshes_reference_after_books_without_network(monkeypatch, refresh_available, features_available):
    from dataclasses import replace
    from datetime import timedelta
    from types import SimpleNamespace
    from unittest.mock import Mock
    import socket
    from scripts.operations import collect_vnext_local as collector
    from tests.shadow.test_paper_acquisition import upstream
    from tests.shadow.test_source_verification_vnext import snapshots
    from tests.shadow.test_stream_driver_vnext import NOW
    from polybtc.shadow.converter_vnext import convert_v1_tail_row
    from polybtc.shadow.acquisition_evidence import attest

    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('Unexpected network')))
    old = replace(snapshots()[2], reference_timestamp=NOW-timedelta(seconds=2))
    new = replace(old, reference_timestamp=NOW-timedelta(milliseconds=100), reference_price=40011.0)
    old_raw, new_raw = upstream(old), upstream(new)
    def sample(row, raw):
        return dict(value=row.reference_price, observed_ts=row.reference_timestamp.timestamp(),
                    observed_ms=int(row.reference_timestamp.timestamp()*1000), evidence=raw['reference'])
    feed = Mock()
    feed.latest.side_effect = [sample(old, old_raw), sample(new, new_raw) if refresh_available else None]
    feed.features.side_effect = [(0.1, 0.2), (0.3, 0.4) if features_available else None]
    worker = object.__new__(collector.MarketCollector)
    worker.feed = feed
    start = int(NOW.timestamp() // 300) * 300
    slug = 'btc-updown-5m-' + str(start)
    worker.market_evidence = {slug: new_raw['market']}
    worker.strike_evidence = {start: new_raw['strike']}
    worker._strike = Mock(return_value=new.strike)
    worker._market = Mock(return_value=dict(market_id=new.condition_id, yes_token_id='101', no_token_id='202'))
    worker.clob = Mock()
    worker.clob.get_order_book.side_effect = [new_raw['yes'], new_raw['no']]
    monkeypatch.setattr(collector.time, 'time', lambda: NOW.timestamp())
    monkeypatch.setattr(collector, 'utc_now', lambda: NOW)
    result = worker.collect()
    assert feed.latest.call_count == 2
    assert worker.clob.get_order_book.call_count == 2
    if not refresh_available or not features_available:
        assert result is None
        return
    assert result['btc_price'] == new.reference_price
    assert result['reference_timestamp'] == int(new.reference_timestamp.timestamp()*1000)
    assert result['reference_age_ms'] == pytest.approx(100, abs=0.001)
    assert result['momentum_60s'] == 0.3 and result['volatility_60s'] == 0.4
    values = {k: '' if result.get(k) is None else str(result[k]) for k in collector.COLUMNS}
    row = convert_v1_tail_row(SimpleNamespace(row_id='new', values=values), source_file='fixture.csv')
    assert attest(row, worker.last_evidence, 'fixture', NOW).snapshot == row
