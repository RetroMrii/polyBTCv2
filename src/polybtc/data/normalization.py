from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Iterable
from dataclasses import replace
from polybtc.data.polymarket_resolution import (
    PolymarketResolution,
)
from polybtc.data.polymarket_metadata import (
    PolymarketMarketMetadata,
)
from polybtc.data.importers.v1_decisions import V1DecisionAudit
from polybtc.data.schema import (
    LabelRecord,
    MarketRecord,
    SnapshotRecord,
)
from polybtc.data.validation import validate_market


DecisionPair = tuple[SnapshotRecord, V1DecisionAudit]


def build_markets_from_decisions(
    rows: Iterable[DecisionPair],
    *,
    ingested_at: datetime | None = None,
) -> list[MarketRecord]:
    ingestion_time = (ingested_at or datetime.now(timezone.utc)).astimezone(
        timezone.utc
    )

    grouped: dict[str, list[DecisionPair]] = defaultdict(list)

    for snapshot, audit in rows:
        grouped[snapshot.condition_id].append((snapshot, audit))

    markets: list[MarketRecord] = []

    for condition_id, items in grouped.items():
        items.sort(key=lambda item: item[0].observed_at)

        first_snapshot, first_audit = items[0]

        strikes = [
            snapshot.strike for snapshot, _ in items if snapshot.strike is not None
        ]
        strike = median(strikes) if strikes else None

        end_candidates = [
            (snapshot.observed_at.timestamp() + snapshot.seconds_to_expiry)
            for snapshot, _ in items
            if snapshot.seconds_to_expiry is not None
        ]

        if not end_candidates:
            raise ValueError(f"cannot reconstruct market_end_at for {condition_id}")

        market_end_at = datetime.fromtimestamp(
            round(median(end_candidates)),
            tz=timezone.utc,
        )
        market_start_at = datetime.fromtimestamp(
            market_end_at.timestamp() - 300,
            tz=timezone.utc,
        )

        questions = {audit.question for _, audit in items if audit.question}
        if len(questions) > 1:
            raise ValueError(
                f"inconsistent question text for {condition_id}: {questions}"
            )

        question = next(iter(questions)) if questions else first_audit.question

        record = MarketRecord(
            condition_id=condition_id,
            question=question,
            market_end_at=market_end_at,
            source_name="polybtc_v1_1_decisions",
            ingested_at=ingestion_time,
            market_start_at=market_start_at,
            strike=strike,
        )
        validate_market(record)
        markets.append(record)

    return sorted(
        markets,
        key=lambda record: record.market_end_at,
    )


def snapshots_from_decisions(
    rows: Iterable[DecisionPair],
) -> list[SnapshotRecord]:
    return [snapshot for snapshot, _ in rows]


def enrich_market_metadata(
    market: MarketRecord,
    metadata: PolymarketMarketMetadata,
) -> MarketRecord:
    if market.condition_id.lower() != metadata.condition_id.lower():
        raise ValueError(
            "condition_id mismatch during "
            f"metadata enrichment: "
            f"{market.condition_id} != "
            f"{metadata.condition_id}"
        )

    return replace(
        market,
        market_slug=metadata.slug,
        question=(metadata.question or market.question),
        yes_token_id=metadata.yes_token_id,
        no_token_id=metadata.no_token_id,
        market_start_at=market.market_start_at,
        market_end_at=(metadata.end_at or market.market_end_at),
        closed=metadata.closed,
        resolution_source=(metadata.resolution_source or market.resolution_source),
    )


def build_label(
    market: MarketRecord,
    metadata: PolymarketMarketMetadata,
    resolution: PolymarketResolution | None,
    *,
    retrieved_at: datetime,
) -> LabelRecord:
    if resolution is None:
        return LabelRecord(
            condition_id=market.condition_id,
            resolved_at=None,
            winning_outcome=None,
            winning_token_id=None,
            label_yes=None,
            resolution_source="polymarket",
            resolution_source_version="p1",
            retrieved_at=retrieved_at,
            validation_status="MISSING",
            validation_note=("No Data API resolution record returned."),
        )

    if not resolution.resolved:
        return LabelRecord(
            condition_id=market.condition_id,
            resolved_at=resolution.resolved_at,
            winning_outcome=None,
            winning_token_id=None,
            label_yes=None,
            resolution_source=resolution.source,
            resolution_source_version="p1",
            retrieved_at=retrieved_at,
            validation_status="UNRESOLVED",
            validation_note=(
                "Resolution record exists but market is not confirmed resolved."
            ),
        )

    winning_outcome = metadata.winning_outcome
    winning_token_id = metadata.winning_token_id

    if winning_outcome not in {"YES", "NO"}:
        return LabelRecord(
            condition_id=market.condition_id,
            resolved_at=resolution.resolved_at,
            winning_outcome=None,
            winning_token_id=None,
            label_yes=None,
            resolution_source=resolution.source,
            resolution_source_version="p1",
            retrieved_at=retrieved_at,
            validation_status="INVALID",
            validation_note=(
                "Gamma metadata does not contain an exact "
                "resolved 1/0 YES/NO outcome pair."
            ),
        )

    expected_token = (
        metadata.yes_token_id if winning_outcome == "YES" else metadata.no_token_id
    )

    if (
        winning_token_id is None
        or expected_token is None
        or winning_token_id != expected_token
    ):
        return LabelRecord(
            condition_id=market.condition_id,
            resolved_at=resolution.resolved_at,
            winning_outcome=winning_outcome,
            winning_token_id=winning_token_id,
            label_yes=None,
            resolution_source=resolution.source,
            resolution_source_version="p1",
            retrieved_at=retrieved_at,
            validation_status="INVALID",
            validation_note=("Winning outcome/token mapping is inconsistent."),
        )

    return LabelRecord(
        condition_id=market.condition_id,
        resolved_at=resolution.resolved_at,
        winning_outcome=winning_outcome,
        winning_token_id=winning_token_id,
        label_yes=1 if winning_outcome == "YES" else 0,
        resolution_source=resolution.source,
        resolution_source_version="p1",
        retrieved_at=retrieved_at,
        validation_status="VALID",
        validation_note=None,
    )
