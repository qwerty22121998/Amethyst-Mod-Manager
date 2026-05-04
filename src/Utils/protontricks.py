"""
Utils/protontricks.py
Helpers for running protontricks commands (native or flatpak),
and winetricks via the bundled copy in the manager's tools folder.
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

from Utils.app_log import safe_log as _safe_log

_WINETRICKS_URL = "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks"
_CABEXTRACT_URL = "https://archlinux.org/packages/extra/x86_64/cabextract/download/"


def _get_tools_dir() -> Path:
    from Utils.config_paths import get_config_dir
    d = get_config_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bundled_winetricks() -> Path:
    return _get_tools_dir() / "winetricks"


def _bundled_cabextract() -> Path:
    return _get_tools_dir() / "cabextract"


def winetricks_installed() -> bool:
    """Return True if winetricks is present in the manager's tools folder."""
    return _bundled_winetricks().is_file()


def cabextract_installed() -> bool:
    """Return True if cabextract is available (system PATH or bundled)."""
    return shutil.which("cabextract") is not None or _bundled_cabextract().is_file()


def install_cabextract(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download a portable cabextract binary into the manager's tools folder."""
    _log = _safe_log(log_fn)
    dest = _bundled_cabextract()
    _log("Downloading cabextract …")
    try:
        import zstandard
    except ImportError as exc:
        _log(f"cabextract install needs the 'zstandard' Python module: {exc}")
        return False
    try:
        req = urllib.request.Request(
            _CABEXTRACT_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            pkg_bytes = resp.read()
        dctx = zstandard.ZstdDecompressor()
        raw = dctx.stream_reader(io.BytesIO(pkg_bytes))
        with tarfile.open(fileobj=raw, mode="r|") as tf:
            for member in tf:
                if member.name == "usr/bin/cabextract" and member.isfile():
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    dest.write_bytes(extracted.read())
                    break
            else:
                _log("cabextract binary not found inside the downloaded package.")
                return False
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        _log(f"cabextract installed to {dest}.")
        return True
    except Exception as exc:
        _log(f"cabextract download failed: {exc}")
        return False


def install_winetricks(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download winetricks into the manager's tools folder.

    Returns True on success, False on failure.
    """
    _log = _safe_log(log_fn)
    dest = _bundled_winetricks()
    _log("Downloading winetricks …")
    try:
        req = urllib.request.Request(
            _WINETRICKS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        dest.write_bytes(data)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        _log(f"winetricks installed to {dest}.")
        return True
    except Exception as exc:
        _log(f"winetricks download failed: {exc}")
        return False


def _get_proton_bin() -> str | None:
    """Return the bin/ path of the newest available Proton installation, or None."""
    proton_root = Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common"
    if not proton_root.is_dir():
        return None
    candidates = sorted(
        [p / "files" / "bin" for p in proton_root.iterdir()
         if p.name.startswith("Proton") and (p / "files" / "bin" / "wine").is_file()],
        key=lambda p: str(p),
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def _get_protontricks_cmd(steam_id: str) -> list[str] | None:
    """Return the protontricks command prefix for *steam_id*, or None if not found."""
    if shutil.which("protontricks") is not None:
        return ["protontricks", steam_id]
    if shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", "com.github.Matoking.protontricks"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return ["flatpak", "run", "com.github.Matoking.protontricks", steam_id]
    return None


def _install_via_winetricks(
    prefix_path: Path,
    component: str,
    log_fn: Callable[[str], None],
) -> bool:
    """Install *component* directly via the bundled winetricks using WINEPREFIX."""
    if not _bundled_winetricks().is_file():
        log_fn("winetricks not found — downloading it now …")
        if not install_winetricks(log_fn=log_fn):
            return False

    if not cabextract_installed():
        log_fn("cabextract not found — downloading a portable copy now …")
        if not install_cabextract(log_fn=log_fn):
            return False

    winetricks = str(_bundled_winetricks())

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix_path)

    path_prefix = str(_get_tools_dir())
    proton_bin = _get_proton_bin()
    if proton_bin:
        path_prefix = proton_bin + os.pathsep + path_prefix
    env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")

    log_fn(f"Installing {component} via winetricks (this may take a minute) …")
    try:
        result = subprocess.run(
            [winetricks, component],
            capture_output=True, text=True, timeout=300, env=env,
        )
        if result.returncode == 0:
            log_fn(f"{component} installed successfully.")
            return True
        else:
            log_fn(f"{component} install failed: {result.stderr or result.stdout or 'unknown error'}")
            return False
    except subprocess.TimeoutExpired:
        log_fn(f"{component} install timed out after 5 minutes.")
        return False
    except Exception as exc:
        log_fn(f"{component} error: {exc}")
        return False


def install_d3dcompiler_47(
    steam_id: str,
    log_fn: Callable[[str], None] | None = None,
    prefix_path: "Path | None" = None,
) -> bool:
    """Install d3dcompiler_47 into the game's Proton prefix.

    Prefers winetricks directly against *prefix_path* when available (avoids
    protontricks needing to resolve the Steam library from the app ID).
    Falls back to protontricks via *steam_id*.

    Returns True on success, False on failure.
    """
    _log = _safe_log(log_fn)

    if prefix_path and Path(prefix_path).is_dir():
        return _install_via_winetricks(Path(prefix_path), "d3dcompiler_47", _log)

    if steam_id:
        cmd = _get_protontricks_cmd(steam_id)
        if cmd is None:
            _log("d3dcompiler_47: protontricks is not installed. Install it to use this feature.")
            return False
        cmd = cmd + ["d3dcompiler_47"]
        _log("Installing d3dcompiler_47 into game prefix (this may take a minute) …")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                _log("d3dcompiler_47 installed successfully.")
                return True
            else:
                _log(f"d3dcompiler_47 install failed: {result.stderr or result.stdout or 'unknown error'}")
                return False
        except subprocess.TimeoutExpired:
            _log("d3dcompiler_47 install timed out after 5 minutes.")
            return False
        except Exception as exc:
            _log(f"d3dcompiler_47 error: {exc}")
            return False

    _log("d3dcompiler_47: no prefix path or Steam ID available — cannot install.")
    return False


def protontricks_available() -> bool:
    """Return True if protontricks (native or flatpak) is available on this system."""
    if shutil.which("protontricks") is not None:
        return True
    if shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", "com.github.Matoking.protontricks"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return True
    return False
