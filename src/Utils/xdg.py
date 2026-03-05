"""
Utils/xdg.py
Helpers for launching host-system programs (xdg-open etc.) safely from
inside an AppImage or a polluted shell environment.

When running as an AppImage, AppRun prepends bundled library paths to
LD_LIBRARY_PATH before launching Python.  Any subprocess that inherits
this environment may load the wrong shared libraries and fail silently
(e.g. Dolphin opening a folder).

host_env() always strips LD_LIBRARY_PATH from the child environment:
  - Inside an AppImage: restores it to the value saved by AppRun before
    the bundled paths were prepended.
  - Outside an AppImage: removes it entirely, protecting against polluted
    environments set by conda/pyenv/Steam runtimes/etc.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable


def host_env() -> dict[str, str]:
    """Return os.environ with LD_LIBRARY_PATH safe for host processes.

    Inside an AppImage: restores LD_LIBRARY_PATH to its pre-AppImage value
    (saved by AppRun as APPIMAGE_ORIGINAL_LD_LIBRARY_PATH).
    Outside an AppImage: strips LD_LIBRARY_PATH entirely to avoid polluted
    environments (conda, pyenv, Steam runtime, etc.) breaking xdg-open.
    """
    env = os.environ.copy()
    original = env.get("APPIMAGE_ORIGINAL_LD_LIBRARY_PATH")
    if original is not None:
        # Running inside an AppImage — restore pre-AppImage library path.
        if original:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)
    else:
        # Not in an AppImage — strip unconditionally.
        env.pop("LD_LIBRARY_PATH", None)
    return env


def xdg_open(path: str | Path, log_fn: Callable[[str], None] | None = None) -> None:
    """Open *path* with the user's default application via xdg-open.

    Uses host_env() so that the launched application (e.g. Dolphin) loads
    its own system libraries.  If xdg-open exits non-zero and log_fn is
    provided, the error is reported via log_fn without blocking the UI.
    """
    proc = subprocess.Popen(
        ["xdg-open", str(path)],
        env=host_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def _watch() -> None:
        _, err = proc.communicate()
        rc = proc.returncode
        if rc != 0 and log_fn:
            msg = err.decode(errors="replace").strip()
            log_fn(f"xdg-open returned {rc}: {msg or '(no output)'}")

    threading.Thread(target=_watch, daemon=True).start()
