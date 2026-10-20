from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from polybtc.data.schema import SnapshotRecord
from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy, FeeCacheError
from polybtc.data.dataset.features import build_snapshot_features
from polybtc.modeling.inference import FrozenProbabilityModel
from polybtc.risk.vnext import VNextRiskGate
from polybtc.shadow.executor_vnext import (
    ShadowExecutionConfig,
    ShadowExecutionQuote,
    ShadowFillStatus,
    VNextShadowExecutor,
)
from polybtc.shadow.ledger_vnext import (
    DecisionContext,
    VNextShadowLedger,
)
from polybtc.strategy.vnext import (
    Action,
    StrategyConfig,
    StrategyInput,
    VNextStrategy,
)


RUNNER_VERSION = "shadow_runner_vnext_v1_2_prediction_first"
LOG = logging.getLogger("polybtc.shadow.vnext.runner")

FEATURE_KEYS = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)

from polybtc.data.paper_policy_vnext import PAPER_POLICY, MAX_BOOK_AGE_MS, MAX_REFERENCE_AGE_MS
HORIZONS = frozenset(PAPER_POLICY.horizons)

ANCHOR_LAG_SECONDS = PAPER_POLICY.anchor_lag_seconds


MAX_EXECUTION_PRICE = 0.70

FEE_POLICY_VERSION = "research_fee_formula_v1"


from polybtc.data.verified_sources_vnext import VerifiedSources

