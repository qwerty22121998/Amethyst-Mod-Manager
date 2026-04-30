#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"   # = src/

# Quick-sharun lives in the user's local bin; make sure it's on PATH.
export PATH="$HOME/.local/bin:$PATH"

ARCH=$(uname -m)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${PROJECT_DIR}/version.py")
[ -n "$VERSION" ] || { echo "ERROR: cannot read __version__" >&2; exit 1; }
WORK_DIR="${TMPDIR:-/tmp}/amethyst-mm-build"
OUTPATH="${WORK_DIR}/dist"
APPDIR="${WORK_DIR}/AppDir"
FINAL_OUTPATH="${SCRIPT_DIR}/dist"

# ── Tooling check ────────────────────────────────────────────────────
for tool in quick-sharun sharun cc awk find ldd strings; do
    command -v "$tool" >/dev/null || {
        echo "ERROR: '$tool' not found in PATH" >&2
        echo "Install sharun + quick-sharun into ~/.local/bin/" >&2
        exit 1
    }
done

# Sanity-check that the host Python has tkinter — without it the
# resulting AppImage won't launch on most distros either.
if ! /usr/bin/python3 -c 'import tkinter' 2>/dev/null; then
    echo "ERROR: /usr/bin/python3 cannot import tkinter." >&2
    echo "Install the system 'tk' package (Arch: pacman -S tk)." >&2
    exit 1
fi

# ── Clean ────────────────────────────────────────────────────────────
echo "=== Cleaning previous build ==="
rm -rf "$WORK_DIR" "$FINAL_OUTPATH"
mkdir -p "$APPDIR/bin" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
         "$OUTPATH" "$FINAL_OUTPATH"

# ── Stage source ─────────────────────────────────────────────────────
echo "=== Staging source ==="
APP_SHARE="$APPDIR/share/amethyst-mod-manager"
mkdir -p "$APP_SHARE" "$APPDIR/usr/share"
ln -sf ../../share/amethyst-mod-manager "$APPDIR/usr/share/amethyst-mod-manager"

cp "${PROJECT_DIR}/gui.py"           "$APP_SHARE/"
cp "${PROJECT_DIR}/cli.py"           "$APP_SHARE/"
cp "${PROJECT_DIR}/version.py"       "$APP_SHARE/"
cp "${PROJECT_DIR}/splash_gtk.py"    "$APP_SHARE/" 2>/dev/null || true
cp "${PROJECT_DIR}/../Changelog.txt" "$APP_SHARE/" 2>/dev/null || true

for dir in gui Utils Games LOOT Nexus icons wizards wrappers; do
    cp -r "${PROJECT_DIR}/${dir}" "$APP_SHARE/${dir}"
done

rm -f "$APP_SHARE/LOOT/rebuild_libloot.sh"
find "$APP_SHARE" -type f -name '*.sh' -exec rm -f {} \;
find "$APP_SHARE" -type f -name 'requirements*.txt' -delete 2>/dev/null || true
LOOT_SO="$APP_SHARE/LOOT/loot.cpython-313-x86_64-linux-gnu.so"
[ -f "$LOOT_SO" ] && strip --strip-unneeded "$LOOT_SO" 2>/dev/null || true
find "$APP_SHARE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$APP_SHARE" -type f -name '*.py' -exec chmod -x {} \;

# Wrapper binary that the .desktop file's Exec= points at.
# quick-sharun rewrites APP_SHARE references after deployment via the
# sed pass below.
cat > "$APPDIR/bin/mod-manager" <<'EOF'
#!/bin/sh
APP_SHARE=/usr/share/amethyst-mod-manager
export PYTHONPATH="$APP_SHARE/_vendor${PYTHONPATH:+:$PYTHONPATH}"
export MOD_MANAGER_PROFILES_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/AmethystModManager/Profiles"
mkdir -p "$MOD_MANAGER_PROFILES_DIR"
case "$1" in
    deploy|restore|list-games|list-profiles|clear-credentials)
        exec python3 "$APP_SHARE/cli.py" "$@" ;;
    *)
        exec python3 "$APP_SHARE/gui.py" "$@" ;;
