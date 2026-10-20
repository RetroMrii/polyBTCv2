from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TradeSide(StrEnum):
    YES = "YES"
    NO = "NO"


class StrategyAction(StrEnum):
    TRADE = "TRADE"
    SKIP = "SKIP"


@dataclass(
    frozen=True,
    slots=True,
)
class StrategyParameters:
    minimum_net_ev_per_share: float = 0.0

    minimum_entry_price: float | None = None
    maximum_entry_price: float | None = None

    allow_yes: bool = True
    allow_no: bool = True


@dataclass(
    frozen=True,
    slots=True,
)
class ExpectedValueDecision:
    action: StrategyAction
    side: TradeSide | None

    p_yes: float
    p_no: float

    yes_ask: float
    no_ask: float

    yes_gross_ev_per_share: float
    no_gross_ev_per_share: float

    estimated_cost_per_share: float

    selected_price: float | None
    selected_gross_ev_per_share: float | None
    selected_net_ev_per_share: float | None

    reason: str


def _validate_probability(
    value: float,
    *,
    name: str,
) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _validate_price(
    value: float,
    *,
    name: str,
) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _price_allowed(
    price: float,
    parameters: StrategyParameters,
) -> bool:
    if (
        parameters.minimum_entry_price is not None
        and price < parameters.minimum_entry_price
    ):
        return False

    if (
        parameters.maximum_entry_price is not None
        and price >= parameters.maximum_entry_price
    ):
        return False

    return True


def evaluate_expected_value(
    *,
    p_yes: float,
    yes_ask: float,
    no_ask: float,
    estimated_cost_per_share: float = 0.0,
    parameters: StrategyParameters | None = None,
) -> ExpectedValueDecision:
    if parameters is None:
        parameters = StrategyParameters()

    _validate_probability(
        p_yes,
        name="p_yes",
    )

    _validate_price(
        yes_ask,
        name="yes_ask",
    )

    _validate_price(
        no_ask,
        name="no_ask",
    )

    if estimated_cost_per_share < 0.0:
        raise ValueError("estimated_cost_per_share cannot be negative")

    p_no = 1.0 - p_yes

    yes_gross_ev = p_yes - yes_ask

    no_gross_ev = p_no - no_ask

    candidates: list[
        tuple[
            TradeSide,
            float,
            float,
        ]
    ] = []

    if parameters.allow_yes and _price_allowed(
        yes_ask,
        parameters,
    ):
        candidates.append(
            (
                TradeSide.YES,
                yes_ask,
                yes_gross_ev,
            )
        )

    if parameters.allow_no and _price_allowed(
        no_ask,
        parameters,
    ):
        candidates.append(
            (
                TradeSide.NO,
                no_ask,
                no_gross_ev,
            )
        )

    if not candidates:
        return ExpectedValueDecision(
            action=StrategyAction.SKIP,
            side=None,
            p_yes=p_yes,
            p_no=p_no,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_gross_ev_per_share=yes_gross_ev,
            no_gross_ev_per_share=no_gross_ev,
            estimated_cost_per_share=(estimated_cost_per_share),
            selected_price=None,
            selected_gross_ev_per_share=None,
            selected_net_ev_per_share=None,
            reason="no_allowed_side",
        )

    side, price, gross_ev = max(
        candidates,
        key=lambda item: (
            item[2],
            item[0].value,
        ),
    )

    net_ev = gross_ev - estimated_cost_per_share

    if net_ev < parameters.minimum_net_ev_per_share:
        return ExpectedValueDecision(
            action=StrategyAction.SKIP,
            side=side,
            p_yes=p_yes,
            p_no=p_no,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_gross_ev_per_share=yes_gross_ev,
            no_gross_ev_per_share=no_gross_ev,
            estimated_cost_per_share=(estimated_cost_per_share),
            selected_price=price,
            selected_gross_ev_per_share=gross_ev,
            selected_net_ev_per_share=net_ev,
            reason="net_ev_below_threshold",
        )

    return ExpectedValueDecision(
        action=StrategyAction.TRADE,
        side=side,
        p_yes=p_yes,
        p_no=p_no,
        yes_ask=yes_ask,
        no_ask=no_ask,
        yes_gross_ev_per_share=yes_gross_ev,
        no_gross_ev_per_share=no_gross_ev,
        estimated_cost_per_share=(estimated_cost_per_share),
        selected_price=price,
        selected_gross_ev_per_share=gross_ev,
        selected_net_ev_per_share=net_ev,
        reason="positive_strategy_decision",
    )
