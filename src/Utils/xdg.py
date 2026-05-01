"""
Utils/xdg.py
Helpers for launching host-system programs (xdg-open etc.) safely from
a polluted shell environment.

Inside an AppImage, anylinux.so (LD_PRELOAD-injected by quick-sharun) hooks
execve and scrubs AppDir-pointing env vars from child processes — so we
don't need to do anything special there. sharun also doesn't use
LD_LIBRARY_PATH; it invokes the dynamic linker with --library-path.

host_env() therefore only protects against pollution from *outside* the
AppImage: conda/pyenv/Steam-runtime can leave LD_LIBRARY_PATH pointing at
incompatible libraries, which would break xdg-open or Dolphin.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from Utils.app_log import app_log


def host_env() -> dict[str, str]:
    """Return os.environ with LD_LIBRARY_PATH stripped.

    Inside an AppImage, anylinux.so already removes AppDir-pointing env
    vars from spawned processes, so nothing extra is needed there.
    Outside an AppImage we strip LD_LIBRARY_PATH defensively to avoid
    polluted environments (conda, pyenv, Steam runtime, etc.) breaking
    xdg-open.
    """
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    return env


def _in_flatpak() -> bool:
    return os.path.exists("/.flatpak-info")


def _spawn_watched(
    cmd: list[str],
    label: str,
    log_fn: Callable[[str], None] | None,
    on_fail: Callable[[], None] | None = None,
) -> None:
    """Run *cmd* in the background, log non-zero exits, optionally chain a fallback."""
    # Use a CWD the host definitely has. Inside Flatpak the sandbox CWD
    # (e.g. /app/share/amethyst-mod-manager) doesn't exist on the host, so
    # `flatpak-spawn --host` inherits it and the spawned host process fails
    # to start with "Failed to change to directory".
    cwd = os.path.expanduser("~") if os.path.isdir(os.path.expanduser("~")) else "/"
    try:
        proc = subprocess.Popen(
            cmd,
            env=host_env(),
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        msg = f"{label}: {cmd[0]} not found ({exc})"
        app_log(msg)
        if log_fn:
            log_fn(msg)
        if on_fail:
            on_fail()
        return

    def _watch() -> None:
        _, err = proc.communicate()
        rc = proc.returncode
        if rc != 0:
            text = err.decode(errors="replace").strip() or "(no output)"
            msg = f"{label}: rc={rc} {text}"
            app_log(msg)
            if log_fn:
                log_fn(msg)
            if on_fail:
                on_fail()

    threading.Thread(target=_watch, daemon=True).start()


def xdg_open(path: str | Path, log_fn: Callable[[str], None] | None = None) -> None:
    """Open *path* with the user's default application via xdg-open.

    Uses host_env() so that the launched application (e.g. Dolphin) loads
    its own system libraries. Failures are logged to app_log (always) and
    log_fn (if provided), so they don't disappear silently.

    Inside a Flatpak sandbox the runtime's xdg-open usually can't resolve
    host MIME associations (or lacks the target app entirely), so we route
    through ``flatpak-spawn --host`` when available. Fall back to bare
    xdg-open if flatpak-spawn isn't usable.
    """
    target = str(path)
    if _in_flatpak() and shutil.which("flatpak-spawn"):
        cmd = ["flatpak-spawn", "--host", "xdg-open", target]
    else:
        cmd = ["xdg-open", target]
    _spawn_watched(cmd, f"xdg-open {target!r}", log_fn)


def open_url(url: str, log_fn: Callable[[str], None] | None = None) -> None:
    """Open *url* in the user's default browser.

    Inside a Flatpak sandbox `xdg-open` from the runtime usually can't reach
    the host's browser. Try, in order:
      1. `flatpak-spawn --host xdg-open <url>` — runs xdg-open on the host.
      2. `gio open <url>` — uses the OpenURI portal from inside the sandbox.
      3. bare `xdg-open <url>` — last resort.
    Each step's failure is logged and triggers the next.
    """
    if not _in_flatpak():
        _spawn_watched(["xdg-open", url], f"xdg-open {url!r}", log_fn)
        return

    def try_gio() -> None:
        if shutil.which("gio"):
            _spawn_watched(["gio", "open", url], f"gio open {url!r}", log_fn,
                           on_fail=try_xdg)
        else:
            try_xdg()

    def try_xdg() -> None:
        if shutil.which("xdg-open"):
            _spawn_watched(["xdg-open", url], f"xdg-open {url!r}", log_fn)
        else:
            msg = f"open_url: no working launcher for {url!r}"
            app_log(msg)
            if log_fn:
                log_fn(msg)

    if shutil.which("flatpak-spawn"):
        _spawn_watched(
            ["flatpak-spawn", "--host", "xdg-open", url],
            f"flatpak-spawn xdg-open {url!r}",
            log_fn,
            on_fail=try_gio,
        )
    else:
        try_gio()
