from __future__ import annotations

import csv
import json

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

ORIGINAL_P4 = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

EXTENSION_P4 = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_extension_pre_block1.csv"
)

OUTPUT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_expanded_development_pre_block1.csv"
)

REPORT_FILE = (
    ROOT
    / "data"
    / "experiments"
    / "p13_model_improvement"
    / "p4_expanded_development_pre_block1_report.json"
)


BLOCK_1_START = datetime.fromisoformat("2026-10-03T20:45:00+00:00")


OUTPUT_FIELDS = (
    "condition_id",
    "target_horizon_seconds",
    "prediction_timestamp",
    "snapshot_observed_at",
    "reference_price",
    "strike",
    "distance_from_strike",
    "absolute_distance_from_strike",
    "relative_distance_from_strike",
    "reference_return_30s",
    "reference_return_60s",
    "reference_return_120s",
    "normalized_yes_mid",
    "label_yes",
    "label_version",
    "eligible_reference_features",
    "eligible_book_features",
    "source_dataset",
)


def parse_timestamp(
    value: str,
) -> datetime:
    return datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )


def clean(
    value: object,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def normalize_original(
    row: dict[str, str],
) -> dict[str, str]:
    return {
        "condition_id": clean(row.get("condition_id")).lower(),
        "target_horizon_seconds": clean(row.get("target_horizon_seconds")),
        "prediction_timestamp": clean(row.get("prediction_timestamp")),
        "snapshot_observed_at": clean(row.get("snapshot_observed_at")),
        "reference_price": clean(row.get("reference_price")),
        "strike": clean(row.get("strike")),
        "distance_from_strike": clean(row.get("distance_from_strike")),
        "absolute_distance_from_strike": clean(
            row.get("absolute_distance_from_strike")
        ),
        "relative_distance_from_strike": clean(
            row.get("relative_distance_from_strike")
        ),
        "reference_return_30s": clean(row.get("reference_return_30s")),
        "reference_return_60s": clean(row.get("reference_return_60s")),
        "reference_return_120s": clean(row.get("reference_return_120s")),
        "normalized_yes_mid": clean(row.get("normalized_yes_mid")),
        "label_yes": clean(row.get("label_yes")),
        "label_version": clean(row.get("label_version")),
        "eligible_reference_features": clean(row.get("eligible_reference_features")),
        "eligible_book_features": clean(row.get("eligible_book_features")),
        "source_dataset": ("original_p4_v1"),
    }


def normalize_extension(
    row: dict[str, str],
) -> dict[str, str]:
    return {
        "condition_id": clean(row.get("condition_id")).lower(),
        "target_horizon_seconds": clean(row.get("target_horizon_seconds")),
        "prediction_timestamp": clean(row.get("prediction_timestamp")),
        "snapshot_observed_at": clean(row.get("snapshot_observed_at")),
        "reference_price": clean(row.get("reference_price")),
        "strike": clean(row.get("strike")),
        "distance_from_strike": clean(row.get("distance_from_strike")),
        "absolute_distance_from_strike": clean(row.get("absolute_distance")),
        "relative_distance_from_strike": clean(
            row.get("relative_distance_from_strike")
        ),
        "reference_return_30s": clean(row.get("reference_return_30s")),
        "reference_return_60s": clean(row.get("reference_return_60s")),
        "reference_return_120s": clean(row.get("reference_return_120s")),
        "normalized_yes_mid": clean(row.get("normalized_yes_mid")),
        "label_yes": clean(row.get("label_yes")),
        "label_version": clean(row.get("label_version")),
        "eligible_reference_features": clean(row.get("eligible_reference_features")),
        "eligible_book_features": clean(row.get("eligible_book_features")),
        "source_dataset": ("p4_extension_pre_block1_v1"),
    }


def load_rows(
    path: Path,
    normalizer,
) -> list[dict[str, str]]:
    rows = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            normalized = normalizer(row)

            if not normalized["condition_id"]:
                continue

            if normalized["label_yes"] not in {
                "0",
                "1",
            }:
                continue

            rows.append(normalized)

    return rows


def row_key(
    row: dict[str, str],
) -> tuple[str, int]:
    return (
        row["condition_id"],
        int(float(row["target_horizon_seconds"])),
    )


def main() -> None:
    original_rows = load_rows(
        ORIGINAL_P4,
        normalize_original,
    )

    extension_rows = load_rows(
        EXTENSION_P4,
        normalize_extension,
    )

    original_markets = {row["condition_id"] for row in original_rows}

    extension_markets = {row["condition_id"] for row in extension_rows}

    market_overlap = original_markets & extension_markets

    if market_overlap:
        raise RuntimeError(
            f"original/extension market overlap detected: {len(market_overlap)}"
        )

    # Protect Block 1 and everything after it.
    for row in extension_rows:
        prediction_time = parse_timestamp(row["prediction_timestamp"])

        if prediction_time >= BLOCK_1_START:
            raise RuntimeError(
                "Block 1 leakage detected: "
                f"{row['condition_id']} "
                f"{prediction_time.isoformat()}"
            )

    combined = original_rows + extension_rows

    duplicate_keys = 0
    seen = set()

    for row in combined:
        key = row_key(row)

        if key in seen:
            duplicate_keys += 1
        else:
            seen.add(key)

    if duplicate_keys:
        raise RuntimeError(f"duplicate market/horizon keys detected: {duplicate_keys}")

    combined.sort(
        key=lambda row: (
            row["prediction_timestamp"],
            row["condition_id"],
            int(float(row["target_horizon_seconds"])),
        )
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(combined)

    combined_markets = original_markets | extension_markets

    complete_baseline_rows = 0
    complete_book_rows = 0

    for row in combined:
        if (
            row["relative_distance_from_strike"]
            and row["reference_return_30s"]
            and row["target_horizon_seconds"]
        ):
            complete_baseline_rows += 1

        if row["normalized_yes_mid"]:
            complete_book_rows += 1

    report = {
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "dataset_version": ("p4_expanded_development_pre_block1_v1"),
        "block1_start": (BLOCK_1_START.isoformat()),
        "block1_consumed": False,
        "block2_consumed": False,
        "original_rows": (len(original_rows)),
        "original_markets": (len(original_markets)),
        "extension_rows": (len(extension_rows)),
        "extension_markets": (len(extension_markets)),
        "combined_rows": (len(combined)),
        "combined_markets": (len(combined_markets)),
        "market_overlap": (len(market_overlap)),
        "duplicate_market_horizon_keys": (duplicate_keys),
        "complete_baseline_rows": (complete_baseline_rows),
        "rows_with_market_probability": (complete_book_rows),
        "output": str(OUTPUT_FILE),
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Expanded P4 development dataset complete")

    print()

    print(
        "original_rows=",
        len(original_rows),
    )

    print(
        "original_markets=",
        len(original_markets),
    )

    print(
        "extension_rows=",
        len(extension_rows),
    )

    print(
        "extension_markets=",
        len(extension_markets),
    )

    print()

    print(
        "combined_rows=",
        len(combined),
    )

    print(
        "combined_markets=",
        len(combined_markets),
    )

    print(
        "market_overlap=",
        len(market_overlap),
    )

    print(
        "duplicate_market_horizon_keys=",
        duplicate_keys,
    )

    print()

    print(
        "complete_baseline_rows=",
        complete_baseline_rows,
    )

    print(
        "rows_with_market_probability=",
        complete_book_rows,
    )

    print()

    print("BLOCK 1 CONSUMED=False")

    print("BLOCK 2 CONSUMED=False")

    print()

    print(
        "output=",
        OUTPUT_FILE,
    )

    print(
        "report=",
        REPORT_FILE,
    )


if __name__ == "__main__":
    main()
