from __future__ import annotations

import csv

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np

from polybtc.data.dataset.features import (
    build_snapshot_features,
)
from polybtc.data.dataset.history_features import (
    build_history_features,
)
from polybtc.data.dataset.horizons import (
    select_market_horizons,
)
from polybtc.data.importers.v1_market_snapshots import (
    import_v1_market_snapshots,
)
from polybtc.strategy.consensus import (
    ConsensusConfig,
    ConsensusDecision,
    ConsensusInput,
    evaluate_consensus,
)


SHADOW_VERSION = "p12_consensus_shadow_v2"

ALLOWED_HORIZONS = (
    60,
    30,
)


OUTPUT_FIELDS = (
    "shadow_version",
    "model_version",
    "research_cutoff",
    "condition_id",
    "prediction_timestamp",
    "snapshot_observed_at",
    "target_horizon_seconds",
    "actual_seconds_to_expiry",
    "horizon_gap_seconds",
    "reference_price",
    "strike",
    "relative_distance_from_strike",
    "reference_return_30s",
    "model_probability",
    "market_probability",
    "probability_gap",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "yes_top_depth",
    "no_top_depth",
    "yes_book_age_ms",
    "no_book_age_ms",
    "decision",
    "side",
    "reason",
    "selected_ask",
    "selected_depth",
    "selected_book_age_ms",
    "selected_tick_size",
)


@dataclass(frozen=True)
class ShadowRunResult:
    snapshots: int
    candidate_horizons: int
    already_emitted: int
    newly_written: int
    trades: int
    abstains: int


def _decision_key(
    condition_id: str,
    horizon: int,
) -> tuple[str, int]:
    return (
        condition_id.strip().lower(),
        int(horizon),
    )


def _ensure_output_schema(
    output_path: Path,
) -> None:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return

    with output_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        existing_fields = reader.fieldnames or []

        rows = list(reader)

    if existing_fields == list(OUTPUT_FIELDS):
        return

    expected_old_fields = [
        field for field in OUTPUT_FIELDS if field != "selected_tick_size"
    ]

    if existing_fields != expected_old_fields:
        raise RuntimeError(f"unsupported P12 shadow CSV schema: {existing_fields}")

    for row in rows:
        row["selected_tick_size"] = ""

    temp_path = output_path.with_suffix(".csv.tmp")

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
            extrasaction="raise",
        )

        writer.writeheader()
        writer.writerows(rows)

    temp_path.replace(output_path)


def _load_existing_state(
    output_path: Path,
) -> tuple[
    set[tuple[str, int]],
    set[str],
]:
    emitted_keys: set[tuple[str, int]] = set()

    traded_markets: set[str] = set()

    if not output_path.exists():
        return (
            emitted_keys,
            traded_markets,
        )

    with output_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            condition_id = row["condition_id"].strip().lower()

            horizon = int(row["target_horizon_seconds"])

            emitted_keys.add(
                _decision_key(
                    condition_id,
                    horizon,
                )
            )

            if row["decision"].strip() == ConsensusDecision.TRADE.value:
                traded_markets.add(condition_id)

    return (
        emitted_keys,
        traded_markets,
    )


def _append_rows(
    output_path: Path,
    rows: list[dict],
) -> None:
    if not rows:
        return

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_header = not output_path.exists() or output_path.stat().st_size == 0

    with output_path.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_FIELDS,
        )

        if write_header:
            writer.writeheader()

        writer.writerows(rows)


