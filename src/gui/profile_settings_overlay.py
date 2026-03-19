"""
Profile Settings overlay — manage profiles (rename/remove) over the modlist panel.
"""

from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_PANEL,
    BORDER,
    FONT_BOLD,
    FONT_NORMAL,
    FONT_SMALL,
    TEXT_MAIN,
    TEXT_DIM,
)
from gui import game_helpers as _gh
from gui.game_helpers import _profiles_for_game
from gui.ctk_components import CTkAlert


class ProfileSettingsOverlay(tk.Frame):
    """
    Overlay for managing profiles (rename / remove).
    Placed over the ModListPanel via place(relx=0, rely=0, relwidth=1, relheight=1).

    Callbacks:
        on_close()       — called when the overlay should be dismissed
        on_profile_renamed(old, new) — called after a successful rename
        on_profile_removed(name)     — called after a successful removal
    """

    def __init__(
        self,
        parent: tk.Widget,
        game_name: str,
        current_profile: str,
        on_close: Optional[Callable[[], None]] = None,
        on_profile_renamed: Optional[Callable[[str, str], None]] = None,
        on_profile_removed: Optional[Callable[[str], None]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._game_name = game_name
        self._current_profile = current_profile
        self._on_close = on_close
        self._on_profile_renamed = on_profile_renamed
        self._on_profile_removed = on_profile_removed
        self._log = log_fn or (lambda msg: None)

        self._rename_frame: tk.Frame | None = None
        self._rename_entry: ctk.CTkEntry | None = None
        self._rename_target: str | None = None

        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Toolbar
        toolbar = tk.Frame(self, bg=BG_HEADER, height=42)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        tk.Label(
            toolbar, text="Profile Settings",
            font=FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        ).pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            toolbar, text="✕ Close", width=85, height=30,
            fg_color="#6b3333", hover_color="#8c4444", text_color="white",
            font=FONT_BOLD, command=self._do_close,
        ).pack(side="right", padx=(6, 12), pady=5)

        # Content area
        content = tk.Frame(self, bg=BG_DEEP)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        # Scrollable inner frame
        outer = tk.Frame(content, bg=BG_DEEP)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=BG_DEEP, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                           bg="#383838", troughcolor=BG_DEEP,
                           highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._canvas = canvas

        self._list_frame = tk.Frame(canvas, bg=BG_DEEP)
        self._list_frame_id = canvas.create_window((0, 0), window=self._list_frame, anchor="nw")

        self._list_frame.bind("<Configure>", self._on_frame_configure)
        canvas.bind("<Configure>", self._on_canvas_configure)
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))
        self._list_frame.bind("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        self._list_frame.bind("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

        self._populate_list()

    def _on_frame_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._list_frame_id, width=event.width)

    # ------------------------------------------------------------------
    # Populate profile rows
    # ------------------------------------------------------------------

    def _populate_list(self):
        for child in self._list_frame.winfo_children():
            child.destroy()
        self._rename_frame = None
        self._rename_entry = None
        self._rename_target = None

        profiles = _profiles_for_game(self._game_name)

        for i, profile in enumerate(profiles):
            row_bg = BG_PANEL if i % 2 == 0 else BG_DEEP
            row = tk.Frame(self._list_frame, bg=row_bg, height=44)
            row.pack(fill="x", pady=(0, 1))
            row.grid_propagate(False)
            row.grid_columnconfigure(0, weight=1)
            row.grid_rowconfigure(0, weight=1)

            is_default = profile == "default" or self._is_original_default(profile)
            is_active = profile == self._current_profile

            # Profile name label
            label_text = profile
            if is_default:
                label_text += "  (default)"  # covers both "default" and renamed originals
            if is_active:
                label_text += "  ★"
            lbl_color = ACCENT if is_active else TEXT_MAIN
            tk.Label(
                row, text=label_text,
                font=FONT_BOLD if is_active else FONT_NORMAL,
                fg=lbl_color, bg=row_bg, anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=12)

            btn_frame = tk.Frame(row, bg=row_bg)
            btn_frame.grid(row=0, column=1, padx=8)

            # Rename button (always available)
            ctk.CTkButton(
                btn_frame, text="Rename", width=72, height=28, font=FONT_SMALL,
                fg_color=BG_HOVER, hover_color=ACCENT_HOV, text_color=TEXT_MAIN,
                command=lambda p=profile, r=row, rb=row_bg: self._show_rename(p, r, rb),
            ).pack(side="left", padx=(0, 6))

            # Remove button (disabled for default)
            remove_btn = ctk.CTkButton(
                btn_frame, text="Remove", width=72, height=28, font=FONT_SMALL,
                fg_color="#6b3333" if not is_default else "#3a3a3a",
                hover_color="#8c4444" if not is_default else "#3a3a3a",
                text_color="white" if not is_default else TEXT_DIM,
                state="normal" if not is_default else "disabled",
                command=(lambda p=profile: self._on_remove(p)) if not is_default else lambda: None,
            )
            remove_btn.pack(side="left")

    # ------------------------------------------------------------------
    # Rename
    # ------------------------------------------------------------------

    def _show_rename(self, profile: str, row: tk.Frame, row_bg: str):
        """Inline rename bar inserted below the profile row."""
        # Close any existing rename bar first
        if self._rename_frame is not None:
            self._rename_frame.destroy()
            self._rename_frame = None

        self._rename_target = profile

        frame = tk.Frame(self._list_frame, bg=BG_HEADER, pady=6)
        frame.pack(fill="x", after=row)
        self._rename_frame = frame

        tk.Label(
            frame, text=f"Rename '{profile}' to:",
            font=FONT_SMALL, fg=TEXT_DIM, bg=BG_HEADER,
        ).pack(side="left", padx=(12, 6))

        entry = ctk.CTkEntry(
            frame, width=180, height=28, font=FONT_NORMAL,
            fg_color=BG_PANEL, text_color=TEXT_MAIN,
            border_color=BORDER,
        )
        entry.insert(0, profile)
        entry.select_range(0, "end")
        entry.pack(side="left", padx=(0, 6))
        entry.focus_set()
        self._rename_entry = entry

        ctk.CTkButton(
            frame, text="OK", width=50, height=28, font=FONT_SMALL,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="white",
            command=self._do_rename,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            frame, text="Cancel", width=60, height=28, font=FONT_SMALL,
            fg_color=BG_HOVER, hover_color="#555", text_color=TEXT_MAIN,
            command=self._cancel_rename,
        ).pack(side="left")

        entry.bind("<Return>", lambda e: self._do_rename())
        entry.bind("<Escape>", lambda e: self._cancel_rename())

        # Scroll so the rename bar is visible
        self.after(50, lambda: self._canvas.yview_moveto(1.0))

    def _cancel_rename(self):
        if self._rename_frame is not None:
            self._rename_frame.destroy()
            self._rename_frame = None
        self._rename_target = None
        self._rename_entry = None

    def _do_rename(self):
        if self._rename_entry is None or self._rename_target is None:
            return
        old_name = self._rename_target
        new_name = self._rename_entry.get().strip()

        if not new_name:
            self._log("Profile name cannot be empty.")
            return
        if new_name == old_name:
            self._cancel_rename()
            return
        if new_name.lower() == "default":
            self._log("Cannot rename to 'default'.")
            return

        existing = _profiles_for_game(self._game_name)
        if new_name in existing:
            self._log(f"Profile '{new_name}' already exists.")
            return

        # Perform the rename (directory rename)
        profile_dir = self._get_profile_dir(old_name)
        new_dir = profile_dir.parent / new_name
        was_original_default = old_name == "default" or self._is_original_default_dir(profile_dir)
        try:
            profile_dir.rename(new_dir)
        except OSError as e:
            self._log(f"Rename failed: {e}")
            return

        # If renaming the original default, mark the new dir so it stays unremovable
        if was_original_default:
            self._mark_original_default(new_dir)

        self._log(f"Profile '{old_name}' renamed to '{new_name}'.")
        if old_name == self._current_profile:
            self._current_profile = new_name

        self._cancel_rename()
        self._populate_list()

        if self._on_profile_renamed:
            self._on_profile_renamed(old_name, new_name)

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def _on_remove(self, profile: str):
        if self._is_original_default(profile):
            return
        alert = CTkAlert(
            state="warning",
            title="Remove Profile",
            body_text=f"Are you sure you want to remove the '{profile}' profile?\n\nThe game will be restored first if this profile is deployed.",
            btn1="Remove",
            btn2="Cancel",
            parent=self.winfo_toplevel(),
        )
        if alert.get() != "Remove":
            return

        game = _gh._GAMES.get(self._game_name)
        profile_dir = self._get_profile_dir(profile)

        # Restore deployed mod files before deleting
        if game is not None and game.is_configured():
            game.set_active_profile_dir(profile_dir)
            try:
                if hasattr(game, "restore"):
                    game.restore()
            except Exception:
                pass
            try:
                from Utils.deploy import restore_root_folder
                root_folder_dir = game.get_effective_root_folder_path()
                game_root = game.get_game_path()
                if root_folder_dir.is_dir() and game_root:
                    restore_root_folder(root_folder_dir, game_root)
            except Exception:
                pass
            game.set_active_profile_dir(None)

        if profile_dir.is_dir():
            from gui.game_helpers import profile_uses_specific_mods
            if profile_uses_specific_mods(profile_dir):
                preserve = {profile_dir / "mods", profile_dir / "modlist.txt"}
                for child in list(profile_dir.iterdir()):
                    if child not in preserve:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
            else:
                shutil.rmtree(profile_dir)

        self._log(f"Profile '{profile}' removed.")

        if profile == self._current_profile:
            self._current_profile = "default"

        self._populate_list()

        if self._on_profile_removed:
            self._on_profile_removed(profile)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_original_default(self, profile: str) -> bool:
        """Return True if this profile was originally the default (by name or flag)."""
        if profile == "default":
            return True
        return self._is_original_default_dir(self._get_profile_dir(profile))

    def _is_original_default_dir(self, profile_dir: Path) -> bool:
        import json
        settings = profile_dir / "profile_settings.json"
        try:
            return json.loads(settings.read_text(encoding="utf-8")).get("original_default", False)
        except Exception:
            return False

    def _mark_original_default(self, profile_dir: Path):
        import json
        settings = profile_dir / "profile_settings.json"
        try:
            data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
        except Exception:
            data = {}
        data["original_default"] = True
        try:
            settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _get_profile_dir(self, profile: str) -> Path:
        game = _gh._GAMES.get(self._game_name)
        if game is not None:
            return game.get_profile_root() / "profiles" / profile
        from Utils.config_paths import get_profiles_dir
        return get_profiles_dir() / self._game_name / "profiles" / profile

    def _do_close(self):
        if self._on_close:
            self._on_close()
        else:
            self.destroy()
