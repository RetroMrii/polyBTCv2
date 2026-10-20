from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from polybtc.data.importers.polymarket_history import (
    AccountHistoryRecord,
)
from polybtc.data.schema import (
    FillRecord,
    LabelRecord,
    MarketRecord,
    SnapshotRecord,
)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    markets: int
    snapshots: int
    labels: int

    valid_labels: int
    duplicate_market_ids: int
    duplicate_snapshot_ids: int

    snapshots_without_market: int
    labels_without_market: int
    markets_without_label: int

    local_fills: int
    account_trade_rows: int
    matched_local_fills: int
    unmatched_local_fills: int


def validate_dataset_integrity(
    markets: list[MarketRecord],
    snapshots: list[SnapshotRecord],
    labels: list[LabelRecord],
) -> dict[str, int]:
    market_ids = [market.condition_id for market in markets]

    snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]

    market_id_set = set(market_ids)

    label_market_ids = {label.condition_id for label in labels}

    return {
        "duplicate_market_ids": (len(market_ids) - len(set(market_ids))),
        "duplicate_snapshot_ids": (len(snapshot_ids) - len(set(snapshot_ids))),
        "snapshots_without_market": sum(
            1 for snapshot in snapshots if snapshot.condition_id not in market_id_set
        ),
        "labels_without_market": sum(
            1 for label in labels if label.condition_id not in market_id_set
        ),
        "markets_without_label": sum(
            1 for market_id in market_id_set if market_id not in label_market_ids
        ),
    }


def reconcile_fills_with_account_history(
    fills: list[FillRecord],
    markets: list[MarketRecord],
    account_history: list[AccountHistoryRecord],
    *,
    tolerance_seconds: int = 60,
) -> tuple[int, int]:
    question_by_market = {market.condition_id: market.question for market in markets}

    available_account_rows = [
        row for row in account_history if row.action.upper() in {"BUY", "SELL"}
    ]

    used_indexes: set[int] = set()
    matched = 0

    for fill in fills:
        question = question_by_market.get(fill.condition_id)

        if not question:
            continue

        expected_action = fill.side.value.upper()

        if fill.outcome is None:
            expected_token = None
        elif fill.outcome.value == "YES":
            expected_token = "UP"
        else:
            expected_token = "DOWN"

        candidates: list[tuple[float, int]] = []

        for index, account_row in enumerate(available_account_rows):
            if index in used_indexes:
                continue

            if account_row.market_name != question:
                continue

            if account_row.action.upper() != expected_action:
                continue

            if (
                expected_token is not None
                and account_row.token_name.upper() != expected_token
            ):
                continue

            delta = abs((account_row.timestamp - fill.filled_at).total_seconds())

            if delta <= tolerance_seconds:
                candidates.append((delta, index))

        if not candidates:
            continue

        _, best_index = min(
            candidates,
            key=lambda item: item[0],
        )

        used_indexes.add(best_index)
        matched += 1

    return matched, len(fills) - matched


def build_reconciliation_report(
    markets: list[MarketRecord],
    snapshots: list[SnapshotRecord],
    labels: list[LabelRecord],
    fills: list[FillRecord],
    account_history: list[AccountHistoryRecord],
) -> ReconciliationReport:
    integrity = validate_dataset_integrity(
        markets,
        snapshots,
        labels,
    )

    matched, unmatched = reconcile_fills_with_account_history(
        fills,
        markets,
        account_history,
    )

    valid_labels = sum(
        1
        for label in labels
        if str(label.validation_status).endswith("VALID")
        and "INVALID" not in str(label.validation_status)
    )

    account_trade_rows = sum(
        1 for row in account_history if row.action.upper() in {"BUY", "SELL"}
    )

    return ReconciliationReport(
        markets=len(markets),
        snapshots=len(snapshots),
        labels=len(labels),
        valid_labels=valid_labels,
        duplicate_market_ids=(integrity["duplicate_market_ids"]),
        duplicate_snapshot_ids=(integrity["duplicate_snapshot_ids"]),
        snapshots_without_market=(integrity["snapshots_without_market"]),
        labels_without_market=(integrity["labels_without_market"]),
        markets_without_label=(integrity["markets_without_label"]),
        local_fills=len(fills),
        account_trade_rows=account_trade_rows,
        matched_local_fills=matched,
        unmatched_local_fills=unmatched,
    )
