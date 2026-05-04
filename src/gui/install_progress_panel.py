"""
Install Progress panel — overlay that shows live log output while a
background install runs (silent VC++ / .NET / d3dcompiler installs etc.).

Mounted into the plugin panel container via App._show_plugin_overlay.
The caller supplies a worker callable ``worker(log_fn) -> bool``; the
panel runs it in a daemon thread and streams output into a textbox.
"""

from __future__ import annotations

import threading
from typing import Callable

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
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_ON_ACCENT,
)


class InstallProgressPanel(ctk.CTkFrame):
    """Overlay frame that runs *worker* in a background thread and shows its log."""

    def __init__(
        self,
        parent,
        title: str,
        worker: Callable[[Callable[[str], None]], bool],
        log_fn: Callable[[str], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._title = title
        self._worker = worker
        self._external_log = log_fn or (lambda _msg: None)
        self._on_close_cb = on_close or (lambda: None)
        self._finished = False

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_propagate(False)
        ctk.CTkLabel(
            title_bar, text=title,
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        self._close_btn = ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self._on_close_clicked,
        )
        self._close_btn.pack(side="right", padx=4, pady=4)

        body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 20))
        body.grid_rowconfigure(2, weight=1)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body, text="Running …",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self._status = ctk.CTkLabel(
            body, text="Starting installer …",
            font=FONT_NORMAL, text_color=TEXT_DIM, anchor="w",
            justify="left", wraplength=520,
        )
        self._status.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self._log_box = ctk.CTkTextbox(
            body, font=FONT_SMALL,
            fg_color=BG_PANEL, text_color=TEXT_MAIN,
            border_color=BORDER, border_width=1,
        )
        self._log_box.grid(row=2, column=0, sticky="nsew")
        self._log_box.configure(state="disabled")

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="e", pady=(12, 0))

        self._action_btn = ctk.CTkButton(
            btn_row, text="Close", width=120, height=34, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_close_clicked, state="disabled",
        )
        self._action_btn.pack(side="right")

        threading.Thread(target=self._run_worker, daemon=True).start()

    def _append_log(self, msg: str):
        self._external_log(msg)
        text = str(msg).rstrip("\n")
        if not text:
            return

        def _apply():
            try:
                if not self.winfo_exists():
                    return
                self._log_box.configure(state="normal")
                self._log_box.insert("end", text + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
                self._status.configure(text=text)
            except Exception:
                pass
        try:
            self.after(0, _apply)
        except Exception:
            pass

    def _run_worker(self):
        try:
            ok = bool(self._worker(self._append_log))
        except Exception as exc:
            self._append_log(f"Error: {exc}")
            ok = False
        self._finished = True

        def _apply():
            try:
                if not self.winfo_exists():
                    return
                if ok:
                    self._status.configure(
                        text="Done — you can close this panel.",
                        text_color="#6bc76b",
                    )
                else:
                    self._status.configure(
                        text="Finished with errors — see log above.",
                        text_color="#e0a83c",
                    )
                self._action_btn.configure(state="normal")
            except Exception:
                pass
        try:
            self.after(0, _apply)
        except Exception:
            pass

    def _on_close_clicked(self):
        if not self._finished:
            self._append_log("Installer is still running — please wait.")
            return
        self._on_close_cb()
