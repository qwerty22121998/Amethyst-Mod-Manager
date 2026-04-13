"""
plugin_loader.py
Discovers and loads external wizard plugin scripts from the Plugins directory.

Plugin files are plain Python scripts placed in ~/.config/AmethystModManager/Plugins/.
Each must define a module-level ``PLUGIN_INFO`` dict and a dialog class that follows
the standard wizard dialog signature::

    PLUGIN_INFO = {
        "id":           "my_tool",
        "label":        "My Tool",
        "description":  "One-line description.",
        "game_ids":     ["skyrim_se"],      # list of supported game_ids
        "all_games":    False,              # True = show for every game
        "dialog_class": "MyToolDialog",     # class name in this file
    }

    class MyToolDialog(ctk.CTkFrame):
        def __init__(self, parent, game, log_fn=None, *, on_close=None, **extra):
            ...

Bad or incomplete plugin files are silently skipped so one broken plugin
doesn't affect the rest of the application.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from Games.base_game import BaseGame, WizardTool
from Utils.config_paths import get_plugins_dir

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_plugins_cache: list[dict] = []
_plugins_dir_mtime: float = 0.0

_REQUIRED_KEYS = {"id", "label", "dialog_class"}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_plugins() -> list[dict]:
    """Scan the Plugins directory and return validated plugin descriptors.

    Each descriptor is the plugin's ``PLUGIN_INFO`` dict augmented with:
      - ``_resolved_class``: the actual dialog class object
      - ``_source_file``:    path to the ``.py`` file

    Results are cached and only re-scanned when the directory's mtime changes.
    """
    global _plugins_cache, _plugins_dir_mtime

    plugins_dir = get_plugins_dir()

    try:
        current_mtime = plugins_dir.stat().st_mtime
    except OSError:
        return _plugins_cache

    if current_mtime == _plugins_dir_mtime and _plugins_cache:
        return _plugins_cache

    plugins: list[dict] = []
    seen_ids: set[str] = set()

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            plugin = _load_plugin_file(py_file)
        except Exception as exc:
            _warn(f"Plugin '{py_file.name}': skipped — {exc}")
            continue

        if plugin is None:
            continue

        pid = plugin["id"]
        if pid in seen_ids:
            _warn(f"Plugin '{py_file.name}': duplicate id '{pid}', skipped.")
            continue

        seen_ids.add(pid)
        plugins.append(plugin)

    _plugins_cache = plugins
    _plugins_dir_mtime = current_mtime
    return plugins


def _load_plugin_file(py_file: Path) -> dict | None:
    """Load a single plugin file and return a validated descriptor, or *None*."""
    module_name = f"_amm_plugins.{py_file.stem}"

    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    info = getattr(module, "PLUGIN_INFO", None)
    if not isinstance(info, dict):
        _warn(f"Plugin '{py_file.name}': missing or invalid PLUGIN_INFO dict.")
        return None

    missing = _REQUIRED_KEYS - info.keys()
    if missing:
        _warn(f"Plugin '{py_file.name}': PLUGIN_INFO missing keys: {missing}")
        return None

    class_name = info["dialog_class"]
    cls = getattr(module, class_name, None)
    if cls is None or not isinstance(cls, type):
        _warn(f"Plugin '{py_file.name}': dialog_class '{class_name}' not found or not a class.")
        return None

    descriptor = dict(info)
    descriptor["_resolved_class"] = cls
    descriptor["_source_file"] = py_file
    descriptor.setdefault("description", "")
    descriptor.setdefault("game_ids", [])
    descriptor.setdefault("all_games", False)
    return descriptor


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_plugin_tools_for_game(game_id: str) -> list[WizardTool]:
    """Return :class:`WizardTool` entries from loaded plugins that match *game_id*."""
    tools: list[WizardTool] = []
    for plugin in discover_plugins():
        if plugin.get("all_games") or game_id in plugin.get("game_ids", []):
            tools.append(WizardTool(
                id=plugin["id"],
                label=plugin["label"],
                description=plugin.get("description", ""),
                dialog_class_path="",
                extra={"_dialog_class": plugin["_resolved_class"]},
            ))
    return tools


def get_all_wizard_tools(game: BaseGame) -> list[WizardTool]:
    """Return built-in wizard tools merged with external plugin tools for *game*."""
    return list(game.wizard_tools) + get_plugin_tools_for_game(game.game_id)


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _warn(msg: str) -> None:
    """Log a plugin warning via the app log if available, otherwise print."""
    try:
        from Utils.app_log import app_log
        app_log(msg)
    except Exception:
        print(f"[plugin_loader] {msg}")
