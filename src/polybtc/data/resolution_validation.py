from __future__ import annotations

from datetime import datetime

from polybtc.data.polymarket_metadata import (
    PolymarketMarketMetadata,
)
from polybtc.data.polymarket_resolution import (
    PolymarketResolution,
)
from polybtc.data.schema import (
    LabelRecord,
    Outcome,
    ResolutionValidationStatus,
)


LABEL_VERSION = "p3_v1"

RESOLUTION_SOURCE_VERSION = "gamma_exact_1_0+data_api_v2"


def _missing_label(
    condition_id: str,
    retrieved_at: datetime,
    *,
    status: ResolutionValidationStatus,
    note: str,
    resolved_at: datetime | None = None,
) -> LabelRecord:
    return LabelRecord(
        condition_id=condition_id,
        resolution_source=("polymarket_gamma+data_api_v2"),
        retrieved_at=retrieved_at,
        validation_status=status,
        resolved_at=resolved_at,
        winning_outcome=None,
        winning_token_id=None,
        label_yes=None,
        resolution_source_version=(RESOLUTION_SOURCE_VERSION),
        label_version=LABEL_VERSION,
        validation_note=note,
    )


def validate_resolution(
    condition_id: str,
    metadata: PolymarketMarketMetadata | None,
    resolution: PolymarketResolution | None,
    *,
    retrieved_at: datetime,
) -> LabelRecord:
    normalized_condition_id = condition_id.strip().lower()

    if metadata is None:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.MISSING,
            note="Gamma market metadata missing.",
        )

    if metadata.condition_id.strip().lower() != normalized_condition_id:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note=("Gamma condition_id does not match requested condition_id."),
        )

    if resolution is None:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.MISSING,
            note="Data API resolution record missing.",
        )

    if resolution.condition_id.strip().lower() != normalized_condition_id:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note=("Data API condition_id does not match requested condition_id."),
            resolved_at=resolution.resolved_at,
        )

    if not resolution.resolved:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.UNRESOLVED,
            note=("Data API does not confirm market resolution."),
            resolved_at=resolution.resolved_at,
        )

    if metadata.closed is not True:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.UNRESOLVED,
            note="Gamma does not mark market closed.",
            resolved_at=resolution.resolved_at,
        )

    if metadata.winning_outcome not in {
        "YES",
        "NO",
    }:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note=("Gamma does not contain an exact 1/0 binary resolved outcome."),
            resolved_at=resolution.resolved_at,
        )

    if metadata.yes_token_id is None:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note="Gamma YES token_id missing.",
            resolved_at=resolution.resolved_at,
        )

    if metadata.no_token_id is None:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note="Gamma NO token_id missing.",
            resolved_at=resolution.resolved_at,
        )

    if metadata.winning_outcome == "YES":
        expected_token_id = metadata.yes_token_id
        outcome = Outcome.YES
        label_yes = 1
    else:
        expected_token_id = metadata.no_token_id
        outcome = Outcome.NO
        label_yes = 0

    if metadata.winning_token_id != expected_token_id:
        return _missing_label(
            condition_id,
            retrieved_at,
            status=ResolutionValidationStatus.INVALID,
            note=("Gamma winning token does not match outcome token mapping."),
            resolved_at=resolution.resolved_at,
        )

    # The Data API sometimes supplies only resolved_at.
    # If it also supplies winner information, require it
    # to agree with Gamma instead of silently choosing one.
    if (
        resolution.winning_outcome is not None
        and resolution.winning_outcome != metadata.winning_outcome
    ):
        return LabelRecord(
            condition_id=condition_id,
            resolution_source=("polymarket_gamma+data_api_v2"),
            retrieved_at=retrieved_at,
            validation_status=(ResolutionValidationStatus.DISPUTED),
            resolved_at=resolution.resolved_at,
            winning_outcome=None,
            winning_token_id=None,
            label_yes=None,
            resolution_source_version=(RESOLUTION_SOURCE_VERSION),
            label_version=LABEL_VERSION,
            validation_note=("Gamma and Data API winning outcomes disagree."),
        )

    if (
        resolution.winning_token_id is not None
        and resolution.winning_token_id != metadata.winning_token_id
    ):
        return LabelRecord(
            condition_id=condition_id,
            resolution_source=("polymarket_gamma+data_api_v2"),
            retrieved_at=retrieved_at,
            validation_status=(ResolutionValidationStatus.DISPUTED),
            resolved_at=resolution.resolved_at,
            winning_outcome=None,
            winning_token_id=None,
            label_yes=None,
            resolution_source_version=(RESOLUTION_SOURCE_VERSION),
            label_version=LABEL_VERSION,
            validation_note=("Gamma and Data API winning token IDs disagree."),
        )

    return LabelRecord(
        condition_id=condition_id,
        resolution_source=("polymarket_gamma+data_api_v2"),
        retrieved_at=retrieved_at,
        validation_status=(ResolutionValidationStatus.VALID),
        resolved_at=resolution.resolved_at,
        winning_outcome=outcome,
        winning_token_id=(metadata.winning_token_id),
        label_yes=label_yes,
        resolution_source_version=(RESOLUTION_SOURCE_VERSION),
        label_version=LABEL_VERSION,
        validation_note=None,
    )
