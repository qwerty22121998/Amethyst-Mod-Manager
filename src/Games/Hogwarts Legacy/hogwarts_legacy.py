"""
hogwarts_legacy.py
Game handler for Hogwarts Legacy (Unreal Engine 5).

Mod structure
-------------
Mods ship files destined for multiple locations inside the Phoenix/ subfolder:

  .pak / .utoc / .ucas  → Phoenix/Content/Paks/~mods/
  ue4ss/ folder         → Phoenix/Binaries/Win64/ue4ss/
  .lua files            → Phoenix/Binaries/Win64/Mods/
  .dll / .pdb files     → Phoenix/Binaries/Win64/
  .bk2 cutscenes        → Phoenix/Content/Movies/
  Binaries/ or Content/ already present → game root (path preserved as-is)
  Loose files (no rule) → game root (Phoenix/)

The game root itself lives inside the Steam install directory:
  <steam_install>/Phoenix/

There are no plugin files (.esp/.esm/.esl) — this is a pure UE5 game.
"""

from __future__ import annotations

from pathlib import Path

from Games.ue5_game import UE5Game, UE5Rule
from Utils.config_paths import get_profiles_dir

_PROFILES_DIR = get_profiles_dir()

# Game root subfolder inside the Steam install directory
_GAME_SUBDIR = "Phoenix"


class HogwartsLegacy(UE5Game):

    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Hogwarts Legacy"

    @property
    def game_id(self) -> str:
        return "hogwarts_legacy"

    @property
    def exe_name(self) -> str:
        return "HogwartsLegacy.exe"

    @property
    def steam_id(self) -> str:
        return "990080"

    @property
    def nexus_game_domain(self) -> str:
        return "hogwartslegacy"
    
    @property
    def conflict_ignore_filenames(self) -> set[str]:
        return {"*.txt","*.html","*.md","*.jpeg","*.png","*.jpg","*.rar"}

    @property
    def wine_dll_overrides(self) -> dict[str, str]:
        return {"version": "native,builtin"}

    # No plugin extensions — HL has no .esp/.esm/.esl files

    # -----------------------------------------------------------------------
    # UE5 routing rules
    # -----------------------------------------------------------------------
    # Rules are evaluated in order; first match wins.
    # ``folder`` matches on the first path segment of the staged relative path.
    # ``extensions`` matches on file extension.
    # ``strip`` lists prefixes to remove so files don't get double-nested.

    @property
    def _ue5_post_passthrough_rules(self) -> list[UE5Rule]:
        return [
            # Lua UE4SS scripts and companion files (config.ini, data .json,
            # enabled.txt) → Binaries/Win64/Mods/  (Hogwarts uses the legacy
            # Binaries/Win64/Mods location rather than ue4ss/Mods)
            UE5Rule(
                dest="Binaries/Win64/Mods",
                extensions=[".lua", ".ini", ".json"],
                filenames=["enabled.txt"],
                strip=[
                    "Binaries/Win64/Mods",
                    "Binaries/Win64/ue4ss/Mods",
                    "Binaries/Win64/ue4ss",
                    "ue4ss/Mods",
                    "UE4SS/Mods",
                    "UE4SS",
                    "ue4ss",
                    "Mods",
                ],
                flatten=True,
            ),
            # Loose UE4SS proxy/runtime files (dwmapi.dll, UE4SS.dll, etc.) → Binaries/Win64/
            UE5Rule(
                dest="Binaries/Win64",
                extensions=[".dll", ".pdb"],
            ),
            # Bink video replacers → Content/Movies/
            UE5Rule(
                dest="Content/Movies",
                extensions=[".bk2"],
                strip=["Content/Movies"],
                flatten=True,
            ),
        ]

    # -----------------------------------------------------------------------
    # Mod install hints
    # -----------------------------------------------------------------------

    @property
    def mod_folder_strip_prefixes(self) -> set[str]:
        # Some mod authors wrap their entire mod in a top-level folder that
        # mirrors the game's install root.  Strip it so routing rules see the
        # correct first segment.
        return {"hogwartslegacy", "phoenix"}

    # -----------------------------------------------------------------------
    # Paths
    # -----------------------------------------------------------------------

    def get_game_path(self) -> Path | None:
        """The actual game root is the Phoenix/ subfolder inside the Steam
        install directory.  Looked up case-insensitively so it works on both
        Windows (via Proton) and Linux test setups."""
        if self._game_path is None:
            return None
        # Exact match first
        sub = self._game_path / _GAME_SUBDIR
        if sub.is_dir():
            return sub
        # Case-insensitive scan
        needle = _GAME_SUBDIR.lower()
        try:
            for child in self._game_path.iterdir():
                if child.is_dir() and child.name.lower() == needle:
                    return child
        except OSError:
            pass
        # Fallback: user pointed directly at the subfolder
        return self._game_path

    def get_mod_staging_path(self) -> Path:
        if self._staging_path is not None:
            return self._staging_path / "mods"
        return _PROFILES_DIR / self.name / "mods"
