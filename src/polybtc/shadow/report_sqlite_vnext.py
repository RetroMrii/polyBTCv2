from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from polybtc.shadow.report_vnext import (
    SettledTrade,
    ShadowReport,
    build_shadow_report,
)


PNL_TOLERANCE = 1e-7


def _read_db(path: Path) -> sqlite3.Connection:
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(path)

    # Open read-only: never create or migrate databases.
    conn = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro",
        uri=True,
        timeout=15,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def _market(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid condition_id")

    return value.strip().lower()


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value)

    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Settlement timestamp missing timezone")

    return result.astimezone(timezone.utc)


def _number(value, name: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Missing or invalid {name}")

    result = float(value)

    if not math.isfinite(result):
        raise ValueError(f"Nonfinite {name}")

    return result


def _events(conn: sqlite3.Connection, entry_id: int):
    return conn.execute(
        """
        SELECT event_type, occurred_at_utc, payload_json
        FROM entry_events
        WHERE entry_id=?
        ORDER BY event_id
    """,
        (entry_id,),
    ).fetchall()


def build_sqlite_shadow_report(
    *,
    journal_path: Path,
    ledger_path: Path,
    registry_path: Path,
) -> ShadowReport:
    """
    Report only auditable, ledger-backed hypothetical
    settlements.

    Never infer outcomes or reconstruct missing fees.
    Does not write to any database.
    """
    paths = [
        Path(journal_path),
        Path(ledger_path),
        Path(registry_path),
    ]

    if len({p.resolve() for p in paths}) != 3:
        raise ValueError("Reporting databases must be distinct")

    journal = _read_db(paths[0])

    try:
        ledger = _read_db(paths[1])

        try:
            registry = _read_db(paths[2])

            try:
                decisions = [
                    dict(row) for row in journal.execute("SELECT * FROM decisions")
                ]

                resolutions = [
                    dict(row) for row in registry.execute("SELECT * FROM resolutions")
                ]

                positions = [
                    dict(row) for row in ledger.execute("SELECT * FROM entries")
                ]

                decision_by_market = {}

                for decision in decisions:
                    market = _market(decision["condition_id"])

                    decision_by_market.setdefault(market, []).append(decision)

                resolution_by_market = {}

                for resolution in resolutions:
                    market = _market(resolution["condition_id"])

                    if market in resolution_by_market:
                        raise ValueError("Duplicate resolution market")

                    resolution_by_market[market] = resolution

                settled_trades = []

                for position in positions:
                    market = _market(position["condition_id"])

                    if position["status"] != "SETTLED":
                        continue

                    resolution = resolution_by_market.get(market)

                    if resolution is None:
                        raise ValueError(
                            f"Settled ledger position missing resolution: {market}"
                        )

                    if resolution["settlement_status"] != "SETTLED":
                        raise ValueError(
                            "Settlement registry not reconciled: " + market
                        )

                    if resolution["label_yes"] != position["label_yes"]:
                        raise ValueError("Settlement label mismatch: " + market)

                    matched_decisions = [
                        row
                        for row in decision_by_market.get(market, [])
                        if row["status"] == "SHADOW_FILLED"
                    ]

                    if len(matched_decisions) != 1:
                        raise ValueError(
                            "Missing or ambiguous journal fill decision: " + market
                        )

                    decision = matched_decisions[0]

                    context_row = ledger.execute(
                        """
                        SELECT context_json
                        FROM entry_decision_context
                        WHERE entry_id=?
                    """,
                        (position["id"],),
                    ).fetchone()

                    if context_row is None:
                        raise ValueError(
                            "Missing immutable decision context: " + market
                        )

                    context = json.loads(context_row["context_json"])

                    if context["snapshot_id"] != decision["snapshot_id"]:
                        raise ValueError("Prediction snapshot mismatch: " + market)

                    if _utc(context["prediction_timestamp_utc"]) != _utc(
                        decision["target_at_utc"]
                    ):
                        raise ValueError("Prediction cutoff mismatch: " + market)

                    if context["strategy_action"] != "BUY_" + position["side"]:
                        raise ValueError("Trading direction mismatch: " + market)

                    price = _number(
                        position["execution_price"],
                        "execution_price",
                    )
                    size = _number(
                        position["filled_size"],
                        "filled_size",
                    )
                    fee = _number(
                        position["entry_fee"],
                        "entry_fee",
                    )
                    recorded_pnl = _number(
                        position["realized_pnl"],
                        "realized_pnl",
                    )

                    if size <= 0 or fee < 0 or not 0 < price <= 0.70:
                        raise ValueError("Invalid settled execution: " + market)

                    if not math.isclose(
                        price,
                        _number(
                            decision["execution_price"],
                            "journal execution_price",
                        ),
                        rel_tol=0,
                        abs_tol=1e-9,
                    ):
                        raise ValueError("Execution price mismatch: " + market)

                    won = (
                        position["side"] == "YES" and position["label_yes"] == 1
                    ) or (position["side"] == "NO" and position["label_yes"] == 0)

                    payout = size if won else 0.0
                    expected_pnl = payout - price * size - fee

                    if not math.isclose(
                        expected_pnl,
                        recorded_pnl,
                        rel_tol=0,
                        abs_tol=PNL_TOLERANCE,
                    ):
                        raise ValueError("Ledger PnL mismatch: " + market)

                    audit = _events(
                        ledger,
                        position["id"],
                    )

                    event_types = [row["event_type"] for row in audit]

                    if event_types != [
                        "ENTRY_RESERVED",
                        "ENTRY_FILLED",
                        "ENTRY_SETTLED",
                    ]:
                        raise ValueError("Incomplete settlement audit: " + market)

                    settled_event = json.loads(audit[-1]["payload_json"])

                    if settled_event.get("label_yes") != position["label_yes"]:
                        raise ValueError("Settlement event label mismatch: " + market)

                    if not math.isclose(
                        _number(
                            settled_event.get("realized_pnl"),
                            "event realized_pnl",
                        ),
                        recorded_pnl,
                        rel_tol=0,
                        abs_tol=PNL_TOLERANCE,
                    ):
                        raise ValueError("Settlement event PnL mismatch: " + market)

                    settled_trades.append(
                        SettledTrade(
                            condition_id=market,
                            side=position["side"],
                            filled_size=size,
                            execution_price=price,
                            entry_fee=fee,
                            label_yes=position["label_yes"],
                            settled_at_utc=_utc(position["settled_at_utc"]),
                        )
                    )

                return build_shadow_report(
                    journal_rows=decisions,
                    resolution_rows=resolutions,
                    settled_trades=settled_trades,
                )

            finally:
                registry.close()

        finally:
            ledger.close()

    finally:
        journal.close()
