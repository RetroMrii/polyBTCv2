from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
import websocket
from py_clob_client.client import ClobClient


LOG = logging.getLogger("polybtc.local_collector")

WS_URL = "wss://ws-live-data.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

TOPIC = "crypto_prices_twap_sixty"
SYMBOL = "btc/usd"
VERSION = "polybtc_vnext_local_v1"

COLUMNS = (
    "observed_at",
    "market_id",
    "question",
    "btc_price",
    "strike",
    "seconds_to_expiry",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "yes_bid_size",
    "yes_ask_size",
    "no_bid_size",
    "no_ask_size",
    "yes_token_id",
    "no_token_id",
    "momentum_60s",
    "volatility_60s",
    "reference_timestamp",
    "reference_age_ms",
    "reference_latency_ms",
    "yes_book_timestamp",
    "yes_book_age_ms",
    "yes_book_latency_ms",
    "no_book_timestamp",
    "no_book_age_ms",
    "no_book_latency_ms",
    "yes_tick_size",
    "yes_min_order_size",
    "no_tick_size",
    "no_min_order_size",
    "snapshot_build_latency_ms",
    "market_end_at",
    "collector_version",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


from polybtc.data.market_values_vnext import (timestamp_seconds, source_age_ms, parse_list, field, number, best_bid_ask)


class ReferenceFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._samples = deque()
        self._connected = False
        self._last_valid_monotonic = None

    def ingest(self, event: Any) -> None:
        if isinstance(event, list):
            for item in event:
                self.ingest(item)
            return

        if not isinstance(event, dict):
            return

        if event.get("type") != "update":
            return

        if event.get("topic") not in (
            TOPIC,
            "prices.crypto.chainlink.twap",
        ):
            return

        payload = event.get("payload")
        if not isinstance(payload, dict):
            return

        if str(payload.get("symbol", "")).lower() != SYMBOL:
            return

        raw_window = payload.get(
            "window_s",
            payload.get(
                "windowSeconds",
                payload.get("window_seconds"),
            ),
        )

        if raw_window is not None:
            try:
                if int(raw_window) != 60:
                    return
            except (ValueError, TypeError):
                return
        elif event["topic"] != TOPIC:
            return

        try:
            observed_ms = int(payload["timestamp"])
            if "full_accuracy_value" in payload:
                value = float(
                    Decimal(str(payload["full_accuracy_value"])) / Decimal(10**18)
                )
            else:
                value = number(payload["value"])

            if not math.isfinite(value) or value <= 0:
                return

            observed_ts = observed_ms / 1000.0

            # Reject impossible future observations.
            if observed_ts > time.time() + 5:
                return

            sample = {
                "observed_ms": observed_ms,
                "observed_ts": observed_ts,
                "value": value,
                "evidence": json.loads(json.dumps(event)),
            }
        except (
            KeyError,
            ValueError,
            TypeError,
            OverflowError,
            ArithmeticError,
        ):
            return

        with self._lock:
            if self._samples and observed_ms < self._samples[-1]["observed_ms"]:
                # Never let out-of-order updates move
                # the latest observation backwards.
                return

            if self._samples and observed_ms == self._samples[-1]["observed_ms"]:
                self._samples[-1] = sample
            else:
                self._samples.append(sample)

            cutoff = observed_ts - 1200
            while self._samples and self._samples[0]["observed_ts"] < cutoff:
                self._samples.popleft()

            self._last_valid_monotonic = time.monotonic()

    def samples(self) -> list[dict]:
        with self._lock:
            return list(self._samples)

    def latest(self) -> dict | None:
        samples = self.samples()
        if not samples:
            return None

        latest = samples[-1]
        age = time.time() - latest["observed_ts"]

        if age < -5 or age > 5:
            return None

        return latest

    def near(
        self,
        target: float,
        max_skew: float = 5.0,
    ) -> dict | None:
        samples = self.samples()
        if not samples:
            return None

        selected = min(
            samples,
            key=lambda s: abs(s["observed_ts"] - target),
        )

        if abs(selected["observed_ts"] - target) > max_skew:
            return None

        return selected

    def features(self, latest: dict) -> tuple | None:
        target = latest["observed_ts"] - 60.0
        samples = self.samples()

        if not samples:
            return None

        anchor = min(
            samples,
            key=lambda s: abs(s["observed_ts"] - target),
        )

        if abs(anchor["observed_ts"] - target) > 8:
            return None

        if anchor["value"] <= 0:
            return None

        momentum = (latest["value"] - anchor["value"]) / anchor["value"]

        window = [
            s for s in samples if target <= s["observed_ts"] <= latest["observed_ts"]
        ]

        unique = {}
        for sample in window:
            unique.setdefault(sample["observed_ms"], sample)

        ordered = [unique[key] for key in sorted(unique)]

        if len(ordered) < 3:
            return None

        returns = [
            (curr["value"] - prev["value"]) / prev["value"]
            for prev, curr in zip(ordered, ordered[1:])
            if prev["value"] > 0
        ]

        if len(returns) < 2:
            return None

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)

        return momentum, math.sqrt(variance)

    def run(self, stop: threading.Event) -> None:
        filters = json.dumps(
            {"symbol": SYMBOL},
            separators=(",", ":"),
        )
        subscription = json.dumps(
            {
                "action": "subscribe",
                "subscriptions": [
                    {
                        "topic": TOPIC,
                        "type": "update",
                        "filters": filters,
                    }
                ],
            },
            separators=(",", ":"),
        )

        while not stop.is_set():
            ws = None
            try:
                ws = websocket.create_connection(
                    WS_URL,
                    timeout=10,
                )
                ws.settimeout(1)
                ws.send(subscription)

                with self._lock:
                    self._connected = True

                LOG.info("RTDS connected")

                last_ping = 0.0
                connected_at = time.monotonic()

                while not stop.is_set():
                    now_mono = time.monotonic()

                    if now_mono - last_ping >= 5:
                        ws.send("PING")
                        last_ping = now_mono

                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        with self._lock:
                            valid = self._last_valid_monotonic

                        freshness_base = (
                            valid
                            if valid is not None and valid >= connected_at
                            else connected_at
                        )

                        if now_mono - freshness_base >= 15:
                            raise RuntimeError("RTDS stream stale")
                        continue

                    if raw is None:
                        raise RuntimeError("RTDS disconnected")

                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")

                    if raw in ("PING", "PONG"):
                        continue

                    try:
                        self.ingest(json.loads(raw))
                    except json.JSONDecodeError:
                        continue

            except Exception as exc:
                LOG.warning("RTDS reconnect: %s", exc)
                stop.wait(2)
            finally:
                with self._lock:
                    self._connected = False
                if ws is not None:
                    ws.close()


