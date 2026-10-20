from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/experiments/model_expansion"
RESEARCH = BASE / "vm_expansion_v2"

OLD_DATASET = BASE / "hgb3_expanded_v1.csv"
NEW_LABELS = RESEARCH / "verified_resolutions.csv"
VM_SNAPSHOTS = ROOT / "data/raw/v1.1/btc_5m_market_snapshots_v1_4.csv"

OUTPUT = RESEARCH / "hgb3_expanded_v2.csv"
REPORT = RESEARCH / "hgb3_expanded_v2_report.json"

DATASET_VERSION = "hgb3_expanded_v2"
FEATURE_VERSION = "hgb3_three_feature_v1"
HORIZONS = (240, 180, 120, 90, 60, 30)


def load_p4_module():
    path = ROOT / "scripts/research/build_p4_extension_from_p12.py"
    spec = importlib.util.spec_from_file_location("p4_extension", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def load_verified_labels():
    labels = {}

    with NEW_LABELS.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            market = row["condition_id"].strip().lower()
            label = row["label_yes"].strip()

            if not market or label not in ("0", "1"):
                raise ValueError("Invalid research label")

            if (
                not row.get("evidence_id")
                or not row.get("winning_token_id")
                or not row.get("resolved_at")
            ):
                raise ValueError(f"Incomplete resolution evidence: {market}")

            if row["label_version"] != "p3_v1":
                raise ValueError(f"Unexpected label version: {market}")

            if market in labels:
                raise ValueError(f"Duplicate verified research label: {market}")

            labels[market] = int(label)

    return labels


def load_existing_dataset():
    with OLD_DATASET.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    if not rows:
        raise ValueError("Existing dataset is empty")

    if len(fields) != len(set(fields)):
        raise ValueError("Duplicate dataset columns")

    required = {
        "condition_id",
        "prediction_timestamp",
        "snapshot_observed_at",
        "target_horizon_seconds",
        "relative_distance_from_strike",
        "reference_return_30s",
        "label_yes",
        "label_version",
        "normalized_yes_mid",
        "source_dataset",
        "reference_provider_status",
        "feature_version",
        "dataset_version",
    }

    if set(fields) != required:
        raise ValueError("Unexpected HGB3 dataset schema")

    keys = set()
    markets = set()

    for row in rows:
        market = row["condition_id"].strip().lower()
        horizon = int(row["target_horizon_seconds"])
        key = (market, horizon)

        if key in keys:
            raise ValueError(f"Duplicate existing key: {key}")

        keys.add(key)
        markets.add(market)

    return fields, rows, keys, markets


def build():
    p4 = load_p4_module()

    fields, existing, keys, existing_markets = load_existing_dataset()
    labels = load_verified_labels()

    if set(labels) & existing_markets:
        raise ValueError("New research labels overlap existing HGB3 markets")

    # Reuse original P4 parsing and selection rules.
    # Only redirect the source file in the imported module.
    p4.SNAPSHOT_FILE = VM_SNAPSHOTS
    snapshots = p4.load_snapshots()

    stats = Counter()
    added = []
    added_markets = set()

    for market, label in sorted(labels.items()):
        market_rows = snapshots.get(market)

        if not market_rows:
            stats["missing_market_snapshots"] += 1
            continue

        market_ends = {row["market_end_at"] for row in market_rows}

        if len(market_ends) != 1:
            raise ValueError(f"Conflicting market expiration: {market}")

        market_end = next(iter(market_ends))
        epochs = [row["observed_epoch"] for row in market_rows]

        for horizon in HORIZONS:
            stats["candidate_horizons"] += 1
            target = market_end - timedelta(seconds=horizon)

            snapshot, lag = p4.find_latest_snapshot(market_rows, epochs, target)

            if snapshot is None:
                stats["missing_snapshot"] += 1
                continue

            if lag is None or lag < 0 or lag > p4.MAX_HORIZON_LAG_SECONDS:
                stats["stale_snapshot"] += 1
                continue

            return_30 = p4.reference_return(market_rows, epochs, snapshot, 30)

            if return_30 is None:
                stats["missing_return_30s"] += 1
                continue

            relative_distance = (
                snapshot["reference_price"] - snapshot["strike"]
            ) / snapshot["strike"]

            if not all(
                math.isfinite(value) for value in (relative_distance, return_30)
            ):
                stats["nonfinite_feature"] += 1
                continue

            _, _, market_probability = p4.market_probability_fields(snapshot)

            key = (market, horizon)

            if key in keys:
                raise ValueError(f"Duplicate expanded dataset key: {key}")

            keys.add(key)
            added_markets.add(market)

            added.append(
                {
                    "condition_id": market,
                    "prediction_timestamp": target.isoformat(),
                    "snapshot_observed_at": snapshot["observed_at"].isoformat(),
                    "target_horizon_seconds": str(horizon),
                    "relative_distance_from_strike": format(relative_distance, ".17g"),
                    "reference_return_30s": format(return_30, ".17g"),
                    "label_yes": str(label),
                    "label_version": "p3_v1",
                    "normalized_yes_mid": (
                        ""
                        if market_probability is None
                        else format(market_probability, ".17g")
                    ),
                    "source_dataset": "vm_expansion_v2",
                    "reference_provider_status": "RTDS",
                    "feature_version": FEATURE_VERSION,
                    "dataset_version": DATASET_VERSION,
                }
            )

    # Preserve original records; only new records carry
    # the new source and dataset version.
    all_rows = existing + added

    stats["existing_rows"] = len(existing)
    stats["added_rows"] = len(added)
    stats["total_rows"] = len(all_rows)
    stats["existing_markets"] = len(existing_markets)
    stats["new_markets_with_features"] = len(added_markets)
    stats["total_markets"] = len(existing_markets | added_markets)
    stats["research_labels"] = len(labels)
    stats["research_markets_without_eligible_features"] = len(labels) - len(
        added_markets
    )

    if not added:
        raise RuntimeError("No new eligible training records")

    # Fail rather than overwrite an existing candidate.
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("v2 dataset or report already exists")

    RESEARCH.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    report = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            "existing_hgb3_dataset": sha256(OLD_DATASET),
            "vm_snapshots": sha256(VM_SNAPSHOTS),
            "verified_research_labels": sha256(NEW_LABELS),
        },
        "statistics": dict(sorted(stats.items())),
        "training_warning": (
            "This dataset includes markets previously "
            "used in research evaluations. Do not reuse "
            "those markets as independent test data."
        ),
        "ohlc_used": False,
    }

    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    build()
