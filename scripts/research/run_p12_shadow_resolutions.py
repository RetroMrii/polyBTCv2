from __future__ import annotations

import csv
import json
import sys
import time

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(
        0,
        str(SRC),
    )


from polybtc.data.polymarket_metadata import (
    fetch_market_metadata,
)
from polybtc.data.polymarket_resolution import (
    fetch_resolution,
)
from polybtc.data.resolution_validation import (
    LABEL_VERSION,
    validate_resolution,
)
from polybtc.data.schema import (
    ResolutionValidationStatus,
)


SHADOW_DIR = ROOT / "data" / "shadow"

DECISIONS_FILE = SHADOW_DIR / "p12_consensus_shadow_decisions.csv"

OUTPUT_LABELS = SHADOW_DIR / "p12_market_resolutions.csv"

OUTPUT_PROBLEMS = SHADOW_DIR / "p12_unresolved_disputed.csv"

OUTPUT_REPORT = SHADOW_DIR / "p12_resolution_report.json"


REPORT_VERSION = "p12_resolution_v1"


OUTPUT_FIELDS = (
    "condition_id",
    "resolution_source",
    "retrieved_at",
    "validation_status",
    "resolved_at",
    "winning_outcome",
    "winning_token_id",
    "label_yes",
    "resolution_source_version",
    "label_version",
    "validation_note",
)


def load_shadow_market_ids() -> list[str]:
    with DECISIONS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    condition_ids = sorted(
        {
            row["condition_id"].strip().lower()
            for row in rows
            if row["condition_id"].strip()
        }
    )

    if not condition_ids:
        raise RuntimeError("no P12 shadow markets found")

    return condition_ids


def serialize_value(
    value: object,
) -> str | int | None:
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()

    if hasattr(
        value,
        "value",
    ):
        return value.value

    return value


def label_to_row(
    label: object,
) -> dict[str, object]:
    raw = asdict(label)

    return {field: serialize_value(raw.get(field)) for field in OUTPUT_FIELDS}


def write_rows(
    path: Path,
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    condition_ids = load_shadow_market_ids()

    labels = []

    for index, condition_id in enumerate(
        condition_ids,
        start=1,
    ):
        retrieved_at = datetime.now(timezone.utc)

        metadata = fetch_market_metadata(condition_id)

        resolution = fetch_resolution(condition_id)

        label = validate_resolution(
            condition_id,
            metadata,
            resolution,
            retrieved_at=(retrieved_at),
        )

        labels.append(label)

        print(
            f"[{index}/{len(condition_ids)}] "
            f"{condition_id[:14]}... "
            f"{label.validation_status} "
            f"label={label.label_yes}"
        )

        time.sleep(0.05)

    output_rows = [label_to_row(label) for label in labels]

    problem_labels = [
        label
        for label in labels
        if (label.validation_status != ResolutionValidationStatus.VALID)
    ]

    problem_rows = [label_to_row(label) for label in problem_labels]

    write_rows(
        OUTPUT_LABELS,
        output_rows,
    )

    write_rows(
        OUTPUT_PROBLEMS,
        problem_rows,
    )

    status_counts = Counter(str(label.validation_status) for label in labels)

    valid_labels = [
        label
        for label in labels
        if (label.validation_status == ResolutionValidationStatus.VALID)
    ]

    yes_count = sum(1 for label in valid_labels if label.label_yes == 1)

    no_count = sum(1 for label in valid_labels if label.label_yes == 0)

    report = {
        "report_version": (REPORT_VERSION),
        "label_version": (LABEL_VERSION),
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "shadow_markets": len(condition_ids),
        "labels": len(labels),
        "valid_labels": len(valid_labels),
        "yes_labels": (yes_count),
        "no_labels": (no_count),
        "status_counts": dict(sorted(status_counts.items())),
        "problem_markets": len(problem_labels),
        "output_labels": str(OUTPUT_LABELS.relative_to(ROOT)),
        "output_problem_report": str(OUTPUT_PROBLEMS.relative_to(ROOT)),
        "important_notes": [
            ("This resolution set is isolated from the frozen P3/P4 research corpus."),
            (
                "All shadow markets are resolved, "
                "not only TRADE markets, so later "
                "prospective prediction/calibration "
                "analysis can use the full stream."
            ),
            ("Only VALID labels may be used for performance accounting."),
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

    print()
    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
