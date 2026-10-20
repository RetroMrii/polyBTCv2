"""Authoritative paper timing contract; no model or execution dependencies."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaperPolicy:
    max_reference_age_ms: float = 3000.0
    max_book_age_ms: float = 500.0
    horizons: tuple[int, ...] = (240, 180, 120, 90, 60, 30)
    horizon_lag_seconds: float = 10.0
    anchor_lag_seconds: float = 10.0
    finalization_grace_seconds: float = 2.0
    execution_wait_seconds: float = 1.0


PAPER_POLICY = PaperPolicy()
MAX_REFERENCE_AGE_MS = PAPER_POLICY.max_reference_age_ms
MAX_BOOK_AGE_MS = PAPER_POLICY.max_book_age_ms
