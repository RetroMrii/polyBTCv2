"""Shared loader for stable script paths after implementation grouping."""
from pathlib import Path
import sys


def configure_paths() -> Path:
    scripts = Path(__file__).resolve().parent
    # Support both direct legacy commands and package/module invocation.
    for directory in (scripts.parent, scripts, scripts.parent / "src"):
        value = str(directory)
        if value not in sys.path:
            sys.path.insert(0, value)
    return scripts


def run(namespace: dict, relative_path: str) -> None:
    scripts = configure_paths()
    target = (scripts / relative_path).resolve()
    if not target.is_relative_to(scripts) or not target.is_file():
        raise ValueError("Invalid script implementation path")
    # Execute in the original module namespace: existing imports, private helper
    # access and monkeypatches retain their behavior. Preserve __name__ so the
    # usual main guard runs only for command-line invocation.
    namespace["__file__"] = str(target)
    exec(compile(target.read_bytes(), str(target), "exec"), namespace)
