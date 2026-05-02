"""
Executable toolbar mixin for PluginPanel.

Owns the exe dropdown and Run/Configure flow:
- Scan for .exe / .bat across game folder, Applications/, filemap, custom exes.
- Persist per-exe settings (args, launch mode, Proton override, launch options,
  data-folder flag, hidden filter) under ~/.config/AmethystModManager/games/<game>/.
- Dispatch Run to native command / Steam / Heroic / Proton, with bat wrappers
  for VRAMr, BENDr, ParallaxR.

Host (PluginPanel) owns: ``self._game``, ``self._log``, ``self._safe_after``,
the dropdown widgets ``self._exe_menu`` / ``self._exe_var`` / ``self._exe_args_var``
/ ``self._run_exe_btn``, and the lists ``self._exe_paths`` / ``self._exe_labels``
/ ``self._game_exe_path``.
"""

import json
import os
import re
import shlex
import subprocess
import threading
from pathlib import Path

from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BTN_SUCCESS,
    BTN_SUCCESS_HOV,
)
from gui.dialogs import _ExeConfigDialog, _ExeFilterDialog, confirm_deploy_appdata
from Utils.config_paths import get_exe_args_path, get_game_config_dir, get_game_config_path
from Utils.profile_state import read_excluded_mod_files
from Utils.xdg import xdg_open