class PolyBoltFeed(ReferenceFeed):
    """Read-only reference transport; explicit CLOB API credentials, no wallet."""
    def __init__(self, credentials):
        super().__init__()
        if set(credentials) != {'apiKey','secret','passphrase'} or not all(credentials.values()):
            raise ValueError('PolyBolt requires existing CLOB API credentials')
        self._credentials=dict(credentials)
        self._sequence=None

    def ingest(self,event):
        if not isinstance(event,dict) or event.get('channel')!='price.crypto.twap': return
        if event.get('v') != 1 or type(event.get('seq')) is not int: raise ValueError('Invalid PolyBolt frame')
        sequence=event['seq']
        if event.get('dropped',0) or (self._sequence is not None and sequence != self._sequence+1):
            with self._lock: self._samples.clear()
            raise ValueError('PolyBolt sequence gap')
        self._sequence=sequence
        payload=event['payload']
        if payload.get('symbol')!='btcusd' or payload.get('window_seconds') != 60 or payload.get('source','').lower()!='chainlink':
            raise ValueError('Unexpected PolyBolt reference')
        points=payload['data'] if event.get('snapshot') is True else [payload]
        for point in points:
            from polybtc.shadow.acquisition_evidence import reference
            normalized=dict(event,payload=dict(payload,**point))
            normalized['payload'].pop('data',None)
            if event.get('snapshot') is True:
                normalized['wire_snapshot']=event
            value,at=reference(normalized)
            legacy=dict(type='update',topic=TOPIC,payload=dict(symbol=SYMBOL,window_s=60,
                value=value,timestamp=int(at.timestamp()*1000)))
            super().ingest(legacy)
            with self._lock:
                if self._samples and self._samples[-1]['observed_ms']==int(at.timestamp()*1000):
                    self._samples[-1]['evidence']=normalized

    def run(self,stop):
        while not stop.is_set():
            ws=None
            try:
                with self._lock:
                    self._samples.clear()
                    self._sequence=None
                ws=websocket.create_connection('wss://ws-live-v2.polymarket.com/ws',timeout=10)
                ws.send(json.dumps(dict(op='auth',rid='auth',auth=self._credentials)))
                reply=json.loads(ws.recv())
                if reply.get('op')!='authed' or reply.get('rid')!='auth':
                    raise ValueError('Authentication failed')
                ws.send(json.dumps(dict(op='subscribe',rid='twap',subscriptions=[dict(
                    channel='price.crypto.twap',filter=dict(symbol='btcusd',window_seconds=60,provider='chainlink'))])))
                ws.settimeout(1)
                connected=time.monotonic()
                with self._lock: self._connected=True
                while not stop.is_set():
                    try:
                        raw=ws.recv()
                        if not raw: raise ValueError('Reference disconnected')
                        event=json.loads(raw)
                        if event.get('op')=='error': raise ValueError('Reference subscription failed')
                        self.ingest(event)
                    except websocket.WebSocketTimeoutException:
                        if time.monotonic()-max(connected,self._last_valid_monotonic or connected)>15:
                            raise ValueError('Reference stale')
            except Exception:
                # Never include authentication responses, frames or exceptions.
                LOG.warning('PolyBolt disconnected or invalid; retrying read-only feed')
                stop.wait(2)
            finally:
                with self._lock: self._connected=False
                if ws is not None: ws.close()