def run_shadow(
    *,
    snapshots_path: Path,
    model_path: Path,
    output_path: Path,
) -> ShadowRunResult:
    artifact = joblib.load(model_path)

    model_version = artifact["model_version"]

    research_cutoff = artifact["research_cutoff"]

    expected_features = [
        "relative_distance_from_strike",
        "target_horizon_seconds",
        "reference_return_30s",
    ]

    if artifact["features"] != expected_features:
        raise RuntimeError(
            f"P12 model feature contract mismatch: {artifact['features']}"
        )

    model = artifact["pipeline"]

    snapshots = import_v1_market_snapshots(snapshots_path)

    if not snapshots:
        return ShadowRunResult(
            snapshots=0,
            candidate_horizons=0,
            already_emitted=0,
            newly_written=0,
            trades=0,
            abstains=0,
        )

    latest_observed_by_market = {}

    for snapshot in snapshots:
        existing = latest_observed_by_market.get(snapshot.condition_id)

        if existing is None or snapshot.observed_at > existing:
            latest_observed_by_market[snapshot.condition_id] = snapshot.observed_at

    selections = select_market_horizons(
        snapshots,
        horizons=ALLOWED_HORIZONS,
    )

    _ensure_output_schema(output_path)

    emitted_keys, traded_markets = _load_existing_state(output_path)

    config = ConsensusConfig()
    pending = []

    for selection in selections:
        if selection.status != "SELECTED":
            continue

        snapshot = selection.snapshot

        if snapshot is None:
            raise RuntimeError("SELECTED horizon missing snapshot")

        if snapshot.market_end_at is None:
            raise RuntimeError("selected snapshot missing market_end_at")

        horizon = int(selection.target_seconds_to_expiry)

        prediction_timestamp = snapshot.market_end_at - timedelta(seconds=horizon)

        if prediction_timestamp.isoformat() <= research_cutoff:
            continue

        latest_observed = latest_observed_by_market[snapshot.condition_id]

        # Do not finalize this horizon until
        # telemetry has progressed past its
        # prediction timestamp. This prevents
        # a later snapshot <= prediction time
        # from changing the P4-style selection.
        if latest_observed <= prediction_timestamp:
            continue

        key = _decision_key(
            snapshot.condition_id,
            horizon,
        )

        if key in emitted_keys:
            continue

        pending.append(
            (
                prediction_timestamp,
                horizon,
                selection,
            )
        )

    pending.sort(
        key=lambda item: (
            item[0],
            item[2].condition_id,
            -item[1],
        )
    )

    output_rows = []

    trade_count = 0
    abstain_count = 0

    for (
        prediction_timestamp,
        horizon,
        selection,
    ) in pending:
        snapshot = selection.snapshot

        if snapshot is None:
            raise RuntimeError("selected shadow snapshot missing")

        condition_id = snapshot.condition_id.strip().lower()

        features = build_snapshot_features(snapshot)

        history_features = build_history_features(
            snapshots,
            snapshot,
        )

        relative_distance = features.relative_distance_from_strike

        reference_return_30s = history_features.reference_return_30s

        if relative_distance is None:
            raise RuntimeError(
                f"selected snapshot missing relative distance: {snapshot.snapshot_id}"
            )

        if reference_return_30s is None:
            # We still emit an explicit
            # abstention rather than silently
            # dropping the horizon.
            model_probability = None
            market_probability = features.normalized_yes_mid

            probability_gap = None

            decision = ConsensusDecision.ABSTAIN.value

            side = None
            reason = "missing_reference_return_30s"

            selected_ask = None
            selected_depth = None
            selected_book_age_ms = None

        else:
            feature_vector = np.array(
                [
                    [
                        relative_distance,
                        float(horizon),
                        reference_return_30s,
                    ]
                ],
                dtype=float,
            )

            model_probability = float(model.predict_proba(feature_vector)[0, 1])

            market_probability = features.normalized_yes_mid

            if condition_id in traded_markets:
                probability_gap = (
                    abs(model_probability - market_probability)
                    if market_probability is not None
                    else None
                )

                decision = ConsensusDecision.ABSTAIN.value

                side = None
                reason = "market_already_has_shadow_entry"

                selected_ask = None
                selected_depth = None
                selected_book_age_ms = None

            else:
                consensus = evaluate_consensus(
                    candidate=ConsensusInput(
                        condition_id=(condition_id),
                        target_horizon_seconds=(horizon),
                        model_probability=(model_probability),
                        market_probability=(market_probability),
                        yes_ask=(snapshot.yes_ask),
                        no_ask=(snapshot.no_ask),
                        yes_top_depth=(features.yes_top_depth),
                        no_top_depth=(features.no_top_depth),
                        yes_book_age_ms=(features.yes_book_age_ms),
                        no_book_age_ms=(features.no_book_age_ms),
                    ),
                    config=config,
                )

                probability_gap = consensus.probability_gap

                decision = consensus.decision.value

                side = consensus.side.value if consensus.side is not None else None

                reason = consensus.reason

                selected_ask = consensus.selected_ask

                selected_depth = consensus.selected_depth

                selected_book_age_ms = consensus.selected_book_age_ms

                if consensus.decision == ConsensusDecision.TRADE:
                    traded_markets.add(condition_id)

        if side == "YES":
            selected_tick_size = snapshot.yes_tick_size
        elif side == "NO":
            selected_tick_size = snapshot.no_tick_size
        else:
            selected_tick_size = None

        if decision == ConsensusDecision.TRADE.value:
            if selected_tick_size is None:
                raise RuntimeError(
                    f"TRADE decision missing selected-side tick size: {condition_id}"
                )

            trade_count += 1
        else:
            abstain_count += 1

        output_rows.append(
            {
                "shadow_version": (SHADOW_VERSION),
                "model_version": (model_version),
                "research_cutoff": (research_cutoff),
                "condition_id": (condition_id),
                "prediction_timestamp": (prediction_timestamp.isoformat()),
                "snapshot_observed_at": (snapshot.observed_at.isoformat()),
                "target_horizon_seconds": (horizon),
                "actual_seconds_to_expiry": (selection.actual_seconds_to_expiry),
                "horizon_gap_seconds": (selection.horizon_gap_seconds),
                "reference_price": (snapshot.reference_price),
                "strike": (snapshot.strike),
                "relative_distance_from_strike": (relative_distance),
                "reference_return_30s": (reference_return_30s),
                "model_probability": (model_probability),
                "market_probability": (market_probability),
                "probability_gap": (probability_gap),
                "yes_bid": (snapshot.yes_bid),
                "yes_ask": (snapshot.yes_ask),
                "no_bid": (snapshot.no_bid),
                "no_ask": (snapshot.no_ask),
                "yes_top_depth": (features.yes_top_depth),
                "no_top_depth": (features.no_top_depth),
                "yes_book_age_ms": (features.yes_book_age_ms),
                "no_book_age_ms": (features.no_book_age_ms),
                "decision": (decision),
                "side": (side),
                "reason": (reason),
                "selected_ask": (selected_ask),
                "selected_depth": (selected_depth),
                "selected_book_age_ms": (selected_book_age_ms),
                "selected_tick_size": (selected_tick_size),
            }
        )

        emitted_keys.add(
            _decision_key(
                condition_id,
                horizon,
            )
        )

    _append_rows(
        output_path,
        output_rows,
    )

    return ShadowRunResult(
        snapshots=len(snapshots),
        candidate_horizons=len(pending),
        already_emitted=(len(selections) - len(pending)),
        newly_written=len(output_rows),
        trades=trade_count,
        abstains=abstain_count,
    )
