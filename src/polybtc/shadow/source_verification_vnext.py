"""Offline source assertions from explicitly trusted acquisition evidence.

CSV timestamps, source_name and collector_version are not attestations. Paper
acquisition supplies retained evidence through its separate verifier adapter.
No network, fee refresh, or execution permission is provided by this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Mapping

from polybtc.data.fee_policy_cache_vnext import CachedFeePolicy, FeeCacheError
from polybtc.data.polymarket_fees import _validate_condition_id
from polybtc.data.schema import SnapshotRecord
from polybtc.data.paper_policy_vnext import MAX_BOOK_AGE_MS, MAX_REFERENCE_AGE_MS
from polybtc.data.verified_sources_vnext import VerifiedSources
from polybtc.data.causal_features_vnext import reference_anchor_30s

VERIFIER_VERSION = "source_verification_vnext_v2_consumed_anchor"


@dataclass(frozen=True, slots=True)
class SnapshotSourceEvidence:
    """Supplied only by a trusted acquisition boundary, never decoded from CSV.

    The producer must bind the entire snapshot to retained upstream messages,
    including the reference and strike semantics, explicit outcome mapping and
    each book response identity. evidence_id locates that retained evidence.
    Merely assigning a trusted producer name does not authenticate an input.
    """
    evidence_id: str
    producer: str
    snapshot: SnapshotRecord
    captured_at_utc: datetime
    reference_endpoint: str | None = None
    reference_topic: str | None = None
    reference_symbol: str | None = None
    reference_window_seconds: int | None = None
    strike_semantics_verified: bool = False
    metadata_endpoint: str | None = None
    metadata_condition_id: str | None = None
    outcome_tokens: tuple[tuple[str, str], ...] = ()
    yes_book_endpoint: str | None = None
    yes_book_condition_id: str | None = None
    yes_book_asset_id: str | None = None
    no_book_endpoint: str | None = None
    no_book_condition_id: str | None = None
    no_book_asset_id: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationDiagnostic:
    role: str
    snapshot_id: str
    source: str
    reason: str
    evidence_id: str | None = None
    source_timestamp: str | None = None
    evaluated_at_utc: str | None = None
    age_ms: float | None = None
    limit_ms: float | None = None


@dataclass(frozen=True, slots=True)
class SourceVerificationResult:
    sources: VerifiedSources
    condition_id: str
    prediction_snapshot_id: str
    execution_snapshot_id: str | None
    checked_at_utc: datetime
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fee_descriptor_verified: bool
    execution_scope: str = 'unverified'
    fee_accounting_model: str | None = None
    strike_model: str | None = None
    diagnostics: tuple[VerificationDiagnostic, ...] = ()
    reference_anchor_snapshot_id: str | None = None

    def provenance(self) -> dict:
        return dict(
            verifier_version=VERIFIER_VERSION,
            condition_id=self.condition_id,
            prediction_snapshot_id=self.prediction_snapshot_id,
            execution_snapshot_id=self.execution_snapshot_id,
            checked_at_utc=self.checked_at_utc.isoformat(),
            reference_source_verified=self.sources.reference_source_verified,
            yes_book_source_verified=self.sources.yes_book_source_verified,
            no_book_source_verified=self.sources.no_book_source_verified,
            fee_policy_verified=self.sources.fee_policy_verified,
            fee_descriptor_verified=self.fee_descriptor_verified,
            reasons=list(self.reasons), evidence_ids=list(self.evidence_ids),
            execution_scope=self.execution_scope,
            fee_accounting_model=self.fee_accounting_model,
            strike_model=self.strike_model,
            reference_anchor_snapshot_id=self.reference_anchor_snapshot_id,
            diagnostics_version=1,
            reference_max_age_ms=MAX_REFERENCE_AGE_MS,
            book_max_age_ms=MAX_BOOK_AGE_MS,
            diagnostics=[asdict(item) for item in self.diagnostics],
        )


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware source time required")
    return value.astimezone(timezone.utc)


def _fresh(stamp: datetime | None, at: datetime, max_age_ms: float) -> bool:
    try:
        return 0 <= (_utc(at) - _utc(stamp)).total_seconds() * 1000 <= max_age_ms
    except (ValueError, TypeError):
        return False


class VNextSourceVerificationAdapter:
    """Separate reference, YES, NO and fee checks; default trust set is empty.

    Evidence is an offline snapshot of trusted upstream attestations. This API
    is an injection boundary, not an implemented CSV authentication mechanism.
    The exact historical anchor consumed by inference must be attested. Selection
    is shared with inference; an invalid selected anchor never falls back to a
    different value merely to pass verification.
    """

    def __init__(
        self, *, trusted_producers: frozenset[str] = frozenset(),
        evidence: Mapping[str, SnapshotSourceEvidence] | None = None,
    ) -> None:
        self._trusted = frozenset(trusted_producers)
        self._evidence = dict(evidence or {})

    def _bound(self, row: SnapshotRecord, at: datetime) -> SnapshotSourceEvidence | None:
        return self._bound_result(row, at)[0]

    def _bound_result(self, row: SnapshotRecord, at: datetime):
        """Return evidence and a stable failure code without exposing raw payloads."""
        ev = self._evidence.get(row.snapshot_id)
        if not isinstance(ev, SnapshotSourceEvidence):
            return None, "missing_evidence"
        if ev.producer not in self._trusted or not ev.evidence_id.strip():
            return None, "untrusted_evidence"
        # The receipt bridge alone may replace the importer ingest timestamp.
        if replace(row, ingested_at=ev.snapshot.ingested_at) != ev.snapshot:
            return None, "snapshot_binding_mismatch"
        try:
            if not _utc(row.observed_at) <= _utc(ev.captured_at_utc) <= _utc(at):
                return None, "capture_outside_deadline"
            if _utc(row.ingested_at) > _utc(at):
                return None, "ingested_after_deadline"
        except (ValueError, TypeError):
            return None, "invalid_binding_timestamp"
        return ev, None

    @staticmethod
    def _reference(row: SnapshotRecord, ev: SnapshotSourceEvidence | None, at: datetime) -> bool:
        return bool(
            ev is not None
            and ((ev.reference_endpoint == "wss://ws-live-data.polymarket.com"
                  and ev.reference_topic in ("crypto_prices_twap_sixty", "prices.crypto.chainlink.twap")
                  and ev.reference_symbol == "btc/usd") or
                 (ev.reference_endpoint == "wss://ws-live-v2.polymarket.com/ws"
                  and ev.reference_topic == 'price.crypto.twap' and ev.reference_symbol == 'btcusd'))
            and type(ev.reference_window_seconds) is int
            and ev.reference_window_seconds == 60
            and ev.strike_semantics_verified is True
            and _fresh(row.reference_timestamp, at, MAX_REFERENCE_AGE_MS)
        )

    @staticmethod
    def _identity(row: SnapshotRecord, ev: SnapshotSourceEvidence | None) -> bool:
        if ev is None:
            return False
        try:
            market = _validate_condition_id(row.condition_id)
        except (ValueError, TypeError):
            return False
        tokens = (row.yes_token_id, row.no_token_id)
        if any(not isinstance(t, str) or not t.isascii() or not t.isdigit() for t in tokens):
            return False
        if tokens[0] == tokens[1]:
            return False
        return (
            ev.metadata_endpoint == "https://gamma-api.polymarket.com"
            and ev.metadata_condition_id == market
            and ev.outcome_tokens in (
                (("Up", tokens[0]), ("Down", tokens[1])),
                (("Yes", tokens[0]), ("No", tokens[1])),
            )
        )

    def verify(
        self, *, prediction: SnapshotRecord, execution: SnapshotRecord | None,
        history: list[SnapshotRecord], prediction_at: datetime, at: datetime,
        fee_policy: CachedFeePolicy | None, fee_rate: float | None,
    ) -> SourceVerificationResult:
        now = _utc(at)
        cutoff = _utc(prediction_at)
        reasons = []
        used = set()
        diagnostics = []
        market = prediction.condition_id.strip().lower()

        def issue(row, role, source, reason, deadline, ev=None, stamp=None, age=None, limit=None):
            diagnostics.append(VerificationDiagnostic(
                role, row.snapshot_id, source, reason,
                evidence_id=ev.evidence_id if ev else None,
                source_timestamp=stamp, evaluated_at_utc=_utc(deadline).isoformat(),
                age_ms=age, limit_ms=limit,
            ))

        def check_age(row, role, source, deadline, limit, ev):
            stamp = getattr(row, source + "_timestamp")
            try:
                stamp_text = _utc(stamp).isoformat()
                age = (_utc(deadline) - _utc(stamp)).total_seconds() * 1000
            except (ValueError, TypeError):
                issue(row, role, source, "invalid_source_timestamp", deadline, ev, limit=limit)
                return False
            if not 0 <= age <= limit:
                issue(row, role, source, "future_source_timestamp" if age < 0 else "stale_source",
                      deadline, ev, stamp_text, age, limit)
                return False
            return True

        def bound(row, deadline, role):
            ev, failure = self._bound_result(row, deadline)
            if ev is not None:
                used.add(ev.evidence_id)
            else:
                issue(row, role, "snapshot", failure, deadline)
            return ev

        def reference_diagnostics(row, ev, deadline, role):
            fresh = check_age(row, role, "reference", deadline, MAX_REFERENCE_AGE_MS, ev)
            if ev is not None and fresh and not self._reference(row, ev, deadline):
                issue(row, role, "reference", "reference_semantics_mismatch", deadline, ev)

        prediction_ev = bound(prediction, cutoff, "prediction")
        reference_diagnostics(prediction, prediction_ev, cutoff, "prediction")
        reference_ok = self._reference(prediction, prediction_ev, cutoff)
        # Historical reference freshness is evaluated at its own observation,
        # never against the later execution time.
        anchor = reference_anchor_30s(history, prediction, decision_at=cutoff)
        if anchor is None:
            reference_ok = False
            issue(prediction, "history", "reference", "missing_reference_anchor", cutoff)
        for row in ([anchor] if anchor is not None else []):
            ev = bound(row, cutoff, "history")
            reference_diagnostics(row, ev, row.observed_at, "history")
            if row.condition_id.strip().lower() != market or row.market_end_at != prediction.market_end_at:
                issue(row, "history", "market", "market_interval_mismatch", cutoff, ev)
            reference_ok = (
                self._reference(row, ev, row.observed_at)
                and row.condition_id.strip().lower() == market
                and row.market_end_at == prediction.market_end_at
                and reference_ok
            )
        yes_ok = no_ok = False
        if execution is None:
            reference_ok = False
            reasons.append("missing_execution_evidence")
        else:
            ev = bound(execution, now, "execution")
            reference_diagnostics(execution, ev, now, "execution")
            same_market = (
                execution.condition_id.strip().lower() == market
                and execution.market_end_at == prediction.market_end_at
                and execution.yes_token_id == prediction.yes_token_id
                and execution.no_token_id == prediction.no_token_id
            )
            reference_ok = reference_ok and same_market and self._reference(execution, ev, now)
            identity_ok = same_market and self._identity(prediction, prediction_ev) and self._identity(execution, ev)
            if not same_market:
                issue(execution, "execution", "market", "market_interval_or_tokens_mismatch", now, ev)
            for row, evidence, role, deadline in (
                (prediction, prediction_ev, "prediction", cutoff), (execution, ev, "execution", now)
            ):
                if evidence is not None and not self._identity(row, evidence):
                    issue(row, role, "market", "market_token_binding_mismatch", deadline, evidence)
            for side in ("yes", "no"):
                check_age(execution, "execution", side + "_book", now, MAX_BOOK_AGE_MS, ev)
                if ev is not None and (
                    getattr(ev, f"{side}_book_endpoint") != "https://clob.polymarket.com/book"
                    or getattr(ev, f"{side}_book_condition_id") != market
                    or getattr(ev, f"{side}_book_asset_id") != getattr(execution, f"{side}_token_id")
                ):
                    issue(execution, "execution", side + "_book", "book_identity_mismatch", now, ev)
                ok = bool(
                    identity_ok and ev is not None
                    and getattr(ev, f"{side}_book_endpoint") == "https://clob.polymarket.com/book"
                    and getattr(ev, f"{side}_book_condition_id") == market
                    and getattr(ev, f"{side}_book_asset_id") == getattr(execution, f"{side}_token_id")
                    and _fresh(getattr(execution, f"{side}_book_timestamp"), now, MAX_BOOK_AGE_MS)
                )
                if side == "yes":
                    yes_ok = ok
                else:
                    no_ok = ok
        for name, ok in (("reference", reference_ok), ("yes_book", yes_ok), ("no_book", no_ok)):
            if not ok:
                reasons.append(f"unverified_{name}_evidence")

        descriptor_ok = False
        if isinstance(fee_policy, CachedFeePolicy):
            try:
                fee_policy.validate_for_decision(market, fee_rate, now)
                descriptor_ok = True
            except (FeeCacheError, ValueError, TypeError):
                pass
        if not descriptor_ok:
            reasons.append("missing_or_invalid_fee_descriptor")
        # Current ledger adds a cash fee while retaining the full share count.
        # Descriptor compatibility alone cannot verify applicable fee accounting.
        reasons.append("fee_applicability_and_accounting_unverified")
        return SourceVerificationResult(
            sources=VerifiedSources(bool(reference_ok), yes_ok, no_ok, False),
            condition_id=market, prediction_snapshot_id=prediction.snapshot_id,
            execution_snapshot_id=execution.snapshot_id if execution else None,
            checked_at_utc=now, reasons=tuple(reasons),
            evidence_ids=tuple(sorted(used)), fee_descriptor_verified=descriptor_ok,
            diagnostics=tuple(diagnostics),
            reference_anchor_snapshot_id=anchor.snapshot_id if anchor is not None else None,
        )
