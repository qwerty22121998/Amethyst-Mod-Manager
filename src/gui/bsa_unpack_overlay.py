"""
BSA Unpack overlay — lists every .bsa in the selected mod folder and
unpacks the chosen one back into the mod folder.

Place over the plugin panel via place(relx=0, rely=0, relwidth=1, relheight=1).

The overlay is a dumb UI; the caller passes a single ``on_unpack`` callback
that does the actual work (extract → delete BSA + stub plugin → clear
exclusions → trigger filemap rebuild → refresh tab). The caller is
responsible for closing the overlay via ``on_close``.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
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
from Utils.bsa_reader import read_bsa_file_list


class BsaUnpackOverlay(tk.Frame):
    """Single-mod BSA picker.

    Shows one row per .bsa in the mod folder with size + file count, plus
    a single "Unpack" button per row. Clicking Unpack invokes
    ``on_unpack(bsa_path)`` and dismisses the overlay; the caller does
    the work and shows progress via its own popup.
    """

    def __init__(
        self,
        parent: tk.Widget,
        *,
        mod_name: str,
        mod_dir: Path,
        on_unpack: Callable[[Path], None],
        on_close: Callable[[], None],
    ):
        super().__init__(parent, bg=BG_DEEP)
        self._mod_name = mod_name
        self._mod_dir = Path(mod_dir)
        self._on_unpack = on_unpack
        self._on_close = on_close
        # Filled in by _add_row; consumed by _on_resize to keep label
        # wraplengths in sync with the overlay width.
        self._row_labels: list[tuple[tk.Label, tk.Label]] = []
        self._title_label: tk.Label | None = None
        self._hint_label: tk.Label | None = None
        self._build()

    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Toolbar — grid layout so the close button always wins horizontal
        # space.  No fixed height: when the title wraps to multiple lines
        # at narrow widths, the toolbar grows vertically to fit instead
        # of clipping.  minsize keeps it from collapsing on a single
        # short title.
        toolbar = tk.Frame(self, bg=BG_HEADER)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(1, weight=0)
        toolbar.grid_rowconfigure(0, minsize=42)

        self._title_label = tk.Label(
            toolbar, text=f"Unpack BSA — {self._mod_name}",
            font=FONT_BOLD, fg=TEXT_MAIN, bg=BG_HEADER,
            anchor="w", justify="left",
        )
        self._title_label.grid(row=0, column=0, sticky="ew", padx=12, pady=8)

        ctk.CTkButton(
            toolbar, text="✕ Close", width=85, height=30,
            fg_color="#6b3333", hover_color="#8c4444", text_color="white",
            font=FONT_BOLD, command=self._on_close,
        ).grid(row=0, column=1, sticky="ne", padx=(6, 12), pady=5)

        # List of BSAs
        body = tk.Frame(self, bg=BG_DEEP)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Scrollable container so a mod with many BSAs (rare but real for
        # texture-pack splits) doesn't get clipped.
        canvas = tk.Canvas(body, bg=BG_DEEP, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb = tk.Scrollbar(
            body, orient="vertical", command=canvas.yview,
            bg="#383838", troughcolor=BG_DEEP, highlightthickness=0, bd=0,
        )
        vsb.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)

        inner = tk.Frame(canvas, bg=BG_DEEP)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(inner_id, width=e.width),
        )

        bsas = self._collect_bsas()
        if not bsas:
            tk.Label(
                inner,
                text="No .bsa files in this mod folder.",
                font=FONT_NORMAL, fg=TEXT_DIM, bg=BG_DEEP,
            ).pack(anchor="w", padx=12, pady=12)
        else:
            for path, size, file_count in bsas:
                self._add_row(inner, path, size, file_count)

        # Hint line — wraplength tracks the overlay width so it never
        # pushes content off-screen at narrow window sizes.
        self._hint_label = tk.Label(
            self,
            text=(
                "Unpacking will extract the archive into this mod's folder, "
                "delete the .bsa, remove its same-named generated stub plugin, "
                "and re-enable the unpacked files in the Mod Files tab."
            ),
            font=FONT_SMALL, fg=TEXT_DIM, bg=BG_DEEP, anchor="w",
            justify="left",
        )
        self._hint_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

        # Update wraplengths whenever the overlay resizes.  Pad allowance
        # of 32px accounts for grid padx on each side (12+12) plus a
        # safety margin for the scrollbar gutter.
        self.bind("<Configure>", self._on_resize)

        self.bind("<Escape>", lambda e: self._on_close())
        self.focus_set()

    # ------------------------------------------------------------------

    def _collect_bsas(self) -> list[tuple[Path, int, int]]:
        """Return [(bsa_path, size_bytes, file_count_in_archive), ...]
        for every .bsa in the mod folder, sorted by name."""
        rows: list[tuple[Path, int, int]] = []
        try:
            entries = sorted(self._mod_dir.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return rows
        for p in entries:
            if not p.is_file() or p.suffix.lower() != ".bsa":
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            # File count is informational; if the parser can't read the
            # archive we still want to list it (the user might want to
            # try unpacking an unfamiliar BSA — and the extractor gives a
            # clearer error than the reader).
            try:
                file_count = len(read_bsa_file_list(p))
            except Exception:
                file_count = -1
            rows.append((p, size, file_count))
        return rows

    # ------------------------------------------------------------------

    def _add_row(self, parent: tk.Widget, path: Path, size: int, file_count: int) -> None:
        # Grid layout so the Unpack button stays anchored in column 1
        # at a fixed minsize, while the info column (0) takes the rest
        # and lets its labels wrap/clip without pushing the button off.
        row = tk.Frame(parent, bg=BG_PANEL, highlightthickness=1,
                       highlightbackground=BORDER)
        row.pack(fill="x", padx=2, pady=4)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0, minsize=130)

        info = tk.Frame(row, bg=BG_PANEL)
        info.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        info.grid_columnconfigure(0, weight=1)

        name_lbl = tk.Label(
            info, text=path.name,
            font=FONT_BOLD, fg=TEXT_MAIN, bg=BG_PANEL,
            anchor="w", justify="left",
        )
        name_lbl.grid(row=0, column=0, sticky="ew")

        size_mb = size / (1024 * 1024)
        if file_count >= 0:
            sub = f"{file_count} file(s) — {size_mb:.1f} MiB"
        else:
            sub = f"unreadable — {size_mb:.1f} MiB"
        sub_lbl = tk.Label(
            info, text=sub,
            font=FONT_SMALL, fg=TEXT_DIM, bg=BG_PANEL,
            anchor="w", justify="left",
        )
        sub_lbl.grid(row=1, column=0, sticky="ew")

        # Track row labels so we can update their wraplengths on resize.
        self._row_labels.append((name_lbl, sub_lbl))

        ctk.CTkButton(
            row, text="Unpack", width=110, height=32,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            text_color=TEXT_ON_ACCENT,
            command=lambda p=path: self._handle_unpack(p),
            state="normal" if file_count != 0 else "disabled",
        ).grid(row=0, column=1, sticky="e", padx=10, pady=8)

    def _handle_unpack(self, path: Path) -> None:
        # Hand off to the caller — the overlay's job ends here. Caller is
        # expected to close us via on_close once it has a progress popup
        # in flight (or to leave us up if it cancels its own confirm).
        self._on_unpack(path)

    # ------------------------------------------------------------------

    def _on_resize(self, event: tk.Event) -> None:
        """Keep label wraplengths in sync with the overlay width so text
        never pushes the Unpack / Close buttons off the right edge.

        Filtering on ``event.widget is self`` avoids reacting to every
        descendant <Configure> event."""
        if event.widget is not self:
            return

        overlay_w = max(event.width, 1)

        # Hint line — full width minus outer padding.
        if self._hint_label is not None:
            self._hint_label.configure(wraplength=max(overlay_w - 32, 100))

        # Title — toolbar minus the close button column (~110px) and padx.
        if self._title_label is not None:
            self._title_label.configure(
                wraplength=max(overlay_w - 130, 80),
            )

        # Per-row info labels — overlay minus button column (130 minsize),
        # row internal padding (~30), and outer body padx (~24) and the
        # scrollbar gutter (~16).  Floor at 100px so labels don't collapse.
        row_wrap = max(overlay_w - 200, 100)
        for name_lbl, sub_lbl in self._row_labels:
            name_lbl.configure(wraplength=row_wrap)
            sub_lbl.configure(wraplength=row_wrap)
