from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "experiments" / "model_expansion"

HISTORICAL = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"
PROSPECTIVE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p13_prospective_supervised.csv"
)

OUTPUT = BASE / "hgb3_expanded_v1.csv"
REPORT = BASE / "hgb3_expanded_v1_report.json"

DATASET_VERSION = "hgb3_expanded_v1"
FEATURE_VERSION = "hgb3_three_feature_v1"
HORIZONS = {240, 180, 120, 90, 60, 30}

FEATURES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

FIELDS = (
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
)

SOURCES = (
    ("historical_v1_1", HISTORICAL),
    ("prospective_p13", PROSPECTIVE),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp is not timezone-aware")
    return result.astimezone(timezone.utc)


def finite_number(value: str) -> float:
    number = float(value.strip())
    if not math.isfinite(number):
        raise ValueError("Nonfinite number")
    return number


def optional_probability(value: str | None) -> str:
    if value is None or not value.strip():
        return ""

    try:
        probability = finite_number(value)
    except ValueError:
        return ""

    if not 0.0 <= probability <= 1.0:
        return ""

    return format(probability, ".17g")


def is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def load_source(
    source_name: str,
    path: Path,
) -> tuple[list[dict], dict]:
    if not path.is_file():
        raise FileNotFoundError(path)

    output = []
    excluded = Counter()
    market_labels = {}
    raw_markets = set()
    seen_keys = set()

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        header = set(reader.fieldnames or [])

        required = {
            "condition_id",
            "prediction_timestamp",
            "snapshot_observed_at",
            "target_horizon_seconds",
            "relative_distance_from_strike",
            "reference_return_30s",
            "label_yes",
        }
        missing = required - header
        if missing:
            raise RuntimeError(f"{source_name}: missing columns {sorted(missing)}")

        if (
            source_name == "prospective_p13"
            and "reference_return_30s_complete" not in header
        ):
            raise RuntimeError("Prospective completeness flag missing")

        row_count = 0

        for line_number, raw in enumerate(reader, 2):
            row_count += 1
            market_id = (raw.get("condition_id") or "").strip().lower()

            if not market_id:
                raise RuntimeError(f"{source_name}:{line_number}: empty market ID")

            raw_markets.add(market_id)

            try:
                label = int(raw["label_yes"].strip())
            except (ValueError, AttributeError):
                raise RuntimeError(f"{source_name}:{line_number}: invalid label")

            if label not in (0, 1):
                raise RuntimeError(f"{source_name}:{line_number}: nonbinary label")

            prior = market_labels.setdefault(market_id, label)
            if prior != label:
                raise RuntimeError(f"{source_name}: conflicting label for {market_id}")

            try:
                horizon = int(raw["target_horizon_seconds"].strip())
            except (ValueError, AttributeError):
                excluded["invalid_horizon"] += 1
                continue

            if horizon not in HORIZONS:
                excluded["unsupported_horizon"] += 1
                continue

            key = (market_id, horizon)
            if key in seen_keys:
                raise RuntimeError(f"{source_name}: duplicate market/horizon {key}")
            seen_keys.add(key)

            try:
                prediction_time = parse_time(raw["prediction_timestamp"])
                snapshot_time = parse_time(raw["snapshot_observed_at"])
            except (ValueError, AttributeError):
                excluded["invalid_timestamp"] += 1
                continue

            if snapshot_time > prediction_time:
                raise RuntimeError(
                    f"{source_name}:{line_number}: snapshot is later than prediction"
                )

            if source_name == "prospective_p13":
                if not is_true(raw.get("reference_return_30s_complete")):
                    excluded["incomplete_reference_return"] += 1
                    continue

            elif "eligible_reference_features" in header:
                if not is_true(raw.get("eligible_reference_features")):
                    excluded["ineligible_reference_features"] += 1
                    continue

            try:
                distance = finite_number(raw["relative_distance_from_strike"])
                return_30s = finite_number(raw["reference_return_30s"])
            except (ValueError, AttributeError, TypeError):
                excluded["missing_or_nonfinite_feature"] += 1
                continue

            # A market outcome is constant across all horizons.
            # Dates are preserved to support chronological splits.
            label_version = (raw.get("label_version") or "").strip()

            output.append(
                {
                    "condition_id": market_id,
                    "prediction_timestamp": prediction_time.isoformat(),
                    "snapshot_observed_at": snapshot_time.isoformat(),
                    "target_horizon_seconds": horizon,
                    "relative_distance_from_strike": format(distance, ".17g"),
                    "reference_return_30s": format(return_30s, ".17g"),
                    "label_yes": label,
                    "label_version": label_version,
                    "normalized_yes_mid": optional_probability(
                        raw.get("normalized_yes_mid")
                    ),
                    "source_dataset": source_name,
                    "reference_provider_status": "unverified",
                    "feature_version": FEATURE_VERSION,
                    "dataset_version": DATASET_VERSION,
                }
            )

    eligible_markets = {row["condition_id"] for row in output}

    report = {
        "input_path": str(path.relative_to(ROOT)),
        "input_sha256": sha256(path),
        "input_rows": row_count,
        "input_markets": len(raw_markets),
        "eligible_rows": len(output),
        "eligible_markets": len(eligible_markets),
        "excluded_rows": dict(sorted(excluded.items())),
        "market_ids": raw_markets,
    }

    return output, report


def main() -> None:
    # Refuse to overwrite a completed version.
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError(
            "Expanded dataset version already exists. "
            "Use a new version instead of overwriting."
        )

    all_rows = []
    source_reports = {}
    source_market_ids = {}

    for name, path in SOURCES:
        rows, report = load_source(name, path)
        source_market_ids[name] = report.pop("market_ids")
        source_reports[name] = report
        all_rows.extend(rows)

    historical_ids = source_market_ids["historical_v1_1"]
    prospective_ids = source_market_ids["prospective_p13"]
    overlap = historical_ids & prospective_ids

    if overlap:
        raise RuntimeError(f"Cross-source market overlap: {len(overlap)}")

    if not all_rows:
        raise RuntimeError("No eligible training rows")

    all_rows.sort(
        key=lambda row: (
            row["prediction_timestamp"],
            row["condition_id"],
            -row["target_horizon_seconds"],
        )
    )

    seen_keys = set()
    market_labels = {}
    market_sources = defaultdict(set)
    market_times = defaultdict(list)
    day_markets = defaultdict(set)
    source_counts = Counter()
    horizon_counts = Counter()
    market_probability_rows = 0

    for row in all_rows:
        market_id = row["condition_id"]
        key = (
            market_id,
            row["target_horizon_seconds"],
        )

        if key in seen_keys:
            raise RuntimeError(f"Duplicate combined market/horizon: {key}")
        seen_keys.add(key)

        label = row["label_yes"]
        if market_id in market_labels:
            if market_labels[market_id] != label:
                raise RuntimeError(f"Conflicting label: {market_id}")
        else:
            market_labels[market_id] = label

        market_sources[market_id].add(row["source_dataset"])
        market_times[market_id].append(parse_time(row["prediction_timestamp"]))

        date = row["prediction_timestamp"][:10]
        day_markets[date].add(market_id)

        source_counts[row["source_dataset"]] += 1
        horizon_counts[str(row["target_horizon_seconds"])] += 1

        if row["normalized_yes_mid"] != "":
            market_probability_rows += 1

    if any(len(sources) != 1 for sources in market_sources.values()):
        raise RuntimeError("A market appears in multiple source datasets")

    timestamps = [parse_time(row["prediction_timestamp"]) for row in all_rows]

    report = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "features": list(FEATURES),
        "source_reports": source_reports,
        "input_market_overlap": len(overlap),
        "eligible_rows": len(all_rows),
        "eligible_markets": len(market_labels),
        "rows_by_source": dict(sorted(source_counts.items())),
        "rows_by_horizon": dict(
            sorted(
                horizon_counts.items(),
                key=lambda item: -int(item[0]),
            )
        ),
        "markets_by_date": {
            date: len(markets) for date, markets in sorted(day_markets.items())
        },
        "first_prediction_timestamp": min(timestamps).isoformat(),
        "last_prediction_timestamp": max(timestamps).isoformat(),
        "market_probability_rows": market_probability_rows,
        "market_probability_missing_rows": (len(all_rows) - market_probability_rows),
        "reference_provider_status": ("unverified_per_source"),
        "chronological_split_status": "not_split",
        "model_training_status": "not_trained",
        "calibration_status": "not_calibrated",
        "production_approved": False,
        "output_path": str(OUTPUT.relative_to(ROOT)),
    }

    BASE.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("x", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(all_rows)

    report["output_sha256"] = sha256(OUTPUT)

    with REPORT.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, sort_keys=True)
        file.write("\n")

    print("HGB3 EXPANDED DATASET COMPLETE")
    print("version=", DATASET_VERSION)
    print("eligible_rows=", len(all_rows))
    print("eligible_markets=", len(market_labels))
    print("source_rows=", dict(source_counts))
    print("market_overlap=", len(overlap))
    print("first=", report["first_prediction_timestamp"])
    print("last=", report["last_prediction_timestamp"])
    print(
        "market_probability_rows=",
        market_probability_rows,
    )
    print("sha256=", report["output_sha256"])
    print("dataset=", OUTPUT)
    print("report=", REPORT)


if __name__ == "__main__":
    main()
