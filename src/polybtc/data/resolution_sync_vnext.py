from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from polybtc.data.polymarket_metadata import (
    fetch_market_metadata,
)
from polybtc.data.polymarket_resolution import (
    fetch_resolution,
)
from polybtc.data.resolution_validation import (
    LABEL_VERSION,
    RESOLUTION_SOURCE_VERSION,
    validate_resolution,
)
from polybtc.data.schema import ResolutionValidationStatus
from polybtc.shadow.settlement_vnext import (
    VerifiedResolution,
    VNextSettlementService,
)


LOG = logging.getLogger("polybtc.vnext.resolutions")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_journal_markets(
    journal_path: Path,
    *,
    now: datetime,
) -> list[str]:
    """Read market IDs whose decision horizon has passed."""
    path = Path(journal_path).resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    with sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=15,
    ) as conn:
        conn.execute("PRAGMA query_only=ON")

        rows = conn.execute(
            """
            SELECT DISTINCT condition_id
            FROM decisions
            WHERE target_at_utc <= ?
              AND condition_id IS NOT NULL
              AND TRIM(condition_id) != ''
            ORDER BY condition_id
        """,
            (now.astimezone(timezone.utc).isoformat(timespec="microseconds"),),
        ).fetchall()

    return sorted({str(row[0]).strip().lower() for row in rows})


def _evidence_id(label) -> str:
    """
    Stable identity for one validated outcome.

    Retrieval time is deliberately excluded so
    fetching the same result twice doesn't produce
    different evidence identities.
    """
    payload = {
        "condition_id": label.condition_id.strip().lower(),
        "label_yes": label.label_yes,
        "winning_token_id": label.winning_token_id,
        "resolved_at": label.resolved_at.isoformat(),
        "source_version": RESOLUTION_SOURCE_VERSION,
        "label_version": LABEL_VERSION,
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def sync_once(
    *,
    journal_path: Path,
    service: VNextSettlementService,
    now: datetime,
    limit: int = 100,
    min_age_seconds: float = 120.0,
    request_delay_seconds: float = 0.1,
    metadata_fetcher=None,
    resolution_fetcher=None,
    validator=None,
) -> dict[str, int]:
    """
    Discover and register completed market outcomes.

    No settlement, execution, or trading operations.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    if min_age_seconds < 0 or request_delay_seconds < 0:
        raise ValueError("Invalid timing configuration")

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware now required")

    metadata_fetcher = metadata_fetcher or fetch_market_metadata
    resolution_fetcher = resolution_fetcher or fetch_resolution
    validator = validator or validate_resolution
    counts: Counter[str] = Counter()

    registered = {row["condition_id"].strip().lower() for row in service.resolutions()}

    markets = _read_journal_markets(
        journal_path,
        now=now,
    )

    # Avoid repeated calls for outcomes we already have.
    pending = [market for market in markets if market not in registered]

    counts["known_markets"] = len(markets)
    counts["already_registered"] = len(markets) - len(pending)

    for condition_id in pending[:limit]:
        counts["checked"] += 1

        try:
            # Market metadata includes the five-minute
            # market's scheduled end timestamp when
            # supported by the existing provider.
            metadata = metadata_fetcher(condition_id)
            resolution = resolution_fetcher(condition_id)

            label = validator(
                condition_id,
                metadata,
                resolution,
                retrieved_at=_utc_now(),
            )

            status = label.validation_status

            if status != ResolutionValidationStatus.VALID:
                counts["not_valid"] += 1
                counts[str(status)] += 1
                LOG.info(
                    "market=%s validation=%s note=%s",
                    condition_id,
                    status,
                    label.validation_note,
                )
                continue

            if (
                label.label_yes not in (0, 1)
                or isinstance(label.label_yes, bool)
                or label.resolved_at is None
                or not label.winning_token_id
            ):
                counts["incomplete_valid_label"] += 1
                LOG.warning(
                    "VALID label lacks settlement evidence: %s",
                    condition_id,
                )
                continue

            resolved_at = label.resolved_at.astimezone(timezone.utc)

            if resolved_at.tzinfo is None or resolved_at > now:
                counts["invalid_resolution_time"] += 1
                continue

            # Give the source time to finalize. This
            # is not a claim about Polymarket finality;
            # VALID verification is still mandatory.
            if (now - resolved_at).total_seconds() < min_age_seconds:
                counts["recent_resolution"] += 1
                continue

            source = f"{label.resolution_source}:{label.resolution_source_version}"

            result = service.register(
                VerifiedResolution(
                    condition_id=condition_id,
                    label_yes=int(label.label_yes),
                    resolved_at_utc=resolved_at,
                    evidence_source=source,
                    evidence_id=_evidence_id(label),
                )
            )

            counts["registered"] += 1

            LOG.info(
                "market=%s outcome=%s status=%s",
                condition_id,
                label.label_yes,
                result.status,
            )

        except ValueError:
            # Conflicting evidence must never be
            # ignored or overwritten.
            LOG.exception(
                "Validation/registry conflict: %s",
                condition_id,
            )
            raise

        except Exception:
            # A provider/network failure is not a NO.
            # Leave the market pending for another run.
            counts["provider_errors"] += 1
            LOG.exception(
                "Resolution fetch failed: %s",
                condition_id,
            )

        finally:
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

    counts["remaining_unregistered"] = len(pending) - counts["registered"]

    return dict(sorted(counts.items()))