@dataclass(frozen=True, slots=True)
class RunnerResult:
    status: str
    reason: str
    condition_id: str
    horizon_seconds: int

    model_probability_yes: float | None = None
    market_probability_yes: float | None = None
    prediction_market_probability_yes: float | None = None

    execution_price: float | None = None
    estimated_net_ev_per_share: float | None = None


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _finite(
    value: object,
    *,
    positive: bool = False,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(number) and (not positive or number > 0)


def _age_ms(
    now: datetime,
    earlier: datetime,
) -> float:
    return (_utc(now) - _utc(earlier)).total_seconds() * 1000.0


def _same_market(
    first: str,
    second: str,
) -> bool:
    return first.strip().lower() == second.strip().lower()


from polybtc.data.causal_features_vnext import reference_anchor_30s, _reference_return_30s


class VNextShadowRunner:
    """
    Single-horizon prospective shadow evaluation.

    Prediction:
        Uses the horizon-selected historical snapshot
        and causal historical reference features.

    Execution:
        Uses a separately supplied, recently collected
        market snapshot.

    Safety:
        No real orders.
        No network requests.
        No automatic settlement.
        No market discovery.
        No strategy or risk modifications.

    The existing SQLite v3 trading ledger remains
    authoritative for reservations and fills.
    """

    def __init__(
        self,
        *,
        model_path: Path,
        ledger_path: Path,
        clock=None,
        store=None,
    ) -> None:
        self.clock = clock
        self.model = FrozenProbabilityModel(model_path)

        self.ledger = VNextShadowLedger(ledger_path, store=store)

        # Carry the runtime's reference contract through the final strategy
        # gate too; its standalone research default is intentionally separate.
        self.strategy = VNextStrategy(StrategyConfig(max_reference_age_ms=MAX_REFERENCE_AGE_MS, max_book_age_ms=MAX_BOOK_AGE_MS))
        self.risk = VNextRiskGate()
        self.executor = VNextShadowExecutor(ShadowExecutionConfig(max_reference_age_ms=MAX_REFERENCE_AGE_MS))

    def evaluate(
        self,
        *,
        snapshot: SnapshotRecord,
        history: list[SnapshotRecord],
        horizon_seconds: int,
        decision_at_utc: datetime,
        sources: VerifiedSources,
        fee_rate: float | None,
        fee_policy: CachedFeePolicy | None = None,
        require_fee_provenance: bool = False,
        execution_snapshot: SnapshotRecord | None = None,
        kill_switch: bool = False,
    ) -> RunnerResult:

        now = _utc(decision_at_utc)

        market = snapshot.condition_id.strip().lower()
        predicted_model_p: float | None = None
        prediction_market_p: float | None = None

        def stop(
            reason: str,
            *,
            model_p: float | None = None,
            market_p: float | None = None,
        ) -> RunnerResult:
            return RunnerResult(
                status="ABSTAIN",
                reason=reason,
                condition_id=market,
                horizon_seconds=horizon_seconds,
                model_probability_yes=(
                    predicted_model_p if model_p is None else model_p
                ),
                prediction_market_probability_yes=prediction_market_p,
                market_probability_yes=market_p,
            )

        # -------------------------------------------
        # 1. Basic market and horizon validation
        # -------------------------------------------

        if not market:
            return stop("invalid_market_id")

        if horizon_seconds not in HORIZONS:
            return stop("unsupported_horizon")

        if snapshot.market_end_at is None:
            return stop("missing_market_expiry")
        # -------------------------------------------
        # 3. Prediction target timestamp
        # -------------------------------------------

        market_end = _utc(snapshot.market_end_at)

        prediction_at = market_end - timedelta(seconds=horizon_seconds)

        if now < prediction_at:
            return stop("before_target_horizon")

        if now >= market_end:
            return stop("market_already_expired")

        # Historical prediction data must have been
        # available at the target horizon.

        if (
            _utc(snapshot.observed_at) > prediction_at
            or _utc(snapshot.ingested_at) > prediction_at
        ):
            return stop("prediction_snapshot_not_causal")

        if snapshot.reference_timestamp is None:
            return stop("missing_prediction_reference_timestamp")

        if _utc(snapshot.reference_timestamp) > prediction_at:
            return stop("noncausal_prediction_reference")

        # Prediction-time market baseline.
        # Derived only from the causally selected
        # historical prediction snapshot.
        prediction_features = build_snapshot_features(snapshot)
        prediction_mid = prediction_features.normalized_yes_mid

        if _finite(prediction_mid) and 0.0 <= float(prediction_mid) <= 1.0:
            prediction_market_p = float(prediction_mid)

        distance = prediction_features.relative_distance_from_strike

        reference_return_30s = _reference_return_30s(
            history,
            snapshot,
            decision_at=prediction_at,
        )

        if not _finite(distance):
            return stop("missing_relative_distance")

        if not _finite(reference_return_30s):
            return stop("missing_reference_return_30s")

        model_features = {
            "relative_distance_from_strike": float(distance),
            "target_horizon_seconds": float(horizon_seconds),
            "reference_return_30s": float(reference_return_30s),
        }

        # -------------------------------------------
        # 2. HGB3 inference from causal features
        # -------------------------------------------

        prediction = self.model.predict(model_features)

        model_p = prediction.probability_yes

        if not _finite(model_p) or not 0 <= model_p <= 1:
            return stop("invalid_model_probability")

        predicted_model_p = float(model_p)

        # -------------------------------------------
        # 2. Provenance verification
        # -------------------------------------------

        if not isinstance(
            sources,
            VerifiedSources,
        ):
            return stop("missing_source_verification")

        if not all(
            (
                sources.reference_source_verified,
                sources.yes_book_source_verified,
                sources.no_book_source_verified,
                sources.fee_policy_verified,
            )
        ):
            return stop("unverified_input_provenance")

        # -------------------------------------------
        # Durable claim, evidence lookup and inference can consume the quote
        # budget. Prospective runtimes recheck real time after that work.
        if self.clock is not None:
            measured = _utc(self.clock())
            if measured < now:
                return stop("evaluation_clock_moved_backwards")
            now = measured
            if now >= market_end:
                return stop("market_expired")

        # Cached evidence is required on the cache-backed path. Legacy research
        # callers remain compatible, but have unknown descriptor provenance.
        if fee_policy is None and require_fee_provenance:
            return stop("missing_fee_provenance")
        if fee_policy is not None:
            if not isinstance(fee_policy, CachedFeePolicy):
                return stop("invalid_fee_provenance")
            try:
                fee_policy.validate_for_decision(market, fee_rate, now)
            except (FeeCacheError, ValueError, TypeError):
                return stop("invalid_fee_provenance")

        # 4. Execution snapshot selection
        # -------------------------------------------

        if execution_snapshot is None:
            # Legacy same-time path for existing
            # integration tests.
            #
            # Prospective evaluation MUST provide
            # a separate execution snapshot.
            if now != prediction_at:
                return stop("missing_execution_snapshot")

            quote_snapshot = snapshot

        else:
            quote_snapshot = execution_snapshot

            if not _same_market(
                quote_snapshot.condition_id,
                market,
            ):
                return stop("execution_market_mismatch")

            if (
                quote_snapshot.market_end_at is None
                or _utc(quote_snapshot.market_end_at) != market_end
            ):
                return stop("execution_expiry_mismatch")

            if (
                not isinstance(
                    quote_snapshot.snapshot_id,
                    str,
                )
                or not quote_snapshot.snapshot_id.strip()
            ):
                return stop("missing_execution_snapshot_id")

            if _utc(quote_snapshot.observed_at) < prediction_at:
                return stop("execution_snapshot_predates_target")

        # An execution snapshot must have actually
        # been observed and available by now.

        if (
            _utc(quote_snapshot.observed_at) > now
            or _utc(quote_snapshot.ingested_at) > now
        ):
            return stop("execution_snapshot_not_available")

        # -------------------------------------------
        # 5. Execution source timestamps
        # -------------------------------------------

        if (
            quote_snapshot.reference_timestamp is None
            or quote_snapshot.yes_book_timestamp is None
            or quote_snapshot.no_book_timestamp is None
        ):
            return stop("missing_execution_source_timestamps")

        reference_age = _age_ms(
            now,
            quote_snapshot.reference_timestamp,
        )

        yes_age = _age_ms(
            now,
            quote_snapshot.yes_book_timestamp,
        )

        no_age = _age_ms(
            now,
            quote_snapshot.no_book_timestamp,
        )
        LOG.info("execution_freshness market=%s horizon=%s evaluated_at=%s snapshot=%s reference_age_ms=%.3f yes_age_ms=%.3f no_age_ms=%.3f reference_limit_ms=%s book_limit_ms=%s",
                 market, horizon_seconds, now.isoformat(), quote_snapshot.snapshot_id,
                 reference_age, yes_age, no_age, MAX_REFERENCE_AGE_MS, MAX_BOOK_AGE_MS)

        if (
            min(
                reference_age,
                yes_age,
                no_age,
            )
            < 0
        ):
            return stop("future_source_timestamp")

        if reference_age > MAX_REFERENCE_AGE_MS:
            return stop("stale_reference")

        if (
            max(
                yes_age,
                no_age,
            )
            > MAX_BOOK_AGE_MS
        ):
            return stop("stale_market_books")

        # -------------------------------------------
        # 6. Fee validation
        # -------------------------------------------

        if not _finite(fee_rate) or float(fee_rate) < 0:
            return stop("missing_or_invalid_fee_rate")

        # -------------------------------------------
        # 9. Execution-time market probability
        # -------------------------------------------

        execution_features = build_snapshot_features(quote_snapshot)

        market_p = execution_features.normalized_yes_mid

        if not _finite(market_p) or not 0 <= market_p <= 1:
            return stop(
                "missing_market_probability",
                model_p=model_p,
            )

        market_p = float(market_p)

        # -------------------------------------------
        # 10. Fee allowance
        # -------------------------------------------

        # Current research fee model:
        #
        # fee = size * fee_rate * price * (1-price)
        #
        # For 0 <= price <= 1:
        #
        # price * (1-price) <= 0.25
        #
        # The fee allowance includes a conservative
        # margin for order-level fee rounding.

        estimated_fee_per_share = float(fee_rate) / 4.0 + 0.00001

        # -------------------------------------------
        # 11. Tick validation
        # -------------------------------------------

        if not _finite(
            quote_snapshot.yes_tick_size,
            positive=True,
        ) or not _finite(
            quote_snapshot.no_tick_size,
            positive=True,
        ):
            return stop(
                "missing_tick_size",
                model_p=model_p,
                market_p=market_p,
            )

        # Strategy currently accepts one tick size.
        # Using the larger YES/NO tick is conservative
        # for direction-independent evaluation.

        conservative_tick = max(
            float(quote_snapshot.yes_tick_size),
            float(quote_snapshot.no_tick_size),
        )

        # -------------------------------------------
        # 12. Strategy evaluation
        # -------------------------------------------

        strategy_input = StrategyInput(
            condition_id=market,
            horizon_seconds=horizon_seconds,
            model_probability_yes=model_p,
            market_probability_yes=market_p,
            yes_ask=quote_snapshot.yes_ask,
            no_ask=quote_snapshot.no_ask,
            yes_ask_size=(quote_snapshot.yes_ask_size),
            no_ask_size=(quote_snapshot.no_ask_size),
            yes_book_age_ms=yes_age,
            no_book_age_ms=no_age,
            reference_age_ms=reference_age,
            tick_size=conservative_tick,
            fee_per_share=(estimated_fee_per_share),
        )

        decision = self.strategy.evaluate(strategy_input)
        LOG.info("strategy_evaluated market=%s horizon=%s evaluated_at=%s action=%s reason=%s",
                 market, horizon_seconds, now.isoformat(), decision.action.value, decision.reason)

        if decision.action == Action.ABSTAIN:
            return stop(
                decision.reason,
                model_p=model_p,
                market_p=market_p,
            )

        # -------------------------------------------
        # 13. Selected execution side
        # -------------------------------------------

        is_yes = decision.action == Action.BUY_YES

        selected_ask = quote_snapshot.yes_ask if is_yes else quote_snapshot.no_ask

        selected_depth = (
            quote_snapshot.yes_ask_size if is_yes else quote_snapshot.no_ask_size
        )

        selected_tick = (
            quote_snapshot.yes_tick_size if is_yes else quote_snapshot.no_tick_size
        )

        minimum_size = (
            quote_snapshot.yes_min_order_size
            if is_yes
            else quote_snapshot.no_min_order_size
        )

        selected_book_timestamp = (
            quote_snapshot.yes_book_timestamp
            if is_yes
            else quote_snapshot.no_book_timestamp
        )

        if not _finite(
            selected_ask,
            positive=True,
        ):
            return stop(
                "missing_selected_ask",
                model_p=model_p,
                market_p=market_p,
            )

        if not _finite(
            selected_depth,
            positive=True,
        ):
            return stop(
                "missing_selected_depth",
                model_p=model_p,
                market_p=market_p,
            )

        if not _finite(
            selected_tick,
            positive=True,
        ):
            return stop(
                "missing_selected_tick",
                model_p=model_p,
                market_p=market_p,
            )

        if not _finite(
            minimum_size,
            positive=True,
        ):
            return stop(
                "missing_minimum_order_size",
                model_p=model_p,
                market_p=market_p,
            )

        # -------------------------------------------
        # 14. Final strategy price ceiling
        # -------------------------------------------

        if decision.execution_price is None:
            return stop(
                "missing_strategy_execution_price",
                model_p=model_p,
                market_p=market_p,
            )

        if (
            not _finite(
                decision.execution_price,
                positive=True,
            )
            or float(decision.execution_price) > MAX_EXECUTION_PRICE
        ):
            return stop(
                "execution_price_ceiling",
                model_p=model_p,
                market_p=market_p,
            )

        # -------------------------------------------
        # 15. Immutable decision provenance
        # -------------------------------------------

        decision_id = f"vnext_v1:{market}:{horizon_seconds}:{snapshot.snapshot_id}"

        context = DecisionContext(
            decision_id=decision_id,
            model_version=(prediction.model_version),
            calibration_version=(prediction.calibration_version),
            model_sha256=(self.model.model_sha256),
            # Historical prediction cutoff,
            # not the execution evaluation time.
            prediction_timestamp_utc=(prediction_at),
            features=model_features,
            model_probability_yes=model_p,
            market_probability_yes=market_p,
            observed_ask=float(selected_ask),
            selected_tick_size=float(selected_tick),
            selected_ask_depth=float(selected_depth),
            quote_observed_at_utc=_utc(selected_book_timestamp),
            reference_source_at_utc=_utc(quote_snapshot.reference_timestamp),
            reference_timestamp_provenance=("source_verified"),
            quote_timestamp_provenance=("source_verified"),
            fee_policy_version=(FEE_POLICY_VERSION),
            fee_rate=float(fee_rate),
            estimated_fee_per_share=(estimated_fee_per_share),
            estimated_net_ev_per_share=float(decision.net_ev_per_share),
            strategy_action=(decision.action.value),
            # The journal identifies the historical
            # prediction snapshot, not the later quote.
            snapshot_id=(snapshot.snapshot_id),
            fee_policy=fee_policy,
        )

        # -------------------------------------------
        # 16. Transactional risk reservation
        # -------------------------------------------

        reservation = self.ledger.reserve(
            decision=decision,
            risk_gate=self.risk,
            requested_size=5.0,
            minimum_order_size=float(minimum_size),
            at=now,
            kill_switch=kill_switch,
            decision_context=context,
        )

        if not reservation.approved:
            return stop(
                f"risk:{reservation.reason}",
                model_p=model_p,
                market_p=market_p,
            )

        # -------------------------------------------
        # 17. Shadow execution quote
        # -------------------------------------------

        quote = ShadowExecutionQuote(
            condition_id=market,
            # Selected-side upstream book timestamp.
            observed_at_utc=_utc(selected_book_timestamp),
            # Execution-time reference event timestamp.
            reference_observed_at_utc=_utc(quote_snapshot.reference_timestamp),
            yes_ask=(quote_snapshot.yes_ask),
            no_ask=(quote_snapshot.no_ask),
            yes_ask_size=(quote_snapshot.yes_ask_size),
            no_ask_size=(quote_snapshot.no_ask_size),
            yes_tick_size=(quote_snapshot.yes_tick_size),
            no_tick_size=(quote_snapshot.no_tick_size),
            minimum_order_size=float(minimum_size),
            fee_rate=float(fee_rate),
        )

        # -------------------------------------------
        # 18. Hypothetical execution
        # -------------------------------------------

        execution_at = _utc(self.clock()) if self.clock is not None else now
        if execution_at < now:
            # Leave the reservation for explicit reconciliation; never fill
            # using an invented timestamp after a clock rollback.
            raise RuntimeError("Execution clock moved backwards")
        execution = self.executor.execute(
            ledger=self.ledger,
            quote=quote,
            at=execution_at,
        )

        if execution.status != ShadowFillStatus.FILLED:
            return stop(
                f"execution:{execution.reason}",
                model_p=model_p,
                market_p=market_p,
            )

        # -------------------------------------------
        # 19. Final successful shadow result
        # -------------------------------------------

        if (
            execution.execution_price is None
            or not _finite(
                execution.execution_price,
                positive=True,
            )
            or float(execution.execution_price) > MAX_EXECUTION_PRICE
        ):
            raise RuntimeError(
                "Executor reported filled trade outside approved price ceiling"
            )

        return RunnerResult(
            status="SHADOW_FILLED",
            reason="shadow_full_fill",
            condition_id=market,
            horizon_seconds=horizon_seconds,
            prediction_market_probability_yes=prediction_market_p,
            model_probability_yes=model_p,
            market_probability_yes=market_p,
            execution_price=(execution.execution_price),
            estimated_net_ev_per_share=(decision.net_ev_per_share),
        )
