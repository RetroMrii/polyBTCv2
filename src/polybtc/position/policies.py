from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PositionPolicyId(StrEnum):
    BASELINE_HOLD = "p9_baseline_hold"


class ExitPolicy(StrEnum):
    HOLD_TO_SETTLEMENT = "hold_to_settlement"


class ReentryPolicy(StrEnum):
    NONE = "none"


@dataclass(
    frozen=True,
    slots=True,
)
class PositionPolicy:
    policy_id: PositionPolicyId

    maximum_entries_per_market: int

    exit_policy: ExitPolicy
    reentry_policy: ReentryPolicy

    allow_scale_in: bool
    allow_scale_out: bool
    allow_reversal: bool


BASELINE_HOLD_POLICY = PositionPolicy(
    policy_id=(PositionPolicyId.BASELINE_HOLD),
    maximum_entries_per_market=1,
    exit_policy=(ExitPolicy.HOLD_TO_SETTLEMENT),
    reentry_policy=(ReentryPolicy.NONE),
    allow_scale_in=False,
    allow_scale_out=False,
    allow_reversal=False,
)
