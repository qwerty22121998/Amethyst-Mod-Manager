"""
Path and file-picker utilities for the GUI.
Used by TopBar and dialogs (e.g. ExeConfigDialog). No dependency on other gui modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from Utils.portal_filechooser import pick_file, pick_files


def _to_wine_path(linux_path: Path | str, prefix: Path | None = None) -> str:
    r"""Convert a Linux absolute path to a Proton/Wine Z:\ path.

    If *prefix* is the Wine pfx directory (containing dosdevices/), the Z:
    symlink target is resolved first.  This handles prefixes where Z: points
    to a UUID mount (e.g. /mnt/c3edc2f9-.../`) rather than / — without this,
    paths on that drive would be double-prefixed (Z:\mnt\uuid\...).
    """
    if prefix is not None:
        z_link = Path(prefix) / "dosdevices" / "z:"
        if z_link.is_symlink():
            z_target = z_link.resolve()
            try:
                rel = Path(linux_path).resolve().relative_to(z_target)
                return "Z:\\" + str(rel).replace("/", "\\")
            except ValueError:
                pass
    return "Z:" + str(linux_path).replace("/", "\\")


def pick_file_mod_archive(title: str, callback: Callable[[str], None]) -> None:
    """
    Open a native file picker (XDG portal or zenity) for mod archives.
    Runs async; callback(path: str) is invoked with the chosen path or ''.
    Caller should schedule callback on main thread for Tkinter, e.g.:
        pick_file_mod_archive(title, lambda p: self.after(0, lambda: self._on_picked(p)))
    """
    def _cb(p: Path | None) -> None:
        callback(str(p) if p else "")

    pick_file(title, _cb)


def pick_files_mod_archive(title: str, callback: Callable[[list[str]], None]) -> None:
    """
    Open a native multi-file picker (XDG portal or zenity) for mod archives.
    Runs async; callback(paths: list[str]) is invoked with the chosen paths (empty on cancel).
    Caller should schedule callback on main thread for Tkinter, e.g.:
        pick_files_mod_archive(title, lambda ps: self.after(0, lambda: self._on_picked(ps)))
    """
    def _cb(ps: list) -> None:
        callback([str(p) for p in ps])

    pick_files(title, _cb)
