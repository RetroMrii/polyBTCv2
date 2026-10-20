"""Runtime mode and durable state ownership; no live execution capability."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class OperatingMode(str, Enum):
    DATA_COLLECTION = "data_collection"
    RESEARCH_SHADOW = "research_shadow"
    PAPER_EXECUTION = "paper_execution"
    LIVE_EXECUTION = "live_execution"


DEFAULT_STATE_DIRS = {
    OperatingMode.DATA_COLLECTION: Path("data/collection/vnext"),
    OperatingMode.RESEARCH_SHADOW: Path("data/shadow/vnext_prospective"),
    OperatingMode.PAPER_EXECUTION: Path("data/paper/vnext"),
}
MODE_MARKER = "runtime_mode.json"
STATE_FILES = frozenset({
    "csv_tail.sqlite3", "receipts.sqlite3", "snapshot_history.sqlite3",
    "decisions.sqlite3", "trades.sqlite3", "paper.sqlite3", MODE_MARKER,
})


def supported_mode(value: OperatingMode | str) -> OperatingMode:
    mode = OperatingMode(value)
    if mode is OperatingMode.LIVE_EXECUTION:
        raise ValueError("Live execution is unavailable; this runtime is shadow/paper only")
    return mode


def bind_state_directory(path: Path, mode: OperatingMode) -> Path:
    """Bind a directory to one mode before constructing any runtime databases.

    Existing unmarked research directories remain compatible. Paper/collection
    require fresh directories or an exact marker match. Never relabel old state.
    Call under the existing single-process CLI lock in operational use.
    """
    mode = supported_mode(mode)
    directory = Path(path).resolve()
    # Do not place paper state in/around the established research default,
    # even when that default directory has not yet been initialized.
    if mode is OperatingMode.PAPER_EXECUTION:
        research = DEFAULT_STATE_DIRS[OperatingMode.RESEARCH_SHADOW].resolve()
        if directory == research or directory.is_relative_to(research) or research.is_relative_to(directory):
            raise ValueError("Paper state must be separate from research state")
    for parent in directory.parents:
        if any((parent / name).exists() for name in STATE_FILES):
            raise ValueError("Runtime state directories must not be nested")
    if directory.exists():
        for marker in directory.rglob(MODE_MARKER):
            if marker.parent != directory:
                raise ValueError("Runtime state directories must not contain other runtime state")
        if mode is not OperatingMode.RESEARCH_SHADOW and not (directory / MODE_MARKER).exists():
            # The process lock is allowed because the CLI obtains it first.
            if any(item.name != "vnext.lock" for item in directory.iterdir()):
                raise ValueError("Paper/collection mode requires a fresh, separate state directory")
    expected = {"version": 1, "mode": mode.value, "live_trading_enabled": False}
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MODE_MARKER
    try:
        with marker.open("x", encoding="utf-8") as handle:
            json.dump(expected, handle, sort_keys=True)
            handle.write("\n")
    except FileExistsError:
        try:
            actual = json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError("Unreadable runtime mode marker; investigate state") from exc
        if actual != expected:
            raise ValueError("State directory belongs to another mode or has invalid metadata")
    return directory
