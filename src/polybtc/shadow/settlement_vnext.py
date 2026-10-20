from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from polybtc.shadow.ledger_vnext import VNextShadowLedger


SETTLEMENT_VERSION = "shadow_settlement_vnext_v1"


def _stamp(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware timestamp required")

    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _market(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid condition_id")
    return value.strip().lower()


@dataclass(frozen=True, slots=True)
class VerifiedResolution:
    condition_id: str
    label_yes: int
    resolved_at_utc: datetime
    evidence_source: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class SettlementResult:
    condition_id: str
    status: str
    reason: str


class VNextSettlementService:
    """
    Independently verified market outcome intake
    and hypothetical settlement reconciliation.

    No API access, network requests, wallet calls,
    redemptions, or real-money execution.

    Resolution evidence must have been validated by
    the caller before register() is invoked.
    """

    def __init__(
        self,
        *,
        registry_path: Path,
        ledger: VNextShadowLedger,
        store=None,
    ) -> None:
        self.store = store
        self.path = Path(registry_path)
        if store is not None and self.path.resolve()!=store.path: raise ValueError("Store/path mismatch")
        self.ledger = ledger

        if self.path.resolve() == ledger.path.resolve() and not (store is not None and store is getattr(ledger,"store",None)):
            raise ValueError("Registry and trading ledger must differ")

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        conn = self._connect()

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resolutions (
                    condition_id TEXT PRIMARY KEY,
                    label_yes INTEGER NOT NULL
                        CHECK (label_yes IN (0, 1)),
                    resolved_at_utc TEXT NOT NULL,
                    evidence_source TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    settlement_status TEXT NOT NULL
                        CHECK (
                            settlement_status IN (
                                'VERIFIED',
                                'SETTLED'
                            )
                        ),
                    settled_at_utc TEXT,
                    registry_version TEXT NOT NULL
                )
            """)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        if self.store is not None: return self.store.lease("resolutions")
        conn = sqlite3.connect(
            str(self.path),
            timeout=15,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def register(
        self,
        resolution: VerifiedResolution,
    ) -> SettlementResult:
        """
        Register an already validated resolution.

        An existing resolution cannot be silently
        replaced, even by a different evidence source.
        """
        market = _market(resolution.condition_id)

        if (
            isinstance(resolution.label_yes, bool)
            or not isinstance(resolution.label_yes, int)
            or resolution.label_yes not in (0, 1)
        ):
            raise ValueError("Invalid binary resolution label")

        if not resolution.evidence_source.strip() or not resolution.evidence_id.strip():
            raise ValueError("Missing resolution evidence")

        resolved = _stamp(resolution.resolved_at_utc)

        payload = (
            market,
            resolution.label_yes,
            resolved,
            resolution.evidence_source.strip(),
            resolution.evidence_id.strip(),
        )

        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT *
                FROM resolutions
                WHERE condition_id=?
            """,
                (market,),
            ).fetchone()

            if row is not None:
                existing = (
                    row["condition_id"],
                    row["label_yes"],
                    row["resolved_at_utc"],
                    row["evidence_source"],
                    row["evidence_id"],
                )

                if existing != payload:
                    raise ValueError("Conflicting resolution evidence: " + market)

                conn.execute("COMMIT")

                return SettlementResult(
                    market,
                    row["settlement_status"],
                    "resolution_already_registered",
                )

            conn.execute(
                """
                INSERT INTO resolutions (
                    condition_id,
                    label_yes,
                    resolved_at_utc,
                    evidence_source,
                    evidence_id,
                    settlement_status,
                    registry_version
                )
                VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?)
            """,
                (*payload, SETTLEMENT_VERSION),
            )

            conn.execute("COMMIT")

            return SettlementResult(
                market,
                "VERIFIED",
                "verified_resolution_registered",
            )

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def settle(
        self,
        *,
        condition_id: str,
        at: datetime,
    ) -> SettlementResult:
        """
        Apply a registered resolution to an eligible
        hypothetical position.

        The trading ledger is authoritative. If the
        ledger was settled before an interruption,
        this method only reconciles registry status.
        """
        market = _market(condition_id)
        now = _stamp(at)

        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            record = conn.execute(
                """
                SELECT *
                FROM resolutions
                WHERE condition_id=?
            """,
                (market,),
            ).fetchone()

            if record is None:
                conn.execute("COMMIT")
                return SettlementResult(
                    market,
                    "UNRESOLVED",
                    "no_verified_resolution",
                )

            # Do not settle before the verified
            # market resolution timestamp.
            if now < record["resolved_at_utc"]:
                conn.execute("COMMIT")
                return SettlementResult(
                    market,
                    "UNRESOLVED",
                    "before_resolution_timestamp",
                )

            positions = [
                p
                for p in self.ledger.positions()
                if p.condition_id.strip().lower() == market
            ]

            if len(positions) == 0:
                conn.execute("COMMIT")
                return SettlementResult(
                    market,
                    "NO_POSITION",
                    "no_shadow_position",
                )

            if len(positions) != 1:
                raise RuntimeError("Ambiguous shadow position count")

            position = positions[0]

            if position.status == "SETTLED":
                # Verify the persisted outcome before
                # acknowledging a recovered settlement.
                with self.ledger._connection() as ledger_conn:
                    settled = ledger_conn.execute(
                        """
                        SELECT label_yes, realized_pnl
                        FROM entries
                        WHERE condition_id=?
                          AND status='SETTLED'
                    """,
                        (market,),
                    ).fetchone()

                if settled is None:
                    raise RuntimeError("Settled position missing ledger evidence")

                if settled["label_yes"] != record["label_yes"]:
                    raise RuntimeError("Registry and ledger settlement labels disagree")

                if settled["realized_pnl"] is None:
                    raise RuntimeError("Settled position missing realized PnL")

            elif position.status == "FILLED":
                # Settlement must be based on verified
                # external outcome, not predicted side.
                self.ledger.settle(
                    condition_id=market,
                    label_yes=int(record["label_yes"]),
                    at=at,
                )

                # Verify the authoritative ledger
                # state before completing the registry.
                updated = [
                    p
                    for p in self.ledger.positions()
                    if p.condition_id.strip().lower() == market
                ]

                if len(updated) != 1 or updated[0].status != "SETTLED":
                    raise RuntimeError("Ledger settlement not confirmed")

            else:
                conn.execute("COMMIT")

                return SettlementResult(
                    market,
                    "UNRESOLVED",
                    "position_not_filled",
                )

            # The two SQLite databases cannot commit
            # atomically together. If this step fails,
            # the next call observes SETTLED in the
            # trading ledger and completes recovery.
            conn.execute(
                """
                UPDATE resolutions
                SET settlement_status='SETTLED',
                    settled_at_utc=COALESCE(
                        settled_at_utc, ?
                    )
                WHERE condition_id=?
            """,
                (now, market),
            )

            conn.execute("COMMIT")

            return SettlementResult(
                market,
                "SETTLED",
                "shadow_ledger_reconciled",
            )

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def resolutions(self) -> list[dict]:
        conn = self._connect()

        try:
            rows = conn.execute("""
                SELECT *
                FROM resolutions
                ORDER BY resolved_at_utc, condition_id
            """).fetchall()

            return [dict(row) for row in rows]
        finally:
            conn.close()
