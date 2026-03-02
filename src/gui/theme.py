"""
Shared theme constants and icon loader for the GUI.
Used by gui.py and all gui submodules.
"""

from pathlib import Path

import customtkinter as ctk
from PIL import Image as PilImage

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
BG_DEEP    = "#1a1a1a"
BG_PANEL   = "#252526"
BG_HEADER  = "#2a2a2b"
BG_ROW     = "#2d2d2d"
BG_ROW_ALT = "#303030"
BG_SEP     = "#383838"
BG_HOVER   = "#094771"
BG_SELECT  = "#0f5fa3"
BG_HOVER_ROW = "#3d3d3d"
ACCENT     = "#0078d4"
ACCENT_HOV = "#1084d8"
TEXT_MAIN  = "#d4d4d4"
TEXT_DIM   = "#858585"
TEXT_SEP   = "#b0b0b0"
TEXT_OK    = "#98c379"
TEXT_ERR   = "#e06c75"
TEXT_WARN  = "#e5c07b"
BORDER     = "#444444"
RED_BTN    = "#a83232"
RED_HOV    = "#c43c3c"

# Highlight colours
plugin_separator = "#A45500"
plugin_mod = "#A45500"
conflict_separator = "#5A5A5A"
conflict_higher = "#108d00"
conflict_lower = "#9a0e0e"

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Base sizes are tuned for Windows/SteamOS at 96 DPI (tk scaling ~1.33).
# Call init_fonts(tk_widget) once after the root window is created to
# rescale everything if the system reports a different DPI.
FONT_NORMAL = ("Segoe UI", 14)
FONT_BOLD   = ("Segoe UI", 14, "bold")
FONT_SMALL  = ("Segoe UI", 12)
FONT_MONO   = ("Courier New", 14)
FONT_SEP    = ("Segoe UI", 12, "bold")
FONT_HEADER = ("Segoe UI", 12, "bold")

# Pre-scaled convenience sizes used by canvas/ttk widgets in panel files.
# These mirror the raw point values used throughout the codebase and are
# updated by init_fonts() to match the display DPI.
FS9  = 9
FS10 = 10
FS11 = 11
FS12 = 12
FS13 = 13
FS16 = 16


def init_fonts(widget) -> None:
    """Rescale font sizes based on the Tk scaling factor.

    Tk's scaling factor reflects the system/DE DPI setting.  We treat 1.333
    (96 DPI / 72 pt) as the baseline the font sizes were designed for.
    Higher values (e.g. 2.0 on a 4K display with 2x DE scaling) mean fonts
    would render too large, so we scale them down proportionally.
    """
    global FONT_NORMAL, FONT_BOLD, FONT_SMALL, FONT_MONO, FONT_SEP, FONT_HEADER
    global FS9, FS10, FS11, FS12, FS13, FS16

    try:
        scaling = float(widget.tk.call("tk", "scaling"))
    except Exception:
        return  # leave defaults untouched

    # 1.3333 = 96 DPI / 72 pt — the baseline the fonts were designed for
    baseline = 1.3333
    if abs(scaling - baseline) < 0.05:
        return  # close enough, no adjustment needed

    factor = baseline / scaling  # <1 when scaling > baseline (HiDPI)

    def _s(size: int) -> int:
        return max(8, round(size * factor))

    FONT_NORMAL = ("Segoe UI", _s(14))
    FONT_BOLD   = ("Segoe UI", _s(14), "bold")
    FONT_SMALL  = ("Segoe UI", _s(12))
    FONT_MONO   = ("Courier New", _s(14))
    FONT_SEP    = ("Segoe UI", _s(12), "bold")
    FONT_HEADER = ("Segoe UI", _s(12), "bold")

    FS9  = _s(9)
    FS10 = _s(10)
    FS11 = _s(11)
    FS12 = _s(12)
    FS13 = _s(13)
    FS16 = _s(16)

# ---------------------------------------------------------------------------
# Icons (package-relative: src/gui/theme.py -> src/icons)
# ---------------------------------------------------------------------------
_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"


def load_icon(name: str, size: tuple[int, int] = (16, 16)) -> ctk.CTkImage | None:
    """Load a CTkImage from the icons directory. Returns None if file not found."""
    path = _ICONS_DIR / name
    if not path.is_file():
        return None
    img = PilImage.open(path).convert("RGBA")
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)
