#!/bin/bash
cd "$(dirname "$0")"

# Drop AppImage-injected env that poisons a from-source run. If the user
# launched a terminal from a running AppImage at any point, these inherit
# into the shell and point at /tmp/.mount_*; once the AppImage exits the
# mount goes away and Python startup fails with "Failed to import encodings"
# or "ImportError: cannot import name '_imaging' from 'PIL'".
unset PYTHONPATH PYTHONHOME APPDIR APPIMAGE OWD URUNTIME ARG0 ARGV0
unset SHARUN_DIR SHARUN_WORKING_DIR APPIMAGE_ARCH APPIMAGE_UUID
unset GIO_LAUNCH_DESKTOP GDK_PIXBUF_MODULEDIR GDK_PIXBUF_MODULE_FILE
unset GIO_MODULE_DIR GSETTINGS_SCHEMA_DIR GTK_PATH GTK_IM_MODULE_FILE
unset QT_PLUGIN_PATH TERMINFO LIBTHAI_DICTDIR
unset SSL_CERT_FILE SSL_CERT_DIR CURL_CA_BUNDLE LD_LIBRARY_PATH LD_PRELOAD
# Drop a stale MOD_MANAGER_GAMES pointing at a vanished mount so gui.py
# re-discovers the source tree's Games/ dir.
case "${MOD_MANAGER_GAMES:-}" in /tmp/.mount_*) unset MOD_MANAGER_GAMES ;; esac
# Strip /tmp/.mount_* fragments from PATH / XDG_DATA_DIRS so a stale
# AppImage's bin/ doesn't shadow system tools.
PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^/tmp/\.mount_' | paste -sd:)
[ -n "${XDG_DATA_DIRS:-}" ] && \
    XDG_DATA_DIRS=$(echo "$XDG_DATA_DIRS" | tr ':' '\n' | grep -v '^/tmp/\.mount_' | paste -sd:)
export PATH XDG_DATA_DIRS

if [ ! -d .venv ]; then
    python3 -m venv --system-site-packages .venv
    [ -f requirements.txt ] && .venv/bin/pip install -r requirements.txt -q
fi

# Install any missing or newly added requirements
if [ -f requirements.txt ]; then
    .venv/bin/pip install -r requirements.txt -q --disable-pip-version-check
fi

.venv/bin/python3 gui.py "$@"

