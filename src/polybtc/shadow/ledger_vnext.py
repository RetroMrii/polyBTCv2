from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy

from polybtc.risk.vnext import (
    PortfolioRiskState,
    RiskAction,
    RiskRequest,
    VNextRiskGate,
)
from polybtc.strategy.vnext import Action, StrategyDecision

SCHEMA_VERSION = 3
MAX_PRICE = 0.70
FEATURE_NAMES = (
    "relative_distance_from_strike",
    "target_horizon_seconds",
    "reference_return_30s",
)


@dataclass(frozen=True, slots=True)
class ReservationResult:
    approved: bool
    reason: str
    condition_id: str
    reservation_id: int | None = None


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    condition_id: str
    side: str
    status: str
    size: float
    execution_price: float
    entry_fee: float
    realized_pnl: float | None


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Decision-time facts. None means unavailable; never infer source timestamps."""

    decision_id: str
    model_version: str
    calibration_version: str
    model_sha256: str
    prediction_timestamp_utc: datetime
    features: Mapping[str, float]
    model_probability_yes: float
    market_probability_yes: float
    observed_ask: float
    selected_tick_size: float
    selected_ask_depth: float
    quote_observed_at_utc: datetime
    reference_source_at_utc: datetime | None
    reference_timestamp_provenance: str
    quote_timestamp_provenance: str
    fee_policy_version: str
    fee_rate: float | None
    estimated_fee_per_share: float
    estimated_net_ev_per_share: float
    strategy_action: str
    # The context can identify a snapshot without assuming it is a source timestamp.
    snapshot_id: str | None = None
    # Absent for legacy callers: unknown evidence, never retroactively verified.
    fee_policy: CachedFeePolicy | None = None


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid numeric value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid numeric value") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Invalid numeric value")
    return result


def _market(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid condition_id")
    return value.strip().lower()


def _context_payload(
    ctx: DecisionContext, decision: StrategyDecision, market: str
) -> str:
    if not isinstance(ctx, DecisionContext):
        raise ValueError("Invalid decision context")
    for name in (
        "decision_id",
        "model_version",
        "calibration_version",
        "reference_timestamp_provenance",
        "quote_timestamp_provenance",
        "fee_policy_version",
    ):
        value = getattr(ctx, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing decision context: {name}")
    if (
        not isinstance(ctx.model_sha256, str)
        or len(ctx.model_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in ctx.model_sha256.lower())
    ):
        raise ValueError("Invalid model SHA-256")
    if set(ctx.features) != set(FEATURE_NAMES):
        raise ValueError("Decision feature contract mismatch")
    features = {name: _number(ctx.features[name]) for name in FEATURE_NAMES}
    if features["target_horizon_seconds"] != decision.horizon_seconds:
        raise ValueError("Decision horizon mismatch")
    for name in ("model_probability_yes", "market_probability_yes", "observed_ask"):
        if not 0 <= _number(getattr(ctx, name)) <= 1:
            raise ValueError(f"Invalid {name}")
    if not 0 <= _number(ctx.estimated_fee_per_share) or not _number(
        ctx.selected_tick_size, positive=True
    ):
        raise ValueError("Invalid fee or tick size")
    _number(ctx.selected_ask_depth, positive=True)
    _number(ctx.estimated_net_ev_per_share)
    if ctx.fee_rate is not None and _number(ctx.fee_rate) < 0:
        raise ValueError("Invalid fee rate")
    if ctx.strategy_action != decision.action.value:
        raise ValueError("Strategy action mismatch")
    comparisons = (
        (ctx.model_probability_yes, decision.model_probability_yes),
        (ctx.market_probability_yes, decision.market_probability_yes),
        (ctx.observed_ask, decision.selected_ask),
        (ctx.estimated_fee_per_share, decision.fee_per_share),
        (ctx.estimated_net_ev_per_share, decision.net_ev_per_share),
    )
    for supplied, approved in comparisons:
        if approved is None or not math.isclose(
            float(supplied), float(approved), abs_tol=1e-9, rel_tol=0
        ):
            raise ValueError("Context and strategy decision mismatch")
    if (
        ctx.reference_source_at_utc is None
        and ctx.reference_timestamp_provenance == "source_verified"
    ):
        raise ValueError("Unverified reference timestamp cannot be source_verified")
    payload = dict(
        decision_id=ctx.decision_id.strip(),
        condition_id=market,
        model_version=ctx.model_version,
        calibration_version=ctx.calibration_version,
        model_sha256=ctx.model_sha256.lower(),
        prediction_timestamp_utc=_stamp(ctx.prediction_timestamp_utc),
        features=features,
        model_probability_yes=float(ctx.model_probability_yes),
        market_probability_yes=float(ctx.market_probability_yes),
        observed_ask=float(ctx.observed_ask),
        selected_tick_size=float(ctx.selected_tick_size),
        selected_ask_depth=float(ctx.selected_ask_depth),
        quote_observed_at_utc=_stamp(ctx.quote_observed_at_utc),
        reference_source_at_utc=(
            _stamp(ctx.reference_source_at_utc)
            if ctx.reference_source_at_utc is not None
            else None
        ),
        reference_timestamp_provenance=ctx.reference_timestamp_provenance,
        quote_timestamp_provenance=ctx.quote_timestamp_provenance,
        fee_policy_version=ctx.fee_policy_version,
        fee_rate=float(ctx.fee_rate) if ctx.fee_rate is not None else None,
        estimated_fee_per_share=float(ctx.estimated_fee_per_share),
        estimated_net_ev_per_share=float(ctx.estimated_net_ev_per_share),
        strategy_action=ctx.strategy_action,
        snapshot_id=ctx.snapshot_id,
    )
    if ctx.fee_policy is not None:
        if not isinstance(ctx.fee_policy, CachedFeePolicy):
            raise ValueError("Invalid fee evidence")
        if ctx.fee_policy.condition_id != market or ctx.fee_policy.fee_rate != ctx.fee_rate:
            raise ValueError("Fee evidence does not match decision")
        payload.update(ctx.fee_policy.provenance())
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


class VNextShadowLedger:
    """SQLite shadow-only ledger. No network access, order placement, or live execution."""

    def __init__(self, path: Path, *, store=None) -> None:
        self.store = store
        self.path = Path(path)
        if store is not None and self.path.resolve()!=store.path: raise ValueError("Store/path mismatch")
        if self.path.exists() and not self.path.is_file():
            raise ValueError("Ledger path is not a file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.store.lease("ledger") if self.store is not None else sqlite3.connect(str(self.path), timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with (self.store.lease("ledger") if self.store is not None else sqlite3.connect(str(self.path), timeout=15.0)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, SCHEMA_VERSION):
                raise RuntimeError(f"Unsupported ledger version: {version}")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT NOT NULL UNIQUE,
                    side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
                    status TEXT NOT NULL CHECK(status IN ('PENDING','FILLED','REJECTED','SETTLED')),
                    strategy_version TEXT NOT NULL,
                    risk_version TEXT NOT NULL,
                    requested_size REAL NOT NULL CHECK(requested_size > 0),
                    approved_price REAL NOT NULL CHECK(approved_price > 0 AND approved_price <= 0.70),
                    reserved_cost REAL NOT NULL CHECK(reserved_cost > 0),
                    reserved_fee_per_share REAL NOT NULL CHECK(reserved_fee_per_share >= 0),
                    created_at_utc TEXT NOT NULL,
                    filled_at_utc TEXT,
                    execution_price REAL,
                    filled_size REAL,
                    entry_fee REAL,
                    rejected_at_utc TEXT,
                    rejection_reason TEXT,
                    settled_at_utc TEXT,
                    label_yes INTEGER CHECK(label_yes IN (0,1)),
                    realized_pnl REAL,
                    CHECK(status != 'FILLED' OR (
                        filled_at_utc IS NOT NULL AND execution_price IS NOT NULL
                        AND filled_size IS NOT NULL AND entry_fee IS NOT NULL)),
                    CHECK(status != 'SETTLED' OR (
                        settled_at_utc IS NOT NULL AND label_yes IS NOT NULL
                        AND realized_pnl IS NOT NULL))
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_settlement ON entries(settled_at_utc)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN (
                        'ENTRY_RESERVED','ENTRY_FILLED','ENTRY_REJECTED',
                        'ENTRY_SETTLED','LEGACY_STATE_IMPORTED')),
                    occurred_at_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
                    FOREIGN KEY(entry_id) REFERENCES entries(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entry_events_entry ON entry_events(entry_id,event_id)"
            )
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_entry_events_no_update
                BEFORE UPDATE ON entry_events BEGIN
                    SELECT RAISE(ABORT,'audit events cannot be updated');
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_entry_events_no_delete
                BEFORE DELETE ON entry_events BEGIN
                    SELECT RAISE(ABORT,'audit events cannot be deleted');
                END
            """)
            if version == 1:
                conn.execute("""
                    INSERT INTO entry_events(entry_id,event_type,occurred_at_utc,payload_json)
                    SELECT id,'LEGACY_STATE_IMPORTED',created_at_utc,
                        json_object('condition_id',condition_id,'imported_status',status,
                            'side',side,'requested_size',requested_size,
                            'approved_price',approved_price,'reserved_cost',reserved_cost,
                            'execution_price',execution_price,'filled_size',filled_size,
                            'entry_fee',entry_fee,'rejection_reason',rejection_reason,
                            'settled_at_utc',settled_at_utc,'label_yes',label_yes,
                            'realized_pnl',realized_pnl,'provenance','legacy_v1_snapshot')
                    FROM entries
                """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_entry_reserved_audit
                AFTER INSERT ON entries BEGIN
                    INSERT INTO entry_events(entry_id,event_type,occurred_at_utc,payload_json)
                    VALUES(NEW.id,'ENTRY_RESERVED',NEW.created_at_utc,
                        json_object('condition_id',NEW.condition_id,'side',NEW.side,
                            'strategy_version',NEW.strategy_version,
                            'risk_version',NEW.risk_version,
                            'requested_size',NEW.requested_size,
                            'approved_price',NEW.approved_price,
                            'reserved_cost',NEW.reserved_cost,
                            'reserved_fee_per_share',NEW.reserved_fee_per_share));
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_entry_status_guard
                BEFORE UPDATE OF status ON entries
                WHEN NOT ((OLD.status='PENDING' AND NEW.status IN ('FILLED','REJECTED'))
                    OR (OLD.status='FILLED' AND NEW.status='SETTLED'))
                BEGIN SELECT RAISE(ABORT,'invalid entry status transition'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_entry_transition_audit
                AFTER UPDATE OF status ON entries BEGIN
                    INSERT INTO entry_events(entry_id,event_type,occurred_at_utc,payload_json)
                    VALUES(NEW.id,
                        CASE NEW.status WHEN 'FILLED' THEN 'ENTRY_FILLED'
                            WHEN 'REJECTED' THEN 'ENTRY_REJECTED'
                            WHEN 'SETTLED' THEN 'ENTRY_SETTLED' END,
                        CASE NEW.status WHEN 'FILLED' THEN NEW.filled_at_utc
                            WHEN 'REJECTED' THEN NEW.rejected_at_utc
                            WHEN 'SETTLED' THEN NEW.settled_at_utc END,
                        json_object('condition_id',NEW.condition_id,'status',NEW.status,
                            'side',NEW.side,'execution_price',NEW.execution_price,
                            'filled_size',NEW.filled_size,'entry_fee',NEW.entry_fee,
                            'rejection_reason',NEW.rejection_reason,
                            'label_yes',NEW.label_yes,'realized_pnl',NEW.realized_pnl));
                END
            """)
            # v3 links exactly one immutable context record to a reservation.
            # Legacy entries stay valid, explicitly missing decision context.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_decision_context (
                    entry_id INTEGER PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    recorded_at_utc TEXT NOT NULL,
                    context_json TEXT NOT NULL CHECK(json_valid(context_json)),
                    FOREIGN KEY(entry_id) REFERENCES entries(id)
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_decision_context_no_update
                BEFORE UPDATE ON entry_decision_context BEGIN
                    SELECT RAISE(ABORT,'decision context cannot be updated'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_decision_context_no_delete
                BEFORE DELETE ON entry_decision_context BEGIN
                    SELECT RAISE(ABORT,'decision context cannot be deleted'); END
            """)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _state(
        conn: sqlite3.Connection, at: datetime, kill_switch: bool
    ) -> PortfolioRiskState:
        day = _utc(at).date().isoformat()
        as_of = _stamp(at)
        rows = conn.execute("""
            SELECT condition_id,status,reserved_cost,execution_price,filled_size,
                entry_fee,created_at_utc,filled_at_utc,rejected_at_utc,
                settled_at_utc,realized_pnl FROM entries
        """).fetchall()
        pending: set[str] = set()
        entered: set[str] = set()
        exposure = open_risk = daily_pnl = 0.0
        for row in rows:
            for field in (
                "created_at_utc",
                "filled_at_utc",
                "rejected_at_utc",
                "settled_at_utc",
            ):
                if row[field] is not None and row[field] > as_of:
                    raise RuntimeError(
                        "Ledger contains events after requested state timestamp: "
                        + row["condition_id"]
                    )
            status = row["status"]
            market = row["condition_id"]
            if status == "PENDING":
                pending.add(market)
                exposure += row["reserved_cost"]
                open_risk += row["reserved_cost"]
            elif status == "FILLED":
                entered.add(market)
                cost = row["execution_price"] * row["filled_size"] + row["entry_fee"]
                exposure += cost
                open_risk += cost
            elif status == "SETTLED":
                entered.add(market)
                if row["settled_at_utc"][:10] == day:
                    daily_pnl += row["realized_pnl"]
        return PortfolioRiskState(
            state_complete=True,
            as_of_utc=_utc(at),
            daily_pnl_date_utc=_utc(at).date(),
            open_exposure_usd=exposure,
            open_capital_at_risk_usd=open_risk,
            daily_realized_pnl_usd=daily_pnl,
            entered_markets=frozenset(entered),
            pending_markets=frozenset(pending),
            kill_switch_active=kill_switch,
        )

    def portfolio_state(
        self, *, at: datetime, kill_switch: bool = False
    ) -> PortfolioRiskState:
        if not isinstance(kill_switch, bool):
            raise ValueError("Invalid kill switch")
        _utc(at)
        with self._connection() as conn:
            return self._state(conn, at, kill_switch)

    def pending_reservations(
        self, *, at: datetime, stale_after_seconds: float = 30.0
    ) -> list[dict]:
        now = _utc(at)
        threshold = _number(stale_after_seconds)
        if threshold < 0:
            raise ValueError("stale_after_seconds must be non-negative")
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT id,condition_id,side,requested_size,approved_price,
                    reserved_cost,created_at_utc FROM entries
                WHERE status='PENDING' ORDER BY id
            """).fetchall()
        result = []
        for row in rows:
            age = (
                now - _utc(datetime.fromisoformat(row["created_at_utc"]))
            ).total_seconds()
            if age < 0:
                raise RuntimeError(
                    "Pending reservation is future-dated: " + row["condition_id"]
                )
            result.append(
                dict(
                    reservation_id=row["id"],
                    condition_id=row["condition_id"],
                    side=row["side"],
                    requested_size=row["requested_size"],
                    approved_price=row["approved_price"],
                    reserved_cost=row["reserved_cost"],
                    created_at_utc=row["created_at_utc"],
                    age_seconds=age,
                    stale=age >= threshold,
                )
            )
        return result

    def reserve(
        self,
        *,
        decision: StrategyDecision,
        risk_gate: VNextRiskGate,
        requested_size: float,
        minimum_order_size: float,
        at: datetime,
        kill_switch: bool = False,
        decision_context: DecisionContext | None = None,
    ) -> ReservationResult:
        now = _stamp(at)
        market = _market(decision.condition_id)
        size = _number(requested_size, positive=True)
        minimum = _number(minimum_order_size, positive=True)
        if not isinstance(kill_switch, bool):
            raise ValueError("Invalid kill switch")
        # Context is optional solely for backward compatibility with pre-v3 tests.
        # Future prospective runner must REQUIRE a context before reserve().
        if decision_context is not None and decision_context.fee_policy is not None:
            if not isinstance(decision_context.fee_policy, CachedFeePolicy):
                raise ValueError("Invalid fee evidence")
            decision_context.fee_policy.validate_for_decision(
                market, decision_context.fee_rate, at
            )
        context_json = (
            _context_payload(decision_context, decision, market)
            if decision_context is not None
            else None
        )
        with self._connection(write=True) as conn:
            existing = conn.execute(
                "SELECT id FROM entries WHERE condition_id=?", (market,)
            ).fetchone()
            if existing is not None:
                return ReservationResult(False, "market_already_reserved", market)
            state = self._state(conn, at, kill_switch)
            approval = risk_gate.evaluate(
                RiskRequest(
                    decision=decision,
                    state=state,
                    requested_size=size,
                    minimum_order_size=minimum,
                    evaluated_at_utc=_utc(at),
                )
            )
            if approval.action != RiskAction.APPROVE_SHADOW:
                return ReservationResult(False, approval.reason, market)
            if (
                approval.condition_id != market
                or approval.approved_side != decision.action
                or not math.isclose(
                    approval.approved_size, size, rel_tol=0, abs_tol=1e-9
                )
            ):
                raise RuntimeError("Risk approval contract mismatch")
            price = _number(approval.maximum_execution_price, positive=True)
            fee_per_share = _number(decision.fee_per_share)
            if fee_per_share < 0 or price > MAX_PRICE:
                raise RuntimeError("Invalid approved execution constraints")
            reserved = size * (price + fee_per_share)
            if not math.isclose(
                reserved, approval.reserved_notional_usd, rel_tol=0, abs_tol=1e-8
            ):
                raise RuntimeError("Approved notional mismatch")
            side = "YES" if decision.action == Action.BUY_YES else "NO"
            cursor = conn.execute(
                """
                INSERT INTO entries(condition_id,side,status,strategy_version,risk_version,
                    requested_size,approved_price,reserved_cost,reserved_fee_per_share,created_at_utc)
                VALUES (?,?,'PENDING',?,?,?,?,?,?,?)
            """,
                (
                    market,
                    side,
                    decision.strategy_version,
                    approval.risk_version,
                    size,
                    price,
                    reserved,
                    fee_per_share,
                    now,
                ),
            )
            if context_json is not None:
                conn.execute(
                    """
                    INSERT INTO entry_decision_context(entry_id,decision_id,recorded_at_utc,context_json)
                    VALUES (?,?,?,?)
                """,
                    (
                        cursor.lastrowid,
                        decision_context.decision_id.strip(),
                        now,
                        context_json,
                    ),
                )
            return ReservationResult(
                True, "shadow_entry_reserved", market, cursor.lastrowid
            )

    def pending_size(self, condition_id: str) -> float:
        market = _market(condition_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT requested_size FROM entries WHERE condition_id=? AND status='PENDING'",
                (market,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Market has no pending reservation")
        return float(row["requested_size"])

    def record_fill(
        self,
        *,
        condition_id: str,
        execution_price: float,
        filled_size: float,
        entry_fee: float,
        at: datetime,
    ) -> None:
        market, now = _market(condition_id), _stamp(at)
        price = _number(execution_price, positive=True)
        size = _number(filled_size, positive=True)
        fee = _number(entry_fee)
        if fee < 0 or price > MAX_PRICE:
            raise ValueError("Invalid price or fee")
        with self._connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE condition_id=?", (market,)
            ).fetchone()
            if row is None or row["status"] != "PENDING":
                raise RuntimeError("No pending reservation for fill")
            if now < row["created_at_utc"]:
                raise ValueError("Fill predates reservation")
            if not math.isclose(size, row["requested_size"], rel_tol=0, abs_tol=1e-9):
                raise ValueError("v1 requires full-size fills")
            if price > row["approved_price"] + 1e-9:
                raise ValueError("Fill exceeds approved execution price")
            if fee > size * row["reserved_fee_per_share"] + 1e-9:
                raise ValueError("Fill fee exceeds reserved estimate")
            if price * size + fee > row["reserved_cost"] + 1e-9:
                raise ValueError("Fill exceeds reserved cost")
            cursor = conn.execute(
                """
                UPDATE entries SET status='FILLED',filled_at_utc=?,execution_price=?,
                    filled_size=?,entry_fee=? WHERE id=? AND status='PENDING'
            """,
                (now, price, size, fee, row["id"]),
            )

            if cursor.rowcount != 1:
                raise RuntimeError("Fill transition did not update exactly one entry")

            if cursor.rowcount != 1:
                raise RuntimeError("Fill transition did not update exactly one entry")

    def reject_pending(self, *, condition_id: str, reason: str, at: datetime) -> None:
        market, now = _market(condition_id), _stamp(at)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Missing rejection reason")
        with self._connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE condition_id=?", (market,)
            ).fetchone()
            if row is None or row["status"] != "PENDING":
                raise RuntimeError("No pending reservation to reject")
            if now < row["created_at_utc"]:
                raise ValueError("Rejection predates reservation")
            cursor = conn.execute(
                """
                UPDATE entries SET status='REJECTED',rejected_at_utc=?,rejection_reason=?
                WHERE id=? AND status='PENDING'
            """,
                (now, reason.strip(), row["id"]),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Rejection transition did not update exactly one entry"
                )

    def settle(self, *, condition_id: str, label_yes: int, at: datetime) -> float:
        market, now = _market(condition_id), _stamp(at)
        if isinstance(label_yes, bool) or label_yes not in (0, 1):
            raise ValueError("Invalid settlement label")
        with self._connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE condition_id=?", (market,)
            ).fetchone()
            if row is None:
                raise RuntimeError("Unknown market")
            if row["status"] == "SETTLED":
                if row["label_yes"] != label_yes:
                    raise RuntimeError("Conflicting settlement label")
                return float(row["realized_pnl"])
            if row["status"] != "FILLED":
                raise RuntimeError("Position is not eligible for settlement")
            if now < row["filled_at_utc"]:
                raise ValueError("Settlement predates fill")
            payout = float(label_yes) if row["side"] == "YES" else float(1 - label_yes)
            pnl = (payout - row["execution_price"]) * row["filled_size"] - row[
                "entry_fee"
            ]
            cursor = conn.execute(
                """
                UPDATE entries SET status='SETTLED',settled_at_utc=?,label_yes=?,realized_pnl=?
                WHERE id=? AND status='FILLED'
            """,
                (now, label_yes, pnl, row["id"]),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "Settlement transition did not update exactly one entry"
                )

            return float(pnl)

    def positions(self) -> list[LedgerPosition]:
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT condition_id,side,status,filled_size,execution_price,
                    entry_fee,realized_pnl FROM entries ORDER BY id
            """).fetchall()
        return [
            LedgerPosition(
                condition_id=r["condition_id"],
                side=r["side"],
                status=r["status"],
                size=float(r["filled_size"] or 0),
                execution_price=float(r["execution_price"] or 0),
                entry_fee=float(r["entry_fee"] or 0),
                realized_pnl=None
                if r["realized_pnl"] is None
                else float(r["realized_pnl"]),
            )
            for r in rows
        ]

    def events(self, condition_id: str | None = None) -> list[dict]:
        with self._connection() as conn:
            if condition_id is None:
                rows = conn.execute("""
                    SELECT event_id,entry_id,event_type,occurred_at_utc,payload_json
                    FROM entry_events ORDER BY event_id
                """).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT e.event_id,e.entry_id,e.event_type,e.occurred_at_utc,e.payload_json
                    FROM entry_events e JOIN entries p ON p.id=e.entry_id
                    WHERE p.condition_id=? ORDER BY e.event_id
                """,
                    (_market(condition_id),),
                ).fetchall()
        return [
            dict(
                event_id=r["event_id"],
                entry_id=r["entry_id"],
                event_type=r["event_type"],
                occurred_at_utc=r["occurred_at_utc"],
                payload=json.loads(r["payload_json"]),
            )
            for r in rows
        ]

    def decision_context(self, condition_id: str) -> dict[str, Any] | None:
        """Return immutable context; None means legacy/unknown, not verified."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT c.context_json FROM entry_decision_context c
                JOIN entries e ON e.id=c.entry_id WHERE e.condition_id=?
            """,
                (_market(condition_id),),
            ).fetchone()
        return None if row is None else json.loads(row["context_json"])
