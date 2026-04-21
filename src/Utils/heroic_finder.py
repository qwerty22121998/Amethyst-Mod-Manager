"""
heroic_finder.py
Utilities for locating game installations managed by Heroic Games Launcher.

Heroic supports Epic Games (via Legendary) and GOG (via heroic-gogdl).
It can be installed as a Flatpak (most common on Steam Deck) or natively.

No UI, no game-specific knowledge.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_HOME = Path.home()
_XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", _HOME / ".config"))

# ---------------------------------------------------------------------------
# Heroic config root candidates
# GamesConfig/<Appname>.json lives under each root; path varies by install type.
# ---------------------------------------------------------------------------
def _heroic_config_candidates() -> list[Path]:
    """All possible Heroic config roots, ordered by likelihood."""
    candidates: list[Path] = []

    # User-configured path takes highest priority
    try:
        from Utils.ui_config import load_heroic_config_path
        custom = load_heroic_config_path()
        if custom:
            candidates.append(Path(custom))
    except Exception:
        pass

    # Built-in fallbacks
    candidates += [
        # Flatpak (most common on Steam Deck)
        _HOME / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic",
        # Native / AppImage — respects XDG_CONFIG_HOME
        _XDG_CONFIG / "heroic",
        _HOME / ".config" / "heroic",  # Fallback if XDG_CONFIG was overridden
    ]
    return candidates


def _find_heroic_config_roots() -> list[Path]:
    """Return all Heroic config directories that exist on disk."""
    seen: set[Path] = set()
    out: list[Path] = []
    for p in _heroic_config_candidates():
        if p not in seen and p.is_dir():
            seen.add(p)
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Epic Games (Legendary backend)
# ---------------------------------------------------------------------------

def _load_epic_installed(heroic_root: Path) -> dict:
    """
    Parse legendaryConfig/legendary/installed.json from a Heroic config root.
    Returns a dict keyed by appName, each value containing at least:
      install_path, title
    Returns an empty dict on any error.
    """
    installed_json = heroic_root / "legendaryConfig" / "legendary" / "installed.json"
    if not installed_json.is_file():
        return {}
    try:
        data = json.loads(installed_json.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _find_epic_game(heroic_root: Path, app_names: list[str]) -> Path | None:
    """
    Search Epic installed.json for any of the given appNames.
    Returns the install_path as a Path if found and the directory exists.
    """
    installed = _load_epic_installed(heroic_root)
    for app_name in app_names:
        entry = installed.get(app_name)
        if not entry:
            continue
        install_path = entry.get("install_path", "")
        if install_path:
            p = Path(install_path)
            if p.is_dir():
                return p
    return None


# ---------------------------------------------------------------------------
# GOG (heroic-gogdl backend)
# ---------------------------------------------------------------------------

def _load_gog_installed(heroic_root: Path) -> list[dict]:
    """
    Parse gog_store/installed.json from a Heroic config root.
    The file has shape {"installed": [ {appName, install_path, executable, ...}, ... ]}.
    Returns the list of entries, or an empty list on any error.
    """
    installed_json = heroic_root / "gog_store" / "installed.json"
    if not installed_json.is_file():
        return []
    try:
        data = json.loads(installed_json.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            entries = data.get("installed", [])
            if isinstance(entries, list):
                return entries
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _find_gog_game(heroic_root: Path, app_names: list[str]) -> Path | None:
    """
    Search gog_store/installed.json for any of the given app_names (GOG product
    IDs as strings).  Returns the install_path as a Path if found and the
    directory exists on disk.
    """
    app_names_lower = {n.lower() for n in app_names}
    for entry in _load_gog_installed(heroic_root):
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("appName") or entry.get("app_name") or "")
        if entry_id and entry_id.lower() in app_names_lower:
            install_path = entry.get("install_path", "")
            if install_path:
                p = Path(install_path)
                if p.is_dir():
                    return p
    return None


# ---------------------------------------------------------------------------
# Wine prefix lookup
# ---------------------------------------------------------------------------

def _find_heroic_prefix_for_app(heroic_root: Path, app_name: str) -> Path | None:
    """
    Look up the Wine prefix for a game in Heroic's GamesConfig/<appName>.json.

    If the per-game config doesn't specify a winePrefix, fall back to the
    global default from config.json (defaultWinePrefix), and if that is also
    absent, try ~/Games/Heroic/Prefixes/<appName>/.

    Returns the prefix Path if it exists on disk, otherwise None.
    """
    # 1. Per-game: heroic_root/GamesConfig/<app_name>.json
    #    Path varies: Flatpak ~/.var/app/.../config/heroic, native ~/.config/heroic (or XDG_CONFIG_HOME)
    games_config = heroic_root / "GamesConfig"
    game_cfg_file = games_config / f"{app_name}.json"
    if game_cfg_file.is_file():
        try:
            cfg = json.loads(game_cfg_file.read_text(encoding="utf-8", errors="replace"))
            # Settings nested under appName key (Heroic format)
            inner = cfg.get(app_name, cfg)
            wine_prefix = (
                inner.get("winePrefix", "")
                or inner.get("wine_prefix", "")
                or cfg.get("winePrefix", "")
                or cfg.get("wine_prefix", "")
            )
            if wine_prefix:
                p = Path(wine_prefix)
                if (p / "pfx").is_dir():
                    return p / "pfx"
                if p.is_dir():
                    return p
        except (OSError, json.JSONDecodeError):
            pass

    # 2. Global default from config.json
    global_cfg_file = heroic_root / "config.json"
    if global_cfg_file.is_file():
        try:
            cfg = json.loads(global_cfg_file.read_text(encoding="utf-8", errors="replace"))
            # Heroic nests settings inside a "defaultSettings" key
            settings = cfg.get("defaultSettings", cfg)
            default_prefix_folder = settings.get("defaultWinePrefix", "")
            if default_prefix_folder:
                p = Path(default_prefix_folder) / app_name
                if (p / "pfx").is_dir():
                    return p / "pfx"
                if p.is_dir():
                    return p
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Hard-coded conventional fallback
    fallback = _HOME / "Games" / "Heroic" / "Prefixes" / app_name
    if (fallback / "pfx").is_dir():
        return fallback / "pfx"
    if fallback.is_dir():
        return fallback

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_heroic_game(app_names: list[str]) -> Path | None:
    """
    Search all Heroic config roots for a game matching any of the given
    app_names.  Checks Epic (Legendary) installs first, then GOG.

    app_names should contain the Heroic/Epic appName identifiers and/or GOG
    product IDs declared by the game handler.  Matching is case-insensitive
    for GOG titles.

    Returns the game install directory Path, or None if not found.
    """
    for heroic_root in _find_heroic_config_roots():
        result = _find_epic_game(heroic_root, app_names)
        if result:
            return result
        result = _find_gog_game(heroic_root, app_names)
        if result:
            return result
    return None


def find_heroic_launch_info(app_names: list[str]) -> "tuple[str, str] | None":
    """
    Search Heroic config for a game matching any of the given app_names.
    Returns (store, matched_app_name) where store is 'legendary' (Epic) or 'gog',
    or None if not found.

    The returned values can be used to build a heroic:// launch URL:
        heroic://launch/<store>/<app_name>
    """
    for heroic_root in _find_heroic_config_roots():
        installed = _load_epic_installed(heroic_root)
        for app_name in app_names:
            if app_name in installed:
                install_path = installed[app_name].get("install_path", "")
                if install_path and Path(install_path).is_dir():
                    return ("legendary", app_name)
        app_names_lower = {n.lower() for n in app_names}
        for entry in _load_gog_installed(heroic_root):
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("appName") or entry.get("app_name") or "")
            if entry_id and entry_id.lower() in app_names_lower:
                install_path = entry.get("install_path", "")
                if install_path and Path(install_path).is_dir():
                    return ("gog", entry_id)
    return None


def find_heroic_app_name_by_exe(exe_name: str) -> str | None:
    """
    Search Heroic's installed.json for a game whose executable matches exe_name.
    Returns the app_name string if found, otherwise None.

    exe_name should be the bare filename, e.g. 'SubnauticaZero.exe'.
    Matching is case-insensitive.
    """
    info = find_heroic_game_info_by_exe(exe_name)
    return info[2] if info else None


def find_heroic_game_info_by_exe(exe_name: str) -> "tuple[Path, Path | None, str] | None":
    """
    Full Heroic detection workflow keyed by executable name from the handler:

    1. Look in Heroic's installed.json (legendaryConfig/legendary/installed.json)
       for a game whose executable matches exe_name.
    2. Get app_name and install_path from that entry.
    3. Look in GamesConfig/<appname>.json for the winePrefix.
    4. Return (install_path, prefix_path, app_name) if all found.

    Used for games like Subnautica Below Zero where the handler provides
    SubnauticaZero.exe; we resolve appname (Foxglove), install path, and prefix.
    """
    exe_lower = exe_name.replace("\\", "/").rsplit("/", 1)[-1].lower()

    for heroic_root in _find_heroic_config_roots():
        # 1. Epic (Legendary) installed.json
        installed = _load_epic_installed(heroic_root)
        for app_name, entry in installed.items():
            if not isinstance(entry, dict):
                continue
            stored_exe = entry.get("executable", "")
            # Heroic may store a bare name or a relative/absolute path — compare only the filename
            stored_bare = stored_exe.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if stored_bare != exe_lower:
                continue
            install_path_raw = entry.get("install_path", "")
            if not install_path_raw:
                continue
            install_path = Path(install_path_raw)
            if not install_path.is_dir():
                continue
            # 2. GamesConfig/<appname>.json for prefix
            prefix_path = _find_heroic_prefix_for_app(heroic_root, app_name)
            if prefix_path:
                return (install_path, prefix_path, app_name)
            # Still return install_path + app_name if prefix lookup fails;
            # caller can retry prefix later
            return (install_path, None, app_name)

        # 3. GOG: check gog_store/installed.json for executable match.
        #    Heroic's GOG entries often have an empty "executable" field, so
        #    fall back to probing install_path for the exe filename.
        for entry in _load_gog_installed(heroic_root):
            if not isinstance(entry, dict):
                continue
            app_id = str(entry.get("appName") or entry.get("app_name") or "")
            install_path_raw = entry.get("install_path", entry.get("path", ""))
            if not install_path_raw:
                continue
            install_path = Path(install_path_raw)
            if not install_path.is_dir():
                continue

            stored_exe = entry.get("executable", "") or entry.get("exe", "")
            stored_bare = stored_exe.replace("\\", "/").rsplit("/", 1)[-1].lower()

            matched = False
            if stored_bare and stored_bare == exe_lower:
                matched = True
            elif not stored_bare:
                # Scan install_path for the exe (case-insensitive, recursive).
                try:
                    for candidate in install_path.rglob("*"):
                        if candidate.is_file() and candidate.name.lower() == exe_lower:
                            matched = True
                            break
                except OSError:
                    pass

            if not matched:
                continue

            prefix_path = _find_heroic_prefix_for_app(heroic_root, app_id)
            if prefix_path:
                return (install_path, prefix_path, app_id)
            return (install_path, None, app_id)

    return None


def find_heroic_prefix(app_names: list[str]) -> Path | None:
    """
    Search all Heroic config roots for the Wine prefix of a game matching any
    of the given app_names.

    Returns the prefix Path (the pfx-equivalent root that Heroic manages),
    or None if not found.
    """
    for heroic_root in _find_heroic_config_roots():
        for app_name in app_names:
            result = _find_heroic_prefix_for_app(heroic_root, app_name)
            if result:
                return result
    return None
