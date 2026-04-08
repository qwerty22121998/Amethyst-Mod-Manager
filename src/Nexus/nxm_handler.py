"""
nxm_handler.py
NXM protocol handler — parses ``nxm://`` links and registers the app
as a handler on Linux via XDG and .desktop files.

NXM link formats
----------------
    Mod download:
    nxm://<game_domain>/mods/<mod_id>/files/<file_id>?key=<key>&expires=<expires>

    Collection:
    nxm://<game_domain>/collections/<slug>
    nxm://<game_domain>/collections/<slug>/revisions/<revision_id>

Free users must click "Download with Manager" on the Nexus website;
the browser fires an ``nxm://`` URL containing a one-time key + expiry.
Premium users can generate download links directly via the API.

Usage
-----
    from Nexus.nxm_handler import NxmHandler, NxmLink

    link = NxmLink.parse("nxm://skyrimspecialedition/mods/2014/files/1234?key=abc&expires=999")
    print(link.game_domain, link.mod_id, link.file_id)

    NxmHandler.register()   # one-time setup
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from Utils.app_log import app_log

# Path for the Unix domain socket used for single-instance IPC
_SOCKET_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
_SOCKET_PATH = _SOCKET_DIR / "amethyst-mod-manager.sock"

# XDG .desktop file name used to register the handler
_DESKTOP_FILE_NAME = "amethystmodmanager-nxm.desktop"


# ---------------------------------------------------------------------------
# Parsed NXM link
# ---------------------------------------------------------------------------

@dataclass
class NxmLink:
    """
    Parsed components of an ``nxm://`` URL.

    Attributes
    ----------
    game_domain : str   e.g. "skyrimspecialedition"
    mod_id      : int   e.g. 2014
    file_id     : int   e.g. 1234
    key         : str   one-time download key (empty for premium direct calls)
    expires     : int   Unix timestamp when the key expires (0 if absent)
    raw         : str   the original URL string
    """
    game_domain: str
    mod_id: int
    file_id: int
    key: str = ""
    expires: int = 0
    raw: str = ""

    # nxm://skyrimspecialedition/mods/2014/files/1234?key=abc&expires=999
    _PATH_RE = re.compile(
        r"^/mods/(?P<mod_id>\d+)/files/(?P<file_id>\d+)",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, url: str) -> NxmLink:
        """
        Parse an ``nxm://`` URL into its components.

        Raises ValueError if the URL is malformed.
        """
        parsed = urlparse(url)

        if parsed.scheme.lower() != "nxm":
            raise ValueError(f"Not an nxm:// URL: {url!r}")

        game_domain = parsed.netloc or parsed.hostname or ""
        if not game_domain:
            raise ValueError(f"Missing game domain in NXM URL: {url!r}")

        match = cls._PATH_RE.match(parsed.path)
        if not match:
            raise ValueError(
                f"Cannot parse mod/file IDs from NXM URL path: {parsed.path!r}"
            )

        qs = parse_qs(parsed.query)
        key = qs.get("key", [""])[0]
        expires_str = qs.get("expires", ["0"])[0]
        try:
            expires = int(expires_str)
        except ValueError:
            expires = 0

        return cls(
            game_domain=game_domain.lower(),
            mod_id=int(match.group("mod_id")),
            file_id=int(match.group("file_id")),
            key=key,
            expires=expires,
            raw=url,
        )


@dataclass
class NxmCollectionLink:
    """
    Parsed components of an nxm:// collection URL.

    Attributes
    ----------
    game_domain : str   e.g. "stardewvalley"
    slug        : str   e.g. "tckf0m"
    revision_id : int   revision number (0 if absent)
    raw         : str   the original URL string
    """
    game_domain: str
    slug: str
    revision_id: int = 0
    raw: str = ""

    # nxm://stardewvalley/collections/tckf0m
    # nxm://stardewvalley/collections/tckf0m/revisions/104
    _PATH_RE = re.compile(
        r"^/collections/(?P<slug>[A-Za-z0-9_-]+)(?:/revisions/(?P<revision_id>\d+))?$",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, url: str) -> NxmCollectionLink:
        """
        Parse an nxm:// collection URL into its components.

        Raises ValueError if the URL is malformed.
        """
        parsed = urlparse(url)

        if parsed.scheme.lower() != "nxm":
            raise ValueError(f"Not an nxm:// URL: {url!r}")

        game_domain = parsed.netloc or parsed.hostname or ""
        if not game_domain:
            raise ValueError(f"Missing game domain in NXM URL: {url!r}")

        match = cls._PATH_RE.match(parsed.path)
        if not match:
            raise ValueError(
                f"Cannot parse collection slug from NXM URL path: {parsed.path!r}"
            )

        slug = match.group("slug")
        rev_str = match.group("revision_id") or "0"
        try:
            revision_id = int(rev_str)
        except ValueError:
            revision_id = 0

        return cls(
            game_domain=game_domain.lower(),
            slug=slug,
            revision_id=revision_id,
            raw=url,
        )


def parse_nxm_url(url: str) -> tuple[NxmLink | None, NxmCollectionLink | None]:
    """
    Parse an nxm:// URL as either a mod download link or a collection link.

    Returns (NxmLink, None) for mod links, (None, NxmCollectionLink) for
    collection links, or raises ValueError if neither matches.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() != "nxm":
        raise ValueError(f"Not an nxm:// URL: {url!r}")

    path = parsed.path or ""
    if "/collections/" in path.lower():
        return None, NxmCollectionLink.parse(url)
    if NxmLink._PATH_RE.match(path):
        return NxmLink.parse(url), None
    raise ValueError(f"Unknown nxm:// URL format: {url!r}")


