from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Any


REPORT_VERSION = "shadow_performance_vnext_v1"


@dataclass(frozen=True, slots=True)
class SettledTrade:
    condition_id: str
    side: str
    filled_size: float
    execution_price: float
    entry_fee: float
    label_yes: int
    settled_at_utc: datetime

    # Optional additional costs must be explicitly
    # measured or assigned by a versioned policy.
    additional_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class ShadowReport:
    report_version: str
    total_opportunities: int
    decision_counts: dict[str, int]
    abstention_reasons: dict[str, int]
    shadow_filled_decisions: int
    processing_decisions: int
    unresolved_decisions: int

    settled_trades: int
    winning_trades: int
    losing_trades: int

    total_stake: float
    gross_payout: float
    total_costs: float
    net_pnl: float

    roi_on_settled_stake: float | None
    win_rate: float | None
    max_realized_drawdown: float
    market_brier_score: float | None
    brier_markets: int


def _finite(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean financial value")

    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid financial value") from exc

    if not math.isfinite(result):
        raise ValueError("Nonfinite financial value")

    return result


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
        raise ValueError("Invalid market identifier")

    return value.strip().lower()


def _validate_trade(trade: SettledTrade) -> None:
    _market(trade.condition_id)
    _utc(trade.settled_at_utc)

    if trade.side not in ("YES", "NO"):
        raise ValueError("Invalid position side")

    if (
        isinstance(trade.label_yes, bool)
        or type(trade.label_yes) is not int
        or trade.label_yes not in (0, 1)
    ):
        raise ValueError("Invalid settlement outcome")

    quantity = _finite(trade.filled_size)
    price = _finite(trade.execution_price)
    entry_fee = _finite(trade.entry_fee)
    additional_cost = _finite(trade.additional_cost)

    if quantity <= 0:
        raise ValueError("Invalid filled quantity")

    if not 0 < price <= 0.70:
        raise ValueError("Execution price outside vNext ceiling")

    if entry_fee < 0 or additional_cost < 0:
        raise ValueError("Negative recorded cost")


def _pnl(trade: SettledTrade) -> tuple[float, float, float]:
    """
    Binary contract payoff is $1/share on the winning
    outcome and $0/share otherwise.

    Cost basis = filled shares * execution price.
    P&L = payout - stake - fees - additional costs.
    """
    _validate_trade(trade)

    won = (trade.side == "YES" and trade.label_yes == 1) or (
        trade.side == "NO" and trade.label_yes == 0
    )

    stake = trade.filled_size * trade.execution_price
    payout = trade.filled_size if won else 0.0
    costs = trade.entry_fee + trade.additional_cost

    return stake, payout, payout - stake - costs


def build_shadow_report(
    *,
    journal_rows: Iterable[Mapping[str, Any]],
    resolution_rows: Iterable[Mapping[str, Any]],
    settled_trades: Iterable[SettledTrade],
) -> ShadowReport:
    decisions = list(journal_rows)
    resolutions = list(resolution_rows)
    trades = list(settled_trades)

    # Reject contradictory market-resolution evidence.
    labels: dict[str, int] = {}

    for row in resolutions:
        market = _market(row["condition_id"])
        label = row["label_yes"]

        if type(label) is not int or label not in (0, 1):
            raise ValueError("Invalid verified resolution")

        if market in labels and labels[market] != label:
            raise ValueError("Conflicting verified market outcomes")

        labels[market] = label

    counts = Counter(str(row["status"]) for row in decisions)

    reasons = Counter(
        str(row["reason"]) for row in decisions if row["status"] == "ABSTAIN"
    )

    # The reporting view is market-level and considers
    # each market/horizon decision separately.
    identities = set()

    for row in decisions:
        key = (
            _market(row["condition_id"]),
            int(row["horizon_seconds"]),
        )

        if key in identities:
            raise ValueError("Duplicate journal decision")

        identities.add(key)

    pnl_rows: list[tuple[datetime, str, float, float, float]] = []
    seen_trades = set()

    total_stake = 0.0
    gross_payout = 0.0
    total_costs = 0.0
    total_pnl = 0.0
    wins = 0

    for trade in trades:
        market = _market(trade.condition_id)

        if market in seen_trades:
            raise ValueError("Duplicate settled market")

        seen_trades.add(market)

        if market not in labels:
            raise ValueError("Settled trade lacks verified resolution")

        if labels[market] != trade.label_yes:
            raise ValueError("Settled trade and registry disagree")

        stake, payout, pnl = _pnl(trade)
        costs = trade.entry_fee + trade.additional_cost

        total_stake += stake
        gross_payout += payout
        total_costs += costs
        total_pnl += pnl

        if pnl > 0:
            wins += 1

        pnl_rows.append(
            (
                _utc(trade.settled_at_utc),
                market,
                stake,
                payout,
                pnl,
            )
        )

    pnl_rows.sort(key=lambda item: (item[0], item[1]))

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for _, _, _, _, pnl in pnl_rows:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    # Evaluate calibration only where a verified
    # outcome and an actual model probability exist.
    # Multiple horizons from the same market must
    # not silently receive independent market weight.
    market_probabilities: dict[str, list[float]] = {}

    for row in decisions:
        market = _market(row["condition_id"])

        if market not in labels:
            continue

        probability = row.get("model_probability_yes")

        if probability is None:
            continue

        p = _finite(probability)

        if not 0 <= p <= 1:
            raise ValueError("Invalid model probability")

        market_probabilities.setdefault(market, []).append(p)

    # Each market contributes once. The mean across
    # available horizons is a diagnostic aggregation,
    # not a substitute for horizon-specific calibration.
    brier_values = [
        (sum(probabilities) / len(probabilities) - labels[market]) ** 2
        for market, probabilities in market_probabilities.items()
    ]

    brier = sum(brier_values) / len(brier_values) if brier_values else None

    n_trades = len(trades)

    return ShadowReport(
        report_version=REPORT_VERSION,
        total_opportunities=len(decisions),
        decision_counts=dict(sorted(counts.items())),
        abstention_reasons=dict(sorted(reasons.items())),
        shadow_filled_decisions=counts["SHADOW_FILLED"],
        processing_decisions=counts["PROCESSING"],
        unresolved_decisions=(
            counts["PROCESSING"] + counts["AWAITING_EXECUTION_ADAPTER"]
        ),
        settled_trades=n_trades,
        winning_trades=wins,
        losing_trades=n_trades - wins,
        total_stake=total_stake,
        gross_payout=gross_payout,
        total_costs=total_costs,
        net_pnl=total_pnl,
        roi_on_settled_stake=(total_pnl / total_stake if total_stake > 0 else None),
        win_rate=(wins / n_trades if n_trades else None),
        max_realized_drawdown=max_drawdown,
        market_brier_score=brier,
        brier_markets=len(brier_values),
    )
