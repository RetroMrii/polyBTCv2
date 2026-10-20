from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math
from uuid import uuid4


from polybtc.data.schema import SnapshotRecord
from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy
from polybtc.shadow.source_verification_vnext import SourceVerificationResult
from polybtc.data.dataset.horizons import (
    DEFAULT_HORIZONS_SECONDS,
    select_market_horizons,
)


from polybtc.data.paper_policy_vnext import PAPER_POLICY

JOURNAL_VERSION = 5


@dataclass(frozen=True, slots=True)
class OrchestratorConfig:
    version: str = "shadow_orchestrator_vnext_v1"
    finalization_grace_seconds: float = PAPER_POLICY.finalization_grace_seconds
    horizons: tuple[int, ...] = PAPER_POLICY.horizons


@dataclass(frozen=True, slots=True)
class JournalResult:
    condition_id: str
    horizon_seconds: int
    target_at_utc: str
    status: str
    reason: str
    snapshot_id: str | None


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


def _market(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid condition_id")

    return value.strip().lower()


class VNextDecisionOrchestrator:
    """
    Durable journal for finalized prediction horizons.

    Does not invoke the execution simulator or submit
    real orders.

    Each market/horizon is finalized once.
    """

    def __init__(
        self,
        *,
        journal_path: Path,
        config: OrchestratorConfig | None = None,
        store=None,
    ) -> None:
        self.store = store
        self.path = Path(journal_path)
        if store is not None and self.path.resolve()!=store.path: raise ValueError("Store/path mismatch")
        self.config = config or OrchestratorConfig()

        if self.config.finalization_grace_seconds < 0:
            raise ValueError("Invalid finalization grace")

        if (
            not self.config.horizons
            or len(set(self.config.horizons)) != len(self.config.horizons)
            or any(
                horizon not in DEFAULT_HORIZONS_SECONDS
                for horizon in self.config.horizons
            )
        ):
            raise ValueError("Unsupported horizon configuration")

        if self.path.exists() and not self.path.is_file():
            raise ValueError("Journal path is not a file")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.store is not None: return self.store.lease("journal")
        conn = sqlite3.connect(
            str(self.path),
            timeout=15,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")

            version = conn.execute("PRAGMA user_version").fetchone()[0]

            if version not in (0, 1, 2, 3, 4, JOURNAL_VERSION):
                raise RuntimeError(f"Unsupported journal schema version: {version}")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    condition_id TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,

                    target_at_utc TEXT NOT NULL,
                    processed_at_utc TEXT NOT NULL,

                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,

                    snapshot_id TEXT,
                    snapshot_observed_at_utc TEXT,
                    snapshot_ingested_at_utc TEXT,
                    snapshot_source TEXT,
                    horizon_gap_seconds REAL,

                    orchestrator_version TEXT NOT NULL,

                    UNIQUE (
                        condition_id,
                        horizon_seconds
                    )
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                    idx_decisions_processed
                ON decisions(processed_at_utc)
            """)

            # v1 -> v2: claim ownership and terminal outcomes.
            # Preserve existing decisions and their identities.
            if version in (0, 1):
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN claim_token TEXT
                """)
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN claimed_at_utc TEXT
                """)
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN completed_at_utc TEXT
                """)
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN model_probability_yes REAL
                """)
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN market_probability_yes REAL
                """)
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN execution_price REAL
                """)

            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_decisions_claim_token
                ON decisions(claim_token)
                WHERE claim_token IS NOT NULL
            """)

            # v2 -> v3: causal prediction-time market
            # baseline, independent of execution quotes.
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(decisions)")
            }

            if "prediction_market_probability_yes" not in columns:
                conn.execute("""
                    ALTER TABLE decisions
                    ADD COLUMN prediction_market_probability_yes REAL
                    CHECK (
                        prediction_market_probability_yes IS NULL
                        OR (
                            prediction_market_probability_yes >= 0
                            AND prediction_market_probability_yes <= 1
                        )
                    )
                """)

            # v4: snapshot evidence atomically with claim ownership, including
            # decisions that abstain before reaching the trading ledger.
            if "fee_provenance_json" not in columns:
                conn.execute("""
                    ALTER TABLE decisions ADD COLUMN fee_provenance_json TEXT
                    CHECK (fee_provenance_json IS NULL OR json_valid(fee_provenance_json))
                """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_fee_provenance_no_update
                BEFORE UPDATE OF fee_provenance_json ON decisions
                WHEN OLD.fee_provenance_json IS NOT NULL
                  OR OLD.status != 'AWAITING_EXECUTION_ADAPTER'
                BEGIN SELECT RAISE(ABORT, 'Immutable fee provenance'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_fee_provenance_no_delete
                BEFORE DELETE ON decisions WHEN OLD.fee_provenance_json IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'Immutable fee provenance'); END
            """)
            if "source_verification_json" not in columns:
                conn.execute("""
                    ALTER TABLE decisions ADD COLUMN source_verification_json TEXT
                    CHECK (source_verification_json IS NULL OR json_valid(source_verification_json))
                """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_source_verification_no_update
                BEFORE UPDATE OF source_verification_json ON decisions
                WHEN OLD.source_verification_json IS NOT NULL
                  OR OLD.status != 'AWAITING_EXECUTION_ADAPTER'
                BEGIN SELECT RAISE(ABORT, 'Immutable source verification'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_source_verification_no_delete
                BEFORE DELETE ON decisions WHEN OLD.source_verification_json IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'Immutable source verification'); END
            """)
            conn.execute(f"PRAGMA user_version={JOURNAL_VERSION}")

            conn.execute("COMMIT")

    def process(
        self,
        *,
        snapshots: list[SnapshotRecord],
        processing_at_utc: datetime,
    ) -> list[JournalResult]:
        now = _utc(processing_at_utc)

        # Only rows available as of the processing cutoff
        # may participate in horizon selection.
        available = []

        for snapshot in snapshots:
            _market(snapshot.condition_id)

            observed = _utc(snapshot.observed_at)
            ingested = _utc(snapshot.ingested_at)

            if observed <= now and ingested <= now:
                available.append(snapshot)

        by_market: dict[str, list[SnapshotRecord]] = {}

        for snapshot in available:
            market = _market(snapshot.condition_id)
            by_market.setdefault(market, []).append(snapshot)

        # Establish one consistent expiry for every market.
        market_end_times = {}

        for market, rows in by_market.items():
            ends = {
                _utc(row.market_end_at) for row in rows if row.market_end_at is not None
            }

            if len(ends) > 1:
                raise RuntimeError(f"Conflicting market expiry: {market}")

            if ends:
                market_end_times[market] = next(iter(ends))

        grace = timedelta(seconds=self.config.finalization_grace_seconds)

        ready_markets = {
            market
            for market, end in market_end_times.items()
            if any(
                now >= end - timedelta(seconds=horizon) + grace
                for horizon in self.config.horizons
            )
        }

        ready_snapshots = [
            row for row in available if _market(row.condition_id) in ready_markets
        ]

        selections = select_market_horizons(
            ready_snapshots,
            horizons=self.config.horizons,
            require_received_by_target=True,
            max_horizon_lag_seconds=PAPER_POLICY.horizon_lag_seconds,
        )

        pending_rows = []

        for selection in selections:
            market = _market(selection.condition_id)
            end = market_end_times.get(market)

            if end is None:
                continue

            horizon = selection.target_seconds_to_expiry
            target = end - timedelta(seconds=horizon)

            if now < target + grace:
                continue

            selected = selection.snapshot

            if selection.status != "SELECTED":
                status = "ABSTAIN"
                reason = selection.status.lower()

            elif selected is None:
                status = "ABSTAIN"
                reason = "missing_selected_snapshot"

            elif _utc(selected.ingested_at) > target:
                # Available by processing time does not
                # mean available at the prediction cutoff.
                status = "ABSTAIN"
                reason = "snapshot_arrived_after_target"

            else:
                status = "AWAITING_EXECUTION_ADAPTER"
                reason = "fresh_execution_quote_required"

            pending_rows.append(
                (
                    market,
                    horizon,
                    _stamp(target),
                    _stamp(now),
                    status,
                    reason,
                    selected.snapshot_id if selected else None,
                    (_stamp(selected.observed_at) if selected else None),
                    (_stamp(selected.ingested_at) if selected else None),
                    selected.source_name if selected else None,
                    selection.horizon_gap_seconds,
                    self.config.version,
                )
            )

        # Unique constraints and one write transaction
        # make repeated processing safe across restarts.
        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            newly_recorded = []

            for row in sorted(
                pending_rows,
                key=lambda item: (item[2], item[0], -item[1]),
            ):
                # A repeated INSERT OR IGNORE still writes sqlite_sequence.
                # Check under the same write lock to preserve cross-process uniqueness.
                if conn.execute(
                    "SELECT 1 FROM decisions WHERE condition_id=? AND horizon_seconds=?",
                    (row[0], row[1]),
                ).fetchone() is not None:
                    continue
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO decisions (
                        condition_id,
                        horizon_seconds,
                        target_at_utc,
                        processed_at_utc,
                        status,
                        reason,
                        snapshot_id,
                        snapshot_observed_at_utc,
                        snapshot_ingested_at_utc,
                        snapshot_source,
                        horizon_gap_seconds,
                        orchestrator_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    row,
                )

                if cursor.rowcount == 1:
                    newly_recorded.append(
                        JournalResult(
                            condition_id=row[0],
                            horizon_seconds=row[1],
                            target_at_utc=row[2],
                            status=row[4],
                            reason=row[5],
                            snapshot_id=row[6],
                        )
                    )

            conn.execute("COMMIT")
            return newly_recorded

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def claim(
        self,
        *,
        condition_id: str,
        horizon_seconds: int,
        at: datetime,
        fee_policy: CachedFeePolicy | None = None,
        source_verification: SourceVerificationResult | None = None,
    ) -> str | None:
        """
        Atomically claim an awaiting decision.

        Returns an ownership token or None when no
        claimable decision exists.

        PROCESSING decisions are never silently retried.
        """
        market = _market(condition_id)
        now = _stamp(at)

        fee_json = None
        if fee_policy is not None:
            if not isinstance(fee_policy, CachedFeePolicy):
                raise ValueError("Invalid fee evidence")
            fee_policy.validate_for_decision(market, fee_policy.fee_rate, at)
            fee_json = json.dumps(
                fee_policy.provenance(), sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            )

        source_json = None
        if source_verification is not None:
            if (
                source_verification.condition_id != market
                or _stamp(source_verification.checked_at_utc) != now
            ):
                raise ValueError("Source verification does not match claim")
            source_json = json.dumps(
                source_verification.provenance(), sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )

        if horizon_seconds not in self.config.horizons:
            raise ValueError("Unsupported horizon")

        token = uuid4().hex
        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            cursor = conn.execute(
                """
                UPDATE decisions
                SET status='PROCESSING',
                    reason='evaluation_claimed',
                    claim_token=?,
                    claimed_at_utc=?,
                    fee_provenance_json=?,
                    source_verification_json=?
                WHERE condition_id=?
                  AND horizon_seconds=?
                  AND status='AWAITING_EXECUTION_ADAPTER'
                  AND target_at_utc <= ?
                  AND processed_at_utc <= ?
                  AND (? IS NULL OR snapshot_id=?)
            """,
                (
                    token,
                    now,
                    fee_json,
                    source_json,
                    market,
                    horizon_seconds,
                    now,
                    now,
                    source_verification.prediction_snapshot_id if source_verification else None,
                    source_verification.prediction_snapshot_id if source_verification else None,
                ),
            )

            claimed = cursor.rowcount == 1

            conn.execute("COMMIT")

            return token if claimed else None

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def complete_abstention(
        self,
        *,
        condition_id: str,
        horizon_seconds: int,
        claim_token: str,
        reason: str,
        at: datetime,
        model_probability_yes: float | None = None,
        market_probability_yes: float | None = None,
        prediction_market_probability_yes: float | None = None,
    ) -> bool:
        """
        Complete a claimed opportunity with abstention.

        Returns False for stale/incorrect ownership,
        or an already completed decision.

        Trade completion is intentionally not supported
        until ledger reconciliation is integrated.
        """
        market = _market(condition_id)
        now = _stamp(at)

        if not isinstance(claim_token, str) or not claim_token.strip():
            raise ValueError("Missing claim token")

        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Missing abstention reason")

        for name, probability in (
            ("model_probability_yes", model_probability_yes),
            ("market_probability_yes", market_probability_yes),
            (
                "prediction_market_probability_yes",
                prediction_market_probability_yes,
            ),
        ):
            if probability is not None:
                if (
                    isinstance(probability, bool)
                    or not isinstance(probability, (int, float))
                    or not 0 <= probability <= 1
                ):
                    raise ValueError(f"Invalid {name}")

                if not math.isfinite(probability):
                    raise ValueError(f"Nonfinite {name}")

        conn = self._connect()

        try:
            conn.execute("BEGIN IMMEDIATE")

            cursor = conn.execute(
                """
                UPDATE decisions
                SET status='ABSTAIN',
                    reason=?,
                    completed_at_utc=?,
                    model_probability_yes=?,
                    market_probability_yes=?,
                    prediction_market_probability_yes=?
                WHERE condition_id=?
                  AND horizon_seconds=?
                  AND status='PROCESSING'
                  AND claim_token=?
                  AND claimed_at_utc <= ?
            """,
                (
                    reason.strip(),
                    now,
                    model_probability_yes,
                    market_probability_yes,
                    prediction_market_probability_yes,
                    market,
                    horizon_seconds,
                    claim_token,
                    now,
                ),
            )

            completed = cursor.rowcount == 1

            conn.execute("COMMIT")

            return completed

        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

        finally:
            conn.close()

    def unresolved_claims(self) -> list[dict]:
        """
        Inspect interrupted or outstanding evaluations.

        Recovery requires reconciliation with the
        shadow trading ledger.
        """
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM decisions
                WHERE status='PROCESSING'
                ORDER BY claimed_at_utc, id
            """).fetchall()

        return [dict(row) for row in rows]

    def decisions(self, *, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM decisions
                WHERE (? IS NULL OR status=?)
                ORDER BY target_at_utc,
                         condition_id,
                         horizon_seconds DESC
            """, (status, status)).fetchall()

        return [dict(row) for row in rows]
