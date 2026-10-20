"""Windows process ownership lock shared by acquisition and paper entry points."""

from contextlib import contextmanager
from pathlib import Path
import msvcrt


@contextmanager
def exclusive_lock(path: Path):
    """
    Windows-only single-instance process lock.

    Hold a one-byte region lock for the entire runtime.
    A second process fails rather than racing the
    same CSV checkpoint and decision databases.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"\0")
        handle.flush()
        handle.seek(0)

        try:
            msvcrt.locking(
                handle.fileno(),
                msvcrt.LK_NBLCK,
                1,
            )
        except OSError as exc:
            raise RuntimeError(
                "Another vNext collector process already owns this state directory"
            ) from exc

        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(
                handle.fileno(),
                msvcrt.LK_UNLCK,
                1,
            )
