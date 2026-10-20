from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConsensusSide(str, Enum):
    YES = "YES"
    NO = "NO"


class ConsensusDecision(str, Enum):
    TRADE = "TRADE"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True)
class ConsensusConfig:
    allowed_horizons_seconds: tuple[int, ...] = (
        60,
        30,
    )

    max_probability_gap: float = 0.05

    max_book_age_ms: float = 500.0

    minimum_depth: float = 5.0


@dataclass(frozen=True)
class ConsensusInput:
    condition_id: str

    target_horizon_seconds: int

    model_probability: float

    market_probability: float | None

    yes_ask: float | None
    no_ask: float | None

    yes_top_depth: float | None
    no_top_depth: float | None

    yes_book_age_ms: float | None
    no_book_age_ms: float | None


@dataclass(frozen=True)
class ConsensusResult:
    decision: ConsensusDecision

    side: ConsensusSide | None

    reason: str

    probability_gap: float | None

    selected_ask: float | None

    selected_depth: float | None

    selected_book_age_ms: float | None


def evaluate_consensus(
    *,
    candidate: ConsensusInput,
    config: ConsensusConfig,
) -> ConsensusResult:
    if candidate.target_horizon_seconds not in config.allowed_horizons_seconds:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=None,
            reason="horizon_not_allowed",
            probability_gap=None,
            selected_ask=None,
            selected_depth=None,
            selected_book_age_ms=None,
        )

    if candidate.market_probability is None:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=None,
            reason="missing_market_probability",
            probability_gap=None,
            selected_ask=None,
            selected_depth=None,
            selected_book_age_ms=None,
        )

    model_probability = candidate.model_probability

    market_probability = candidate.market_probability

    probability_gap = abs(model_probability - market_probability)

    if probability_gap > config.max_probability_gap:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=None,
            reason="probability_gap_too_large",
            probability_gap=probability_gap,
            selected_ask=None,
            selected_depth=None,
            selected_book_age_ms=None,
        )

    model_yes = model_probability > 0.5

    market_yes = market_probability > 0.5

    model_no = model_probability < 0.5

    market_no = market_probability < 0.5

    if model_yes and market_yes:
        side = ConsensusSide.YES

        selected_ask = candidate.yes_ask

        selected_depth = candidate.yes_top_depth

        selected_book_age_ms = candidate.yes_book_age_ms

    elif model_no and market_no:
        side = ConsensusSide.NO

        selected_ask = candidate.no_ask

        selected_depth = candidate.no_top_depth

        selected_book_age_ms = candidate.no_book_age_ms

    else:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=None,
            reason="direction_disagreement",
            probability_gap=probability_gap,
            selected_ask=None,
            selected_depth=None,
            selected_book_age_ms=None,
        )

    if selected_ask is None:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=side,
            reason="missing_selected_ask",
            probability_gap=probability_gap,
            selected_ask=None,
            selected_depth=selected_depth,
            selected_book_age_ms=(selected_book_age_ms),
        )

    if selected_depth is None:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=side,
            reason="missing_selected_depth",
            probability_gap=probability_gap,
            selected_ask=selected_ask,
            selected_depth=None,
            selected_book_age_ms=(selected_book_age_ms),
        )

    if selected_depth < config.minimum_depth:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=side,
            reason="insufficient_depth",
            probability_gap=probability_gap,
            selected_ask=selected_ask,
            selected_depth=selected_depth,
            selected_book_age_ms=(selected_book_age_ms),
        )

    if selected_book_age_ms is None:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=side,
            reason="missing_book_age",
            probability_gap=probability_gap,
            selected_ask=selected_ask,
            selected_depth=selected_depth,
            selected_book_age_ms=None,
        )

    if selected_book_age_ms > config.max_book_age_ms:
        return ConsensusResult(
            decision=ConsensusDecision.ABSTAIN,
            side=side,
            reason="stale_book",
            probability_gap=probability_gap,
            selected_ask=selected_ask,
            selected_depth=selected_depth,
            selected_book_age_ms=(selected_book_age_ms),
        )

    return ConsensusResult(
        decision=ConsensusDecision.TRADE,
        side=side,
        reason="consensus_pass",
        probability_gap=probability_gap,
        selected_ask=selected_ask,
        selected_depth=selected_depth,
        selected_book_age_ms=(selected_book_age_ms),
    )