esac
EOF
chmod +x "$APPDIR/bin/mod-manager"

# ── pip dependencies ─────────────────────────────────────────────────
echo "=== Installing pip dependencies ==="
VENDOR_DIR="$APP_SHARE/_vendor"
mkdir -p "$VENDOR_DIR"

if /usr/bin/python3 -m pip --version >/dev/null 2>&1; then
    PIP_PYTHON=/usr/bin/python3
elif [ -x "${PROJECT_DIR}/.venv/bin/pip" ]; then
    PIP_PYTHON="${PROJECT_DIR}/.venv/bin/python3"
elif /usr/bin/python3 -m ensurepip --user >/dev/null 2>&1; then
    PIP_PYTHON=/usr/bin/python3
else
    echo "ERROR: no working pip found (host python3 lacks it, no .venv either)" >&2
    exit 1
fi
echo "  using pip from: $PIP_PYTHON"
"$PIP_PYTHON" -m pip install --no-cache-dir --quiet \
    --target "$VENDOR_DIR" \
    -r "${PROJECT_DIR}/requirements-appimage.txt"

# Drop pip-generated console-script wrappers (keyring, py7zr, wsdump, …).
rm -rf "$VENDOR_DIR/bin"

# Strip +x bits from .py files
find "$APP_SHARE" -type f -name '*.py' -exec chmod -x {} \;

# Strip native extensions in vendored deps. pip wheels often ship with
# debug symbols; quick-sharun only strips files it copies into shared/lib,
# but our _vendor stays inside usr/share/, so do it ourselves.
find "$VENDOR_DIR" -type f -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true

# ── Aux binaries ────────────────────
echo "=== Bundling 7-Zip (7zzs) ==="
SEVENZIP_URL="https://github.com/ip7z/7zip/releases/download/26.00/7z2600-linux-x64.tar.xz"
SEVENZIP_TMP="${WORK_DIR}/.7z-tmp"
mkdir -p "$SEVENZIP_TMP"
wget -q -O "${SEVENZIP_TMP}/7z.tar.xz" "$SEVENZIP_URL"
tar -xf "${SEVENZIP_TMP}/7z.tar.xz" -C "$SEVENZIP_TMP"
cp "$SEVENZIP_TMP/7zzs" "$APPDIR/bin/7zzs"
chmod +x "$APPDIR/bin/7zzs"
ln -sf 7zzs "$APPDIR/bin/7z"
ln -sf 7zzs "$APPDIR/bin/7za"
rm -rf "$SEVENZIP_TMP"

echo "=== Bundling bsdtar ==="
BSDTAR_BIN="$(command -v bsdtar 2>/dev/null || true)"
if [ -n "$BSDTAR_BIN" ]; then
    cp "$BSDTAR_BIN" "$APPDIR/bin/bsdtar"
    chmod +x "$APPDIR/bin/bsdtar"
fi

echo "=== Bundling Cantarell font ==="
CANTARELL_URL="https://gitlab.gnome.org/GNOME/cantarell-fonts/-/archive/0.303.1/cantarell-fonts-0.303.1.tar.gz"
CANTARELL_TMP="${WORK_DIR}/.cantarell-tmp"
FONT_DEST="$APPDIR/usr/share/fonts/amethyst"
mkdir -p "$FONT_DEST" "$CANTARELL_TMP"
if wget -q -O "${CANTARELL_TMP}/cantarell.tar.gz" "$CANTARELL_URL"; then
    tar -xf "${CANTARELL_TMP}/cantarell.tar.gz" -C "$CANTARELL_TMP"
    VF_OTF="$(find "$CANTARELL_TMP" -name 'Cantarell-VF.otf' | head -1)"
    [ -n "$VF_OTF" ] && cp "$VF_OTF" "$FONT_DEST/"
fi
rm -rf "$CANTARELL_TMP"

