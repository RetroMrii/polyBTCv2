import json
import time

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.exports.csv_export import (
    write_dataclasses_csv,
)

from polybtc.data.importers.polymarket_history import (
    load_polymarket_history,
)

from polybtc.data.importers.v1_decisions import (
    load_v1_decisions,
)

from polybtc.data.importers.v1_trades import (
    load_v1_trade_audit,
    reconstruct_fills,
    reconstruct_orders,
)

from polybtc.data.normalization import (
    build_label,
    build_markets_from_decisions,
    enrich_market_metadata,
    snapshots_from_decisions,
)

from polybtc.data.polymarket_metadata import (
    fetch_market_metadata,
)

from polybtc.data.polymarket_resolution import (
    fetch_resolution,
)

from polybtc.data.reconciliation import (
    build_reconciliation_report,
)

ROOT = Path(__file__).resolve().parents[2]

RAW = ROOT / "data" / "raw" / "v1.1"

NORMALIZED = ROOT / "data" / "normalized"


def main() -> None:
    ingestion_time = datetime.now(timezone.utc)

    decisions = load_v1_decisions(
        RAW / "btc_5m_decisions_v1_1.csv",
        ingested_at=ingestion_time,
    )
    markets = build_markets_from_decisions(
        decisions,
        ingested_at=ingestion_time,
    )
    enriched_markets = []
    labels = []

    metadata_found = 0
    metadata_missing = 0

    labels_valid = 0
    labels_invalid = 0
    labels_missing = 0
    labels_unresolved = 0

    for index, market in enumerate(
        markets,
        start=1,
    ):
        metadata = fetch_market_metadata(market.condition_id)

        if metadata is None:
            metadata_missing += 1
            enriched_markets.append(market)

            print(f"[{index}/{len(markets)}] metadata missing")

            continue

        metadata_found += 1

        enriched_market = enrich_market_metadata(
            market,
            metadata,
        )

        enriched_markets.append(enriched_market)

        resolution = fetch_resolution(market.condition_id)

        label = build_label(
            enriched_market,
            metadata,
            resolution,
            retrieved_at=ingestion_time,
        )

        labels.append(label)

        status = str(label.validation_status)

        if "VALID" in status and "INVALID" not in status:
            labels_valid += 1

        elif "INVALID" in status:
            labels_invalid += 1

        elif "UNRESOLVED" in status:
            labels_unresolved += 1

        else:
            labels_missing += 1

        print(
            f"[{index}/{len(markets)}] "
            f"{market.condition_id[:12]}... "
            f"label={label.label_yes} "
            f"status={label.validation_status}"
        )

        time.sleep(0.05)

    markets = enriched_markets
    snapshots = snapshots_from_decisions(decisions)

    trades = load_v1_trade_audit(RAW / "btc_5m_trades_v1_1.csv")
    orders = reconstruct_orders(
        trades,
        ingested_at=ingestion_time,
    )
    fills = reconstruct_fills(
        trades,
        ingested_at=ingestion_time,
    )

    history = load_polymarket_history(RAW / "Polymarket-History-2026-09-16.csv")

    reconciliation = build_reconciliation_report(
        markets,
        snapshots,
        labels,
        fills,
        history,
    )

    if reconciliation.duplicate_market_ids != 0:
        raise RuntimeError("duplicate canonical market IDs detected")

    if reconciliation.duplicate_snapshot_ids != 0:
        raise RuntimeError("duplicate snapshot IDs detected")

    if reconciliation.snapshots_without_market != 0:
        raise RuntimeError("snapshots reference missing markets")

    if reconciliation.labels_without_market != 0:
        raise RuntimeError("labels reference missing markets")

    if reconciliation.markets_without_label != 0:
        raise RuntimeError("canonical markets are missing labels")

    counts = {
        "decision_rows": len(decisions),
        "markets": len(markets),
        "snapshots": len(snapshots),
        "trade_event_rows": len(trades),
        "reconstructed_orders": len(orders),
        "reconstructed_fills": len(fills),
        "account_history_rows": len(history),
        "trade_event_types": dict(sorted(Counter(x.side for x in trades).items())),
        "account_actions": dict(sorted(Counter(x.action for x in history).items())),
        "metadata_found": metadata_found,
        "metadata_missing": metadata_missing,
        "labels": len(labels),
        "labels_valid": labels_valid,
        "labels_invalid": labels_invalid,
        "labels_missing": labels_missing,
        "labels_unresolved": labels_unresolved,
        "reconciliation": asdict(reconciliation),
    }

    NORMALIZED.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_dataclasses_csv(
        markets,
        NORMALIZED / "markets.csv",
    )
    write_dataclasses_csv(
        snapshots,
        NORMALIZED / "snapshots.csv",
    )
    write_dataclasses_csv(
        orders,
        NORMALIZED / "orders_reconstructed.csv",
    )
    write_dataclasses_csv(
        fills,
        NORMALIZED / "fills_reconstructed.csv",
    )
    write_dataclasses_csv(
        labels,
        NORMALIZED / "labels.csv",
    )

    report_path = NORMALIZED / "p1c_import_report.json"
    report_path.write_text(
        json.dumps(
            counts,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            counts,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
