"""Pure causal reference selection shared by verification and inference."""

import math
from datetime import datetime, timedelta, timezone
from polybtc.data.schema import SnapshotRecord
from polybtc.data.paper_policy_vnext import PAPER_POLICY

ANCHOR_LAG_SECONDS = PAPER_POLICY.anchor_lag_seconds


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def _finite(
    value: object,
    *,
    positive: bool = False,
) -> bool:
    if value is None or isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(number) and (not positive or number > 0)


def _age_ms(
    now: datetime,
    earlier: datetime,
) -> float:
    return (_utc(now) - _utc(earlier)).total_seconds() * 1000.0


def _same_market(
    first: str,
    second: str,
) -> bool:
    return first.strip().lower() == second.strip().lower()


def reference_anchor_30s(
    history: list[SnapshotRecord],
    current: SnapshotRecord,
    *,
    decision_at: datetime,
) -> SnapshotRecord | None:
    """
    Exact causal dependency of the 30-second reference return.

    Prediction history is evaluated as of decision_at,
    which must be the historical prediction cutoff,
    not the later execution timestamp.

    The selected anchor must:

      - Belong to the same market.
      - Have been observed by decision_at.
      - Have been ingested by decision_at.
      - Have an observed_at <= current_at - 30s.
      - Be no more than 10 seconds older than
        the desired 30-second anchor.

    When an anchor has an upstream reference timestamp,
    that source event must also be no later than
    the prediction cutoff.
    """

    if not _finite(
        current.reference_price,
        positive=True,
    ):
        return None

    cutoff = _utc(decision_at)
    current_at = _utc(current.observed_at)

    if current_at > cutoff or _utc(current.ingested_at) > cutoff:
        return None

    target = current_at - timedelta(seconds=30)

    eligible = []

    for row in history:
        if not _same_market(
            row.condition_id,
            current.condition_id,
        ):
            continue

        if not _finite(
            row.reference_price,
            positive=True,
        ):
            continue

        row_observed = _utc(row.observed_at)
        row_ingested = _utc(row.ingested_at)

        if row_observed > target:
            continue

        if row_observed > cutoff:
            continue

        if row_ingested > cutoff:
            continue

        if row.reference_timestamp is not None:
            if _utc(row.reference_timestamp) > cutoff:
                continue

        eligible.append(row)

    if not eligible:
        return None

    anchor = max(
        eligible,
        key=lambda row: row.observed_at,
    )

    lag = (target - _utc(anchor.observed_at)).total_seconds()

    if lag < 0 or lag > ANCHOR_LAG_SECONDS:
        return None

    return anchor


def _reference_return_30s(history, current, *, decision_at):
    anchor = reference_anchor_30s(history, current, decision_at=decision_at)
    if anchor is None:
        return None
    return float(current.reference_price) / float(anchor.reference_price) - 1.0
