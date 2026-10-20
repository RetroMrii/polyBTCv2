from polybtc.execution.model import (
    ExecutionRequest,
    ExecutionSide,
    FillStatus,
    MarketExecutionState,
    calculate_taker_fee,
    execute_level1_crossing,
    settlement_pnl,
    execute_depth_constrained_crossing,
)


def test_level1_crossing_and_settlement() -> None:
    market = MarketExecutionState(
        yes_ask=0.42,
        no_ask=0.59,
    )

    yes_result = execute_level1_crossing(
        ExecutionRequest(
            side=ExecutionSide.YES,
            requested_size=1.0,
        ),
        market,
    )

    assert yes_result.status == FillStatus.FILLED

    assert yes_result.execution_price == 0.42
    assert yes_result.filled_size == 1.0

    yes_pnl = settlement_pnl(
        side=ExecutionSide.YES,
        label_yes=1,
        execution_price=0.42,
        filled_size=1.0,
    )

    assert abs(yes_pnl - 0.58) < 1e-12

    no_result = execute_level1_crossing(
        ExecutionRequest(
            side=ExecutionSide.NO,
            requested_size=1.0,
        ),
        market,
    )

    assert no_result.status == FillStatus.FILLED

    assert no_result.execution_price == 0.59

    no_pnl = settlement_pnl(
        side=ExecutionSide.NO,
        label_yes=1,
        execution_price=0.59,
        filled_size=1.0,
    )

    assert abs(no_pnl - (-0.59)) < 1e-12


def test_crypto_taker_fee() -> None:
    fee = calculate_taker_fee(
        filled_size=100.0,
        execution_price=0.50,
        fee_rate=0.07,
    )

    assert fee == 1.75


def test_taker_fee_is_price_symmetric() -> None:
    low = calculate_taker_fee(
        filled_size=100.0,
        execution_price=0.30,
        fee_rate=0.07,
    )

    high = calculate_taker_fee(
        filled_size=100.0,
        execution_price=0.70,
        fee_rate=0.07,
    )

    assert low == high


def test_depth_constrained_execution() -> None:
    market = MarketExecutionState(
        yes_ask=0.42,
        no_ask=0.59,
    )

    filled = execute_depth_constrained_crossing(
        ExecutionRequest(
            side=ExecutionSide.YES,
            requested_size=5.0,
        ),
        market,
        available_ask_size=10.0,
        minimum_order_size=5.0,
    )

    assert filled.status == FillStatus.FILLED
    assert filled.filled_size == 5.0
    assert filled.execution_price == 0.42

    insufficient = execute_depth_constrained_crossing(
        ExecutionRequest(
            side=ExecutionSide.YES,
            requested_size=5.0,
        ),
        market,
        available_ask_size=4.99,
        minimum_order_size=5.0,
    )

    assert insufficient.status == FillStatus.REJECTED
    assert insufficient.filled_size == 0.0
    assert insufficient.reason == "insufficient_top_of_book_depth"

    below_minimum = execute_depth_constrained_crossing(
        ExecutionRequest(
            side=ExecutionSide.YES,
            requested_size=1.0,
        ),
        market,
        available_ask_size=100.0,
        minimum_order_size=5.0,
    )

    assert below_minimum.status == FillStatus.REJECTED
    assert below_minimum.reason == "below_minimum_order_size"