class MarketCollector:
    def __init__(self, feed: ReferenceFeed):
        self.feed = feed
        self.session = requests.Session()
        self.clob = ClobClient(CLOB_URL)
        self.market_cache = {}
        self.strike_cache = {}
        self.strike_evidence = {}
        self.market_evidence = {}
        self.last_evidence = None

    def _market(self, slug: str) -> dict | None:
        cached = self.market_cache.get(slug)
        if cached is not None:
            return cached

        try:
            response = self.session.get(
                f"{GAMMA_URL}/events/slug/{slug}",
                timeout=10,
            )

            if response.status_code != 200:
                return None

            event = response.json()
            markets = event.get("markets") or []
            if not markets:
                return None

            market = markets[0]
            tokens = parse_list(market.get("clobTokenIds"))

            outcomes = parse_list(market.get("outcomes"))

            if len(tokens) != 2:
                return None

            # Fail closed if Gamma explicitly supplies
            # an unexpected YES/NO ordering.
            if outcomes:
                normalized = [str(x).strip().lower() for x in outcomes]
                if normalized not in (
                    ["up", "down"],
                    ["yes", "no"],
                ):
                    LOG.warning(
                        "Unexpected token ordering: %s",
                        normalized,
                    )
                    return None

            identity = market.get("conditionId")
            if not identity:
                return None

            result = {
                "market_id": identity,
                "question": market.get("question", ""),
                "yes_token_id": tokens[0],
                "no_token_id": tokens[1],
            }

            self.market_cache = {slug: result}
            self.market_evidence = {slug: market}
            return result

        except Exception as exc:
            LOG.warning("Gamma lookup error: %s", exc)
            return None

    def _strike(
        self,
        interval_start: int,
        now: float,
    ) -> float | None:
        if interval_start in self.strike_cache:
            return self.strike_cache[interval_start]

        # Allow all boundary-near observations
        # to arrive before freezing the strike.
        if now - interval_start < 5:
            return None

        sample = self.feed.near(
            float(interval_start),
            max_skew=5,
        )

        if sample is None:
            return None

        self.strike_cache = {interval_start: sample["value"]}
        self.strike_evidence = {interval_start: sample.get('evidence')}
        return sample["value"]

    def collect(self) -> dict | None:
        self.last_skip_reason = None
        started = time.perf_counter()
        now = time.time()
        interval_start = int(now // 300) * 300
        interval_end = interval_start + 300
        slug = f"btc-updown-5m-{interval_start}"

        ref_started = time.perf_counter()
        latest = self.feed.latest()
        ref_latency_ms = (time.perf_counter() - ref_started) * 1000

        if latest is None:
            self.last_skip_reason = "reference_unavailable"
            return None

        strike = self._strike(interval_start, now)
        if strike is None:
            self.last_skip_reason = "strike_unavailable"
            return None

        features = self.feed.features(latest)
        if features is None:
            self.last_skip_reason = "auxiliary_history_unavailable"
            return None

        market = self._market(slug)
        if market is None:
            self.last_skip_reason = "market_unavailable"
            return None

        try:
            yes_started = time.perf_counter()
            yes_book = self.clob.get_order_book(market["yes_token_id"])
            yes_latency = (time.perf_counter() - yes_started) * 1000

            no_started = time.perf_counter()
            no_book = self.clob.get_order_book(market["no_token_id"])
            no_latency = (time.perf_counter() - no_started) * 1000

            yes = best_bid_ask(yes_book)
            no = best_bid_ask(no_book)

        except Exception as exc:
            LOG.warning("CLOB book error: %s", exc)
            self.last_skip_reason = "book_request_failed"
            return None

        if any(
            x is None
            for x in (
                yes[0],
                yes[1],
                yes[2],
                yes[3],
                no[0],
                no[1],
                no[2],
                no[3],
            )
        ):
            self.last_skip_reason = "incomplete_book"
            return None

        if yes[0] > yes[1] or no[0] > no[1]:
            self.last_skip_reason = "crossed_book"
            return None

        # The websocket can advance during market discovery and the two HTTP
        # book requests. Sample it again so the published reference, features,
        # timestamp and retained evidence all describe the same latest sample.
        # This is a local cache read, never a network refresh or timestamp edit.
        ref_started = time.perf_counter()
        latest = self.feed.latest()
        ref_latency_ms = (time.perf_counter() - ref_started) * 1000
        if latest is None:
            self.last_skip_reason = "reference_unavailable_after_books"
            return None
        features = self.feed.features(latest)
        if features is None:
            self.last_skip_reason = "auxiliary_history_unavailable_after_books"
            return None

        # Source ages are calculated at the time the
        # snapshot is ready to be written, not before
        # the sequential order-book requests.
        written_at = utc_now()
        observed_ts = written_at.timestamp()

        if observed_ts >= interval_end:
            # Never attach next-market observations to
            # the previous market identifier.
            self.last_skip_reason = "interval_expired"
            return None

        yes_timestamp = field(yes_book, "timestamp")
        no_timestamp = field(no_book, "timestamp")

        yes_age = source_age_ms(yes_timestamp, now=observed_ts)
        no_age = source_age_ms(no_timestamp, now=observed_ts)

        if yes_age is None or no_age is None:
            self.last_skip_reason = "invalid_book_timestamp"
            return None

        if yes_age < -5000 or no_age < -5000:
            self.last_skip_reason = "future_book_timestamp"
            return None

        # Reference age is likewise measured against
        # current local time, not its original read time.
        ref_age = (observed_ts - latest["observed_ts"]) * 1000

        if ref_age < -5000:
            self.last_skip_reason = "future_reference_timestamp"
            return None

        momentum, volatility = features

        self.last_evidence = dict(market=self.market_evidence.get(slug),
            reference=latest.get('evidence'), strike=self.strike_evidence.get(interval_start),
            yes=asdict(yes_book) if is_dataclass(yes_book) else yes_book,
            no=asdict(no_book) if is_dataclass(no_book) else no_book)

        return {
            "observed_at": written_at.isoformat(),
            **market,
            "btc_price": latest["value"],
            "strike": strike,
            "seconds_to_expiry": max(0, interval_end - observed_ts),
            "yes_bid": yes[0],
            "yes_ask": yes[1],
            "no_bid": no[0],
            "no_ask": no[1],
            "yes_bid_size": yes[2],
            "yes_ask_size": yes[3],
            "no_bid_size": no[2],
            "no_ask_size": no[3],
            "momentum_60s": momentum,
            "volatility_60s": volatility,
            "reference_timestamp": latest["observed_ms"],
            "reference_age_ms": ref_age,
            "reference_latency_ms": ref_latency_ms,
            "yes_book_timestamp": yes_timestamp,
            "yes_book_age_ms": yes_age,
            "yes_book_latency_ms": yes_latency,
            "no_book_timestamp": no_timestamp,
            "no_book_age_ms": no_age,
            "no_book_latency_ms": no_latency,
            "yes_tick_size": field(yes_book, "tick_size"),
            "yes_min_order_size": field(yes_book, "min_order_size"),
            "no_tick_size": field(no_book, "tick_size"),
            "no_min_order_size": field(no_book, "min_order_size"),
            "snapshot_build_latency_ms": (time.perf_counter() - started) * 1000,
            "market_end_at": datetime.fromtimestamp(
                interval_end, timezone.utc
            ).isoformat(),
            "collector_version": VERSION,
        }


def append_snapshot(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    needs_header = not path.exists() or path.stat().st_size == 0

    if not needs_header:
        with path.open("r", newline="", encoding="utf-8") as existing:
            header = next(csv.reader(existing), None)

        if header != list(COLUMNS):
            raise RuntimeError(
                "Existing CSV header does not match the v1.1 telemetry contract"
            )

    # Single writer only. CSV is append-only.
    with path.open("a", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=COLUMNS,
            extrasaction="ignore",
        )

        if needs_header:
            writer.writeheader()

        writer.writerow(row)
        output.flush()
        os.fsync(output.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
    )
    parser.add_argument('--evidence-db',type=Path,help='Retain upstream evidence for paper execution')
    parser.add_argument('--reference-feed',choices=['rtds','polybolt'],default='rtds')
    parser.add_argument('--fee-cache',type=Path,help='Explicitly refresh market fees in acquisition, outside decision processing')
    parser.add_argument('--input-db',type=Path,help='Publish canonical observations and fees in one input store; CSV is optional export')
    parser.add_argument('--paper-state',type=Path,help='Consolidated paper state for background resolution discovery')
    args = parser.parse_args()
    if args.input_db:
        for supplied in (args.evidence_db,args.fee_cache):
            if supplied is not None and supplied.resolve()!=args.input_db.resolve():
                parser.error('--input-db owns evidence and fees')
        args.evidence_db=args.fee_cache=args.input_db
    elif args.paper_state:
        parser.error('--paper-state requires --input-db')
    elif args.csv is None:
        args.csv=Path('data/live/vnext_market_snapshots.csv')


    if args.interval <= 0:
        parser.error("--interval must be positive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.reference_feed=='polybolt':
        feed=PolyBoltFeed({key:os.environ.get(name,'') for key,name in (
            ('apiKey','POLYMARKET_API_KEY'),('secret','POLYMARKET_API_SECRET'),
            ('passphrase','POLYMARKET_API_PASSPHRASE'))})
    else:
        feed = ReferenceFeed()
    LOG.info("acquisition_configuration interval_seconds=%s reference_feed=%s csv=%s evidence_db=%s fee_cache=%s",
             args.interval, args.reference_feed, (args.csv.resolve() if args.csv else None),
             args.evidence_db.resolve() if args.evidence_db else None,
             args.fee_cache.resolve() if args.fee_cache else None)
    from contextlib import ExitStack
    ownership=ExitStack()
    if args.input_db:
        from polybtc.shadow.writer_lock_vnext import exclusive_lock
        ownership.enter_context(exclusive_lock(args.input_db.with_suffix('.writer.lock')))
    stop = threading.Event()

    thread = threading.Thread(
        target=feed.run,
        args=(stop,),
        daemon=True,
        name="vnext-rtds-reference",
    )
    thread.start()

    collector = MarketCollector(feed)
    evidence_store = None
    fee_cache = None
    refreshed = set()
    if args.fee_cache:
        from polybtc.data.fee_policy_cache_vnext import VNextFeePolicyCache
        fee_cache=VNextFeePolicyCache(args.fee_cache)
    if args.evidence_db:
        from polybtc.shadow.acquisition_evidence import AcquisitionEvidenceStore
        evidence_store=AcquisitionEvidenceStore(args.evidence_db,create=True,stream=bool(args.input_db))

    resolution_worker = None
    if args.paper_state:
        from polybtc.data.resolution_handoff_vnext import ResolutionWorker
        resolution_worker=ResolutionWorker(args.input_db,args.paper_state,stop)
        resolution_worker.start()

    LOG.info(
        "Local telemetry started: %s",
        (args.csv.resolve() if args.csv else None),
    )

    try:
        last_skip = None
        while True:
            try:
                if resolution_worker is not None:
                    resolution_worker.drain()
                row = collector.collect()
                if row is None and collector.last_skip_reason != last_skip:
                    last_skip = collector.last_skip_reason
                    LOG.info("acquisition_wait reason=%s", last_skip)
                elif row is not None:
                    last_skip = None

                if row is not None:
                    if fee_cache is not None and row['market_id'] not in refreshed:
                        try:
                            fee_cache.refresh(row['market_id'])
                            refreshed={row['market_id']}
                        except Exception:
                            LOG.warning('Fee refresh failed; no verified paper entry for this market')
                            stop.wait(30)
                        # Metadata latency must not be represented as a fresh quote.
                        stop.wait(args.interval)
                        continue
                    if evidence_store is not None:
                        from types import SimpleNamespace
                        from polybtc.shadow.converter_vnext import convert_v1_tail_row
                        values={k: row.get(k) if row.get(k) is not None else '' for k in COLUMNS}
                        snapshot=convert_v1_tail_row(SimpleNamespace(row_id='',values=values),source_file=args.csv.name if args.csv else None)
                        # Commit before publishing the corresponding CSV row.
                        evidence_store.record(snapshot,collector.last_evidence,utc_now())
                    if args.csv is not None:
                        append_snapshot(args.csv, row)
                    published_at = utc_now()
                    LOG.info("publication observed_at=%s published_at=%s delay_ms=%.3f",
                             row["observed_at"], published_at.isoformat(),
                             (published_at - datetime.fromisoformat(row["observed_at"])).total_seconds()*1000)
                    LOG.info(
                        "snapshot market=%s expiry=%.1fs "
                        "ref_age=%.0fms yes_age=%.0fms "
                        "no_age=%.0fms",
                        row["market_id"],
                        row["seconds_to_expiry"],
                        row["reference_age_ms"],
                        row["yes_book_age_ms"],
                        row["no_book_age_ms"],
                    )

            except OSError:
                LOG.exception("CSV write failure; stopping collector")
                raise
            except RuntimeError:
                LOG.exception("Collector invariant failure; stopping")
                raise

            stop.wait(args.interval)
    except KeyboardInterrupt:
        LOG.info("Collector interrupted")
    finally:
        stop.set()
        thread.join(timeout=3)
        if resolution_worker is not None:
            resolution_worker.join(timeout=3)
        if evidence_store is not None:
            evidence_store.close()
        ownership.close()


if __name__ == "__main__":
    main()
