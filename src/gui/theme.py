"""
Shared theme constants and icon loader for the GUI.
Used by gui.py and all gui submodules.
"""

from pathlib import Path

import customtkinter as ctk
from PIL import Image as PilImage

from Utils.ui_config import (
    get_ui_scale, get_font_family, load_font_family,
    load_theme_colors, get_theme_color, get_appearance_mode,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
# The app ships two palettes: "dark" (default) and "light". The mode is read
# from amethyst.ini at import time; switching requires an app restart.
#
# Every constant below exists in both palettes. New additions: define in both
# _PALETTE_DARK and _PALETTE_LIGHT, then re-export via _bind_palette().

_PALETTE_DARK: dict[str, str | tuple] = {
    # Backgrounds
    "BG_DEEP":       "#1a1a1a",
    "BG_PANEL":      "#252526",
    "BG_HEADER":     "#2a2a2b",
    "BG_ROW":        "#2d2d2d",
    "BG_ROW_ALT":    "#303030",
    "BG_ROW_HOVER":  "#3d3d3d",
    "BG_SEP":        "#383838",   # overridden via load_theme_colors
    "BG_HOVER":      "#094771",
    "BG_SELECT":     "#0f5fa3",
    "BG_HOVER_ROW":  "#3d3d3d",

    # Accents
    "ACCENT":        "#0078d4",
    "ACCENT_HOV":    "#1084d8",

    # Text
    "TEXT_MAIN":     "#d4d4d4",
    "TEXT_DIM":      "#858585",
    "TEXT_MUTED":    "#aaaaaa",
    "TEXT_FAINT":    "#888888",
    "TEXT_SEP":      "#b0b0b0",
    "TEXT_WHITE":    "#ffffff",
    "TEXT_BLACK":    "#000000",
    "TEXT_OK":       "#98c379",
    "TEXT_ERR":      "#e06c75",
    "TEXT_WARN":     "#e5c07b",
    "TEXT_OK_BRIGHT":   "#6bc76b",
    "TEXT_ERR_BRIGHT":  "#e06c6c",
    "TEXT_WARN_BRIGHT": "#e5a04a",

    # Borders
    "BORDER":        "#444444",
    "BORDER_DIM":    "#555555",
    "BORDER_FAINT":  "#666666",

    # Buttons — reds
    "RED_BTN":       "#a83232",
    "RED_HOV":       "#c43c3c",
    "BTN_DANGER":        "#b33a3a",
    "BTN_DANGER_HOV":    "#c94848",
    "BTN_DANGER_ALT":    "#8b1a1a",
    "BTN_DANGER_ALT_HOV":"#b22222",
    "BTN_DANGER_DEEP":   "#7a1a1a",
    "BTN_DANGER_DEEP_HOV":"#a02020",
    "BTN_CANCEL":        "#c0392b",
    "BTN_CANCEL_HOV":    "#a93226",

    # Buttons — greens
    "BTN_SUCCESS":          "#2d7a2d",
    "BTN_SUCCESS_HOV":      "#3a9e3a",
    "BTN_SUCCESS_ALT":      "#2e6b30",
    "BTN_SUCCESS_ALT_HOV":  "#3a8a3d",
    "BTN_SUCCESS_DEEP":     "#2a6e3f",
    "BTN_SUCCESS_DEEP_HOV": "#369150",

    # Buttons — oranges
    "BTN_WARN":          "#c37800",
    "BTN_WARN_HOV":      "#e28b00",
    "BTN_WARN_DEEP":     "#7a5a00",
    "BTN_WARN_DEEP_HOV": "#a07800",
    "BTN_WARN_BROWN":    "#5a3a00",
    "BTN_WARN_BROWN_HOV":"#7a5200",
    "BTN_WARN_ORANGE":   "#b35a00",
    "BTN_WARN_ORANGE_HOV":"#d97000",

    # Buttons — blues
    "BTN_INFO":          "#1e4d7a",
    "BTN_INFO_HOV":      "#2a6aab",
    "BTN_INFO_DEEP":     "#1a5a8a",
    "BTN_INFO_DEEP_HOV": "#2070a8",
    "BTN_NEUTRAL":       "#3a5a8a",
    "BTN_NEUTRAL_HOV":   "#4a70aa",

    # Buttons — greys
    "BTN_GREY":        "#444444",
    "BTN_GREY_HOV":    "#555555",
    "BTN_GREY_ALT":    "#3c3c3c",
    "BTN_GREY_ALT_HOV":"#505050",

    # Buttons — purples
    "BTN_PURPLE":     "#7b2fa8",
    "BTN_PURPLE_HOV": "#9b3fd0",

    # Tree tags
    "TAG_FOLDER":       "#56b6c2",
    "TAG_BSA":          "#d8a657",
    "TAG_BSA_ALT":      "#56d8e4",
    "TAG_INI_PROFILE":  "#00e5ff",
    "TAG_BUNDLED_FG":   "#7ab8e8",
    "TAG_BUNDLED_BG":   "#1a2a3a",
    "TAG_INSTALLED_BG": "#1e4d1e",
    "TAG_UNORDERED_FG": "#888888",

    # Tones
    "TONE_GREEN":     "#98c379",
    "TONE_RED":       "#e06c75",
    "TONE_BLUE":      "#61afef",
    "TONE_CYAN":      "#7ec8e3",
    "TONE_BLUE_SOFT": "#7aa2f7",
    "TONE_FLAG":      "#e5c07b",

    # Scrollbars
    "SCROLL_BG":     "#383838",
    "SCROLL_TROUGH": "#1a1a1a",
    "SCROLL_ACTIVE": "#0078d4",

    # Overlays / special
    "BG_OVERLAY_ERR":  "#1a1a2e",
    "BG_OVERLAY_DEEP": "#1a1a1a",
    "BG_CARD":         "#333333",
    "BG_CARD_ALT":     "#2b2b2b",
    "BG_GREEN_ROW":    "#1a5c1a",
    "BG_GREEN_DEEP":   "#1b4d1b",
    "BG_RED_DEEP":     "#4d1b1b",
    "BG_GREEN_TEXT":   "#c8ffc8",
    "BG_RED_TEXT":     "#ffc8c8",
    "BG_DARK_BLUE":    "#1e1e2e",
    "BG_DARK_GREEN":   "#1e2a1e",
    "BG_ENTRY":        "#1e1e1e",
    "BG_BTN_SAVE":     "#4a4a8a",
    "BG_SELECT_BAR":   "#3a3a5a",
    "BG_MOD_REQ":      "#2d7a2d",
    "BG_MOD_OPT":      "#c37800",

    # Status
    "STATUS_ERR_BRIGHT":    "#ff6b6b",
    "STATUS_BADGE_RED":     "#e74c3c",
    "STATUS_BADGE_GREEN":   "#2a8c2a",
    "STATUS_SUCCESS_SOLID": "#00ff88",
    "STATUS_QUEUED":        "#ff9a3c",
    "STATUS_DL_GREEN":      "#4caf50",

    # Card text
    "TEXT_CARD":     "#cccccc",
    "TEXT_CARD_DIM": "#777777",
    "TEXT_CARD_MED": "#dddddd",
    "TEXT_TREE_FG":  "#6dbf6d",

    # CTk light/dark tuples — CustomTkinter picks one based on appearance mode.
    # These stay as tuples in both palettes so built-in CTk widgets work either way.
    "CTK_TEXT":       ("#000000", "#FFFFFF"),
    "CTK_FOOTER_FG":  ("#EBECF0", "#393B40"),
    "CTK_FOOTER_HOV": ("#DFE1E5", "#43454A"),
    "CTK_SEP":        ("#C9CCD6", "#5A5D63"),
    "CTK_SEP_ALT":    ("#D0D0D0", "#505050"),
    "CTK_BTN_HOVER":  ("gray90", "gray25"),

    # Misc
    "LINK_BLUE":     "#3574F0",
}

_PALETTE_LIGHT: dict[str, str | tuple] = {
    # Backgrounds — near-white bases with enough separation that gutter,
    # alternating panels, and alternating rows are each readable. Aim for
    # ~15-unit steps between layers so stacked surfaces don't merge.
    "BG_DEEP":       "#9c9c9c",   # app gutter / outer scroll bg
    "BG_PANEL":      "#e0e0e0",   # panel A / primary surface (grey so white inputs on it contrast)
    "BG_HEADER":     "#b4b4b4",   # panel B / column headers / button-on-panel
    "BG_ROW":        "#ffffff",   # list row / textbox fill
    "BG_ROW_ALT":    "#d8d8d8",   # alternating row (~40-unit delta for non-OLED panels)
    "BG_ROW_HOVER":  "#b8b8b8",
    "BG_SEP":        "#b8b8b8",
    "BG_HOVER":      "#b8d4f0",
    "BG_SELECT":     "#8cbde8",
    "BG_HOVER_ROW":  "#b8b8b8",

    # Accents — keep the same blue (works in both modes)
    "ACCENT":        "#0078d4",
    "ACCENT_HOV":    "#1084d8",

    # Text — dark on light
    "TEXT_MAIN":     "#1e1e1e",
    "TEXT_DIM":      "#555555",
    "TEXT_MUTED":    "#6b6b6b",
    "TEXT_FAINT":    "#8a8a8a",
    "TEXT_SEP":      "#404040",
    "TEXT_WHITE":    "#ffffff",
    "TEXT_BLACK":    "#000000",
    "TEXT_OK":       "#2e7a2e",
    "TEXT_ERR":      "#b02020",
    "TEXT_WARN":     "#a06a00",
    "TEXT_OK_BRIGHT":   "#2e7a2e",
    "TEXT_ERR_BRIGHT":  "#b02020",
    "TEXT_WARN_BRIGHT": "#a06a00",

    # Borders — visible greys (need enough contrast against BG_PANEL #f3f3f3
    # for 1px divider lines to read on non-OLED monitors).
    "BORDER":        "#8a8a8a",
    "BORDER_DIM":    "#9a9a9a",
    "BORDER_FAINT":  "#a8a8a8",

    # Buttons — reds (slightly darker so text reads on lighter bg)
    "RED_BTN":       "#c43c3c",
    "RED_HOV":       "#d44848",
    "BTN_DANGER":        "#c94848",
    "BTN_DANGER_HOV":    "#b33a3a",
    "BTN_DANGER_ALT":    "#a83232",
    "BTN_DANGER_ALT_HOV":"#8b1a1a",
    "BTN_DANGER_DEEP":   "#8b1a1a",
    "BTN_DANGER_DEEP_HOV":"#7a1a1a",
    "BTN_CANCEL":        "#c0392b",
    "BTN_CANCEL_HOV":    "#a93226",

    # Buttons — greens
    "BTN_SUCCESS":          "#3a9e3a",
    "BTN_SUCCESS_HOV":      "#2d7a2d",
    "BTN_SUCCESS_ALT":      "#3a8a3d",
    "BTN_SUCCESS_ALT_HOV":  "#2e6b30",
    "BTN_SUCCESS_DEEP":     "#369150",
    "BTN_SUCCESS_DEEP_HOV": "#2a6e3f",

    # Buttons — oranges
    "BTN_WARN":          "#e28b00",
    "BTN_WARN_HOV":      "#c37800",
    "BTN_WARN_DEEP":     "#a07800",
    "BTN_WARN_DEEP_HOV": "#7a5a00",
    "BTN_WARN_BROWN":    "#7a5200",
    "BTN_WARN_BROWN_HOV":"#5a3a00",
    "BTN_WARN_ORANGE":   "#d97000",
    "BTN_WARN_ORANGE_HOV":"#b35a00",

    # Buttons — blues
    "BTN_INFO":          "#2a6aab",
    "BTN_INFO_HOV":      "#1e4d7a",
    "BTN_INFO_DEEP":     "#2070a8",
    "BTN_INFO_DEEP_HOV": "#1a5a8a",
    "BTN_NEUTRAL":       "#4a70aa",
    "BTN_NEUTRAL_HOV":   "#3a5a8a",

    # Buttons — greys
    "BTN_GREY":        "#c8c8c8",
    "BTN_GREY_HOV":    "#b8b8b8",
    "BTN_GREY_ALT":    "#d4d4d4",
    "BTN_GREY_ALT_HOV":"#c0c0c0",

    # Buttons — purples
    "BTN_PURPLE":     "#9b3fd0",
    "BTN_PURPLE_HOV": "#7b2fa8",

    # Tree tags — darker saturations that read on light bg
    "TAG_FOLDER":       "#1e7a8a",
    "TAG_BSA":          "#8a6a00",
    "TAG_BSA_ALT":      "#1e7a8a",
    "TAG_INI_PROFILE":  "#006a80",
    "TAG_BUNDLED_FG":   "#1a5c8a",
    "TAG_BUNDLED_BG":   "#d8e4f0",
    "TAG_INSTALLED_BG": "#d0e8d0",
    "TAG_UNORDERED_FG": "#888888",

    # Tones
    "TONE_GREEN":     "#2e7a2e",
    "TONE_RED":       "#b02020",
    "TONE_BLUE":      "#1e5a8a",
    "TONE_CYAN":      "#1e7a8a",
    "TONE_BLUE_SOFT": "#3a5a9a",
    "TONE_FLAG":      "#a06a00",

    # Scrollbars
    "SCROLL_BG":     "#c8c8c8",
    "SCROLL_TROUGH": "#e8e8e8",
    "SCROLL_ACTIVE": "#0078d4",

    # Overlays / special
    "BG_OVERLAY_ERR":  "#f8e0e0",
    "BG_OVERLAY_DEEP": "#e8e8e8",
    "BG_CARD":         "#ffffff",
    "BG_CARD_ALT":     "#f5f5f5",
    "BG_GREEN_ROW":    "#d0e8d0",
    "BG_GREEN_DEEP":   "#c8e0c8",
    "BG_RED_DEEP":     "#f0d0d0",
    "BG_GREEN_TEXT":   "#1a4d1a",
    "BG_RED_TEXT":     "#6b1a1a",
    "BG_DARK_BLUE":    "#dce4f0",
    "BG_DARK_GREEN":   "#dcebdc",
    "BG_ENTRY":        "#ffffff",
    "BG_BTN_SAVE":     "#5a5a9a",
    "BG_SELECT_BAR":   "#c0c8e0",
    "BG_MOD_REQ":      "#3a9e3a",
    "BG_MOD_OPT":      "#e28b00",

    # Status
    "STATUS_ERR_BRIGHT":    "#c42020",
    "STATUS_BADGE_RED":     "#c0392b",
    "STATUS_BADGE_GREEN":   "#2a8c2a",
    "STATUS_SUCCESS_SOLID": "#2ea74d",
    "STATUS_QUEUED":        "#c37800",
    "STATUS_DL_GREEN":      "#2e8e40",

    # Card text
    "TEXT_CARD":     "#2a2a2a",
    "TEXT_CARD_DIM": "#6a6a6a",
    "TEXT_CARD_MED": "#404040",
    "TEXT_TREE_FG":  "#2e7a2e",

    # CTk light/dark tuples — tuples stay identical across palettes.
    "CTK_TEXT":       ("#000000", "#FFFFFF"),
    "CTK_FOOTER_FG":  ("#EBECF0", "#393B40"),
    "CTK_FOOTER_HOV": ("#DFE1E5", "#43454A"),
    "CTK_SEP":        ("#C9CCD6", "#5A5D63"),
    "CTK_SEP_ALT":    ("#D0D0D0", "#505050"),
    "CTK_BTN_HOVER":  ("gray90", "gray25"),

    # Misc
    "LINK_BLUE":     "#0a5ad4",
}


def _bind_palette(mode: str) -> None:
    """Bind the selected palette's values onto this module's globals."""
    palette = _PALETTE_LIGHT if mode == "light" else _PALETTE_DARK
    globals().update(palette)


# Static name declarations so linters / IDE autocomplete can see every
# constant. The values are placeholders — _bind_palette() below overwrites
# them immediately with the real palette values.
BG_DEEP = BG_PANEL = BG_HEADER = BG_ROW = BG_ROW_ALT = BG_ROW_HOVER = ""
BG_SEP = BG_HOVER = BG_SELECT = BG_HOVER_ROW = ""
ACCENT = ACCENT_HOV = ""
TEXT_MAIN = TEXT_DIM = TEXT_MUTED = TEXT_FAINT = TEXT_SEP = ""
TEXT_WHITE = TEXT_BLACK = TEXT_OK = TEXT_ERR = TEXT_WARN = ""
TEXT_OK_BRIGHT = TEXT_ERR_BRIGHT = TEXT_WARN_BRIGHT = ""
BORDER = BORDER_DIM = BORDER_FAINT = ""
RED_BTN = RED_HOV = ""
BTN_DANGER = BTN_DANGER_HOV = BTN_DANGER_ALT = BTN_DANGER_ALT_HOV = ""
BTN_DANGER_DEEP = BTN_DANGER_DEEP_HOV = BTN_CANCEL = BTN_CANCEL_HOV = ""
BTN_SUCCESS = BTN_SUCCESS_HOV = BTN_SUCCESS_ALT = BTN_SUCCESS_ALT_HOV = ""
BTN_SUCCESS_DEEP = BTN_SUCCESS_DEEP_HOV = ""
BTN_WARN = BTN_WARN_HOV = BTN_WARN_DEEP = BTN_WARN_DEEP_HOV = ""
BTN_WARN_BROWN = BTN_WARN_BROWN_HOV = BTN_WARN_ORANGE = BTN_WARN_ORANGE_HOV = ""
BTN_INFO = BTN_INFO_HOV = BTN_INFO_DEEP = BTN_INFO_DEEP_HOV = ""
BTN_NEUTRAL = BTN_NEUTRAL_HOV = ""
BTN_GREY = BTN_GREY_HOV = BTN_GREY_ALT = BTN_GREY_ALT_HOV = ""
BTN_PURPLE = BTN_PURPLE_HOV = ""
TAG_FOLDER = TAG_BSA = TAG_BSA_ALT = TAG_INI_PROFILE = ""
TAG_BUNDLED_FG = TAG_BUNDLED_BG = TAG_INSTALLED_BG = TAG_UNORDERED_FG = ""
TONE_GREEN = TONE_RED = TONE_BLUE = TONE_CYAN = TONE_BLUE_SOFT = TONE_FLAG = ""
SCROLL_BG = SCROLL_TROUGH = SCROLL_ACTIVE = ""
BG_OVERLAY_ERR = BG_OVERLAY_DEEP = BG_CARD = BG_CARD_ALT = ""
BG_GREEN_ROW = BG_GREEN_DEEP = BG_RED_DEEP = BG_GREEN_TEXT = BG_RED_TEXT = ""
BG_DARK_BLUE = BG_DARK_GREEN = BG_ENTRY = BG_BTN_SAVE = BG_SELECT_BAR = ""
BG_MOD_REQ = BG_MOD_OPT = ""
STATUS_ERR_BRIGHT = STATUS_BADGE_RED = STATUS_BADGE_GREEN = ""
STATUS_SUCCESS_SOLID = STATUS_QUEUED = STATUS_DL_GREEN = ""
TEXT_CARD = TEXT_CARD_DIM = TEXT_CARD_MED = TEXT_TREE_FG = ""
CTK_TEXT: tuple = ("", "")
CTK_FOOTER_FG: tuple = ("", "")
CTK_FOOTER_HOV: tuple = ("", "")
CTK_SEP: tuple = ("", "")
CTK_SEP_ALT: tuple = ("", "")
CTK_BTN_HOVER: tuple = ("", "")
LINK_BLUE = ""

APPEARANCE_MODE = get_appearance_mode()
_bind_palette(APPEARANCE_MODE)

# ---------------------------------------------------------------------------
# Contrast helper
# ---------------------------------------------------------------------------
def contrasting_text_color(hex_bg: str) -> str:
    """Return '#111111' or '#eeeeee' (dark/light) based on the luminance of
    *hex_bg* (e.g. '#3a7bd5') so text always stays readable."""
    try:
        hex_bg = hex_bg.lstrip("#")
        r, g, b = (int(hex_bg[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        # Convert sRGB to linear light (WCAG 2 formula)
        def _lin(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
        # Threshold: use dark text on light backgrounds, light text on dark
        return "#111111" if lum > 0.179 else "#eeeeee"
    except Exception:
        return TEXT_SEP


def hover_tint(hex_bg: str, amount: int = 20) -> str:
    """Return a hover variant of *hex_bg* — brighter by *amount* per channel,
    or darker if brightening would clip (channel already near 255).

    When darkening a near-saturated colour, a plain ``-amount`` on one channel
    is barely perceptible (e.g. pure red #ff0000 only shifts luminance by ~8%).
    So darkening scales all channels proportionally toward black to produce a
    shift roughly comparable to the lighten case.
    """
    try:
        h = hex_bg.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # If any channel would clip when brightening, darken instead.
        if max(r, g, b) + amount > 255:
            # Scale toward black by ~15% — perceptible regardless of hue.
            factor = 0.82
            r = int(r * factor)
            g = int(g * factor)
            b = int(b * factor)
        else:
            r = min(255, r + amount)
            g = min(255, g + amount)
            b = min(255, b + amount)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_bg

# Highlight colours — user-customisable via Settings → Theme, persisted in amethyst.ini.
load_theme_colors()
plugin_separator   = get_theme_color("plugin_separator")
plugin_mod         = get_theme_color("plugin_mod")
conflict_separator = get_theme_color("conflict_separator")
conflict_higher    = get_theme_color("conflict_higher")
conflict_lower     = get_theme_color("conflict_lower")
BG_SEP             = get_theme_color("separator_bg")


def refresh_theme_colors() -> None:
    """Re-read theme colours from amethyst.ini and rebind the module globals.

    Rendering sites must use `theme.X` attribute access for values to update
    live — callers that captured names via `from gui.theme import X` will see
    their old (startup) binding only.
    """
    global plugin_separator, plugin_mod, conflict_separator, conflict_higher, conflict_lower, BG_SEP
    load_theme_colors()
    plugin_separator   = get_theme_color("plugin_separator")
    plugin_mod         = get_theme_color("plugin_mod")
    conflict_separator = get_theme_color("conflict_separator")
    conflict_higher    = get_theme_color("conflict_higher")
    conflict_lower     = get_theme_color("conflict_lower")
    BG_SEP             = get_theme_color("separator_bg")

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Font families — loaded from amethyst.ini at startup via load_font_family().
load_font_family()
FONT_FAMILY = get_font_family()
FONT_MONO_FAMILY = "Liberation Mono"

# Base sizes are tuned for Windows/SteamOS at 96 DPI (tk scaling ~1.33).
# Point sizes are scaled by ui_scale so fonts scale on HiDPI; CustomTkinter
# does not scale user-provided font tuples.
def _font_pt(base: int) -> int:
    """Return scaled point size for font tuples."""
    return max(8, round(base * get_ui_scale()))


def font_sized(name: str, base_pt: int, *styles: str) -> tuple:
    """Return a font tuple (name, size, *styles) with size scaled by ui_scale.
    Use for one-off fonts instead of hardcoding e.g. font=(FONT_FAMILY, 11)."""
    return (name, _font_pt(base_pt), *styles)


def font_sized_px(name: str, base_pt: int, *styles: str) -> tuple:
    """Return a font tuple with pixel size (negative) for tk widgets.
    Use for tk.Label/tk.Button where point sizes may not scale on Linux HiDPI."""
    return (name, _pt_to_px(base_pt), *styles)


FONT_NORMAL = (FONT_FAMILY, _font_pt(14))
FONT_BOLD   = (FONT_FAMILY, _font_pt(14), "bold")
FONT_SMALL  = (FONT_FAMILY, _font_pt(12))
FONT_MONO   = (FONT_MONO_FAMILY, _font_pt(14))
FONT_SEP    = (FONT_FAMILY, _font_pt(12), "bold")
FONT_HEADER = (FONT_FAMILY, _font_pt(12), "bold")

# Pixel sizes for tk.Label / canvas create_text / ttk.Style font= args.
# Negative values tell Tk to treat them as pixels rather than points,
# bypassing Tk's own DPI scaling (which would double-scale on HiDPI).
# The pixel count is fixed at what the design looks like at 96 DPI
# (tk scaling 1.3333): e.g. 11pt * 1.3333 ≈ 15px.
# Multiplied by get_ui_scale() for HiDPI support.
_BASELINE = 1.3333  # 96 DPI / 72 pt

def _pt_to_px(pt: int) -> int:
    """Convert a design point size to a negative-pixel size (96 DPI baseline)."""
    return -max(8, round(pt * _BASELINE * get_ui_scale()))

FS9  = _pt_to_px(9)
FS10 = _pt_to_px(10)
FS11 = _pt_to_px(11)
FS12 = _pt_to_px(12)
FS13 = _pt_to_px(13)
FS16 = _pt_to_px(16)


def init_fonts(widget) -> None:
    """Set Tk scaling to design baseline. Font scaling is done via explicit
    point sizes in FONT_* and FS* (not via tk scaling) so it works on Linux
    where CustomTkinter doesn't scale user-provided fonts.
    """
    try:
        widget.tk.call("tk", "scaling", _BASELINE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scrollbar helper — single source of truth for tk.Scrollbar styling.
# ---------------------------------------------------------------------------
def scrollbar_kwargs() -> dict:
    """Return the kwargs every tk.Scrollbar in the app uses.
    Callers: ``tk.Scrollbar(parent, orient=..., command=..., **scrollbar_kwargs())``.
    """
    return dict(
        bg=SCROLL_BG,
        troughcolor=SCROLL_TROUGH,
        activebackground=SCROLL_ACTIVE,
        highlightthickness=0,
        bd=0,
    )

# ---------------------------------------------------------------------------
# Icons (package-relative: src/gui/theme.py -> src/icons)
# ---------------------------------------------------------------------------
_ICONS_DIR = Path(__file__).resolve().parent.parent / "icons"


def load_icon(name: str, size: tuple[int, int] = (16, 16)) -> ctk.CTkImage | None:
    """Load a CTkImage from the icons directory. Returns None if file not found.

    Icon size is scaled by ui_scale for HiDPI displays.
    """
    path = _ICONS_DIR / name
    if not path.is_file():
        return None
    scale = get_ui_scale()
    scaled_size = (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
    img = PilImage.open(path).convert("RGBA")
    return ctk.CTkImage(light_image=img, dark_image=img, size=scaled_size)


def scaled(px: int | float) -> int:
    """Scale a pixel value by the current UI scale. Use for layout constants
    (row heights, paddings, icon sizes) that CustomTkinter does not scale."""
    return max(1, round(float(px) * get_ui_scale()))


def scaled_layout_minsize(base: int | float) -> int:
    """Scale a layout minsize so it preserves weight ratios at low scales.

    At 1x scale returns *base* unchanged. Below 1x uses scale² so minsize
    shrinks more aggressively and doesn't force ~50/50 when weights expect 5:4.
    Use for grid minsize in weighted layouts (e.g. plugin panel).
    """
    s = get_ui_scale()
    if s >= 1.0:
        return max(1, round(float(base) * s))
    # Below 1x: use scale² so 0.5x → base*0.25, 0.75x → base*0.56
    return max(1, round(float(base) * s * s))
