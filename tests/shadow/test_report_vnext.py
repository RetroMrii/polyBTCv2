from datetime import datetime, timedelta, timezone

import pytest

from polybtc.shadow.report_vnext import (
    SettledTrade,
    build_shadow_report,
)


T0 = datetime(
    2026,
    10,
    9,
    15,
    5,
    tzinfo=timezone.utc,
)


def decision(
    market,
    status,
    *,
    probability=None,
    reason="test",
):
    return {
        "condition_id": market,
        "horizon_seconds": 60,
        "status": status,
        "reason": reason,
        "model_probability_yes": probability,
    }


def resolution(market, label):
    return {
        "condition_id": market,
        "label_yes": label,
        "settlement_status": "SETTLED",
    }


def trade(
    market,
    side,
    label,
    *,
    at=T0,
):
    return SettledTrade(
        condition_id=market,
        side=side,
        filled_size=5,
        execution_price=0.60,
        entry_fee=0.05,
        label_yes=label,
        settled_at_utc=at,
    )


def test_empty_report():
    report = build_shadow_report(
        journal_rows=[],
        resolution_rows=[],
        settled_trades=[],
    )

    assert report.total_opportunities == 0
    assert report.net_pnl == 0
    assert report.roi_on_settled_stake is None
    assert report.market_brier_score is None


def test_profit_and_loss():
    report = build_shadow_report(
        journal_rows=[
            decision("m1", "SHADOW_FILLED", probability=0.8),
            decision("m2", "SHADOW_FILLED", probability=0.7),
        ],
        resolution_rows=[
            resolution("m1", 1),
            resolution("m2", 0),
        ],
        settled_trades=[
            trade("m1", "YES", 1),
            trade(
                "m2",
                "YES",
                0,
                at=T0 + timedelta(seconds=1),
            ),
        ],
    )

    # Win: 5 - 3 - 0.05 = +1.95
    # Loss: 0 - 3 - 0.05 = -3.05
    assert report.net_pnl == pytest.approx(-1.10)
    assert report.total_stake == pytest.approx(6.0)
    assert report.total_costs == pytest.approx(0.10)
    assert report.roi_on_settled_stake == pytest.approx(-1.10 / 6.0)
    assert report.win_rate == pytest.approx(0.5)
    assert report.max_realized_drawdown == pytest.approx(3.05)


def test_abstention_counts():
    report = build_shadow_report(
        journal_rows=[
            decision(
                "m1",
                "ABSTAIN",
                reason="stale_market_books",
            ),
            decision(
                "m2",
                "ABSTAIN",
                reason="missing_execution_snapshot",
            ),
        ],
        resolution_rows=[],
        settled_trades=[],
    )

    assert report.total_opportunities == 2
    assert report.abstention_reasons == {
        "missing_execution_snapshot": 1,
        "stale_market_books": 1,
    }


def test_unresolved_not_counted_as_settled():
    report = build_shadow_report(
        journal_rows=[
            decision("m1", "PROCESSING"),
        ],
        resolution_rows=[],
        settled_trades=[],
    )

    assert report.unresolved_decisions == 1
    assert report.settled_trades == 0
    assert report.net_pnl == 0


def test_conflicting_resolution_rejected():
    with pytest.raises(ValueError, match="Conflicting"):
        build_shadow_report(
            journal_rows=[],
            resolution_rows=[
                resolution("m1", 1),
                resolution("m1", 0),
            ],
            settled_trades=[],
        )


def test_missing_trade_resolution_rejected():
    with pytest.raises(ValueError, match="verified resolution"):
        build_shadow_report(
            journal_rows=[],
            resolution_rows=[],
            settled_trades=[
                trade("m1", "YES", 1),
            ],
        )


def test_outcome_mismatch_rejected():
    with pytest.raises(ValueError, match="disagree"):
        build_shadow_report(
            journal_rows=[],
            resolution_rows=[
                resolution("m1", 0),
            ],
            settled_trades=[
                trade("m1", "YES", 1),
            ],
        )


def test_duplicate_journal_identity_rejected():
    row = decision("m1", "ABSTAIN")

    with pytest.raises(ValueError, match="Duplicate"):
        build_shadow_report(
            journal_rows=[row, row],
            resolution_rows=[],
            settled_trades=[],
        )


def test_market_brier_score():
    report = build_shadow_report(
        journal_rows=[
            decision("m1", "ABSTAIN", probability=0.8),
            decision("m2", "ABSTAIN", probability=0.3),
        ],
        resolution_rows=[
            resolution("m1", 1),
            resolution("m2", 0),
        ],
        settled_trades=[],
    )

    assert report.market_brier_score == pytest.approx((0.2**2 + 0.3**2) / 2)
    assert report.brier_markets == 2
