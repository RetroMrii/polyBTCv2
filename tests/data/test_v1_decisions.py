from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.importers.v1_decisions import iter_v1_decisions


def test_import_uploaded_v1_decisions() -> None:
    path = Path("data/raw/v1.1/btc_5m_decisions_v1_1.csv")
    if not path.exists():
        return

    rows = list(
        iter_v1_decisions(path, ingested_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
    )
    assert len(rows) == 10844
    snapshots = [row[0] for row in rows]
    assert len({s.snapshot_id for s in snapshots}) == 10844
    assert len({s.condition_id for s in snapshots}) == 280
    assert all(s.observed_at.utcoffset().total_seconds() == 0 for s in snapshots)
