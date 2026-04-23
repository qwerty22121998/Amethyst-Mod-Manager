"""
Download locations overlay — manage extra folders to scan for archives.

Shown when the user clicks the Locations button in the Downloads tab.
Lets users add/remove paths; saved to ~/.config/AmethystModManager/download_locations.json.

The default Downloads folder (XDG_DOWNLOAD_DIR or ~/Downloads) is always
listed first. Users may disable it so it's skipped during scans; this is
persisted via the `default_disabled` flag in the config file.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

from Utils.config_paths import get_download_locations_path
from Utils.portal_filechooser import pick_folder

from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
from gui.theme import (
    BG_DEEP,
    BG_HEADER,
    BG_PANEL,
    ACCENT,
    ACCENT_HOV,
    TEXT_MAIN,
    TEXT_DIM,
    FONT_BOLD,
    FONT_SMALL,
)


def _read_config() -> tuple[list[str], bool]:
    """Load (extras, default_disabled) from config.

    Supports the legacy format (a bare JSON list of paths) as well as the
    newer object form `{"extras": [...], "default_disabled": bool}`.
    """
    path = get_download_locations_path()
    if not path.is_file():
        return [], False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], False
    if isinstance(data, list):
        return [str(p).strip() for p in data if p and str(p).strip()], False
    if isinstance(data, dict):
        raw = data.get("extras", [])
        extras = (
            [str(p).strip() for p in raw if p and str(p).strip()]
            if isinstance(raw, list) else []
        )
        return extras, bool(data.get("default_disabled", False))
    return [], False


def _write_config(extras: list[str], default_disabled: bool) -> None:
    path = get_download_locations_path()
    path.write_text(
        json.dumps({"extras": extras, "default_disabled": default_disabled}, indent=2),
        encoding="utf-8",
    )


def _load_locations() -> list[str]:
    """Load extra download scan paths from config."""
    return _read_config()[0]


def _save_locations(locations: list[str]) -> None:
    """Save extra download scan paths (preserving the default_disabled flag)."""
    _, disabled = _read_config()
    _write_config(locations, disabled)


def get_default_downloads_dir() -> Path:
    """Return the system default Downloads folder (XDG_DOWNLOAD_DIR or ~/Downloads)."""
    xdg = os.environ.get("XDG_DOWNLOAD_DIR")
    return Path(xdg) if xdg else Path.home() / "Downloads"


def is_default_downloads_disabled() -> bool:
    """True if the user has opted out of scanning the default Downloads folder."""
    return _read_config()[1]


def set_default_downloads_disabled(disabled: bool) -> None:
    extras, _ = _read_config()
    _write_config(extras, bool(disabled))


def load_extra_download_locations() -> list[str]:
    """Return extra scan paths only (excludes the default Downloads folder)."""
    return _load_locations()


def get_effective_download_locations() -> list[Path]:
    """Return all folders that should be scanned for archives.

    Includes the default Downloads folder (unless the user disabled it) plus
    any user-added extras. De-duplicated by resolved path.
    """
    dirs: list[Path] = []
    seen: set[Path] = set()
    if not is_default_downloads_disabled():
        default = get_default_downloads_dir()
        try:
            key = default.resolve()
        except OSError:
            key = default
        dirs.append(default)
        seen.add(key)
    for p in _load_locations():
        path = Path(p).expanduser()
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        dirs.append(path)
        seen.add(key)
    return dirs


class DownloadLocationsOverlay(tk.Frame):
    """
    Overlay for managing extra download scan locations.
    Placed over the plugin panel when the user clicks Locations.
    """

    def __init__(
        self,
        parent: tk.Widget,
        on_close: Optional[Callable[[], None]] = None,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._on_close = on_close
        self._on_saved = on_saved
        extras, disabled = _read_config()
        self._locations: list[str] = extras
        self._default_disabled: bool = disabled

        self._build()

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Toolbar
        toolbar = tk.Frame(self, bg=BG_HEADER, height=42)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        tk.Label(
            toolbar, text="Download Locations",
            font=FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        ).pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            toolbar, text="✕ Close", width=85, height=30,
            fg_color="#6b3333", hover_color="#8c4444", text_color="white",
            font=FONT_BOLD, command=self._do_close,
        ).pack(side="right", padx=(6, 12), pady=5)

        # Content
        content = tk.Frame(self, bg=BG_DEEP)
        content.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        content.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)

        tk.Label(
            content,
            text=(
                "Folders to scan for mod archives. The default Downloads folder "
                "is included automatically — remove it if you don't want it scanned."
            ),
            font=FONT_SMALL, fg=TEXT_DIM, bg=BG_DEEP, wraplength=400,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # Scrollable list of paths
        list_frame = tk.Frame(content, bg=BG_PANEL, bd=0, highlightthickness=0)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._list_canvas = tk.Canvas(
            list_frame, bg=BG_PANEL, bd=0,
            highlightthickness=0, yscrollincrement=1,
        )
        self._list_canvas.bind("<MouseWheel>", self._on_list_scroll)
        if not LEGACY_WHEEL_REDUNDANT:
            self._list_canvas.bind("<Button-4>", lambda e: self._list_canvas.yview_scroll(-3, "units"))
            self._list_canvas.bind("<Button-5>", lambda e: self._list_canvas.yview_scroll(3, "units"))
        self._list_vsb = tk.Scrollbar(
            list_frame, orient="vertical", command=self._list_canvas.yview,
            bg="#383838", troughcolor=BG_DEEP, activebackground=ACCENT,
            highlightthickness=0, bd=0,
        )
        self._list_canvas.configure(yscrollcommand=self._list_vsb.set)
        self._list_canvas.grid(row=0, column=0, sticky="nsew")
        self._list_vsb.grid(row=0, column=1, sticky="ns")

        self._list_inner = tk.Frame(self._list_canvas, bg=BG_PANEL)
        self._list_canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        self._list_inner.bind("<Configure>", self._on_list_configure)

        # Add button row
        btn_row = tk.Frame(content, bg=BG_DEEP)
        btn_row.grid(row=2, column=0, sticky="w", pady=(8, 0))

        ctk.CTkButton(
            btn_row, text="+ Add Folder", width=120, height=28,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            font=FONT_BOLD, command=self._on_add,
        ).pack(side="left", padx=(0, 8))

        self._repaint_list()

    def _on_list_configure(self, event):
        self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

    def _on_list_scroll(self, event):
        self._list_canvas.yview_scroll(-3 if (event.delta or 0) > 0 else 3, "units")

    def _repaint_list(self):
        """Rebuild the list of path rows."""
        for w in self._list_inner.winfo_children():
            w.destroy()

        self._list_inner.grid_columnconfigure(0, weight=1)
        row_idx = 0

        # Default Downloads row — always shown, either as an active entry with
        # a Remove button, or greyed-out with a Restore button when disabled.
        default_dir = get_default_downloads_dir()
        row = tk.Frame(self._list_inner, bg=BG_PANEL)
        row.grid(row=row_idx, column=0, sticky="ew", pady=2)
        row.grid_columnconfigure(0, weight=1)

        if self._default_disabled:
            lbl_text = f"{default_dir}  (default — disabled)"
            fg_col = TEXT_DIM
            btn = ctk.CTkButton(
                row, text="Restore", width=80, height=24,
                fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
                font=FONT_SMALL, command=self._on_restore_default,
            )
        else:
            lbl_text = f"{default_dir}  (default)"
            fg_col = TEXT_MAIN
            btn = ctk.CTkButton(
                row, text="Remove", width=80, height=24,
                fg_color="#a83232", hover_color="#c43c3c", text_color="white",
                font=FONT_SMALL, command=self._on_remove_default,
            )
        tk.Label(
            row, text=lbl_text, anchor="w",
            font=FONT_SMALL, fg=fg_col, bg=BG_PANEL,
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        btn.grid(row=0, column=1, padx=4, pady=4)
        row_idx += 1

        for path_str in self._locations:
            row = tk.Frame(self._list_inner, bg=BG_PANEL)
            row.grid(row=row_idx, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)

            path = Path(path_str).expanduser()
            display = str(path) if path.is_dir() else str(path_str)
            tk.Label(
                row, text=display, anchor="w",
                font=FONT_SMALL, fg=TEXT_MAIN, bg=BG_PANEL,
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=4)

            extras_idx = row_idx - 1
            ctk.CTkButton(
                row, text="Remove", width=80, height=24,
                fg_color="#a83232", hover_color="#c43c3c", text_color="white",
                font=FONT_SMALL, command=lambda idx=extras_idx: self._on_remove(idx),
            ).grid(row=0, column=1, padx=4, pady=4)
            row_idx += 1

        if not self._locations and not self._default_disabled:
            tk.Label(
                self._list_inner,
                text="Click 'Add Folder' to scan additional locations.",
                font=FONT_SMALL, fg=TEXT_DIM, bg=BG_PANEL,
            ).grid(row=row_idx, column=0, sticky="w", padx=8, pady=8)

    def _on_add(self):
        root = self.winfo_toplevel()

        def _on_picked(chosen: Path | None) -> None:
            root.after(0, lambda: self._add_picked(chosen))

        pick_folder("Select folder to scan for archives", _on_picked)

    def _add_picked(self, chosen: Path | None) -> None:
        if chosen is None:
            return
        path_str = str(chosen.resolve())
        if path_str not in self._locations:
            self._locations.append(path_str)
            _save_locations(self._locations)
            self._repaint_list()
            if self._on_saved:
                self._on_saved()

    def _on_remove(self, idx: int) -> None:
        if 0 <= idx < len(self._locations):
            self._locations.pop(idx)
            _save_locations(self._locations)
            self._repaint_list()
            if self._on_saved:
                self._on_saved()

    def _on_remove_default(self) -> None:
        self._default_disabled = True
        _write_config(self._locations, True)
        self._repaint_list()
        if self._on_saved:
            self._on_saved()

    def _on_restore_default(self) -> None:
        self._default_disabled = False
        _write_config(self._locations, False)
        self._repaint_list()
        if self._on_saved:
            self._on_saved()

    def _do_close(self):
        if self._on_close:
            self._on_close()
        else:
            self.place_forget()
