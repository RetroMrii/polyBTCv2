from polybtc.strategy.expected_value import (
    StrategyAction,
    StrategyParameters,
    TradeSide,
    evaluate_expected_value,
)


def test_selects_yes_when_yes_has_greater_ev():
    decision = evaluate_expected_value(
        p_yes=0.70,
        yes_ask=0.55,
        no_ask=0.46,
    )

    assert decision.action == StrategyAction.TRADE

    assert decision.side == TradeSide.YES

    assert abs(decision.yes_gross_ev_per_share - 0.15) < 1e-12


def test_selects_no_when_no_has_greater_ev():
    decision = evaluate_expected_value(
        p_yes=0.30,
        yes_ask=0.45,
        no_ask=0.55,
    )

    assert decision.action == StrategyAction.TRADE

    assert decision.side == TradeSide.NO

    assert abs(decision.no_gross_ev_per_share - 0.15) < 1e-12


def test_transaction_cost_reduces_net_ev():
    decision = evaluate_expected_value(
        p_yes=0.60,
        yes_ask=0.55,
        no_ask=0.46,
        estimated_cost_per_share=0.02,
    )

    assert abs(decision.selected_net_ev_per_share - 0.03) < 1e-12


def test_skips_when_net_ev_below_threshold():
    parameters = StrategyParameters(
        minimum_net_ev_per_share=0.05,
    )

    decision = evaluate_expected_value(
        p_yes=0.60,
        yes_ask=0.57,
        no_ask=0.44,
        parameters=parameters,
    )

    assert decision.action == StrategyAction.SKIP

    assert decision.reason == "net_ev_below_threshold"


def test_price_filter_can_reject_both_sides():
    parameters = StrategyParameters(
        minimum_entry_price=0.40,
        maximum_entry_price=0.60,
    )

    decision = evaluate_expected_value(
        p_yes=0.90,
        yes_ask=0.80,
        no_ask=0.20,
        parameters=parameters,
    )

    assert decision.action == StrategyAction.SKIP

    assert decision.reason == "no_allowed_side"
