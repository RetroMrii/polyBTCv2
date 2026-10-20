from __future__ import annotations

import json
import sys

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from polybtc.data.dataset.horizons import (
    DEFAULT_HORIZONS_SECONDS,
    select_market_horizons,
)
from polybtc.data.dataset.supervised import (
    DATASET_VERSION,
    FEATURE_VERSION,
    build_supervised_rows,
    load_valid_labels,
)
from polybtc.data.exports.csv_export import (
    write_dataclasses_csv,
)
from polybtc.data.importers.v1_market_snapshots import (
    import_v1_market_snapshots,
)


SNAPSHOTS_FILE = ROOT / "data" / "raw" / "v1.1" / "btc_5m_market_snapshots_v1_4.csv"

LABELS_FILE = ROOT / "data" / "normalized" / "market_resolutions.csv"

OUTPUT_DATASET = ROOT / "data" / "normalized" / "p4_supervised_v1.csv"

OUTPUT_REPORT = ROOT / "data" / "normalized" / "p4_dataset_report.json"


def main() -> None:
    snapshots = import_v1_market_snapshots(SNAPSHOTS_FILE)

    selections = select_market_horizons(snapshots)

    labels = load_valid_labels(LABELS_FILE)

    rows = build_supervised_rows(
        selections,
        labels,
        snapshots,
    )
    write_dataclasses_csv(
        rows,
        OUTPUT_DATASET,
    )

    status_counts = Counter(row.row_status for row in rows)

    horizon_counts = {
        str(horizon): sum(1 for row in rows if row.target_horizon_seconds == horizon)
        for horizon in DEFAULT_HORIZONS_SECONDS
    }

    market_ids = {row.condition_id for row in rows}

    observed_times = [row.snapshot_observed_at for row in rows]

    report = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "label_version": "p3_v1",
        "built_at": (datetime.now(timezone.utc).isoformat()),
        "snapshot_rows_input": len(snapshots),
        "markets": len(market_ids),
        "dataset_rows": len(rows),
        "horizons_seconds": list(DEFAULT_HORIZONS_SECONDS),
        "rows_by_horizon": horizon_counts,
        "eligible_reference_rows": sum(row.eligible_reference_features for row in rows),
        "eligible_book_rows": sum(row.eligible_book_features for row in rows),
        "history_feature_coverage": {
            "reference_return_30s": sum(
                row.reference_return_30s is not None for row in rows
            ),
            "reference_return_60s": sum(
                row.reference_return_60s is not None for row in rows
            ),
            "reference_return_120s": sum(
                row.reference_return_120s is not None for row in rows
            ),
            "realized_volatility_60s": sum(
                row.realized_volatility_60s is not None for row in rows
            ),
            "realized_volatility_120s": sum(
                row.realized_volatility_120s is not None for row in rows
            ),
        },
        "row_status_counts": dict(sorted(status_counts.items())),
        "first_snapshot_observed_at": (
            min(observed_times).isoformat() if observed_times else None
        ),
        "last_snapshot_observed_at": (
            max(observed_times).isoformat() if observed_times else None
        ),
        "output_dataset": str(OUTPUT_DATASET.relative_to(ROOT)),
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

    print(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
