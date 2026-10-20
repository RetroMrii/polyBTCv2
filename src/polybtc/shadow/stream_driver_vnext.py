from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.adapter_vnext import (
    VNextEvaluationAdapter,
)
from polybtc.shadow.orchestrator_vnext import (
    VNextDecisionOrchestrator,
)
from polybtc.shadow.runner_vnext import VerifiedSources
from polybtc.shadow.source_verification_vnext import VNextSourceVerificationAdapter
from polybtc.data.fee_policy_cache_vnext import (
    FeeCacheError,
    VNextFeePolicyCache,
)

DRIVER_VERSION = "stream_driver_vnext_v2_bounded_execution_handoff"


@dataclass(frozen=True, slots=True)
class StreamDriverConfig:
    # These limits control driver inputs, not the
    # strategy's execution-freshness thresholds.
    max_observation_delay_seconds: float = 2.0
    require_distinct_execution_snapshot: bool = True
    execution_wait_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class StreamResult:
    condition_id: str
    horizon_seconds: int
    status: str
    reason: str
    prediction_snapshot_id: str | None
    execution_snapshot_id: str | None


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _market(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid condition_id")

    return value.strip().lower()


def _available(
    snapshot: SnapshotRecord,
    at: datetime,
) -> bool:
    return _utc(snapshot.observed_at) <= at and _utc(snapshot.ingested_at) <= at


class VNextSnapshotStreamDriver:
    """
    Stateless snapshot-batch processing.

    Durable state belongs to:
      - VNextDecisionOrchestrator
      - VNextShadowLedger

    No network calls, trading orders, or settlement.

    The caller supplies the complete relevant snapshot
    window, including prediction history and the latest
    execution observation.

    Do not reconstruct historical ingest timestamps as
    though they were genuine live availability times.
    """

    def __init__(
        self,
        *,
        journal: VNextDecisionOrchestrator,
        adapter: VNextEvaluationAdapter,
        config: StreamDriverConfig | None = None,
        fee_cache: VNextFeePolicyCache | None = None,
        source_verifier: VNextSourceVerificationAdapter | None = None,
        clock=None,
    ) -> None:
        self.journal = journal
        self.adapter = adapter
        self.config = config or StreamDriverConfig()
        self.fee_cache = fee_cache
        self.source_verifier = source_verifier
        self.clock = clock

        if self.adapter.journal is not self.journal:
            raise ValueError("Adapter and driver must share a journal")

        if not math.isfinite(self.config.execution_wait_seconds) or not 0 <= self.config.execution_wait_seconds <= 1:
            raise ValueError("Execution evidence wait must be between zero and one second")
        if self.config.max_observation_delay_seconds <= 0:
            raise ValueError("Invalid observation delay limit")

    def process(
        self,
        *,
        snapshots: list[SnapshotRecord],
        at: datetime,
        sources: VerifiedSources,
        fee_rate: float | None,
        kill_switch: bool = False,
    ) -> list[StreamResult]:
        now = _utc(at)

        # Do not permit duplicate IDs with inconsistent
        # contents to create ambiguous evidence.
        snapshot_by_id: dict[str, SnapshotRecord] = {}

        for row in snapshots:
            if not isinstance(row.snapshot_id, str):
                raise ValueError("Invalid snapshot_id")

            if not row.snapshot_id.strip():
                raise ValueError("Empty snapshot_id")

            existing = snapshot_by_id.get(row.snapshot_id)

            if existing is not None and existing != row:
                raise ValueError("Conflicting snapshot_id: " + row.snapshot_id)

            snapshot_by_id[row.snapshot_id] = row

        # Exclude observations that did not yet exist
        # at the current processing timestamp.
        available = [row for row in snapshot_by_id.values() if _available(row, now)]

        available.sort(
            key=lambda row: (
                _utc(row.observed_at),
                _utc(row.ingested_at),
                row.snapshot_id,
            )
        )

        # Finalize eligible horizons transactionally.
        newly_finalized = self.journal.process(
            snapshots=available,
            processing_at_utc=now,
        )

        output: list[StreamResult] = []

        for decision in newly_finalized:
            if decision.status != "AWAITING_EXECUTION_ADAPTER":
                output.append(
                    StreamResult(
                        condition_id=decision.condition_id,
                        horizon_seconds=decision.horizon_seconds,
                        status=decision.status,
                        reason=decision.reason,
                        prediction_snapshot_id=decision.snapshot_id,
                        execution_snapshot_id=None,
                    )
                )

        # Also handle decisions finalized previously but
        # still awaiting their first evaluation attempt.
        #
        # Claims and uniqueness constraints ensure they
        # cannot execute more than once.
        awaiting = [
            row
            for row in self.journal.decisions(status="AWAITING_EXECUTION_ADAPTER")
            if row["status"] == "AWAITING_EXECUTION_ADAPTER"
        ]

        awaiting.sort(
            key=lambda row: (
                row["target_at_utc"],
                row["condition_id"],
                -row["horizon_seconds"],
            )
        )

        for decision in awaiting:
            if self.clock is not None:
                measured = _utc(self.clock())
                if measured < now:
                    raise RuntimeError("Evaluation clock moved backwards")
                now = measured
            market = decision["condition_id"]
            horizon = decision["horizon_seconds"]
            prediction_id = decision["snapshot_id"]

            target = _utc(datetime.fromisoformat(decision["target_at_utc"]))

            # Never evaluate an opportunity before its
            # own journaled prediction cutoff.
            if now < target:
                continue

            prediction = snapshot_by_id.get(prediction_id)

            if prediction is None:
                # This is a data/restart recovery issue.
                # Do not claim or overwrite the decision.
                output.append(
                    StreamResult(
                        condition_id=market,
                        horizon_seconds=horizon,
                        status="UNRESOLVED",
                        reason="prediction_snapshot_unavailable",
                        prediction_snapshot_id=prediction_id,
                        execution_snapshot_id=None,
                    )
                )
                continue

            # The prediction snapshot must be the exact
            # snapshot chosen by the durable journal.
            if not _available(prediction, now):
                output.append(
                    StreamResult(
                        condition_id=market,
                        horizon_seconds=horizon,
                        status="UNRESOLVED",
                        reason="prediction_snapshot_not_available",
                        prediction_snapshot_id=prediction_id,
                        execution_snapshot_id=None,
                    )
                )
                continue

            market_rows = [
                row for row in available if _market(row.condition_id) == market
            ]

            # History is bounded by prediction time.
            # The runner applies additional reference
            # timestamp and 30s anchor validation.
            history = [
                row
                for row in market_rows
                if (_utc(row.observed_at) <= target and _utc(row.ingested_at) <= target)
            ]

            # Execution observations must come from
            # the same market, at or after the target.
            # The runner separately enforces:
            # - same market expiry
            # - source timestamp provenance
            # - 500ms book freshness
            # - configured reference freshness
            # - execution price ceiling
            quote_candidates = [
                row
                for row in market_rows
                if (
                    _utc(row.observed_at) >= target
                    and (
                        not self.config.require_distinct_execution_snapshot
                        or row.snapshot_id != prediction_id
                    )
                )
            ]

            if quote_candidates:
                quote = max(
                    quote_candidates,
                    key=lambda row: (
                        _utc(row.observed_at),
                        _utc(row.ingested_at),
                        row.snapshot_id,
                    ),
                )

                observation_delay = (now - _utc(quote.observed_at)).total_seconds()

                if observation_delay > self.config.max_observation_delay_seconds:
                    quote = None

            else:
                quote = None

            # A missing or old execution quote is a
            # genuine abstention in this one-attempt
            # design, not a reason to reuse the
            # historical prediction snapshot.

            market_fee_rate = fee_rate
            market_sources = sources
            policy = None

            if self.fee_cache is not None:
                try:
                    policy = self.fee_cache.get(
                        market,
                        at=now,
                    )
                except FeeCacheError:
                    market_fee_rate = None

                    market_sources = VerifiedSources(
                        reference_source_verified=(sources.reference_source_verified),
                        yes_book_source_verified=(sources.yes_book_source_verified),
                        no_book_source_verified=(sources.no_book_source_verified),
                        fee_policy_verified=False,
                    )
                else:
                    market_fee_rate = policy.fee_rate

                    market_sources = VerifiedSources(
                        reference_source_verified=(sources.reference_source_verified),
                        yes_book_source_verified=(sources.yes_book_source_verified),
                        no_book_source_verified=(sources.no_book_source_verified),
                        # Compatible metadata is not fee-accounting permission.
                        fee_policy_verified=sources.fee_policy_verified,
                    )

            verification = None
            if self.source_verifier is not None:
                verification = self.source_verifier.verify(
                    prediction=prediction, execution=quote, history=history,
                    prediction_at=target, at=now,
                    fee_policy=policy, fee_rate=market_fee_rate,
                )
                market_sources = verification.sources

            # Freeze prediction selection, but do not claim a decision against
            # a transiently stale/future execution source immediately at grace.
            # One observed reference cadence is the maximum handoff wait. This
            # never retries a finalized/claimed decision or changes its target.
            if verification is not None and self.config.execution_wait_seconds:
                deadline = target + timedelta(seconds=(
                    self.journal.config.finalization_grace_seconds
                    + self.config.execution_wait_seconds
                ))
                issues = verification.diagnostics
                transient_execution = (
                    not any(item.role != "execution" for item in issues)
                    and (quote is None or (issues and all(
                        item.role == "execution" and item.reason in (
                            "stale_source", "future_source_timestamp"
                        ) for item in issues
                    )))
                )
                if (now < deadline and transient_execution
                        and verification.sources.fee_policy_verified):
                    continue

            adapter_result = self.adapter.evaluate(
                condition_id=market,
                horizon_seconds=horizon,
                prediction_snapshot=prediction,
                execution_snapshot=quote,
                history=history,
                at=now,
                sources=market_sources,
                fee_rate=market_fee_rate,
                fee_policy=policy,
                require_fee_provenance=self.fee_cache is not None,
                source_verification=verification,
                kill_switch=kill_switch,
            )

            output.append(
                StreamResult(
                    condition_id=market,
                    horizon_seconds=horizon,
                    status=adapter_result.status,
                    reason=adapter_result.reason,
                    prediction_snapshot_id=prediction_id,
                    execution_snapshot_id=(
                        quote.snapshot_id if quote is not None else None
                    ),
                )
            )

        return output
