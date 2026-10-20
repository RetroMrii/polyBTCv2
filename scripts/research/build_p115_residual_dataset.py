from __future__ import annotations

import csv
import json

from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

ORIGINAL_PREDICTIONS = ROOT / "data" / "normalized" / "p11_walk_forward_predictions.csv"

EXTENSION_PREDICTIONS = (
    ROOT / "data" / "normalized" / "p11_extension_walk_forward_predictions.csv"
)

P4_FILE = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

RAW_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

OUTPUT_DATASET = ROOT / "data" / "normalized" / "p115_residual_dataset.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p115_residual_dataset_report.json"


DATASET_VERSION = "p115_residual_dataset_v1"


def load_csv(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def optional_float(
    value: object,
) -> float | None:
    if value is None:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    return float(raw)


def prediction_key(
    row: dict[str, str],
) -> tuple[str, str, int]:
    return (
        row["condition_id"].strip().lower(),
        row["prediction_timestamp"].strip(),
        int(row["target_horizon_seconds"]),
    )


def raw_key(
    condition_id: str,
    observed_at: str,
) -> tuple[str, str]:
    return (
        condition_id.strip().lower(),
        observed_at.strip(),
    )


def main() -> None:
    original_predictions = load_csv(ORIGINAL_PREDICTIONS)

    extension_predictions = load_csv(EXTENSION_PREDICTIONS)

    p4_rows = load_csv(P4_FILE)

    raw_rows = load_csv(RAW_FILE)

    p4_index = {}

    for row in p4_rows:
        key = prediction_key(row)

        if key in p4_index:
            raise RuntimeError(f"duplicate P4 key: {key}")

        p4_index[key] = row

    raw_index = {}

    for row in raw_rows:
        key = raw_key(
            row["market_id"],
            row["observed_at"],
        )

        if key in raw_index:
            raise RuntimeError(f"duplicate raw key: {key}")

        raw_index[key] = row

    prediction_sources = []

    for row in original_predictions:
        prediction_sources.append(
            (
                "ORIGINAL_FORWARD",
                row,
            )
        )

    for row in extension_predictions:
        prediction_sources.append(
            (
                "FORWARD_EXTENSION",
                row,
            )
        )

    seen_prediction_keys = set()

    output_rows = []

    missing_p4 = 0
    missing_raw = 0
    missing_market_probability = 0

    for source_split, prediction in prediction_sources:
        key = prediction_key(prediction)

        if key in seen_prediction_keys:
            raise RuntimeError(f"duplicate prediction across P11 streams: {key}")

        seen_prediction_keys.add(key)

        p4 = p4_index.get(key)

        if p4 is None:
            missing_p4 += 1
            continue

        condition_id = prediction["condition_id"].strip().lower()

        snapshot_observed_at = p4["snapshot_observed_at"].strip()

        raw = raw_index.get(
            raw_key(
                condition_id,
                snapshot_observed_at,
            )
        )

        if raw is None:
            missing_raw += 1
            continue

        model_probability = float(prediction["walk_forward_probability"])

        market_probability = optional_float(p4.get("normalized_yes_mid"))

        if market_probability is None:
            missing_market_probability += 1

        residual = (
            model_probability - market_probability
            if market_probability is not None
            else None
        )

        absolute_residual = abs(residual) if residual is not None else None

        yes_ask = optional_float(raw.get("yes_ask"))

        no_ask = optional_float(raw.get("no_ask"))

        yes_executable_edge = (
            model_probability - yes_ask if yes_ask is not None else None
        )

        no_probability = 1.0 - model_probability

        no_executable_edge = no_probability - no_ask if no_ask is not None else None

        market_error = (
            market_probability - int(prediction["label_yes"])
            if market_probability is not None
            else None
        )

        model_error = model_probability - int(prediction["label_yes"])

        output_rows.append(
            {
                "dataset_version": (DATASET_VERSION),
                "source_split": (source_split),
                "condition_id": (condition_id),
                "prediction_timestamp": (prediction["prediction_timestamp"].strip()),
                "snapshot_observed_at": (snapshot_observed_at),
                "target_horizon_seconds": int(prediction["target_horizon_seconds"]),
                "label_yes": int(prediction["label_yes"]),
                "model_probability": (model_probability),
                "market_probability": (market_probability),
                "residual": (residual),
                "absolute_residual": (absolute_residual),
                "model_error": (model_error),
                "market_error": (market_error),
                "yes_bid": optional_float(raw.get("yes_bid")),
                "yes_ask": (yes_ask),
                "no_bid": optional_float(raw.get("no_bid")),
                "no_ask": (no_ask),
                "yes_mid": optional_float(p4.get("yes_mid")),
                "no_mid": optional_float(p4.get("no_mid")),
                "yes_spread": optional_float(p4.get("yes_spread")),
                "no_spread": optional_float(p4.get("no_spread")),
                "yes_top_depth": optional_float(p4.get("yes_top_depth")),
                "no_top_depth": optional_float(p4.get("no_top_depth")),
                "yes_book_age_ms": optional_float(p4.get("yes_book_age_ms")),
                "no_book_age_ms": optional_float(p4.get("no_book_age_ms")),
                "relative_distance_from_strike": (
                    optional_float(p4.get("relative_distance_from_strike"))
                ),
                "reference_return_30s": (
                    optional_float(p4.get("reference_return_30s"))
                ),
                "reference_return_60s": (
                    optional_float(p4.get("reference_return_60s"))
                ),
                "reference_return_120s": (
                    optional_float(p4.get("reference_return_120s"))
                ),
                "realized_volatility_60s": (
                    optional_float(p4.get("realized_volatility_60s"))
                ),
                "realized_volatility_120s": (
                    optional_float(p4.get("realized_volatility_120s"))
                ),
                "yes_executable_edge": (yes_executable_edge),
                "no_executable_edge": (no_executable_edge),
                "eligible_book_features": (p4["eligible_book_features"].strip()),
                "row_status": (p4["row_status"].strip()),
            }
        )

    if not output_rows:
        raise RuntimeError("P11.5 residual dataset is empty")

    with OUTPUT_DATASET.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(output_rows[0].keys()),
        )

        writer.writeheader()
        writer.writerows(output_rows)

    market_ids = {row["condition_id"] for row in output_rows}

    source_counts = Counter(row["source_split"] for row in output_rows)

    book_complete = sum(row["market_probability"] is not None for row in output_rows)

    report = {
        "dataset_version": (DATASET_VERSION),
        "rows": len(output_rows),
        "markets": len(market_ids),
        "source_split_rows": dict(source_counts),
        "market_probability_rows": (book_complete),
        "missing_market_probability_rows": (len(output_rows) - book_complete),
        "lineage": {
            "missing_p4_rows": (missing_p4),
            "missing_raw_rows": (missing_raw),
            "duplicate_prediction_keys": 0,
        },
        "important_notes": [
            ("Primary model probability is walk-forward out-of-sample probability."),
            (
                "Original P11 forward and P11 extension "
                "are retained as separate source splits."
            ),
            (
                "All data through 2026-10-01 has already "
                "been inspected and is research data for "
                "P11.5, not a future untouched validation set."
            ),
            ("Market probability is normalized YES mid, not executable entry price."),
            (
                "Executable YES/NO edges are included only "
                "for later economic diagnostics."
            ),
        ],
    }

    OUTPUT_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("P11.5 residual dataset build complete")

    print(
        "rows=",
        len(output_rows),
    )

    print(
        "markets=",
        len(market_ids),
    )

    print(
        "source splits=",
        dict(source_counts),
    )

    print(
        "market probability rows=",
        book_complete,
    )

    print(
        "missing market probability rows=",
        len(output_rows) - book_complete,
    )

    print(
        "missing P4 lineage=",
        missing_p4,
    )

    print(
        "missing raw lineage=",
        missing_raw,
    )

    print()

    print(f"Wrote {OUTPUT_DATASET}")

    print(f"Wrote {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
