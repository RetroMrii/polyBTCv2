from dataclasses import replace

import pytest

from polybtc.strategy.vnext import (
    Action,
    StrategyConfig,
    StrategyInput,
    VNextStrategy,
)


def example_input():
    return StrategyInput(
        condition_id="test-market-001",
        horizon_seconds=60,
        model_probability_yes=0.73,
        market_probability_yes=0.72,
        yes_ask=0.65,
        no_ask=0.36,
        yes_ask_size=10.0,
        no_ask_size=10.0,
        yes_book_age_ms=100.0,
        no_book_age_ms=100.0,
        reference_age_ms=100.0,
        tick_size=0.01,
        fee_per_share=0.01,
    )


def test_yes_trade():
    strategy = VNextStrategy()
    decision = strategy.evaluate(example_input())

    assert decision.action == Action.BUY_YES
    assert decision.reason == "positive_net_ev"
    assert decision.execution_price == pytest.approx(0.66)
    assert decision.net_ev_per_share == pytest.approx(0.05)


def test_no_trade():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        model_probability_yes=0.27,
        market_probability_yes=0.28,
        no_ask=0.65,
    )

    decision = strategy.evaluate(item)

    assert decision.action == Action.BUY_NO
    assert decision.execution_price == pytest.approx(0.66)
    assert decision.net_ev_per_share == pytest.approx(0.05)


def test_price_ceiling():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        yes_ask=0.70,
    )

    decision = strategy.evaluate(item)

    assert decision.action == Action.ABSTAIN
    assert decision.reason == "price_ceiling_exceeded"


def test_disagreement():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        model_probability_yes=0.40,
    )

    decision = strategy.evaluate(item)

    assert decision.action == Action.ABSTAIN
    assert decision.reason == "model_market_disagreement"


def test_stale_quote():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        yes_book_age_ms=1000.0,
    )

    decision = strategy.evaluate(item)

    assert decision.reason == "stale_book"


def test_missing_probability():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        market_probability_yes=None,
    )

    decision = strategy.evaluate(item)

    assert decision.reason == "missing_market_probability"


def test_insufficient_depth():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        yes_ask_size=2.0,
    )

    decision = strategy.evaluate(item)

    assert decision.reason == "insufficient_depth"


def test_negative_ev():
    strategy = VNextStrategy()

    item = replace(
        example_input(),
        market_probability_yes=0.67,
        model_probability_yes=0.68,
        yes_ask=0.68,
    )

    decision = strategy.evaluate(item)

    assert decision.reason == "insufficient_net_ev"


def test_fixed_price_ceiling():
    with pytest.raises(ValueError):
        VNextStrategy(StrategyConfig(max_execution_price=0.80))


def test_deterministic():
    strategy = VNextStrategy()
    item = example_input()

    assert strategy.evaluate(item) == strategy.evaluate(item)
