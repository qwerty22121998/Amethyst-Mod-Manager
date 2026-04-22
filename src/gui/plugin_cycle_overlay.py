"""
Plugin Cycle overlay — view and resolve a broken cycle in userlist.yaml.

Shown when the user right-clicks a plugin with a red userlist dot and picks
'Show cycle...'. Once open, the overlay is pinned to the set of plugins that
formed the cycle at open time. Each plugin rule connecting any two of those
plugins gets a Before/After flip button so the user can iteratively resolve
(and, if needed, revert) the cycle in-place. Group rules are informational.

A status banner at the top turns red while a cycle is still present among the
pinned plugins and green once it has been resolved.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

import gui.theme as _theme
from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT
from gui.theme import (
    ACCENT,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_PANEL,
    BG_ROW,
    BG_ROW_ALT,
    BORDER,
    FONT_BOLD,
    FONT_FAMILY,
    FONT_SMALL,
    font_sized_px,
    TEXT_DIM,
    TEXT_MAIN,
)


STATUS_BROKEN_BG = "#6b3333"
STATUS_BROKEN_FG = "#ffd9d9"
STATUS_OK_BG = "#2f5d3a"
STATUS_OK_FG = "#dcf5dc"

# Background for rule rows whose flip (on its own) would resolve every cycle
# currently present in the scope. Chosen to read as a warm highlight against
# the normal BG_ROW / BG_ROW_ALT palette without mimicking the red error tone.
FIXABLE_ROW_BG = "#4a4320"
FIXABLE_ROW_FG = "#f5e28a"

# Per-keyword colors so "before" and "after" read as opposites at a glance.
BEFORE_FG = "#e89862"
AFTER_FG = "#62b0e8"


class PluginCycleOverlay(tk.Frame):
    """
    Overlay describing one userlist.yaml cycle, with Flip actions for plugin
    rules so the user can iteratively resolve (or revert) the cycle in place.
    """

    def __init__(
        self,
        parent: tk.Widget,
        starting_plugin: str,
        on_close: Optional[Callable[[], None]] = None,
        on_flip: Optional[Callable[[str, str, str], None]] = None,
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._starting = starting_plugin
        self._on_close = on_close
        self._on_flip = on_flip

        # Populated by update_cycle(); default to empty state so _build works
        # before data arrives.
        self._plugins: list[str] = []
        self._edges: dict[tuple[str, str], list[dict]] = {}
        self._cyclic_edges: set[tuple[str, str]] = set()
        self._fixable_reasons: set[tuple[str, str, str]] = set()
        self._display: dict[str, str] = {}
        self._is_broken: bool = True

        self._build()

    # ------------------------------------------------------------------
    # Data updates
    # ------------------------------------------------------------------

    def update_cycle(
        self,
        starting_plugin: str,
        scope_plugins: frozenset[str],
        scope_edges: dict[tuple[str, str], list[dict]],
        cyclic_edges: set[tuple[str, str]],
        fixable_reasons: set[tuple[str, str, str]],
        display_names: dict[str, str],
        is_broken: bool,
    ) -> None:
        """Replace the overlay's data and repaint.

        `scope_plugins`    — plugins pinned to this overlay (the original SCC).
        `scope_edges`      — every rule between scope plugins (cyclic or not).
        `cyclic_edges`     — subset of scope_edges whose endpoints are still in
                             the same SCC right now.
        `fixable_reasons`  — set of reason ids (owner_lower, field, target_lower)
                             whose single flip would resolve every current cycle.
        `is_broken`        — True if the scope currently contains any cycle.
        """
        self._starting = starting_plugin
        self._plugins = sorted(scope_plugins)
        self._edges = scope_edges
        self._cyclic_edges = cyclic_edges
        self._fixable_reasons = fixable_reasons
        self._display = display_names
        self._is_broken = is_broken
        self._repaint_title()
        self._repaint_status()
        self._repaint_plugins()
        self._repaint_rules()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _disp(self, name_lower: str) -> str:
        return self._display.get(name_lower, name_lower)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        toolbar = tk.Frame(self, bg=BG_HEADER, height=42)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        self._title_label = tk.Label(
            toolbar, text="", font=FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
        )
        self._title_label.pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            toolbar, text="✕ Close", width=85, height=30,
            fg_color="#6b3333", hover_color="#8c4444", text_color="white",
            font=FONT_BOLD, command=self._do_close,
        ).pack(side="right", padx=(6, 12), pady=5)

        # Status banner — red while broken, green when resolved.
        self._status_frame = tk.Frame(self, bg=STATUS_BROKEN_BG)
        self._status_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        self._status_label = tk.Label(
            self._status_frame, text="", font=FONT_BOLD,
            fg=STATUS_BROKEN_FG, bg=STATUS_BROKEN_BG, anchor="w",
        )
        self._status_label.pack(fill="x", padx=12, pady=8)

        body = tk.Frame(self, bg=BG_DEEP)
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(2, weight=2)
        body.grid_rowconfigure(0, weight=1)

        tk.Frame(body, bg=BORDER, width=1).grid(row=0, column=1, sticky="ns", padx=8)

        self._build_plugins_panel(body)
        self._build_rules_panel(body)

        self._repaint_title()
        self._repaint_status()

    def _build_plugins_panel(self, body: tk.Frame):
        left = tk.Frame(body, bg=BG_DEEP)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        tk.Label(
            left, text="Plugins in cycle", font=FONT_BOLD,
            fg=TEXT_MAIN, bg=BG_DEEP, anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        list_frame = tk.Frame(left, bg=BG_PANEL, highlightthickness=1,
                              highlightbackground=BORDER)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._plugins_listbox = tk.Listbox(
            list_frame,
            bg=BG_PANEL, fg=TEXT_MAIN, selectbackground=ACCENT,
            selectforeground="white", activestyle="none",
            relief="flat", bd=0, highlightthickness=0,
            font=font_sized_px(FONT_FAMILY, 11),
            exportselection=False,
        )
        vsb = tk.Scrollbar(list_frame, orient="vertical",
                           command=self._plugins_listbox.yview,
                           bg=_theme.BG_SEP, troughcolor=BG_DEEP,
                           activebackground=ACCENT, highlightthickness=0, bd=0)
        self._plugins_listbox.configure(yscrollcommand=vsb.set)
        self._plugins_listbox.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        if not LEGACY_WHEEL_REDUNDANT:
            self._plugins_listbox.bind(
                "<Button-4>",
                lambda e: self._plugins_listbox.yview_scroll(-3, "units"),
            )
            self._plugins_listbox.bind(
                "<Button-5>",
                lambda e: self._plugins_listbox.yview_scroll(3, "units"),
            )

    def _build_rules_panel(self, body: tk.Frame):
        right = tk.Frame(body, bg=BG_DEEP)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        tk.Label(
            right, text="Rules between these plugins", font=FONT_BOLD,
            fg=TEXT_MAIN, bg=BG_DEEP, anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        outer = tk.Frame(right, bg=BG_PANEL, highlightthickness=1,
                         highlightbackground=BORDER)
        outer.grid(row=1, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self._rules_canvas = tk.Canvas(
            outer, bg=BG_PANEL, bd=0, highlightthickness=0, yscrollincrement=1,
        )
        rules_vsb = tk.Scrollbar(
            outer, orient="vertical", command=self._rules_canvas.yview,
            bg=_theme.BG_SEP, troughcolor=BG_DEEP,
            activebackground=ACCENT, highlightthickness=0, bd=0,
        )
        self._rules_canvas.configure(yscrollcommand=rules_vsb.set)
        self._rules_canvas.grid(row=0, column=0, sticky="nsew")
        rules_vsb.grid(row=0, column=1, sticky="ns")
        if not LEGACY_WHEEL_REDUNDANT:
            self._rules_canvas.bind(
                "<Button-4>",
                lambda e: self._rules_canvas.yview_scroll(-3, "units"),
            )
            self._rules_canvas.bind(
                "<Button-5>",
                lambda e: self._rules_canvas.yview_scroll(3, "units"),
            )

        self._rules_inner = tk.Frame(self._rules_canvas, bg=BG_PANEL)
        self._rules_inner_id = self._rules_canvas.create_window(
            (0, 0), window=self._rules_inner, anchor="nw",
        )

        def _on_inner_cfg(_e):
            self._rules_canvas.configure(scrollregion=self._rules_canvas.bbox("all"))

        def _on_canvas_cfg(e):
            self._rules_canvas.itemconfigure(self._rules_inner_id, width=e.width)

        self._rules_inner.bind("<Configure>", _on_inner_cfg)
        self._rules_canvas.bind("<Configure>", _on_canvas_cfg)

    # ------------------------------------------------------------------
    # Repaint
    # ------------------------------------------------------------------

    def _repaint_title(self):
        n = len(self._plugins)
        self._title_label.configure(
            text=f"Userlist rules ({n} plugin{'s' if n != 1 else ''}) — anchor: {self._starting}"
        )

    def _repaint_status(self):
        if self._is_broken:
            bg, fg = STATUS_BROKEN_BG, STATUS_BROKEN_FG
            text = "Status: BROKEN — these plugins still form a cycle."
        else:
            bg, fg = STATUS_OK_BG, STATUS_OK_FG
            text = "Status: OK — no cycle among these plugins."
        self._status_frame.configure(bg=bg)
        self._status_label.configure(text=text, fg=fg, bg=bg)

    def _repaint_plugins(self):
        self._plugins_listbox.delete(0, tk.END)
        for p in self._plugins:
            self._plugins_listbox.insert(tk.END, self._disp(p))

    def _repaint_rules(self):
        for w in self._rules_inner.winfo_children():
            w.destroy()

        # Flatten: one row per reason (not one row per edge). Each rule is a
        # single line showing the rule text + a flip/info control on the right.
        flat: list[tuple[tuple[str, str], dict]] = []
        for edge, reasons in self._edges.items():
            for reason in reasons:
                flat.append((edge, reason))
        flat.sort(key=lambda it: (
            self._disp(it[0][0]).lower(),
            self._disp(it[0][1]).lower(),
            0 if it[1].get("kind") == "plugin" else 1,
        ))

        if not flat:
            tk.Label(
                self._rules_inner,
                text="No rules between these plugins.",
                font=FONT_SMALL, fg=TEXT_DIM, bg=BG_PANEL, justify="left",
            ).pack(padx=12, pady=12)
            return

        for i, (edge, reason) in enumerate(flat):
            rid = reason.get("id")
            fixable = rid is not None and rid in self._fixable_reasons
            if fixable:
                row_bg = FIXABLE_ROW_BG
                text_fg = FIXABLE_ROW_FG
            else:
                row_bg = BG_ROW if i % 2 == 0 else BG_ROW_ALT
                text_fg = TEXT_MAIN

            row = tk.Frame(self._rules_inner, bg=row_bg)
            row.pack(fill="x")

            line = tk.Frame(row, bg=row_bg)
            line.pack(fill="x", padx=10, pady=6)
            line.grid_columnconfigure(0, weight=1)

            tokens = tk.Frame(line, bg=row_bg)
            tokens.grid(row=0, column=0, sticky="w")

            self._build_rule_tokens(tokens, row_bg, text_fg, reason)

            flip_cb = self._on_flip
            if reason.get("kind") == "plugin" and flip_cb is not None:
                owner = reason.get("owner", "")
                field = reason.get("field", "")
                target = reason.get("target", "")
                if owner and target and field in ("after", "before"):
                    ctk.CTkButton(
                        line, text="Flip rule", width=90, height=22,
                        fg_color=BG_HEADER, hover_color=BG_HOVER,
                        text_color=FIXABLE_ROW_FG if fixable else ACCENT,
                        font=FONT_SMALL,
                        command=lambda o=owner, f=field, t=target, cb=flip_cb: cb(o, f, t),
                    ).grid(row=0, column=1, padx=(6, 0), sticky="e")
            elif reason.get("kind") == "group":
                tk.Label(
                    line, text="(group rule — edit via Groups overlay)",
                    font=FONT_SMALL, fg=TEXT_DIM, bg=row_bg,
                ).grid(row=0, column=1, padx=(6, 0), sticky="e")

    def _build_rule_tokens(self, parent: tk.Frame, row_bg: str, text_fg: str,
                            reason: dict) -> None:
        """Render a rule as inline tokens so 'before' and 'after' can be
        colored distinctly. Falls back to the plain text for anything we
        don't recognise."""
        kind = reason.get("kind")
        if kind == "plugin":
            owner = reason.get("owner", "")
            field = reason.get("field", "")
            target = reason.get("target", "")
            if owner and target and field in ("after", "before"):
                kw_fg = AFTER_FG if field == "after" else BEFORE_FG
                tk.Label(
                    parent, text=owner, font=FONT_SMALL,
                    fg=text_fg, bg=row_bg, anchor="w",
                ).pack(side="left")
                tk.Label(
                    parent, text=f"  {field}  ",
                    font=(FONT_FAMILY, FONT_SMALL[1], "bold"),
                    fg=kw_fg, bg=row_bg, anchor="w",
                ).pack(side="left")
                tk.Label(
                    parent, text=target, font=FONT_SMALL,
                    fg=text_fg, bg=row_bg, anchor="w",
                ).pack(side="left")
                return
        if kind == "group":
            # Group-rule text mentions "after" once; highlight that keyword too.
            text = reason.get("text", "")
            # Format: "group rule: 'G1' after 'G2' (...)". Split on the first
            # " after " so we can color it.
            marker = " after "
            if marker in text:
                left, right = text.split(marker, 1)
                tk.Label(
                    parent, text=left, font=FONT_SMALL,
                    fg=TEXT_DIM, bg=row_bg, anchor="w",
                ).pack(side="left")
                tk.Label(
                    parent, text="after",
                    font=(FONT_FAMILY, FONT_SMALL[1], "bold"),
                    fg=AFTER_FG, bg=row_bg, anchor="w",
                ).pack(side="left", padx=(4, 4))
                tk.Label(
                    parent, text=right, font=FONT_SMALL,
                    fg=TEXT_DIM, bg=row_bg, anchor="w",
                ).pack(side="left")
                return
        # Fallback — flat text.
        tk.Label(
            parent, text=reason.get("text", ""), font=FONT_SMALL,
            fg=text_fg, bg=row_bg, anchor="w", justify="left",
        ).pack(side="left")

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _do_close(self):
        if self._on_close:
            self._on_close()
        self.destroy()