# ---------------------------------------------------------------------------
# Protocol registration (Linux / XDG)
# ---------------------------------------------------------------------------

class NxmHandler:
    """
    Manages ``nxm://`` protocol registration on Linux.

    Calling ``NxmHandler.register()`` creates (or updates) a .desktop file
    in ``~/.local/share/applications/`` that associates ``nxm://`` URLs
    with the running AmethystModManager executable, then registers it
    with ``xdg-mime``.
    """

    @staticmethod
    def _desktop_path() -> Path:
        # Inside a Flatpak XDG_DATA_HOME is redirected to ~/.var/app/<id>/data,
        # which the host xdg-mime doesn't search.  Always write to the real
        # host location so the registration actually takes effect.
        if Path("/.flatpak-info").exists():
            return Path.home() / ".local" / "share" / "applications" / _DESKTOP_FILE_NAME
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
        return base / "applications" / _DESKTOP_FILE_NAME

    @staticmethod
    def _flatpak_desktop_path() -> Path:
        """Flatpak exports dir — visible to Flatpak-sandboxed browsers."""
        return (
            Path.home()
            / ".local" / "share" / "flatpak" / "exports" / "share"
            / "applications" / _DESKTOP_FILE_NAME
        )

    @staticmethod
    def _get_exec_command() -> str:
        """
        Build the Exec= line for the .desktop file.

        The command must be resolvable on the *host* system (where the browser
        runs), not inside the sandbox.
        """
        # Flatpak: the host can't see /app/..., so use `flatpak run <app-id>`
        flatpak_app_id = os.environ.get("FLATPAK_ID")
        if flatpak_app_id:
            return f"flatpak run {flatpak_app_id} --nxm %u"

        appimage = os.environ.get("APPIMAGE")
        if appimage:
            return f'"{appimage}" --nxm %u'

        # Running from source — use python + gui.py
        script = Path(sys.argv[0]).resolve()
        return f'"{sys.executable}" "{script}" --nxm %u'

    @classmethod
    def register(cls) -> bool:
        """
        Register AmethystModManager as the handler for nxm:// links.

        Returns True on success, False if it could not be registered
        (e.g. xdg-mime not available).
        """
        desktop_path = cls._desktop_path()
        desktop_path.parent.mkdir(parents=True, exist_ok=True)

        exec_cmd = cls._get_exec_command()

        desktop_content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Amethyst Mod Manager (NXM Handler)\n"
            "Comment=Handle nxm:// download links from Nexus Mods\n"
            f"Exec={exec_cmd}\n"
            "Terminal=false\n"
            "NoDisplay=true\n"
            "MimeType=x-scheme-handler/nxm;\n"
            "Categories=Game;\n"
        )

        desktop_path.write_text(desktop_content)
        app_log(f"Wrote NXM .desktop file: {desktop_path}")

        # Also write to Flatpak exports dir so Flatpak-sandboxed browsers can
        # see the handler.  The dir may not exist if Flatpak isn't installed,
        # so we only write if the parent already exists.
        flatpak_path = cls._flatpak_desktop_path()
        if flatpak_path.parent.exists():
            try:
                flatpak_path.write_text(desktop_content)
                app_log(f"Wrote NXM .desktop file to Flatpak exports: {flatpak_path}")
            except OSError as exc:
                app_log(f"Could not write Flatpak .desktop file: {exc}")

        # Register as default handler.
        # Inside a Flatpak sandbox xdg-mime is not available directly; use
        # flatpak-spawn --host to run it on the host system instead.
        in_flatpak = Path("/.flatpak-info").exists()
        if in_flatpak and shutil.which("flatpak-spawn"):
            xdg_mime_cmd = ["flatpak-spawn", "--host", "--directory=/", "xdg-mime"]
        elif shutil.which("xdg-mime"):
            xdg_mime_cmd = ["xdg-mime"]
        else:
            app_log("xdg-mime not found — nxm:// handler not registered")
            return False

        try:
            subprocess.run(
                [*xdg_mime_cmd, "default", _DESKTOP_FILE_NAME,
                 "x-scheme-handler/nxm"],
                check=True,
                capture_output=True,
            )
            app_log("Registered nxm:// protocol handler via xdg-mime")
        except subprocess.CalledProcessError as exc:
            app_log(f"xdg-mime default failed: {exc.stderr}")
            return False

        # Refresh the desktop database so Flatpak apps pick up the new entry.
        if in_flatpak and shutil.which("flatpak-spawn"):
            udd_cmd = ["flatpak-spawn", "--host", "--directory=/", "update-desktop-database"]
            udd_available = True
        else:
            udd_cmd = ["update-desktop-database"]
            udd_available = bool(shutil.which("update-desktop-database"))
        if udd_available:
            for db_dir in {desktop_path.parent, flatpak_path.parent}:
                if db_dir.exists():
                    try:
                        subprocess.run(
                            [*udd_cmd, str(db_dir)],
                            check=True,
                            capture_output=True,
                        )
                        app_log(f"Updated desktop database: {db_dir}")
                    except subprocess.CalledProcessError as exc:
                        app_log(f"update-desktop-database failed for {db_dir}: {exc.stderr}")

        return True

    @classmethod
    def unregister(cls) -> None:
        """Remove the .desktop file(s) (best-effort)."""
        for path in (cls._desktop_path(), cls._flatpak_desktop_path()):
            try:
                path.unlink(missing_ok=True)
                app_log(f"Removed NXM .desktop file: {path}")
            except OSError as exc:
                app_log(f"Could not remove NXM .desktop {path}: {exc}")

    @classmethod
    def is_registered(cls) -> bool:
        """Check whether our .desktop file exists."""
        return cls._desktop_path().is_file()


