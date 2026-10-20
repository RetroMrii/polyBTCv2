"""Dashboard-owned, startup-only configuration. No request can select a file."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2]
ROOT = DASHBOARD.parent


@dataclass(frozen=True)
class Settings:
    telemetry: Path = ROOT / "data/live/vnext_market_snapshots.csv"
    decisions: Path = ROOT / "data/paper/vnext_verified/decisions.sqlite3"
    trades: Path = ROOT / "data/paper/vnext_verified/trades.sqlite3"
    resolutions: Path = ROOT / "data/paper/vnext_verified/resolutions.sqlite3"
    report: Path = ROOT / "data/paper/vnext_verified/prediction_report.json"
    recent_limit: int = 10000
    tail_bytes: int = 2 * 1024 * 1024

    @classmethod
    def load(cls):
        file = DASHBOARD / "config.toml"
        if not file.exists():
            return cls()
        data = tomllib.loads(file.read_text(encoding="utf-8")).get("paths", {})
        allowed = {"telemetry", "decisions", "trades", "resolutions", "report"}
        if set(data) - allowed:
            raise ValueError("Unknown dashboard path setting")
        return cls(**{key: (ROOT / value).resolve() for key, value in data.items()})
