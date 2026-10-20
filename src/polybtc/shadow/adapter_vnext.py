from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from polybtc.data.schema import SnapshotRecord
from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy, FeeCacheError
from polybtc.shadow.source_verification_vnext import SourceVerificationResult
from polybtc.shadow.orchestrator_vnext import (
    VNextDecisionOrchestrator,
)
from polybtc.shadow.reconciler_vnext import (
    VNextClaimReconciler,
)
from polybtc.shadow.runner_vnext import (
    VerifiedSources,
    VNextShadowRunner,
)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    status: str
    reason: str
    condition_id: str
    horizon_seconds: int


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


class VNextEvaluationAdapter:
    """
    Journal -> runner -> ledger reconciliation.

    Shadow-only. No network calls, market discovery,
    real orders, or automatic settlement.

    The journal identifies the prediction snapshot.
    The caller supplies an independently collected
    execution-time snapshot.
    """

    def __init__(
        self,
        *,
        journal: VNextDecisionOrchestrator,
        runner: VNextShadowRunner,
    ) -> None:
        self.journal = journal
        self.runner = runner
        self.reconciler = VNextClaimReconciler(
            journal=journal,
            ledger=runner.ledger,
        )

    def evaluate(
        self,
        *,
        condition_id: str,
        horizon_seconds: int,
        prediction_snapshot: SnapshotRecord,
        execution_snapshot: SnapshotRecord | None,
        history: list[SnapshotRecord],
        at: datetime,
        sources: VerifiedSources,
        fee_rate: float | None,
        fee_policy: CachedFeePolicy | None = None,
        require_fee_provenance: bool = False,
        source_verification: SourceVerificationResult | None = None,
        kill_switch: bool = False,
    ) -> AdapterResult:
        now = _utc(at)
        market = condition_id.strip().lower()

        if not market:
            raise ValueError("Missing condition_id")

        def result(status: str, reason: str):
            return AdapterResult(
                status=status,
                reason=reason,
                condition_id=market,
                horizon_seconds=horizon_seconds,
            )

        # Resolve the existing, immutable journal
        # selection before claiming the opportunity.
        candidates = [
            row
            for row in self.journal.decisions()
            if (
                row["condition_id"] == market
                and row["horizon_seconds"] == horizon_seconds
            )
        ]

        if len(candidates) != 1:
            return result(
                "UNRESOLVED",
                "missing_or_ambiguous_journal_decision",
            )

        recorded = candidates[0]

        if recorded["status"] != "AWAITING_EXECUTION_ADAPTER":
            return result(
                "UNRESOLVED",
                "journal_not_awaiting",
            )

        if (
            prediction_snapshot.condition_id.strip().lower() != market
            or prediction_snapshot.snapshot_id != recorded["snapshot_id"]
        ):
            return result(
                "UNRESOLVED",
                "prediction_snapshot_mismatch",
            )

        if prediction_snapshot.market_end_at is None:
            return result(
                "UNRESOLVED",
                "missing_prediction_expiry",
            )

        target = _utc(prediction_snapshot.market_end_at) - timedelta(
            seconds=horizon_seconds
        )

        if target.isoformat(timespec="microseconds") != (recorded["target_at_utc"]):
            return result(
                "UNRESOLVED",
                "prediction_target_mismatch",
            )

        if source_verification is not None:
            if (
                source_verification.condition_id != market
                or source_verification.prediction_snapshot_id != prediction_snapshot.snapshot_id
                or source_verification.execution_snapshot_id != (
                    execution_snapshot.snapshot_id if execution_snapshot else None
                )
                or source_verification.checked_at_utc != now
                or source_verification.sources != sources
            ):
                raise ValueError("Source verification does not match evaluation")

        fee_error = None
        if fee_policy is None and require_fee_provenance:
            fee_error = "missing_fee_provenance"
        elif fee_policy is not None:
            if not isinstance(fee_policy, CachedFeePolicy):
                fee_error = "invalid_fee_provenance"
            else:
                try:
                    fee_policy.validate_for_decision(market, fee_rate, now)
                except (FeeCacheError, ValueError, TypeError):
                    fee_error = "invalid_fee_provenance"

        # One journal claim owner across processes; persist the same immutable
        # evidence before any runner outcome (including pre-reservation abstention).
        token = self.journal.claim(
            condition_id=market,
            horizon_seconds=horizon_seconds,
            at=now,
            fee_policy=fee_policy if fee_error is None else None,
            source_verification=source_verification,
        )

        if token is None:
            return result(
                "UNRESOLVED",
                "claim_not_acquired",
            )

        def finish_abstention(
            reason: str,
            *,
            model_p: float | None = None,
            market_p: float | None = None,
            prediction_market_p: float | None = None,
        ) -> AdapterResult:
            completed = self.journal.complete_abstention(
                condition_id=market,
                horizon_seconds=horizon_seconds,
                claim_token=token,
                reason=reason,
                at=now,
                prediction_market_probability_yes=prediction_market_p,
                model_probability_yes=model_p,
                market_probability_yes=market_p,
            )

            if not completed:
                raise RuntimeError("Journal abstention completion failed")

            return result("ABSTAIN", reason)

        if fee_error is not None:
            return finish_abstention(fee_error)

        store = getattr(self.journal, "store", None)
        with store.atomic() if store is not None else nullcontext():
            # The runner evaluates HGB3 at the historical
            # prediction cutoff and evaluates trade entry
            # against the current execution snapshot.
            #
            # Unexpected exceptions intentionally leave
            # PROCESSING in place for investigation.
            decision = self.runner.evaluate(
                snapshot=prediction_snapshot,
                execution_snapshot=execution_snapshot,
                history=history,
                horizon_seconds=horizon_seconds,
                decision_at_utc=now,
                sources=sources,
                fee_rate=fee_rate,
                fee_policy=fee_policy,
                require_fee_provenance=require_fee_provenance,
                kill_switch=kill_switch,
            )

            # Always check the trading ledger first.
            # A runner may have reserved/rejected/filled
            # a position before returning an abstention.
            reconciliation = self.reconciler.reconcile(
                condition_id=market,
                horizon_seconds=horizon_seconds,
                claim_token=token,
                at=now,
            )

            if reconciliation.status in ("SHADOW_FILLED", "ABSTAIN"):
                return result(
                    reconciliation.status,
                    reconciliation.reason,
                )

            if (
                reconciliation.reason == "no_trading_ledger_entry"
                and decision.status == "ABSTAIN"
            ):
                return finish_abstention(
                    decision.reason,
                    model_p=decision.model_probability_yes,
                    market_p=decision.market_probability_yes,
                    prediction_market_p=(decision.prediction_market_probability_yes),
                )

            # If a reservation exists but cannot be
            # reconciled, leave the claim PROCESSING.
            # Never retry or manufacture a fill.
            return result(
                "UNRESOLVED",
                reconciliation.reason,
            )
