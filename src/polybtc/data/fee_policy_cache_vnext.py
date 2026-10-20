from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from polybtc.data.polymarket_fees import (
    EXPECTED_FEE_EXPONENT,
    EXPECTED_FEE_FLAG,
    EXPECTED_FEE_RATE,
    FEE_PROVIDER_VERSION,
    PolymarketFeePolicy,
    fetch_market_fee_policy,
    _validate_condition_id,
)


CACHE_VERSION = "fee_policy_cache_vnext_v1"
DEFAULT_MAX_AGE_SECONDS = 86400.0


class FeeCacheError(RuntimeError):
    """Missing, stale, invalid or conflicting fee evidence."""


@dataclass(frozen=True, slots=True)
class CachedFeePolicy:
    condition_id: str
    fee_rate: float
    fee_exponent: int
    fee_flag: bool
    source: str
    provider_version: str
    retrieved_at_utc: datetime
    cache_version: str

    def validate_for_decision(
        self, condition_id: str, fee_rate: float | None, at: datetime
    ) -> None:
        """Validate a detached evidence snapshot without reading cache or network."""
        market = _validate_condition_id(condition_id)
        if self.condition_id != market:
            raise FeeCacheError("Fee evidence market mismatch")
        if not _descriptor_matches(self.fee_rate, self.fee_exponent, self.fee_flag):
            raise FeeCacheError("Invalid fee evidence descriptor")
        if (
            self.source != f"https://clob.polymarket.com/clob-markets/{market}"
            or self.provider_version != FEE_PROVIDER_VERSION
            or self.cache_version != CACHE_VERSION
        ):
            raise FeeCacheError("Fee evidence provenance mismatch")
        if (
            isinstance(fee_rate, bool)
            or not isinstance(fee_rate, (int, float))
            or not math.isfinite(fee_rate)
            or fee_rate != self.fee_rate
        ):
            raise FeeCacheError("Fee evidence rate mismatch")
        age = (_utc(at) - _utc(self.retrieved_at_utc)).total_seconds()
        if not 0 <= age <= DEFAULT_MAX_AGE_SECONDS:
            raise FeeCacheError("Fee evidence is stale or from the future")

    def provenance(self) -> dict[str, object]:
        """JSON-ready evidence, distinct from fee formula or execution permission."""
        return {
            "fee_condition_id": self.condition_id,
            "fee_policy_source": self.source,
            "fee_provider_version": self.provider_version,
            "fee_retrieved_at_utc": _stamp(self.retrieved_at_utc),
            "fee_cache_version": self.cache_version,
            "fee_descriptor_rate": self.fee_rate,
            "fee_descriptor_exponent": self.fee_exponent,
            "fee_descriptor_flag": self.fee_flag,
        }


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _positive_seconds(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("Maximum cache age must be positive and finite")

    return float(value)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse_stamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise FeeCacheError("Invalid cached timestamp")

    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _utc(result)
    except (ValueError, TypeError) as exc:
        raise FeeCacheError("Invalid cached timestamp") from exc


def _descriptor_matches(
    rate: float,
    exponent: int,
    flag: bool,
) -> bool:
    return (
        type(rate) is float
        and math.isfinite(rate)
        and math.isclose(rate, EXPECTED_FEE_RATE, rel_tol=0, abs_tol=1e-12)
        and type(exponent) is int
        and exponent == EXPECTED_FEE_EXPONENT
        and type(flag) is bool
        and flag is EXPECTED_FEE_FLAG
    )


class VNextFeePolicyCache:
    """
    SQLite cache of independently fetched CLOB fee descriptors.

    Refresh may make one CLOB metadata request.
    Get is strictly offline.

    No trade execution, risk approval, wallet access
    or runtime verification-flag changes.
    """

    def __init__(self, path: Path, *, readonly=False) -> None:
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            if not self.path.is_file(): raise ValueError("Fee cache missing")
            return

        if self.path.exists() and not self.path.is_file():
            raise ValueError("Fee cache path is not a file")

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection(write=True) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fee_policies (
                    condition_id TEXT PRIMARY KEY,
                    fee_rate REAL NOT NULL,
                    fee_exponent INTEGER NOT NULL,
                    fee_flag INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    provider_version TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL,
                    cache_version TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS fee_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT NOT NULL,
                    previous_rate REAL NOT NULL,
                    previous_exponent INTEGER NOT NULL,
                    previous_flag INTEGER NOT NULL,
                    incoming_rate REAL NOT NULL,
                    incoming_exponent INTEGER NOT NULL,
                    incoming_flag INTEGER NOT NULL,
                    detected_at_utc TEXT NOT NULL
                )
            """)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.readonly: raise ValueError("Read-only fee cache")
        conn = sqlite3.connect(
            self.path.resolve().as_uri()+"?mode=ro" if self.readonly else str(self.path),
            uri=self.readonly,
            timeout=15.0,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA busy_timeout=15000")
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

    @staticmethod
    def _validate_fetched(
        market: str,
        policy: PolymarketFeePolicy,
        now: datetime,
    ) -> None:
        if not isinstance(policy, PolymarketFeePolicy):
            raise FeeCacheError("Invalid provider response type")

        if policy.condition_id != market:
            raise FeeCacheError("Provider market identity mismatch")

        if (
            policy.provider_version != FEE_PROVIDER_VERSION
            or policy.descriptor_verified is not True
            or policy.research_formula_compatible is not True
        ):
            raise FeeCacheError("Unverified fee provider evidence")

        if not _descriptor_matches(
            policy.fee_rate,
            policy.fee_exponent,
            policy.fee_flag,
        ):
            raise FeeCacheError("Unsupported fee descriptor")

        if policy.source != (f"https://clob.polymarket.com/clob-markets/{market}"):
            raise FeeCacheError("Unexpected fee evidence source")

        retrieved = _utc(policy.retrieved_at_utc)
        if retrieved > now:
            raise FeeCacheError("Fee evidence timestamp is in the future")

    def refresh(
        self,
        condition_id: str,
        *,
        at: datetime | None = None,
    ) -> CachedFeePolicy:
        """
        Explicitly fetch and persist one fee policy.

        Existing incompatible evidence is not overwritten.
        A conflict is recorded and the market is blocked.
        """
        market = _validate_condition_id(condition_id)

        # Fetch outside the write transaction.
        policy = fetch_market_fee_policy(market)

        now = _utc(at) if at is not None else datetime.now(timezone.utc)

        self._validate_fetched(market, policy, now)

        with self._connection(write=True) as conn:
            existing = conn.execute(
                "SELECT * FROM fee_policies WHERE condition_id=?",
                (market,),
            ).fetchone()

            if existing is not None:
                different = (
                    not math.isclose(
                        float(existing["fee_rate"]),
                        policy.fee_rate,
                        rel_tol=0,
                        abs_tol=1e-12,
                    )
                    or existing["fee_exponent"] != policy.fee_exponent
                    or existing["fee_flag"] != int(policy.fee_flag)
                )

                if different:
                    conn.execute(
                        """
                        INSERT INTO fee_conflicts (
                            condition_id,
                            previous_rate,
                            previous_exponent,
                            previous_flag,
                            incoming_rate,
                            incoming_exponent,
                            incoming_flag,
                            detected_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            market,
                            existing["fee_rate"],
                            existing["fee_exponent"],
                            existing["fee_flag"],
                            policy.fee_rate,
                            policy.fee_exponent,
                            int(policy.fee_flag),
                            _stamp(now),
                        ),
                    )

                    # Commit conflict evidence, then fail.
                    conflict = True
                else:
                    conflict = False
            else:
                conflict = False

            if not conflict:
                incoming_stamp = _stamp(policy.retrieved_at_utc)

                if existing is not None:
                    old_stamp = _parse_stamp(existing["retrieved_at_utc"])
                    if _utc(policy.retrieved_at_utc) < old_stamp:
                        raise FeeCacheError("Refusing older fee evidence")

                conn.execute(
                    """
                    INSERT INTO fee_policies (
                        condition_id,
                        fee_rate,
                        fee_exponent,
                        fee_flag,
                        source,
                        provider_version,
                        retrieved_at_utc,
                        cache_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(condition_id) DO UPDATE SET
                        fee_rate=excluded.fee_rate,
                        fee_exponent=excluded.fee_exponent,
                        fee_flag=excluded.fee_flag,
                        source=excluded.source,
                        provider_version=excluded.provider_version,
                        retrieved_at_utc=excluded.retrieved_at_utc,
                        cache_version=excluded.cache_version
                """,
                    (
                        market,
                        policy.fee_rate,
                        policy.fee_exponent,
                        int(policy.fee_flag),
                        policy.source,
                        policy.provider_version,
                        incoming_stamp,
                        CACHE_VERSION,
                    ),
                )

        if conflict:
            raise FeeCacheError(f"Conflicting fee descriptor for {market}")

        return self.get(market, at=now)

    def get(
        self,
        condition_id: str,
        *,
        at: datetime | None = None,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    ) -> CachedFeePolicy:
        """
        Offline lookup. Fail closed on any cache problem.
        """
        market = _validate_condition_id(condition_id)
        now = _utc(at) if at is not None else datetime.now(timezone.utc)
        max_age = _positive_seconds(max_age_seconds)

        with self._connection() as conn:
            conflicting = conn.execute(
                "SELECT 1 FROM fee_conflicts WHERE condition_id=? LIMIT 1",
                (market,),
            ).fetchone()

            if conflicting is not None:
                raise FeeCacheError(f"Conflicting fee evidence: {market}")

            row = conn.execute(
                "SELECT * FROM fee_policies WHERE condition_id=?",
                (market,),
            ).fetchone()

        if row is None:
            raise FeeCacheError(f"No cached fee policy: {market}")

        retrieved = _parse_stamp(row["retrieved_at_utc"])

        age = (now - retrieved).total_seconds()

        if age < 0:
            raise FeeCacheError("Cached evidence is from the future")

        if age > max_age:
            raise FeeCacheError(f"Cached fee policy expired: age={age:.1f}s")

        if not _descriptor_matches(
            row["fee_rate"],
            row["fee_exponent"],
            bool(row["fee_flag"]) if row["fee_flag"] in (0, 1) else None,
        ):
            raise FeeCacheError("Cached fee descriptor is invalid")

        if (
            row["provider_version"] != FEE_PROVIDER_VERSION
            or row["cache_version"] != CACHE_VERSION
            or row["source"] != f"https://clob.polymarket.com/clob-markets/{market}"
        ):
            raise FeeCacheError("Cached fee provenance mismatch")

        return CachedFeePolicy(
            condition_id=market,
            fee_rate=float(row["fee_rate"]),
            fee_exponent=int(row["fee_exponent"]),
            fee_flag=bool(row["fee_flag"]),
            source=row["source"],
            provider_version=row["provider_version"],
            retrieved_at_utc=retrieved,
            cache_version=row["cache_version"],
        )
