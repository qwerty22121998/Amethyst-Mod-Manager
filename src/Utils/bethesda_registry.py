"""Register Bethesda game install paths in an isolated Proton prefix.

Bethesda tools (xEdit, LOOT, Synthesis, Wrye Bash, etc.) locate the game
by reading ``HKLM\\Software\\Wow6432Node\\Bethesda Softworks\\<Game>``.
A fresh Proton prefix has no such key, so tools launched in a custom
per-exe prefix can't find the game until we write it ourselves.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable


def _posix_to_wine_path(p: Path) -> str:
    s = str(p).replace("/", "\\")
    if not s.endswith("\\"):
        s += "\\"
    return "Z:" + s


def _marker_path(prefix_dir: Path, registry_game_name: str) -> Path:
    safe = registry_game_name.replace(" ", "_").replace("\\", "_").replace("/", "_")
    return prefix_dir / ".bethesda_registry" / f"{safe}.done"


def register_bethesda_game_path(
    prefix_dir: Path,
    proton_script: Path,
    env: dict[str, str],
    game_path: Path,
    registry_game_name: str,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Write the game's install path to the Bethesda Softworks registry key.

    *prefix_dir* is the STEAM_COMPAT_DATA_PATH directory (the parent of pfx/).
    *proton_script* is the Proton entrypoint (run via ``python3 <script> run``).
    *env* must already contain STEAM_COMPAT_DATA_PATH / STEAM_COMPAT_CLIENT_INSTALL_PATH.

    Idempotent — a marker file under the prefix skips the write on subsequent
    launches. Returns True on success or if already done.
    """
    def _log(msg: str) -> None:
        if log_fn is not None:
            try:
                log_fn(msg)
            except Exception:
                pass

    marker = _marker_path(prefix_dir, registry_game_name)
    if marker.is_file():
        return True

    if not game_path or not Path(game_path).is_dir():
        _log(f"Bethesda registry: game path not available, skipping ({registry_game_name}).")
        return False

    wine_value = _posix_to_wine_path(Path(game_path))
    key = (
        r"HKLM\Software\Wow6432Node\Bethesda Softworks"
        + "\\" + registry_game_name
    )
    cmd = [
        "python3", str(proton_script), "run",
        "reg", "add", key,
        "/v", "Installed Path",
        "/t", "REG_SZ",
        "/d", wine_value,
        "/f",
    ]
    _log(f"Bethesda registry: registering {registry_game_name} → {wine_value}")
    try:
        result = subprocess.run(
            cmd, env=env,
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        _log(f"Bethesda registry: reg add failed: {exc}")
        return False
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()[:200]
        _log(f"Bethesda registry: reg add exited {result.returncode}: {stderr}")
        return False

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok\n")
    except OSError:
        pass
    return True


def maybe_register_for_game(
    prefix_dir: Path,
    proton_script: Path,
    env: dict[str, str],
    game,
    log_fn: Callable[[str], None] | None = None,
) -> bool:
    """Register the game's install path if *game* is a Bethesda title.

    No-op (returns True) for games that don't expose ``synthesis_registry_name``.
    """
    registry_name = getattr(game, "synthesis_registry_name", None)
    if not registry_name:
        return True
    game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
    if game_path is None:
        return False
    return register_bethesda_game_path(
        prefix_dir=prefix_dir,
        proton_script=proton_script,
        env=env,
        game_path=Path(game_path),
        registry_game_name=registry_name,
        log_fn=log_fn,
    )