class PluginPanelExeLauncherMixin:
    """Executable scan, configuration, and launch dispatch for PluginPanel."""

    # Extensions detected in the executable dropdown (.exe always, .bat for wrapper support)
    _EXE_SCAN_EXTENSIONS = {".exe", ".bat"}

    # These exes only work correctly when run from the game's Data folder.
    # Only show them in the dropdown if they appear under Data/ in the filemap
    # (i.e. they have been deployed there).
    _DATA_FOLDER_ONLY_EXES = frozenset({
        "OutfitStudio x64.exe",
        "OutfitStudio.exe",
        "BodySlide x64.exe",
        "BodySlide.exe",
        "Nemesis Unlimited Behavior Engine.exe",
    })

    from Utils.exe_args_builder import EXE_FILTER_DEFAULTS as _EXE_FILTER_DEFAULTS

    _EXE_ARGS_FILE = get_exe_args_path()
    _ADD_CUSTOM_SENTINEL = "+ Add custom EXE…"
    _CUSTOM_EXES_FILE = "custom_exes.json"
    _EXE_FILTER_FILE  = "exe_filter.json"
    _LAUNCH_MODE_FILE = "exe_launch_mode.json"

    _EXE_PICKER_FILTERS = [
        ("Executables (*.exe, *.bat)", ["*.exe", "*.bat"]),
        ("All files", ["*"]),
    ]

    # ── .bat/.exe wrapper registry ──────────────────────────────────────
    # Maps lowercase .bat/.exe filenames to wrapper launcher methods.
    # When the user tries to "Run" an entry listed here, the wrapper is
    # invoked instead of launching through Proton.
    # (v15 has VRAMr.bat; v16+ uses VRAMr.exe as the main entry.)
    _BAT_WRAPPERS: dict[str, str] = {
        "vramr.bat": "_run_vramr_wrapper",
        "vramr.exe": "_run_vramr_wrapper",
        "bendr.bat": "_run_bendr_wrapper",
        "parallaxr.bat": "_run_parallaxr_wrapper",
    }

    def refresh_exe_list(self, _select_after=None):
        """Scan for .exe and .bat files in a background thread, then populate the dropdown.

        _select_after: optional callable(exes) invoked on the main thread after the list is applied.
        """
        game = self._game

        def _worker():
            exes: list[Path] = []
            game_exe_path: Path | None = None

            if game is not None:
                # 0. Add the game's own exe (exe_name resolved against game_path).
                #    Also try exe_name_alts so native Linux binaries (e.g. bin/bg3)
                #    are picked up when the Windows exe isn't installed.
                game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
                exe_name = game.exe_name if hasattr(game, "exe_name") else None
                exe_name_alts = list(getattr(game, "exe_name_alts", []) or [])
                candidates_rel = [n for n in [exe_name, *exe_name_alts] if n]
                if game_path and candidates_rel:
                    for rel in candidates_rel:
                        candidate = game_path / rel
                        if candidate.is_file():
                            game_exe_path = candidate
                            exes.append(candidate)
                            break
                    else:
                        # Fallback: search recursively for any of the bare exe names
                        # (needed for UE5 games where the exe lives in Binaries/Win64/)
                        try:
                            for rel in candidates_rel:
                                bare = Path(rel).name
                                for found in game_path.rglob(bare):
                                    if found.is_file():
                                        game_exe_path = found
                                        exes.append(found)
                                        break
                                if game_exe_path is not None:
                                    break
                        except OSError:
                            pass

                # 0b. Check for a preferred launch exe (e.g. a script extender
                #     that must be launched instead of, but cannot replace, the
                #     normal game exe).  If present on disk it becomes the
                #     game_exe_path so it sorts first and gets the Play button.
                preferred_rel = getattr(game, "preferred_launch_exe", "")
                if preferred_rel and game_path:
                    preferred_candidate = game_path / preferred_rel
                    if preferred_candidate.is_file():
                        if preferred_candidate not in exes:
                            exes.insert(0, preferred_candidate)
                        game_exe_path = preferred_candidate

                staging = (
                    game.get_effective_mod_staging_path()
                    if hasattr(game, "get_mod_staging_path") else None
                )

                # Build the full set of exe names that must run from the Data folder:
                # hardcoded set + any user-configured via the Configure dialog.
                _lm_path = self._get_launch_mode_path()
                _user_data_folder_exes: set[str] = set()
                if _lm_path is not None and _lm_path.is_file():
                    try:
                        _lm_data = json.loads(_lm_path.read_text(encoding="utf-8"))
                        for _k, _v in _lm_data.items():
                            if _k.startswith("__data_folder_") and _v:
                                _user_data_folder_exes.add(_k[len("__data_folder_"):])
                    except (OSError, ValueError):
                        pass
                _all_data_folder_exes = self._DATA_FOLDER_ONLY_EXES | _user_data_folder_exes

                # Build a set of Data-folder-only exe names that are actually present
                # under game_path/Data/ (recursively) after deployment.
                data_folder_deployed: set[str] = set()
                if game_path is not None:
                    data_dir = game_path / "Data"
                    if data_dir.is_dir():
                        for name in _all_data_folder_exes:
                            for _ in data_dir.rglob(name):
                                data_folder_deployed.add(name)
                                break  # one hit is enough

                # 1. Scan filemap for .exe/.bat files — resolve from the mods staging folder
                if staging is not None and staging.is_dir():
                    filemap_path = staging.parent / "filemap.txt"
                    if filemap_path.is_file():
                        try:
                            for line in filemap_path.read_text(encoding="utf-8").splitlines():
                                line = line.strip()
                                if not line or "\t" not in line:
                                    continue
                                rel_path, mod_name = line.split("\t", 1)
                                rel = Path(rel_path)
                                if rel.suffix.lower() not in self._EXE_SCAN_EXTENSIONS:
                                    continue
                                # Exes that require the Data folder are only shown
                                # if they have been deployed there.
                                if rel.name in _all_data_folder_exes:
                                    if rel.name not in data_folder_deployed:
                                        continue
                                mod_dir = staging / mod_name
                                candidate = mod_dir / rel_path
                                if any(
                                    part.startswith("prefix_") or part in ("prefix", "pfx")
                                    for part in candidate.parts
                                ):
                                    continue
                                if candidate.is_file():
                                    exes.append(candidate)
                        except OSError:
                            pass

                # 2. Scan Profiles/<game>/Applications/ for .exe/.bat files (recursive),
                #    excluding custom_exes.json entries (added separately below)
                if staging is not None:
                    _shared_staging = (
                        game.get_mod_staging_path()
                        if hasattr(game, "get_mod_staging_path") else staging
                    )
                    apps_dir = _shared_staging.parent / "Applications"
                    if apps_dir.is_dir():
                        for ext in self._EXE_SCAN_EXTENSIONS:
                            for entry in apps_dir.rglob(f"*{ext}"):
                                if entry.is_file() and entry.name not in _all_data_folder_exes:
                                    if not any(
                                        part.startswith("prefix_") or part in ("prefix", "pfx")
                                        for part in entry.parts
                                    ):
                                        exes.append(entry)

                # 3. Custom exes saved via "Add custom EXE" (arbitrary paths on disk)
                for p in self._load_custom_exes():
                    if p not in exes:
                        exes.append(p)

            # Sort: game exe first, then Applications/, then custom/filemap entries, alpha within each
            apps_dir_root = None
            if game and hasattr(game, "get_mod_staging_path"):
                apps_dir_root = game.get_mod_staging_path().parent / "Applications"

            custom_set = set(self._load_custom_exes())

            def _sort_key(p: Path):
                if game_exe_path is not None and p == game_exe_path:
                    return (0, p.name.lower())
                in_apps = apps_dir_root is not None and p.is_relative_to(apps_dir_root)
                if in_apps:
                    return (1, p.name.lower())
                if p in custom_set:
                    return (2, p.name.lower())
                return (3, p.name.lower())

            exes.sort(key=_sort_key)

            # Apply exe filter — built-in defaults combined with user-hidden list.
            # Custom exes always bypass the filter.
            _filtered_names = self._EXE_FILTER_DEFAULTS | {n.lower() for n in self._load_exe_filter()}
            if _filtered_names:
                exes = [
                    p for p in exes
                    if p.name.lower() not in _filtered_names or p in custom_set
                ]

            # Auto-populate exe_args.json with default prefixes for known tools
            if game is not None and exes:
                try:
                    from Utils.exe_args_builder import build_default_exe_args
                    build_default_exe_args(exes, game, log_fn=self._log)
                except Exception:
                    pass

            # Native games (e.g. OpenMW) have no .exe in the game folder.
            # If no game exe was found but the handler provides a native launch
            # command, add a synthetic Path as the Play entry.
            if game_exe_path is None and game is not None:
                _native_cmd = getattr(game, "get_launch_command", lambda: None)()
                if _native_cmd is not None:
                    _exe_display_name = (getattr(game, "exe_name", "") or _native_cmd[-1])
                    _synthetic = Path(_exe_display_name)
                    exes.insert(0, _synthetic)
                    game_exe_path = _synthetic

            self._safe_after(0, lambda: self._apply_exe_list(exes, game_exe_path, _select_after))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_exe_list(self, exes: "list[Path]", game_exe_path: "Path | None",
                        select_after=None) -> None:
        """Apply exe scan results to the UI (must be called on the main thread)."""
        self._exe_paths = exes
        self._game_exe_path = game_exe_path
        game_label = self._game.name if self._game is not None else None
        entry_labels: list[str] = []
        for p in exes:
            if game_label and game_exe_path is not None and p == game_exe_path:
                entry_labels.append(game_label)
            else:
                entry_labels.append(p.name)
        self._exe_labels = entry_labels
        labels = entry_labels + [self._ADD_CUSTOM_SENTINEL]
        if not exes:
            labels = ["(no executables)", self._ADD_CUSTOM_SENTINEL]
        self._exe_menu.configure(values=labels)
        if exes:
            self._exe_var.set(labels[0])
            self._on_exe_selected(labels[0])
        else:
            self._exe_var.set("(no executables)")
        if select_after is not None:
            select_after(exes)

    def _on_exe_selected(self, name: str):
        """Called when the user selects an exe from the dropdown. Loads saved args if present."""
        if name == self._ADD_CUSTOM_SENTINEL:
            self._add_custom_exe()
            return
        idx = self._exe_var_index()
        if idx < 0 or not self._exe_paths:
            self._exe_args_var.set("")
            self._update_run_exe_btn(None)
            return
        exe_path = self._exe_paths[idx]
        loaded_args = self._load_exe_args(exe_path.name)
        self._exe_args_var.set(self._apply_profile_output_to_args(exe_path.name, loaded_args))
        self._update_run_exe_btn(exe_path)

    def _update_run_exe_btn(self, exe_path: "Path | None") -> None:
        """Switch the Run EXE button to green ▶ Play when the game's launch exe is selected."""
        is_game_exe = (
            exe_path is not None
            and self._game_exe_path is not None
            and exe_path == self._game_exe_path
        )
        if is_game_exe:
            self._run_exe_btn.configure(
                text="▶  Play",
                fg_color=BTN_SUCCESS,
                hover_color=BTN_SUCCESS_HOV,
            )
        else:
            self._run_exe_btn.configure(
                text="▶ Run EXE",
                fg_color=ACCENT,
                hover_color=ACCENT_HOV,
            )

    def _get_launch_mode_path(self) -> "Path | None":
        """Return path to ~/.config/AmethystModManager/games/<game>/exe_launch_mode.json."""
        if self._game is None:
            return None
        return get_game_config_dir(self._game.name) / self._LAUNCH_MODE_FILE

    def _load_launch_mode(self, exe_name: str) -> str:
        """Return saved launch mode for exe_name ('auto', 'steam', 'heroic', 'none')."""
        p = self._get_launch_mode_path()
        if p is None or not p.is_file():
            return "auto"
        try:
            return json.loads(p.read_text(encoding="utf-8")).get(exe_name, "auto")
        except (OSError, ValueError):
            return "auto"

    def _save_launch_mode(self, exe_name: str, mode: str) -> None:
        p = self._get_launch_mode_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        data[exe_name] = mode
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_deploy_before_launch(self) -> bool:
        """Return whether deploy-before-launch is enabled (default True)."""
        p = self._get_launch_mode_path()
        if p is None or not p.is_file():
            return True
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("__deploy_before_launch", True)
        except (OSError, ValueError):
            return True

    def _load_proton_override(self, exe_name: str) -> "str | None":
        """Return saved Proton override name for exe_name, '' for game default, or None if never saved."""
        p = self._get_launch_mode_path()
        if p is None or not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            key = f"__proton_override_{exe_name}"
            if key not in data:
                return None
            return data[key]
        except (OSError, ValueError):
            return None

    def _save_proton_override(self, exe_name: str, proton_name: str) -> None:
        p = self._get_launch_mode_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        key = f"__proton_override_{exe_name}"
        if proton_name:
            data[key] = proton_name
        else:
            data.pop(key, None)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_data_folder_exe(self, exe_name: str) -> bool:
        """Return whether this exe is configured to run from the game's Data folder."""
        p = self._get_launch_mode_path()
        if p is None or not p.is_file():
            return False
        try:
            return bool(json.loads(p.read_text(encoding="utf-8")).get(f"__data_folder_{exe_name}", False))
        except (OSError, ValueError):
            return False

    def _save_data_folder_exe(self, exe_name: str, enabled: bool) -> None:
        p = self._get_launch_mode_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        key = f"__data_folder_{exe_name}"
        if enabled:
            data[key] = True
        else:
            data.pop(key, None)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_launch_options(self, exe_name: str) -> str:
        """Return saved launch options string for exe_name (empty string if none)."""
        p = self._get_launch_mode_path()
        if p is None or not p.is_file():
            return ""
        try:
            return json.loads(p.read_text(encoding="utf-8")).get(f"__launch_options_{exe_name}", "")
        except (OSError, ValueError):
            return ""

    def _save_launch_options(self, exe_name: str, options: str) -> None:
        p = self._get_launch_mode_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        key = f"__launch_options_{exe_name}"
        if options:
            data[key] = options
        else:
            data.pop(key, None)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _is_apps_exe(self, exe_path: "Path") -> bool:
        """Return True if exe_path lives under the game's Applications folder."""
        if self._game is None or not hasattr(self._game, "get_mod_staging_path"):
            return False
        apps_dir = self._game.get_mod_staging_path().parent / "Applications"
        try:
            exe_path.relative_to(apps_dir)
            return True
        except ValueError:
            return False

    def _save_deploy_before_launch(self, enabled: bool) -> None:
        p = self._get_launch_mode_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except (OSError, ValueError):
            data = {}
        data["__deploy_before_launch"] = enabled
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _is_game_exe(self, exe_path: "Path") -> bool:
        """Return True if exe_path is this game's own launcher exe, preferred launch exe,
        or a framework executable (e.g. script extender) that should launch via Steam."""
        if self._game is None:
            return False
        game_exe_name = getattr(self._game, "exe_name", None)
        if not game_exe_name:
            return False
        candidate_name = exe_path.name.lower()
        if candidate_name == Path(game_exe_name).name.lower():
            return True
        # Alternate launch exes (e.g. native Linux binary bin/bg3 vs bg3.exe)
        for alt in getattr(self._game, "exe_name_alts", []) or []:
            if candidate_name == Path(alt).name.lower():
                return True
        preferred_rel = getattr(self._game, "preferred_launch_exe", "")
        if preferred_rel and candidate_name == Path(preferred_rel).name.lower():
            return True
        # Framework exes (e.g. skse64_loader.exe) should also launch via Steam/Heroic
        # rather than being run directly via Proton, since the game must initialise
        # properly through the platform's runtime for the framework to work.
        frameworks: dict = getattr(self._game, "frameworks", None) or {}
        for fw_exe in frameworks.values():
            if exe_path.name.lower() == Path(fw_exe).name.lower():
                return True
        return False

    def _open_applications_folder(self) -> None:
        """Open the Profiles/<game>/Applications folder in the file manager."""
        if self._game is None:
            self._log("Open Applications folder: no game selected.")
            return
        if not hasattr(self._game, "get_mod_staging_path"):
            self._log("Open Applications folder: could not determine staging path.")
            return
        apps_dir = self._game.get_mod_staging_path().parent / "Applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        try:
            xdg_open(apps_dir)
        except Exception as e:
            self._log(f"Could not open Applications folder: {e}")

    def _get_exe_filter_path(self) -> "Path | None":
        """Return path to ~/.config/AmethystModManager/games/<game>/exe_filter.json."""
        if self._game is None:
            return None
        return get_game_config_dir(self._game.name) / self._EXE_FILTER_FILE

    def _load_exe_filter(self) -> "list[str]":
        """Return list of exe names (lowercase) that should be hidden from the dropdown."""
        p = self._get_exe_filter_path()
        if p is None or not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [s.lower() for s in data if isinstance(s, str)]
        except (OSError, ValueError):
            return []

    def _save_exe_filter(self, names: "list[str]") -> None:
        p = self._get_exe_filter_path()
        if p is None:
            return
        p.write_text(json.dumps([n.lower() for n in names], indent=2), encoding="utf-8")

    def _get_custom_exes_path(self) -> "Path | None":
        """Return path to <game>/Applications/custom_exes.json, or None if no game."""
        if self._game is None or not hasattr(self._game, "get_mod_staging_path"):
            return None
        return self._game.get_mod_staging_path().parent / "Applications" / self._CUSTOM_EXES_FILE

    def _load_custom_exes(self) -> "list[Path]":
        """Return list of custom exe Paths saved in custom_exes.json."""
        p = self._get_custom_exes_path()
        if p is None or not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return [Path(s) for s in data if Path(s).is_file()]
        except (OSError, ValueError):
            return []

    def _save_custom_exes(self, paths: "list[Path]") -> None:
        p = self._get_custom_exes_path()
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([str(x) for x in paths], indent=2), encoding="utf-8")

    def _on_exe_filter(self) -> None:
        """Open the EXE filter list panel/dialog."""
        app = self.winfo_toplevel()
        show_fn = getattr(app, "show_exe_filter_panel", None)
        if show_fn:
            show_fn(
                load_fn=self._load_exe_filter,
                save_fn=self._save_exe_filter,
                refresh_fn=self.refresh_exe_list,
            )
        else:
            _ExeFilterDialog(
                self.winfo_toplevel(),
                load_fn=self._load_exe_filter,
                save_fn=self._save_exe_filter,
                refresh_fn=self.refresh_exe_list,
            )

    def _add_custom_exe(self) -> None:
        """Open native file browser (XDG portal / zenity), save chosen exe, refresh list."""
        from Utils.portal_filechooser import _run_file_picker_worker

        def _on_picked(chosen: "Path | None") -> None:
            if chosen is None:
                # User cancelled — restore previous selection
                if self._exe_paths:
                    first_label = self._exe_labels[0] if self._exe_labels else self._exe_paths[0].name
                    self._safe_after(0, lambda: self._exe_var.set(first_label))
                else:
                    self._safe_after(0, lambda: self._exe_var.set("(no executables)"))
                return
            existing = self._load_custom_exes()
            if chosen not in existing:
                existing.append(chosen)
                self._save_custom_exes(existing)

            def _after_refresh(exes):
                for p in exes:
                    if p == chosen:
                        self._exe_var.set(p.name)
                        self._on_exe_selected(p.name)
                        break

            self._safe_after(0, lambda: self.refresh_exe_list(_select_after=_after_refresh))

        threading.Thread(
            target=_run_file_picker_worker,
            args=("Select executable", self._EXE_PICKER_FILTERS, _on_picked),
            daemon=True,
        ).start()

    def _load_exe_args(self, exe_name: str) -> str:
        """Load saved args for an exe, checking the profile-local file first."""
        from Utils.config_paths import get_profile_exe_args_path
        # Check profile-local exe_args.json for profiles with specific mods
        try:
            active_dir = getattr(self._game, "_active_profile_dir", None) if self._game else None
            if active_dir is not None:
                from gui.game_helpers import profile_uses_specific_mods
                if profile_uses_specific_mods(active_dir):
                    profile_file = get_profile_exe_args_path(active_dir)
                    if profile_file.is_file():
                        data = json.loads(profile_file.read_text(encoding="utf-8"))
                        if exe_name in data:
                            return data[exe_name]
        except Exception:
            pass
        # Fall back to global exe_args.json
        try:
            data = json.loads(self._EXE_ARGS_FILE.read_text(encoding="utf-8"))
            return data.get(exe_name, "")
        except (OSError, ValueError):
            return ""

    def _apply_profile_output_to_args(self, exe_name: str, args_str: str) -> str:
        """If the active profile uses profile-specific mods, rewrite the output
        path in *args_str* so it points at the profile's effective overwrite
        folder. Returns the string unchanged for standard profiles."""
        game = self._game
        if game is None:
            return args_str
        active_dir = getattr(game, "_active_profile_dir", None)
        if active_dir is None:
            return args_str
        try:
            from gui.game_helpers import profile_uses_specific_mods  # type: ignore
            if not profile_uses_specific_mods(active_dir):
                return args_str
        except Exception:
            return args_str
        from Utils.exe_args_builder import EXE_PROFILES, _to_wine_path  # type: ignore
        profile_def = EXE_PROFILES.get(exe_name)
        if profile_def is None or not profile_def.output_flag:
            return args_str
        new_path = _to_wine_path(game.get_effective_overwrite_path())
        flag_re = re.escape(profile_def.output_flag)
        # Replace flagged argument (quoted path first, then unquoted token)
        result = re.sub(
            rf'({flag_re}\s*)"[^"]*"',
            lambda m: f'{m.group(1)}"{new_path}"',
            args_str,
        )
        if result == args_str:
            result = re.sub(
                rf'({flag_re}\s*)(\S+)',
                lambda m: f'{m.group(1)}"{new_path}"',
                args_str,
            )
        return result

    def _on_configure_exe(self):
        """Open the Configure dialog for the selected exe."""
        idx = self._exe_var_index()
        if idx < 0 or not self._exe_paths:
            self._log("Configure: no executable selected.")
            return
        exe_path = self._exe_paths[idx]
        game = self._game
        if game is None:
            self._log("Configure: no game selected.")
            return
        saved_args = self._load_exe_args(exe_path.name)
        custom_exes = self._load_custom_exes()
        is_game_exe = self._is_game_exe(exe_path)
        saved_launch_mode = self._load_launch_mode(exe_path.name) if is_game_exe else None
        deploy_before_launch = self._load_deploy_before_launch() if is_game_exe else None
        saved_proton_override = self._load_proton_override(exe_path.name) if not is_game_exe else None
        saved_launch_options = self._load_launch_options(exe_path.name)
        # Determine current hidden state from user filter (builtin filter names
        # are always hidden and can't be toggled, so we only look at the user list).
        user_filter = {n.lower() for n in self._load_exe_filter()}
        is_hidden = exe_path.name.lower() in user_filter
        # Data-folder setting: hardcoded exes are always on; user-configured ones loaded from disk.
        # Applications-folder exes don't need this (they already run from the right location).
        _is_apps = self._is_apps_exe(exe_path)
        is_data_folder_exe = (
            exe_path.name in self._DATA_FOLDER_ONLY_EXES
            or self._load_data_folder_exe(exe_path.name)
        )

        def _handle_result(panel_or_dialog):
            r = panel_or_dialog
            if r.result is not None:
                self._exe_args_var.set(r.result)
            if r.launch_mode is not None:
                self._save_launch_mode(exe_path.name, r.launch_mode)
            if r.deploy_before_launch is not None:
                self._save_deploy_before_launch(r.deploy_before_launch)
            if r.proton_override is not None:
                self._save_proton_override(exe_path.name, r.proton_override)
            if r.launch_options is not None:
                self._save_launch_options(exe_path.name, r.launch_options)
            if r.removed:
                remaining = [p for p in custom_exes if p != exe_path]
                self._save_custom_exes(remaining)
                self.refresh_exe_list()
            if r.hide is not None:
                name = exe_path.name.lower()
                current = list(self._load_exe_filter())
                if r.hide and name not in current:
                    current.append(name)
                    self._save_exe_filter(current)
                    self.refresh_exe_list()
                elif not r.hide and name in current:
                    current.remove(name)
                    self._save_exe_filter(current)
                    self.refresh_exe_list()
            if r.data_folder_exe is not None:
                self._save_data_folder_exe(exe_path.name, r.data_folder_exe)
                self.refresh_exe_list()

        app = self.winfo_toplevel()
        show_fn = getattr(app, "show_exe_config_panel", None)
        if show_fn:
            show_fn(
                exe_path=exe_path, game=game, saved_args=saved_args,
                custom_exes=custom_exes, launch_mode=saved_launch_mode,
                deploy_before_launch=deploy_before_launch, is_hidden=is_hidden,
                proton_override=saved_proton_override,
                is_data_folder_exe=is_data_folder_exe, is_apps_exe=_is_apps,
                saved_launch_options=saved_launch_options,
                log_fn=self._log,
                on_done=_handle_result,
            )
        else:
            dialog = _ExeConfigDialog(
                self.winfo_toplevel(),
                exe_path=exe_path,
                game=game,
                saved_args=saved_args,
                custom_exes=custom_exes,
                launch_mode=saved_launch_mode,
                deploy_before_launch=deploy_before_launch,
                is_hidden=is_hidden,
                proton_override=saved_proton_override,
                is_data_folder_exe=is_data_folder_exe,
                is_apps_exe=_is_apps,
                saved_launch_options=saved_launch_options,
                log_fn=self._log,
            )
            self.winfo_toplevel().wait_window(dialog)
            _handle_result(dialog)

    def _exe_var_index(self) -> int:
        """Return the index of the currently selected exe in _exe_paths."""
        name = self._exe_var.get()
        for i, label in enumerate(self._exe_labels):
            if label == name:
                return i
        for i, p in enumerate(self._exe_paths):
            if p.name == name:
                return i
        return -1

    def _on_run_exe(self):
        """Launch the selected exe/bat in the game's Proton prefix."""
        idx = self._exe_var_index()
        if idx < 0 or not self._exe_paths:
            self._log("Run EXE: no executable selected.")
            return

        exe_path = self._exe_paths[idx]
        game = self._game
        if game is None:
            self._log("Run EXE: no game selected.")
            return

        # Native games (e.g. OpenMW) use a system command instead of a .exe path.
        # Handle this before the is_file() guard so the synthetic Path entry works.
        _native_cmd = getattr(game, "get_launch_command", lambda: None)()
        if _native_cmd is not None and self._game_exe_path is not None and exe_path == self._game_exe_path:
            if self._load_deploy_before_launch():
                self._log("Run EXE: deploying mods before launch…")
                self._run_deploy_then_launch(exe_path, game)
                return
            self._launch_exe(exe_path, game)
            return

        if not exe_path.is_file():
            self._log(f"Run EXE: file not found: {exe_path}")
            return

        # Check for a native wrapper before falling through to Proton
        wrapper_method = self._BAT_WRAPPERS.get(exe_path.name.lower())
        if wrapper_method is not None:
            getattr(self, wrapper_method)(exe_path)
            return

        is_game_exe = self._is_game_exe(exe_path)

        if is_game_exe and self._load_deploy_before_launch():
            # Run deploy in a background thread, then launch the game when done.
            self._log("Run EXE: deploying mods before launch…")
            self._run_deploy_then_launch(exe_path, game)
            return

        self._launch_exe(exe_path, game)

    def _run_deploy_then_launch(self, exe_path: "Path", game):
        """Deploy mods in a background thread, then call _launch_exe on the main thread."""
        from Utils.filemap import build_filemap
        from Utils.deploy import LinkMode, deploy_root_folder, restore_root_folder, load_per_mod_strip_prefixes

        if not confirm_deploy_appdata(self.winfo_toplevel(), game):
            self._log("Run EXE: deploy cancelled — AppData folder missing.")
            return

        try:
            topbar = self.winfo_toplevel()._topbar
            profile = topbar._profile_var.get()
        except AttributeError:
            profile = "default"

        game_root = game.get_game_path()

        def _worker():
            def _tlog(msg):
                self._safe_after(0, lambda m=msg: self._log(m))

            try:
                # Activate the last-deployed profile for restore so rescued
                # runtime files land in *that* profile's overwrite/ — not
                # the shared default. Critical for profile_specific_mods.
                profile_root = game.get_profile_root()
                last_deployed = game.get_last_deployed_profile()
                if last_deployed:
                    game.set_active_profile_dir(
                        profile_root / "profiles" / last_deployed
                    )

                if getattr(game, "restore_before_deploy", True) and hasattr(game, "restore"):
                    try:
                        game.restore(log_fn=_tlog)
                    except RuntimeError:
                        pass
                # Restore Root_Folder using the last-deployed profile's Root_Folder.
                restore_rf_dir = game.get_effective_root_folder_path()
                if restore_rf_dir.is_dir() and game_root:
                    restore_root_folder(restore_rf_dir, game_root, log_fn=_tlog)

                # Switch to the target profile before deploy.
                game.set_active_profile_dir(
                    profile_root / "profiles" / profile
                )

                staging = game.get_effective_mod_staging_path()
                modlist_path = profile_root / "profiles" / profile / "modlist.txt"
                filemap_out = game.get_effective_filemap_path()
                if modlist_path.is_file():
                    try:
                        _exc_raw = read_excluded_mod_files(modlist_path.parent, None)
                        _exc = {k: set(v) for k, v in _exc_raw.items()} if _exc_raw else None
                        build_filemap(
                            modlist_path, staging, filemap_out,
                            strip_prefixes=game.mod_folder_strip_prefixes or None,
                            per_mod_strip_prefixes=load_per_mod_strip_prefixes(modlist_path.parent),
                            allowed_extensions=game.mod_install_extensions or None,
                            root_deploy_folders=game.mod_root_deploy_folders or None,
                            excluded_mod_files=_exc,
                            conflict_ignore_filenames=getattr(game, "conflict_ignore_filenames", None) or None,
                            exclude_dirs=getattr(game, "filemap_exclude_dirs", None) or None,
                            filemap_casing=getattr(game, "filemap_casing", "upper"),
                        )
                    except Exception as fm_err:
                        _tlog(f"Run EXE: filemap rebuild warning: {fm_err}")

                deploy_mode = game.get_deploy_mode() if hasattr(game, "get_deploy_mode") else LinkMode.HARDLINK
                game.deploy(log_fn=_tlog, profile=profile, mode=deploy_mode)
                game.save_last_deployed_profile(profile)

                # Apply Wine DLL overrides (user-added + handler-defined)
                from Utils.wine_dll_config import deploy_game_wine_dll_overrides
                _pfx = game.get_prefix_path()
                if _pfx and _pfx.is_dir():
                    deploy_game_wine_dll_overrides(game.name, _pfx, game.wine_dll_overrides, log_fn=_tlog)

                # Deploy Root_Folder using the target profile's Root_Folder.
                target_rf_dir = game.get_effective_root_folder_path()
                rf_allowed = getattr(game, "root_folder_deploy_enabled", True)
                if rf_allowed and target_rf_dir.is_dir() and game_root:
                    deploy_root_folder(target_rf_dir, game_root, mode=deploy_mode, log_fn=_tlog)

                # Launcher swap runs after root-folder deploy so that script
                # extender executables are present first.
                if hasattr(game, "swap_launcher"):
                    game.swap_launcher(_tlog)

                _tlog("Run EXE: deploy complete, launching…")
                self._safe_after(0, lambda: self._launch_exe(exe_path, game))
            except Exception as e:
                self._safe_after(0, lambda err=e: self._log(f"Run EXE: deploy error: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _launch_exe(self, exe_path: "Path", game):
        """Route to native command / Steam / Heroic / Proton."""
        # Native launch hook: games that run natively (e.g. OpenMW via flatpak run).
        _native_cmd = getattr(game, "get_launch_command", lambda: None)()
        if _native_cmd is not None and self._game_exe_path is not None and exe_path == self._game_exe_path:
            self._log(f"Run EXE: launching natively: {' '.join(_native_cmd)}")
            def _native_worker():
                try:
                    subprocess.Popen(
                        _native_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    self._safe_after(0, lambda err=e: self._log(f"Run EXE error: {err}"))
            threading.Thread(target=_native_worker, daemon=True).start()
            return

        if self._is_game_exe(exe_path):
            mode = self._load_launch_mode(exe_path.name)  # 'auto'|'steam'|'heroic'|'none'
            steam_id = getattr(game, "steam_id", "")
            heroic_app_names = self._get_heroic_app_names_for_launch(game)

            if mode == "steam":
                if steam_id:
                    self._run_game_via_steam(steam_id)
                else:
                    self._log("Run EXE: launch mode is Steam but game has no Steam ID.")
                return

            if mode == "heroic":
                if heroic_app_names:
                    self._run_game_via_heroic(heroic_app_names)
                else:
                    self._log("Run EXE: launch mode is Heroic but game has no Heroic app name.")
                return

            if mode == "none":
                pass  # fall through to direct Proton launch below

            else:  # "auto"
                if steam_id and self._game_is_steam_install(game):
                    self._run_game_via_steam(steam_id)
                    return
                if heroic_app_names and self._game_is_heroic_install(game):
                    self._run_game_via_heroic(heroic_app_names)
                    return

            # Native Linux binary (no .exe / .bat suffix): run directly instead
            # of routing through Proton, which would fail on an ELF executable.
            suffix = exe_path.suffix.lower()
            if suffix not in (".exe", ".bat"):
                self._log(f"Run EXE: launching native binary: {exe_path}")
                def _elf_worker():
                    try:
                        subprocess.Popen(
                            [str(exe_path)],
                            cwd=str(exe_path.parent),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    except Exception as e:
                        self._safe_after(0, lambda err=e: self._log(f"Run EXE error: {err}"))
                threading.Thread(target=_elf_worker, daemon=True).start()
                return

        self._run_exe_via_proton(exe_path, game)

    def _run_exe_via_proton(self, exe_path: Path, game):
        """Standard Proton launch path for .exe files."""
        from gui.plugin_panel import _resolve_compat_data, _read_prefix_runner, _parse_launch_options
        from Utils.steam_finder import (
            find_any_installed_proton,
            find_proton_for_game,
            find_steam_root_for_proton_script,
        )

        # Check for a per-exe Proton override (user-selected version with own prefix)
        proton_override_name = self._load_proton_override(exe_path.name)
        if proton_override_name:
            from Utils.steam_finder import list_installed_proton
            # Try exact match first, then prefix match (e.g. "Proton 10" → "Proton 10.0")
            proton_script = find_any_installed_proton(proton_override_name)
            if proton_script is None:
                override_lower = proton_override_name.lower()
                for candidate in list_installed_proton():
                    if candidate.parent.name.lower().startswith(override_lower):
                        proton_script = candidate
                        break
            if proton_script is None:
                self._log(f"Run EXE: Proton override '{proton_override_name}' not found.")
                return
            # Use a dedicated prefix next to the exe so it's isolated from the game prefix
            compat_data = exe_path.parent / f"prefix_{proton_script.parent.name}"
            compat_data.mkdir(parents=True, exist_ok=True)
            self._log(f"Run EXE: using {proton_script.parent.name} with isolated prefix.")
        else:
            prefix_path = (
                game.get_prefix_path()
                if hasattr(game, "get_prefix_path") else None
            )
            if prefix_path is None or not prefix_path.is_dir():
                self._log("Run EXE: Proton prefix not configured for this game.")
                return

            compat_data = _resolve_compat_data(prefix_path)

            steam_id = getattr(game, "steam_id", "")
            proton_script = find_proton_for_game(steam_id) if steam_id else None
            if proton_script is None:
                # Read the runner name from the prefix's config_info so we use the
                # same Proton version the prefix was built with (e.g. GE-Proton10-28).
                preferred_runner = _read_prefix_runner(compat_data)
                proton_script = find_any_installed_proton(preferred_runner)
                if proton_script is None:
                    if steam_id:
                        self._log(
                            f"Run EXE: could not find Proton version for app {steam_id}, "
                            "and no installed Proton tool was found."
                        )
                    else:
                        self._log("Run EXE: no Steam ID and no installed Proton tool was found.")
                    return
                self._log(
                    f"Run EXE: using fallback Proton tool {proton_script.parent.name} "
                    "(no per-game Steam mapping found)."
                )

        steam_root = find_steam_root_for_proton_script(proton_script)
        if steam_root is None:
            self._log("Run EXE: could not determine Steam root for the selected Proton tool.")
            return

        env = os.environ.copy()
        env["STEAM_COMPAT_DATA_PATH"] = str(compat_data)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(steam_root)
        # Proton expects these to locate the game install and per-game shader/compat caches.
        # Without them GE-Proton (and others) fall back to app ID 0 / skip library detection.
        game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
        if game_path and not proton_override_name:
            env["STEAM_COMPAT_INSTALL_PATH"] = str(game_path)
        if not proton_override_name:
            steam_id = getattr(game, "steam_id", "")
            if steam_id:
                env.setdefault("SteamAppId", steam_id)
                env.setdefault("SteamGameId", steam_id)

        if proton_override_name and getattr(game, "synthesis_registry_name", None):
            from Utils.bethesda_registry import maybe_register_for_game
            maybe_register_for_game(
                prefix_dir=compat_data,
                proton_script=proton_script,
                env=env,
                game=game,
                log_fn=self._log,
            )

        # Re-apply profile-specific output substitution at launch time so the
        # correct path is used even if the profile changed after the exe was
        # selected in the dropdown.
        runtime_args_str = self._apply_profile_output_to_args(
            exe_path.name, self._exe_args_var.get()
        )
        try:
            extra_args = shlex.split(runtime_args_str)
        except ValueError as e:
            self._log(f"Run EXE: invalid arguments — {e}")
            return

        # Inject runtime-only args not saved to exe_args.json
        if exe_path.name in ("xLODGenx64.exe", "xLODGen.exe"):
            from Utils.exe_args_builder import _XLODGEN_GAME_FLAGS
            game_id = getattr(game, "game_id", None)
            xlodgen_flag = _XLODGEN_GAME_FLAGS.get(game_id, "") if game_id else ""
            if xlodgen_flag and xlodgen_flag not in extra_args:
                extra_args.append(xlodgen_flag)

        if exe_path.name == "PGPatcher.exe":
            from Utils.exe_args_builder import _bootstrap_pgpatcher_settings
            staging_path = game.get_effective_mod_staging_path() if hasattr(game, "get_effective_mod_staging_path") else None
            # Resolve the user-selected output mod folder (saved separately as
            # "PGPatcher.exe:output_mod" in exe_args.json). Falls back to
            # staging_path/"PGPatcher_output" by default.
            _pgp_output_mod: "Path | None" = None
            if staging_path is not None:
                _pgp_saved = self._load_exe_args("PGPatcher.exe:output_mod").strip()
                if _pgp_saved:
                    _pgp_output_mod = staging_path / _pgp_saved
            _bootstrap_pgpatcher_settings(exe_path, game_path, staging_path, self._log, update=True, output_mod=_pgp_output_mod)

        if exe_path.name == "Pandora Behaviour Engine+.exe":
            from Utils.exe_args_builder import _bootstrap_pandora_settings
            staging_path = (
                game.get_effective_mod_staging_path()
                if hasattr(game, "get_effective_mod_staging_path") else None
            )
            _bootstrap_pandora_settings(
                getattr(game, "game_id", None),
                game_path,
                staging_path,
                compat_data,
                self._log,
            )
            env.pop("DOTNET_ROOT", None)
            env.pop("DOTNET_BUNDLE_EXTRACT_BASE_DIR", None)
            env["PROTON_USE_WINED3D"] = "1"
            env["WINE_D3D_CONFIG"] = "renderer=gdi"

        if exe_path.name == "Wrye Bash.exe":
            game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
            if game_path and "-o" not in extra_args:
                # WB computes its .wbtemp dir from the drive of the game path.
                # Z:\ paths (Linux root mapped by Wine) are not writable, so
                # we create a symlink inside the Wine prefix's drive_c and pass
                # a C:\ path instead — WB then uses C:\users\steamuser\AppData
                # \Local\Temp which is always writable.
                real_game = game_path.resolve()
                c_games = compat_data / "pfx" / "drive_c" / "wb_games"
                c_games.mkdir(parents=True, exist_ok=True)
                link = c_games / real_game.name
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(real_game)
                extra_args += ["-o", f"C:\\wb_games\\{real_game.name}"]

        # For exes that must run from the game's Data folder, resolve the
        # deployed path so both the exe path and cwd point there.
        launch_path = exe_path
        _is_data_folder = (
            exe_path.name in self._DATA_FOLDER_ONLY_EXES
            or self._load_data_folder_exe(exe_path.name)
        )
        if _is_data_folder and game_path is not None:
            data_dir = game_path / "Data"
            for hit in data_dir.rglob(exe_path.name):
                launch_path = hit
                break

        self._log(f"Run EXE: launching {exe_path.name} via {proton_script.parent.name} ...")

        base_cmd = ["python3", str(proton_script), "run", str(launch_path)] + extra_args
        launch_opts = self._load_launch_options(exe_path.name)
        if not launch_opts:
            final_cmd = base_cmd
        else:
            env_updates, final_cmd = _parse_launch_options(launch_opts, base_cmd)
            if env_updates:
                env.update(env_updates)

        self._log(f"Run EXE:   cmd: {' '.join(final_cmd)}")
        _env_keys = (
            "WINE_D3D_CONFIG", "PROTON_USE_WINED3D", "WINEDLLOVERRIDES",
            "STEAM_COMPAT_DATA_PATH", "WINEDEBUG", "DXVK_HUD", "PROTON_LOG",
        )
        _env_summary = " ".join(
            f"{k}={env.get(k)}" for k in _env_keys if env.get(k) is not None
        )
        if _env_summary:
            self._log(f"Run EXE:   env: {_env_summary}")

        def _worker():
            try:
                subprocess.Popen(
                    final_cmd,
                    env=env,
                    cwd=launch_path.parent,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                self._safe_after(0, lambda err=e: self._log(f"Run EXE error: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _game_is_steam_install(self, game) -> bool:
        """Return True if the game folder lives inside a Steam library (steamapps/common)."""
        game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
        if game_path is None:
            return False
        from Utils.steam_finder import find_steam_libraries
        try:
            resolved = game_path.resolve()
            for lib in find_steam_libraries():
                if resolved.is_relative_to(lib.resolve()):
                    return True
        except Exception:
            pass
        return False

    def _run_game_via_steam(self, steam_id: str) -> None:
        """Launch the game through Steam (steam://rungameid) so the Steam API initialises."""
        self._log(f"Run EXE: launching via Steam (app {steam_id}) ...")

        def _worker():
            from Utils.xdg import host_env
            url = f"steam://rungameid/{steam_id}"
            in_flatpak = Path("/.flatpak-info").exists()
            # Inside Flatpak, the runtime has neither `steam` nor a working
            # xdg-open for steam:// URLs — only flatpak-spawn --host can reach
            # the user's real Steam client. Try host-spawn variants first so
            # we don't waste attempts on candidates that will always fail.
            if in_flatpak:
                candidates = (
                    ["flatpak-spawn", "--host", "steam", url],
                    ["flatpak-spawn", "--host", "xdg-open", url],
                    ["steam", url],
                    ["xdg-open", url],
                )
            else:
                candidates = (
                    ["steam", url],
                    ["xdg-open", url],
                )
            env = host_env()
            last_err = None
            for cmd in candidates:
                try:
                    subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except FileNotFoundError as e:
                    last_err = e
                    continue
                except Exception as e:
                    last_err = e
                    break
            self._safe_after(0, lambda err=last_err: self._log(f"Run EXE error: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _get_heroic_app_names_for_launch(self, game) -> list:
        """Return heroic app names for launch.

        Detected at runtime by scanning Heroic's installed.json for the
        game's exe — same mechanism used by Add Game. Falls back to the
        legacy handler property / saved paths.json field for compatibility
        with older configs."""
        names: list[str] = []
        from Utils.heroic_finder import find_heroic_app_name_by_exe
        exe_names = [getattr(game, "exe_name", None)]
        exe_names += list(getattr(game, "exe_name_alts", []) or [])
        for exe in [e for e in exe_names if e]:
            try:
                found = find_heroic_app_name_by_exe(exe)
            except Exception:
                found = None
            if found and found not in names:
                names.append(found)

        names.extend(n for n in (getattr(game, "heroic_app_names", []) or []) if n not in names)

        if not names and hasattr(game, "name"):
            try:
                paths_file = get_game_config_path(game.name)
                if paths_file.is_file():
                    data = json.loads(paths_file.read_text(encoding="utf-8"))
                    saved = data.get("heroic_app_name", "").strip()
                    if saved:
                        names = [saved]
            except (OSError, json.JSONDecodeError):
                pass
        return names

    def _game_is_heroic_install(self, game) -> bool:
        """Return True if Heroic knows about this game (it's in an Epic/GOG library)."""
        app_names = self._get_heroic_app_names_for_launch(game)
        if not app_names:
            return False
        from Utils.heroic_finder import find_heroic_launch_info
        try:
            return find_heroic_launch_info(app_names) is not None
        except Exception:
            return False

    def _run_game_via_heroic(self, heroic_app_names: list) -> None:
        """Launch the game through Heroic (heroic://launch) so Epic/GOG auth initialises."""
        from Utils.heroic_finder import find_heroic_launch_info
        info = find_heroic_launch_info(heroic_app_names)
        if info is None:
            self._log("Run EXE: game not found in Heroic library, falling through to Proton.")
            return
        store, app_name = info
        url = f"heroic://launch/{store}/{app_name}"
        self._log(f"Run EXE: launching via Heroic ({store}/{app_name}) ...")

        def _worker():
            try:
                xdg_open(url)
            except Exception as e:
                self._safe_after(0, lambda err=e: self._log(f"Run EXE error: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── VRAMr wrapper ────────────────────────────────────────────────

    def _run_vramr_wrapper(self, bat_path: Path):
        """Show a preset picker and run VRAMr natively via the Linux wrapper."""
        game = self._game
        if game is None:
            self._log("VRAMr: no game selected.")
            return

        data_dir = (
            game.get_mod_data_path()
            if hasattr(game, "get_mod_data_path") else None
        )
        if data_dir is None or not data_dir.is_dir():
            self._log("VRAMr: game Data directory not configured or missing.")
            return

        staging = (
            game.get_effective_mod_staging_path()
            if hasattr(game, "get_mod_staging_path") else None
        )
        if staging is None:
            self._log("VRAMr: mod staging path not configured.")
            return

        output_dir = staging / "VRAMr"

        app = self.winfo_toplevel()
        show_fn = getattr(app, "show_vramr_panel", None)
        if show_fn:
            show_fn(
                bat_dir=bat_path.parent,
                game_data_dir=data_dir,
                output_dir=output_dir,
                log_fn=self._log,
            )
        else:
            self._log("VRAMr: could not open preset panel.")

    # ── BENDr wrapper ─────────────────────────────────────────────────

    def _run_bendr_wrapper(self, bat_path: Path):
        """Run BENDr normal-map pipeline via the Linux wrapper."""
        game = self._game
        if game is None:
            self._log("BENDr: no game selected.")
            return

        data_dir = (
            game.get_mod_data_path()
            if hasattr(game, "get_mod_data_path") else None
        )
        if data_dir is None or not data_dir.is_dir():
            self._log("BENDr: game Data directory not configured or missing.")
            return

        staging = (
            game.get_effective_mod_staging_path()
            if hasattr(game, "get_mod_staging_path") else None
        )
        if staging is None:
            self._log("BENDr: mod staging path not configured.")
            return

        output_dir = staging / "BENDr"

        from gui.dialogs import _BENDrRunDialog
        _BENDrRunDialog(
            self.winfo_toplevel(),
            bat_dir=bat_path.parent,
            game_data_dir=data_dir,
            output_dir=output_dir,
            log_fn=self._log,
        )

    # ── ParallaxR wrapper ──────────────────────────────────────────────

    def _run_parallaxr_wrapper(self, bat_path: Path):
        """Run ParallaxR parallax-texture pipeline via the Linux wrapper."""
        game = self._game
        if game is None:
            self._log("ParallaxR: no game selected.")
            return

        data_dir = (
            game.get_mod_data_path()
            if hasattr(game, "get_mod_data_path") else None
        )
        if data_dir is None or not data_dir.is_dir():
            self._log("ParallaxR: game Data directory not configured or missing.")
            return

        staging = (
            game.get_effective_mod_staging_path()
            if hasattr(game, "get_mod_staging_path") else None
        )
        if staging is None:
            self._log("ParallaxR: mod staging path not configured.")
            return

        output_dir = staging / "ParallaxR"

        from gui.dialogs import _ParallaxRRunDialog
        _ParallaxRRunDialog(
            self.winfo_toplevel(),
            bat_dir=bat_path.parent,
            game_data_dir=data_dir,
            output_dir=output_dir,
            log_fn=self._log,
        )
