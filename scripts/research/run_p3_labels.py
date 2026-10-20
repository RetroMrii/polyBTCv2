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
    sys.path.insert(0, str(SRC))


from polybtc.data.exports.csv_export import (
    write_dataclasses_csv,
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


NORMALIZED = ROOT / "data" / "normalized"

MARKETS_FILE = NORMALIZED / "markets.csv"

OUTPUT_LABELS = NORMALIZED / "market_resolutions.csv"

OUTPUT_REPORT = NORMALIZED / "p3_resolution_report.json"

OUTPUT_DISPUTES = NORMALIZED / "p3_unresolved_disputed.csv"


def load_condition_ids() -> list[str]:
    with MARKETS_FILE.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        rows = csv.DictReader(file)

        condition_ids = [
            row["condition_id"].strip() for row in rows if row["condition_id"].strip()
        ]

    if len(condition_ids) != len(set(condition_ids)):
        raise RuntimeError("duplicate condition_ids in markets.csv")

    return condition_ids


def main() -> None:
    condition_ids = load_condition_ids()

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
            retrieved_at=retrieved_at,
        )

        labels.append(label)

        print(
            f"[{index}/{len(condition_ids)}] "
            f"{condition_id[:14]}... "
            f"{label.validation_status} "
            f"label={label.label_yes}"
        )

        time.sleep(0.05)

    write_dataclasses_csv(
        labels,
        OUTPUT_LABELS,
    )

    problem_labels = [
        label
        for label in labels
        if label.validation_status != ResolutionValidationStatus.VALID
    ]

    write_dataclasses_csv(
        problem_labels,
        OUTPUT_DISPUTES,
    )

    status_counts = Counter(str(label.validation_status) for label in labels)

    yes_count = sum(1 for label in labels if label.label_yes == 1)

    no_count = sum(1 for label in labels if label.label_yes == 0)

    report = {
        "label_version": LABEL_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "markets": len(condition_ids),
        "labels": len(labels),
        "yes_labels": yes_count,
        "no_labels": no_count,
        "status_counts": dict(sorted(status_counts.items())),
        "problem_markets": len(problem_labels),
        "output_labels": str(OUTPUT_LABELS.relative_to(ROOT)),
        "output_problem_report": str(OUTPUT_DISPUTES.relative_to(ROOT)),
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
