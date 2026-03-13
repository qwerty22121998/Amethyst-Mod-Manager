"""
Nexus browser overlay — Browse, Tracked, Endorsed, Trending mods from Nexus Mods.

Embeds inside the ModListPanel area as an overlay (like Collections).
Shows when the Nexus toolbar button is pressed.
"""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk
from Utils.xdg import open_url

from gui.tracked_mods_panel import TrackedModsPanel
from gui.endorsed_mods_panel import EndorsedModsPanel
from gui.browse_mods_panel import BrowseModsPanel
from gui.trending_mods_panel import TrendingModsPanel
from gui.install_mod import install_mod_from_archive
from Nexus.nexus_meta import build_meta_from_download

from gui.theme import (
    BG_DEEP,
    BG_HEADER,
    ACCENT,
    ACCENT_HOV,
    TEXT_MAIN,
    FONT_BOLD,
)


class NexusBrowserOverlay(tk.Frame):
    """
    Browse / Tracked / Endorsed mods panel — embeds inside the ModListPanel area.
    """

    def __init__(
        self,
        parent: tk.Widget,
        game_domain: str,
        api,
        game=None,
        log_fn: Optional[Callable] = None,
        app_root: Optional[tk.Widget] = None,
        on_close: Optional[Callable] = None,
        on_open_settings: Optional[Callable] = None,
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._game_domain = game_domain
        self._api = api
        self._game = game
        self._app_root = app_root or parent.winfo_toplevel()
        self._log = log_fn or (lambda msg: None)
        self._on_close = on_close
        self._on_open_settings = on_open_settings

        self._build()

    def _build(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Toolbar
        toolbar = tk.Frame(self, bg=BG_HEADER, height=42)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        def _btn(name: str, cmd, w=85):
            return ctk.CTkButton(
                toolbar, text=name, width=w, height=30,
                fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="white",
                font=FONT_BOLD, command=cmd,
            )

        self._browse_btn = _btn("Browse", lambda: self._show_panel("Browse"), 90)
        self._browse_btn.pack(side="left", padx=4, pady=5)
        self._tracked_btn = _btn("Tracked", lambda: self._show_panel("Tracked"), 95)
        self._tracked_btn.pack(side="left", padx=4, pady=5)
        self._endorsed_btn = _btn("Endorsed", lambda: self._show_panel("Endorsed"), 105)
        self._endorsed_btn.pack(side="left", padx=4, pady=5)
        self._trending_btn = _btn("Trending", lambda: self._show_panel("Trending"), 100)
        self._trending_btn.pack(side="left", padx=4, pady=5)

        if self._on_open_settings:
            ctk.CTkButton(
                toolbar, text="⚙ Settings", width=100, height=30,
                fg_color="#da8e35", hover_color="#e5a04a", text_color="white",
                font=FONT_BOLD, command=self._on_open_settings,
            ).pack(side="left", padx=(12, 6), pady=5)

        ctk.CTkButton(
            toolbar, text="✕ Close", width=85, height=36,
            fg_color="#6b3333", hover_color="#8c4444", text_color="white",
            font=FONT_BOLD, command=self._do_close,
        ).pack(side="right", padx=(6, 12), pady=5)

        # Content area — stacked panel frames
        content = tk.Frame(self, bg=BG_DEEP)
        content.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        def _get_api():
            return self._api

        def _get_game_domain():
            return self._game_domain

        self._panel_frames = {}
        for name in ("Browse", "Tracked", "Endorsed", "Trending"):
            frame = tk.Frame(content, bg=BG_DEEP)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_rowconfigure(1, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            self._panel_frames[name] = frame

        self._tracked_panel = TrackedModsPanel(
            self._panel_frames["Tracked"],
            log_fn=self._log,
            get_api=_get_api,
            get_game_domain=_get_game_domain,
            install_fn=self._install_from_tracked,
        )
        self._endorsed_panel = EndorsedModsPanel(
            self._panel_frames["Endorsed"],
            log_fn=self._log,
            get_api=_get_api,
            get_game_domain=_get_game_domain,
            install_fn=self._install_from_endorsed,
        )
        self._browse_panel = BrowseModsPanel(
            self._panel_frames["Browse"],
            log_fn=self._log,
            get_api=_get_api,
            get_game_domain=_get_game_domain,
            install_fn=self._install_from_browse,
        )
        self._trending_panel = TrendingModsPanel(
            self._panel_frames["Trending"],
            log_fn=self._log,
            get_api=_get_api,
            get_game_domain=_get_game_domain,
            install_fn=self._install_from_trending,
        )

        self._current_panel = "Browse"
        self._show_panel("Browse")

    def _show_panel(self, name: str):
        """Switch to the Browse, Tracked, Endorsed, or Trending panel."""
        for n, frame in self._panel_frames.items():
            if n == name:
                frame.grid()
            else:
                frame.grid_remove()
        self._current_panel = name
        # Highlight active button
        for btn, n in [
            (self._browse_btn, "Browse"),
            (self._tracked_btn, "Tracked"),
            (self._endorsed_btn, "Endorsed"),
            (self._trending_btn, "Trending"),
        ]:
            btn.configure(fg_color=ACCENT_HOV if n == name else ACCENT)
        # Auto-refresh the panel when switching to it
        panel_map = {
            "Browse": self._browse_panel,
            "Tracked": self._tracked_panel,
            "Endorsed": self._endorsed_panel,
            "Trending": self._trending_panel,
        }
        panel = panel_map.get(name)
        if panel is not None and hasattr(panel, "refresh"):
            panel.refresh()

    def _do_close(self):
        if self._on_close:
            self._on_close()
        else:
            self.place_forget()

    def _install_from_tracked(self, entry):
        self._install_nexus_mod(
            entry, "Tracked Mods",
            lambda e: (e.domain_name, e.mod_id, e.name),
        )

    def _install_from_endorsed(self, entry):
        self._install_nexus_mod(
            entry, "Endorsed Mods",
            lambda e: (e.domain_name, e.mod_id, e.name),
        )

    def _install_from_browse(self, entry):
        self._install_nexus_mod(
            entry, "Browse",
            lambda e: (e.domain_name, e.mod_id, e.name),
        )

    def _install_from_trending(self, entry):
        self._install_nexus_mod(
            entry, "Trending",
            lambda e: (e.domain_name, e.mod_id, e.name),
        )

    def _install_nexus_mod(self, entry, label: str, extract_fn: Callable):
        """Download and install a mod from Nexus (Tracked/Endorsed/Browse)."""
        app = self._app_root
        api = self._api
        game = self._game
        mod_panel = getattr(app, "_mod_panel", None)

        if api is None:
            self._log(f"{label}: Set your Nexus API key first.")
            return
        if game is None or not game.is_configured():
            self._log(f"{label}: No configured game selected.")
            return

        domain, mod_id, mod_name = extract_fn(entry)
        mod_name = mod_name or f"Mod {mod_id}"
        self._log(f"{label}: Installing '{mod_name}'...")

        cancel_ev = mod_panel.get_download_cancel_event() if mod_panel else None
        if mod_panel:
            mod_panel.show_download_progress(f"Installing: {mod_name}", cancel=cancel_ev)
        log_fn = self._log

        def _worker():
            downloader = getattr(app, "_nexus_downloader", None)
            if downloader is None:
                app.after(0, lambda: (
                    mod_panel.hide_download_progress(cancel=cancel_ev) if mod_panel else None,
                    log_fn(f"{label}: Downloader not initialised."),
                ))
                return

            is_premium = False
            try:
                user = api.validate()
                is_premium = user.is_premium
            except Exception:
                pass

            if not is_premium:
                files_url = f"https://www.nexusmods.com/{domain}/mods/{mod_id}?tab=files"
                def _fallback():
                    if mod_panel:
                        mod_panel.hide_download_progress(cancel=cancel_ev)
                    log_fn(f"{label}: Premium required for direct download.")
                    log_fn(f'{label}: Opening files page — click "Download with Mod Manager" there.')
                    log_fn(f"{label}: {files_url}")
                    try:
                        open_url(files_url)
                    except Exception as exc:
                        log_fn(f"{label}: Could not open browser — {exc}")
                app.after(0, _fallback)
                return

            file_info = None
            try:
                files_resp = api.get_mod_files(domain, mod_id)
                main_files = [f for f in files_resp.files if f.category_name == "MAIN"]
                if main_files:
                    file_info = max(main_files, key=lambda f: f.uploaded_timestamp)
                elif files_resp.files:
                    file_info = max(files_resp.files, key=lambda f: f.uploaded_timestamp)
            except Exception as exc:
                app.after(0, lambda: (
                    mod_panel.hide_download_progress(cancel=cancel_ev) if mod_panel else None,
                    log_fn(f"{label}: Could not fetch file list — {exc}"),
                ))
                return

            if file_info is None:
                app.after(0, lambda: (
                    mod_panel.hide_download_progress(cancel=cancel_ev) if mod_panel else None,
                    log_fn(f"{label}: No files found for '{mod_name}'."),
                ))
                return

            result = downloader.download_file(
                game_domain=domain,
                mod_id=mod_id,
                file_id=file_info.file_id,
                progress_cb=lambda cur, total: app.after(
                    0, lambda c=cur, t=total: (
                        mod_panel.update_download_progress(c, t, cancel=cancel_ev)
                        if mod_panel else None
                    )
                ),
                cancel=cancel_ev,
                known_file_name=file_info.file_name,
            )

            if result.success and result.file_path:
                def _install():
                    try:
                        if app.grab_current() is not None:
                            app.after(500, _install)
                            return
                    except Exception:
                        pass
                    if mod_panel:
                        mod_panel.hide_download_progress(cancel=cancel_ev)
                    log_fn(f"{label}: Installing '{mod_name}'...")
                    try:
                        _prebuilt = build_meta_from_download(
                            game_domain=domain,
                            mod_id=mod_id,
                            file_id=file_info.file_id,
                            archive_name=result.file_name,
                            mod_info=entry,
                            file_info=file_info,
                        )
                    except Exception:
                        _prebuilt = None
                    install_mod_from_archive(
                        str(result.file_path), app, log_fn, game, mod_panel,
                        prebuilt_meta=_prebuilt)
                app.after(0, _install)
            else:
                app.after(0, lambda: (
                    mod_panel.hide_download_progress(cancel=cancel_ev) if mod_panel else None,
                    log_fn(f"{label}: Download failed — {result.error}"),
                ))

        threading.Thread(target=_worker, daemon=True).start()
