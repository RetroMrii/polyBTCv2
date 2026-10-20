from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.polymarket_metadata import fetch_market_metadata
from polybtc.data.polymarket_resolution import fetch_resolution
from polybtc.data.resolution_validation import (
    LABEL_VERSION,
    RESOLUTION_SOURCE_VERSION,
    validate_resolution,
)
from polybtc.data.schema import ResolutionValidationStatus


ROOT = Path(__file__).resolve().parents[2]

VM_FILE = ROOT / "data/raw/v1.1" / "btc_5m_market_snapshots_v1_4.csv"

P12_LABELS = ROOT / "data/shadow/p12_market_resolutions.csv"

BASE = ROOT / "data/experiments/model_expansion/vm_expansion_v2"
OUTPUT = BASE / "verified_resolutions.csv"
REPORT = BASE / "resolution_sync_report.json"

FIELDS = (
    "condition_id",
    "label_yes",
    "resolved_at",
    "winning_token_id",
    "resolution_source",
    "resolution_source_version",
    "label_version",
    "evidence_id",
)


def now_utc():
    return datetime.now(timezone.utc)


def parse_time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-naive timestamp")
    return result.astimezone(timezone.utc)


def load_existing_labels():
    """
    Existing historical labels remain read-only.
    Only already VALID labels suppress a new fetch.
    """
    known = set()

    with P12_LABELS.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            market = (row.get("condition_id") or "").strip().lower()

            if (
                market
                and row.get("validation_status", "").strip()
                == ResolutionValidationStatus.VALID.value
                and row.get("label_yes", "").strip() in ("0", "1")
            ):
                known.add(market)

    return known


def load_vm_markets():
    """
    Discover unique markets and their scheduled
    expiration time, without loading all snapshots.
    """
    markets = {}

    with VM_FILE.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)

        required = {"market_id", "market_end_at"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"Missing VM columns: {sorted(missing)}")

        for row in reader:
            market = (row.get("market_id") or "").strip().lower()

            if not market:
                raise ValueError("Empty VM market ID")

            end = parse_time(row["market_end_at"])

            previous = markets.get(market)
            if previous is not None and previous != end:
                raise ValueError(f"Conflicting expiry for {market}")

            markets[market] = end

    return markets


def evidence_id(label):
    payload = {
        "condition_id": label.condition_id.strip().lower(),
        "label_yes": label.label_yes,
        "winning_token_id": label.winning_token_id,
        "resolved_at": label.resolved_at.isoformat(),
        "resolution_source_version": RESOLUTION_SOURCE_VERSION,
        "label_version": LABEL_VERSION,
    }

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def load_output_registry():
    known = {}

    if not OUTPUT.exists():
        return known

    with OUTPUT.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)

        if tuple(reader.fieldnames or ()) != FIELDS:
            raise RuntimeError("Existing output registry schema mismatch")

        for row in reader:
            market = row["condition_id"].strip().lower()

            if market in known:
                if known[market] != row:
                    raise RuntimeError(f"Conflicting output labels: {market}")
                raise RuntimeError(f"Duplicate output label: {market}")

            if row["label_yes"] not in ("0", "1"):
                raise RuntimeError(f"Invalid output label: {market}")

            known[market] = row

    return known


def append_verified(row):
    """
    Append one verified label. No source CSV,
    journal, ledger or model is modified.
    """
    BASE.mkdir(parents=True, exist_ok=True)

    needs_header = not OUTPUT.exists() or OUTPUT.stat().st_size == 0

    with OUTPUT.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)

        if needs_header:
            writer.writeheader()

        writer.writerow(row)
        handle.flush()


def sync(limit, delay, min_age_seconds):
    if limit <= 0 or delay < 0 or min_age_seconds < 0:
        raise ValueError("Invalid sync configuration")

    markets = load_vm_markets()
    historical = load_existing_labels()
    registered = load_output_registry()

    overlapping = set(registered) & historical
    if overlapping:
        raise RuntimeError(
            "Research registry overlaps existing VALID labels: "
            + str(sorted(overlapping)[:5])
        )

    extra = set(registered) - set(markets)
    if extra:
        raise RuntimeError("Registry contains markets absent from VM snapshots")

    current = now_utc()
    pending = [
        (market, end)
        for market, end in sorted(markets.items(), key=lambda item: (item[1], item[0]))
        if market not in historical and market not in registered
    ]

    counts = Counter(
        {
            "vm_markets": len(markets),
            "existing_valid_p12_labels": len(set(markets) & historical),
            "already_registered_research": len(registered),
            "pending_before_run": len(pending),
        }
    )

    attempted = 0

    for market, end in pending:
        if attempted >= limit:
            break

        if (current - end).total_seconds() < min_age_seconds:
            counts["too_recent"] += 1
            continue

        attempted += 1
        counts["checked"] += 1

        try:
            metadata = fetch_market_metadata(market)
            resolution = fetch_resolution(market)

            label = validate_resolution(
                market,
                metadata,
                resolution,
                retrieved_at=now_utc(),
            )

            if label.validation_status != ResolutionValidationStatus.VALID:
                counts["not_valid"] += 1
                counts[str(label.validation_status)] += 1
                continue

            if (
                type(label.label_yes) is not int
                or label.label_yes not in (0, 1)
                or label.resolved_at is None
                or not label.winning_token_id
            ):
                counts["incomplete_valid_label"] += 1
                continue

            resolved_at = parse_time(label.resolved_at.isoformat())

            if resolved_at > now_utc():
                counts["future_resolution"] += 1
                continue

            record = {
                "condition_id": market,
                "label_yes": str(label.label_yes),
                "resolved_at": resolved_at.isoformat(),
                "winning_token_id": str(label.winning_token_id),
                "resolution_source": str(label.resolution_source),
                "resolution_source_version": str(label.resolution_source_version),
                "label_version": LABEL_VERSION,
                "evidence_id": evidence_id(label),
            }

            append_verified(record)
            registered[market] = record
            counts["registered"] += 1

            print(
                f"VERIFIED {market} YES={label.label_yes}",
                flush=True,
            )

        except ValueError:
            # Preserve conflict and validation failures
            # rather than quietly treating them as NO.
            logging.exception("Validation conflict: %s", market)
            raise

        except Exception:
            counts["provider_errors"] += 1
            logging.exception("Provider failure: %s", market)

        finally:
            if delay:
                time.sleep(delay)

    counts["remaining_unregistered"] = len(pending) - counts["registered"]

    result = dict(sorted(counts.items()))

    BASE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return result


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--min-age-seconds", type=float, default=120)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(
        json.dumps(
            sync(args.limit, args.delay, args.min_age_seconds),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