# ---------------------------------------------------------------------------
# Single-instance IPC via Unix domain socket
# ---------------------------------------------------------------------------

class NxmIPC:
    """
    Ensures only one instance of the app runs at a time.

    The first instance calls ``start_server(callback)`` which listens on
    a Unix domain socket.  Subsequent instances call ``send_to_running()``
    which sends the ``nxm://`` URL to the existing instance and returns True,
    signalling the caller to exit immediately.

    Usage (entry point)::

        def on_nxm(url: str):
            app.after(0, lambda: app._process_nxm_link(url))

        if NxmIPC.send_to_running(nxm_url):
            sys.exit(0)          # handed off to running instance

        app = App()
        NxmIPC.start_server(on_nxm)
        app.mainloop()
    """

    _server_socket: Optional[socket.socket] = None
    _thread: Optional[threading.Thread] = None

    @classmethod
    def send_to_running(cls, nxm_url: str) -> bool:
        """
        Try to send *nxm_url* to an already-running instance.

        Returns True if delivered, False if no instance was listening.
        """
        if not _SOCKET_PATH.exists():
            return False

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(str(_SOCKET_PATH))
            payload = json.dumps({"nxm_url": nxm_url}).encode("utf-8")
            sock.sendall(payload)
            sock.close()
            app_log("Sent NXM link to running instance")
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            app_log(f"No running instance to hand off to: {exc}")
            # Stale socket — clean up
            _SOCKET_PATH.unlink(missing_ok=True)
            return False

    @classmethod
    def start_server(cls, callback: Callable[[str], None]) -> None:
        """
        Start listening for NXM links from new instances.

        *callback* is called (from a background thread) with the nxm:// URL
        string whenever another instance sends one.  The callback should use
        ``app.after()`` to schedule work on the main thread.
        """
        # Clean stale socket
        _SOCKET_PATH.unlink(missing_ok=True)

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(_SOCKET_PATH))
        srv.listen(4)
        cls._server_socket = srv

        def _accept_loop():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    break  # socket closed → shutting down
                try:
                    data = conn.recv(4096)
                    if data:
                        msg = json.loads(data.decode("utf-8"))
                        url = msg.get("nxm_url", "")
                        if url:
                            app_log(f"Received NXM link from new instance: {url}")
                            callback(url)
                except Exception as exc:
                    app_log(f"Error handling IPC message: {exc}")
                finally:
                    conn.close()

        t = threading.Thread(target=_accept_loop, daemon=True, name="nxm-ipc")
        t.start()
        cls._thread = t
        app_log(f"NXM IPC server listening on {_SOCKET_PATH}")

    @classmethod
    def shutdown(cls) -> None:
        """Close the IPC socket and clean up."""
        if cls._server_socket:
            try:
                cls._server_socket.close()
            except OSError:
                pass
            cls._server_socket = None
        _SOCKET_PATH.unlink(missing_ok=True)
