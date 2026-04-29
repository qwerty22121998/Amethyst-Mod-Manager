"""
Download progress popup mixin for ModListPanel.

Each concurrent download owns one CTkProgressPopup, tracked as a _DlSlot.
Popups stack upward from the bottom-right corner of the toplevel window.

Public API consumed by external callers (gui.py, nexus_browser_overlay.py):
- get_download_cancel_event()  → threading.Event
- show_download_progress(label, cancel=None)
- update_download_progress(current, total, label="", cancel=None)
- hide_download_progress(cancel=None)
"""

import threading

from gui.ctk_components import CTkProgressPopup
from gui.theme import scaled


class _DlSlot:
    __slots__ = ("popup", "cancel", "bind_id")

    def __init__(self, popup: CTkProgressPopup, cancel: threading.Event,
                 bind_id: str | None):
        self.popup = popup
        self.cancel = cancel
        self.bind_id = bind_id


class ModListDownloadBarMixin:
    """Adds the stacked download-popup slot system to ModListPanel."""

    def _build_download_bar(self):
        self._dl_slots: list[_DlSlot] = []
        self._dl_cancel_locked: bool = False

    def _reposition_all_dl_popups(self, *_) -> None:
        """Stack all live download popups upward from the bottom-right."""
        root = self.winfo_toplevel()
        try:
            if root.state() != "normal":
                return
        except Exception:
            pass
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        rw, rh = root.winfo_width(), root.winfo_height()
        gap = scaled(8)
        margin = scaled(20)
        y = ry + rh - margin
        for slot in self._dl_slots:
            p = slot.popup
            if not p.winfo_exists():
                continue
            pw, ph = p.winfo_width(), p.winfo_height()
            y -= ph
            x = rx + rw - pw - margin
            p.geometry(f"+{x}+{y}")
            y -= gap

    def get_download_cancel_event(self) -> threading.Event:
        """Create a new download slot with a popup; return its cancel event."""
        root = self.winfo_toplevel()
        cancel = threading.Event()
        popup = CTkProgressPopup(
            root, title="Downloading", label="Starting...", message="0%",
            on_show=self._reposition_all_dl_popups,
        )
        # CTkProgressPopup binds its own update_position to <Configure>, which
        # calls update_idletasks() twice on every event — expensive during
        # scroll. Silence it and re-bind reposition through our own handler.
        popup.update_position = lambda *_: None
        popup._configure_bid = root.bind(
            "<Configure>", self._reposition_all_dl_popups, add="+",
        )
        slot = _DlSlot(popup, cancel, None)
        self._dl_slots.append(slot)
        # Wire this popup's X button to cancel just this slot
        popup.cancel_btn.configure(command=lambda s=slot: self._cancel_dl_slot(s))
        self._reposition_all_dl_popups()
        self.after(100, self._reposition_all_dl_popups)
        return cancel

    def _cancel_dl_slot(self, slot: _DlSlot) -> None:
        if self._dl_cancel_locked:
            return
        slot.cancel.set()
        self._close_dl_slot(slot, user_cancel=True)

    def _close_dl_slot(self, slot: _DlSlot, user_cancel: bool = False) -> None:
        bid = getattr(slot.popup, "_configure_bid", None)
        if bid is not None:
            try:
                self.winfo_toplevel().unbind("<Configure>", bid)
            except Exception:
                pass
        if slot.popup.winfo_exists():
            slot.popup.destroy()
        try:
            self._dl_slots.remove(slot)
        except ValueError:
            pass

        if user_cancel and self._dl_slots:
            # Hide surviving popups and defer reposition so the mouse button
            # is released before any popup appears under the cursor.
            for s in self._dl_slots:
                if s.popup.winfo_exists():
                    s.popup.withdraw()
            self._dl_cancel_locked = True
            self.after(300, self._deferred_reshow)
        else:
            self._reposition_all_dl_popups()

    def _deferred_reshow(self) -> None:
        self._dl_cancel_locked = False
        for s in self._dl_slots:
            if s.popup.winfo_exists():
                s.popup.deiconify()
        self._reposition_all_dl_popups()

    def _slot_for_cancel(self, cancel: threading.Event) -> "_DlSlot | None":
        for slot in self._dl_slots:
            if slot.cancel is cancel:
                return slot
        return None

    def _resolve_slot(self, cancel: threading.Event | None) -> "_DlSlot | None":
        if cancel is not None:
            return self._slot_for_cancel(cancel)
        return self._dl_slots[-1] if self._dl_slots else None

    def show_download_progress(self, label: str = "Downloading...",
                               cancel: threading.Event | None = None):
        """Update the label on the popup for `cancel` (or the most recent)."""
        slot = self._resolve_slot(cancel)
        if slot and slot.popup.winfo_exists():
            slot.popup.update_label(label)
            slot.popup.update_progress(0)
            slot.popup.update_message("0%")

    def update_download_progress(self, current: int, total: int, label: str = "",
                                 cancel: threading.Event | None = None):
        """Update progress on the popup for `cancel` (or most recent)."""
        slot = self._resolve_slot(cancel)
        if slot is None or not slot.popup.winfo_exists() or total <= 0:
            return
        frac = min(current / total, 1.0)
        pct = int(frac * 100)
        _GB = 1024 * 1024 * 1024
        if total >= _GB:
            cur_u = current / _GB
            tot_u = total / _GB
            unit = "GB"
        else:
            cur_u = current / (1024 * 1024)
            tot_u = total / (1024 * 1024)
            unit = "MB"
        slot.popup.update_progress(frac)
        slot.popup.update_message(
            label if label else f"{cur_u:.2f} / {tot_u:.2f} {unit}  ({pct}%)"
        )

    def hide_download_progress(self, cancel: threading.Event | None = None):
        """Close the popup for `cancel` (or most recent). No-op if already gone."""
        slot = self._resolve_slot(cancel)
        if slot:
            self._close_dl_slot(slot)