# ── Desktop / icon ───────────────────────────────────────────────────
ASSETS_DIR="${WORK_DIR}/assets"
mkdir -p "$ASSETS_DIR"
cp "${SCRIPT_DIR}/mod-manager.desktop" "$ASSETS_DIR/mod-manager.desktop"
cp "${SCRIPT_DIR}/mod-manager.png"     "$ASSETS_DIR/mod-manager.png"

echo "=== Desktop integration ==="
cp "$ASSETS_DIR/mod-manager.desktop" "$APPDIR/usr/share/applications/mod-manager.desktop"
cp "$ASSETS_DIR/mod-manager.png"     "$APPDIR/usr/share/icons/hicolor/512x512/apps/mod-manager.png"

# ── Run quick-sharun ─────────────────────────────────────────────────
# DEPLOY_PYTHON=1   pulls /usr/bin/python3 + stdlib (incl tkinter)
# DEPLOY_GTK=1      pulls libgtk-3 + gi typelibs for splash_gtk.py
# ALWAYS_SOFTWARE=1 forces software rendering (matches upstream)
TCLTK_STAGE="${WORK_DIR}/tcltk"
mkdir -p "$TCLTK_STAGE"
cp -a /usr/lib/tcl8.6 "$TCLTK_STAGE/tcl8.6"
cp -a /usr/lib/tk8.6  "$TCLTK_STAGE/tk8.6"
rm -rf "$TCLTK_STAGE/tk8.6/demos" "$TCLTK_STAGE/tcl8.6/demos"

echo "=== Running quick-sharun ==="
export ARCH VERSION OUTPATH APPDIR
export ICON="${ASSETS_DIR}/mod-manager.png"
export DESKTOP="${ASSETS_DIR}/mod-manager.desktop"
export DEPLOY_PYTHON=1
export DEPLOY_GTK=1
export ALWAYS_SOFTWARE=1
export ANYLINUX_LIB=1

# SteamOS strips glibc headers from /usr/include to keep the system
# image small, so quick-sharun's `cc` step for anylinux.so can't find
# dlfcn.h. Point gcc at a header-only sysroot at ~/sdk/include
# (extracted from the matching glibc Arch package — see appimage README).
# If the sysroot is missing, fall back to skipping anylinux.so so the
# build still completes.
if [ -f "$HOME/sdk/include/dlfcn.h" ]; then
    export C_INCLUDE_PATH="$HOME/sdk/include${C_INCLUDE_PATH:+:$C_INCLUDE_PATH}"
else
    echo "  NOTE: ~/sdk/include not found — disabling anylinux.so." >&2
    export ANYLINUX_LIB=0
fi

quick-sharun \
    "$APPDIR/bin/mod-manager"        \
    "$APP_SHARE"                     \
    "$APPDIR/bin/7zzs"               \
    /usr/bin/zenity                  \
    /usr/lib/libgtk-3.so*            \
    /usr/lib/libtcl8.6.so*           \
    /usr/lib/libtk8.6.so*            \
    "$TCLTK_STAGE/tcl8.6"            \
    "$TCLTK_STAGE/tk8.6"             \
    $( [ -f "$APPDIR/bin/bsdtar" ] && printf %s "$APPDIR/bin/bsdtar" )

sed -i 's|/usr/share/amethyst-mod-manager|"$APPDIR"/usr/share/amethyst-mod-manager|g' \
    "$APPDIR/bin/mod-manager"

# ── Build the AppImage ───────────────────────────────────────────────
echo "=== Building AppImage ==="
quick-sharun --make-appimage

# Move the AppImage from the whitespace-free WORK_DIR back into
# src/appimage/dist/ under our preferred name.
RAW_OUT=$(find "$OUTPATH" -maxdepth 2 -name '*.AppImage' -type f | head -1)
FINAL="${FINAL_OUTPATH}/AmethystModManager-${VERSION}-${ARCH}.AppImage"
if [ -n "$RAW_OUT" ]; then
    mv "$RAW_OUT" "$FINAL"
fi

echo ""
echo "=== Build complete ==="
[ -f "$FINAL" ] && {
    echo "AppImage: $FINAL"
    echo "Size: $(du -h "$FINAL" | cut -f1)"
}
