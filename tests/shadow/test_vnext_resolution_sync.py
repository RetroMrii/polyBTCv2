import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from polybtc.data.schema import ResolutionValidationStatus
from scripts.operations import run_vnext_resolutions as sync


NOW = datetime(
    2026,
    10,
    9,
    18,
    0,
    tzinfo=timezone.utc,
)


class FakeService:
    def __init__(self):
        self.records = {}

    def resolutions(self):
        return list(self.records.values())

    def register(self, resolution):
        market = resolution.condition_id

        if market in self.records:
            raise ValueError("Duplicate registration")

        self.records[market] = {
            "condition_id": market,
            "label_yes": resolution.label_yes,
            "evidence_id": resolution.evidence_id,
        }

        return SimpleNamespace(status="VERIFIED")


def journal(tmp_path):
    path = tmp_path / "decisions.sqlite3"

    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE decisions (
                condition_id TEXT,
                target_at_utc TEXT
            )
        """)

        db.executemany(
            """
            INSERT INTO decisions VALUES (?, ?)
        """,
            [
                ("market-a", (NOW - timedelta(minutes=5)).isoformat()),
                ("market-a", (NOW - timedelta(minutes=4)).isoformat()),
                ("market-b", (NOW - timedelta(minutes=3)).isoformat()),
            ],
        )

    return path


def valid_label(market, label=1):
    return SimpleNamespace(
        condition_id=market,
        validation_status=ResolutionValidationStatus.VALID,
        label_yes=label,
        winning_token_id="winning-token-a",
        resolved_at=NOW - timedelta(minutes=3),
        resolution_source="polymarket_gamma+data_api_v2",
        resolution_source_version="gamma_exact_1_0+data_api_v2",
        validation_note=None,
    )


def test_registers_unique_market_outcomes(tmp_path, monkeypatch):
    path = journal(tmp_path)
    service = FakeService()

    monkeypatch.setattr(
        sync,
        "fetch_market_metadata",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "fetch_resolution",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "validate_resolution",
        lambda market, metadata, resolution, retrieved_at: valid_label(market),
    )

    result = sync.sync_once(
        journal_path=path,
        service=service,
        now=NOW,
        request_delay_seconds=0,
    )

    assert result["known_markets"] == 2
    assert result["registered"] == 2
    assert len(service.records) == 2


def test_repeat_does_not_duplicate(tmp_path, monkeypatch):
    path = journal(tmp_path)
    service = FakeService()

    monkeypatch.setattr(
        sync,
        "fetch_market_metadata",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "fetch_resolution",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "validate_resolution",
        lambda market, metadata, resolution, retrieved_at: valid_label(market),
    )

    first = sync.sync_once(
        journal_path=path,
        service=service,
        now=NOW,
        request_delay_seconds=0,
    )

    second = sync.sync_once(
        journal_path=path,
        service=service,
        now=NOW,
        request_delay_seconds=0,
    )

    assert first["registered"] == 2
    assert second.get("registered", 0) == 0
    assert second["already_registered"] == 2


def test_invalid_label_not_registered(tmp_path, monkeypatch):
    path = journal(tmp_path)
    service = FakeService()

    monkeypatch.setattr(
        sync,
        "fetch_market_metadata",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "fetch_resolution",
        lambda market: object(),
    )

    monkeypatch.setattr(
        sync,
        "validate_resolution",
        lambda market, metadata, resolution, retrieved_at: SimpleNamespace(
            validation_status=ResolutionValidationStatus.DISPUTED,
            validation_note="Gamma and Data API disagree",
        ),
    )

    result = sync.sync_once(
        journal_path=path,
        service=service,
        now=NOW,
        request_delay_seconds=0,
    )

    assert result.get("registered", 0) == 0
    assert len(service.records) == 0
    assert result["not_valid"] == 2


def test_recent_resolution_remains_pending(tmp_path, monkeypatch):
    path = journal(tmp_path)
    service = FakeService()

    monkeypatch.setattr(
        sync,
        "fetch_market_metadata",
        lambda market: object(),
    )
    monkeypatch.setattr(
        sync,
        "fetch_resolution",
        lambda market: object(),
    )

    def validate(market, metadata, resolution, retrieved_at):
        label = valid_label(market)
        label.resolved_at = NOW - timedelta(seconds=30)
        return label

    monkeypatch.setattr(sync, "validate_resolution", validate)

    result = sync.sync_once(
        journal_path=path,
        service=service,
        now=NOW,
        request_delay_seconds=0,
    )

    assert result["recent_resolution"] == 2
    assert not service.records


def test_missing_journal_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        sync.sync_once(
            journal_path=tmp_path / "missing.sqlite3",
            service=FakeService(),
            now=NOW,
            request_delay_seconds=0,
        )
