from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from polybtc.shadow.ledger_vnext import VNextShadowLedger
from polybtc.shadow.orchestrator_vnext import (
    VNextDecisionOrchestrator,
)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: str
    reason: str
    condition_id: str
    horizon_seconds: int


def _stamp(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware timestamp required")

    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class VNextClaimReconciler:
    """
    Reconcile claimed journal decisions against durable
    shadow-ledger outcomes.

    Does not place orders, reserve positions, execute
    fills, settle markets, or retry failed decisions.
    """

    def __init__(
        self,
        *,
        journal: VNextDecisionOrchestrator,
        ledger: VNextShadowLedger,
    ) -> None:
        if journal.path.resolve() == ledger.path.resolve() and not (getattr(journal,"store",None) is not None and journal.store is getattr(ledger,"store",None)):
            raise ValueError("Journal and trading ledger must be separate")

        self.journal = journal
        self.ledger = ledger

    def reconcile(
        self,
        *,
        condition_id: str,
        horizon_seconds: int,
        claim_token: str,
        at: datetime,
    ) -> ReconciliationResult:
        market = condition_id.strip().lower()
        now = _stamp(at)

        if not market:
            raise ValueError("Missing condition_id")

        if not isinstance(claim_token, str) or not claim_token:
            raise ValueError("Missing claim_token")

        def result(status, reason):
            return ReconciliationResult(
                status=status,
                reason=reason,
                condition_id=market,
                horizon_seconds=horizon_seconds,
            )

        # Lock the journal first. Only one reconciliation
        # can complete this claim at a time.
        conn = self.journal._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT *
                FROM decisions
                WHERE condition_id=?
                  AND horizon_seconds=?
            """,
                (market, horizon_seconds),
            ).fetchone()

            if row is None:
                conn.execute("COMMIT")
                return result("UNRESOLVED", "unknown_decision")

            if row["status"] != "PROCESSING":
                conn.execute("COMMIT")
                return result(
                    "UNRESOLVED",
                    "decision_not_processing",
                )

            if row["claim_token"] != claim_token:
                conn.execute("COMMIT")
                return result(
                    "UNRESOLVED",
                    "claim_ownership_mismatch",
                )

            if row["claimed_at_utc"] is None or row["claimed_at_utc"] > now:
                raise RuntimeError("Invalid reconciliation timestamp")

            positions = [p for p in self.ledger.positions() if p.condition_id == market]

            if not positions:
                conn.execute("COMMIT")
                return result(
                    "UNRESOLVED",
                    "no_trading_ledger_entry",
                )

            if len(positions) != 1:
                raise RuntimeError("Ambiguous trading ledger position")

            position = positions[0]

            if position.status not in ("PENDING", "REJECTED", "FILLED", "SETTLED"):
                raise RuntimeError("Unsupported ledger status")

            context = self.ledger.decision_context(market)

            if context is None:
                raise RuntimeError("Missing immutable decision provenance")

            if context.get("condition_id") != market:
                raise RuntimeError("Decision context market mismatch")

            if context.get("snapshot_id") != row["snapshot_id"]:
                raise RuntimeError("Decision snapshot mismatch")

            prediction_time = datetime.fromisoformat(
                context["prediction_timestamp_utc"]
            )

            if _stamp(prediction_time) != row["target_at_utc"]:
                raise RuntimeError("Prediction timestamp mismatch")

            action = context.get("strategy_action")

            expected_side = {
                "BUY_YES": "YES",
                "BUY_NO": "NO",
            }.get(action)

            if expected_side != position.side:
                raise RuntimeError("Trading side/context mismatch")

            events = self.ledger.events(market)
            kinds = [e["event_type"] for e in events]

            if not kinds or kinds[0] != "ENTRY_RESERVED":
                raise RuntimeError("Missing prospective reservation event")

            # A pending reservation must also have
            # consistent decision provenance.
            if position.status == "PENDING":
                if kinds != ["ENTRY_RESERVED"]:
                    raise RuntimeError("Pending reservation audit mismatch")

                conn.execute("COMMIT")
                return result(
                    "UNRESOLVED",
                    "pending_execution",
                )

            if position.status == "REJECTED":
                if kinds != [
                    "ENTRY_RESERVED",
                    "ENTRY_REJECTED",
                ]:
                    raise RuntimeError("Rejection audit mismatch")

                final_status = "ABSTAIN"
                final_reason = "execution_rejected"
                price = None

            else:
                expected_events = [
                    "ENTRY_RESERVED",
                    "ENTRY_FILLED",
                ]

                if position.status == "SETTLED":
                    expected_events.append("ENTRY_SETTLED")

                if kinds != expected_events:
                    raise RuntimeError("Fill audit mismatch")

                price = position.execution_price

                if not math.isfinite(price) or not 0 < price <= 0.70:
                    raise RuntimeError("Invalid recorded fill price")

                final_status = "SHADOW_FILLED"
                final_reason = "ledger_fill_reconciled"

            model_p = float(context["model_probability_yes"])
            market_p = float(context["market_probability_yes"])

            if not all(math.isfinite(p) and 0 <= p <= 1 for p in (model_p, market_p)):
                raise RuntimeError("Invalid audited probabilities")

            cursor = conn.execute(
                """
                UPDATE decisions
                SET status=?,
                    reason=?,
                    completed_at_utc=?,
                    model_probability_yes=?,
                    market_probability_yes=?,
                    execution_price=?
                WHERE condition_id=?
                  AND horizon_seconds=?
                  AND status='PROCESSING'
                  AND claim_token=?
                  AND claimed_at_utc <= ?
            """,
                (
                    final_status,
                    final_reason,
                    now,
                    model_p,
                    market_p,
                    price,
                    market,
                    horizon_seconds,
                    claim_token,
                    now,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Journal completion lost ownership")

            conn.execute("COMMIT")

            return result(final_status, final_reason)

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()
