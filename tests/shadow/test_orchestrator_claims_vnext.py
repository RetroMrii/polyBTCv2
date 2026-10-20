from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from polybtc.data.schema import SnapshotRecord
from polybtc.shadow.orchestrator_vnext import (
    OrchestratorConfig,
    VNextDecisionOrchestrator,
)


END = datetime(2026, 10, 8, 15, 5, tzinfo=timezone.utc)

TARGET = END - timedelta(seconds=60)
PROCESSING_TIME = TARGET + timedelta(seconds=2)


def ready_snapshot():
    return SnapshotRecord(
        snapshot_id="claim-snapshot",
        condition_id="claim-market",
        observed_at=TARGET,
        ingested_at=TARGET,
        source_name="claim_test",
        market_end_at=END,
    )


def make_orchestrator(path):
    return VNextDecisionOrchestrator(
        journal_path=path,
        config=OrchestratorConfig(
            horizons=(60,),
            finalization_grace_seconds=2.0,
        ),
    )


@pytest.fixture
def prepared(tmp_path):
    journal = make_orchestrator(tmp_path / "claims.sqlite3")

    results = journal.process(
        snapshots=[ready_snapshot()],
        processing_at_utc=PROCESSING_TIME,
    )

    assert len(results) == 1
    assert results[0].status == ("AWAITING_EXECUTION_ADAPTER")

    return journal


def claim(journal):
    return journal.claim(
        condition_id="claim-market",
        horizon_seconds=60,
        at=PROCESSING_TIME,
    )


def test_claim_once(prepared):
    token = claim(prepared)

    assert isinstance(token, str)
    assert token

    assert claim(prepared) is None

    row = prepared.decisions()[0]

    assert row["status"] == "PROCESSING"
    assert row["claim_token"] == token


def test_complete_abstention(prepared):
    token = claim(prepared)

    assert prepared.complete_abstention(
        condition_id="claim-market",
        horizon_seconds=60,
        claim_token=token,
        reason="unverified_fee_policy",
        at=PROCESSING_TIME,
    )

    row = prepared.decisions()[0]

    assert row["status"] == "ABSTAIN"
    assert row["reason"] == "unverified_fee_policy"
    assert row["completed_at_utc"] is not None


def test_wrong_owner_cannot_complete(prepared):
    claim(prepared)

    completed = prepared.complete_abstention(
        condition_id="claim-market",
        horizon_seconds=60,
        claim_token="wrong-owner",
        reason="test",
        at=PROCESSING_TIME,
    )

    assert not completed
    assert prepared.decisions()[0]["status"] == "PROCESSING"


def test_completion_is_not_repeated(prepared):
    token = claim(prepared)

    arguments = dict(
        condition_id="claim-market",
        horizon_seconds=60,
        claim_token=token,
        reason="missing_verified_quote",
        at=PROCESSING_TIME,
    )

    assert prepared.complete_abstention(**arguments)
    assert not prepared.complete_abstention(**arguments)


def test_restart_preserves_claim(prepared):
    token = claim(prepared)

    reopened = make_orchestrator(prepared.path)

    unresolved = reopened.unresolved_claims()

    assert len(unresolved) == 1
    assert unresolved[0]["claim_token"] == token
    assert claim(reopened) is None


def test_concurrent_claim_has_one_winner(prepared):
    def attempt(_):
        journal = make_orchestrator(prepared.path)
        return claim(journal)

    with ThreadPoolExecutor(max_workers=6) as pool:
        tokens = list(pool.map(attempt, range(6)))

    winners = [token for token in tokens if token]

    assert len(winners) == 1

    assert prepared.decisions()[0]["claim_token"] == (winners[0])


def test_reject_invalid_probability(prepared):
    token = claim(prepared)

    with pytest.raises(ValueError):
        prepared.complete_abstention(
            condition_id="claim-market",
            horizon_seconds=60,
            claim_token=token,
            reason="invalid_probability_test",
            at=PROCESSING_TIME,
            model_probability_yes=float("nan"),
        )

    assert prepared.decisions()[0]["status"] == "PROCESSING"
