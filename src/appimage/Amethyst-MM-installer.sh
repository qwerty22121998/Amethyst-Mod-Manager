#!/bin/bash
# Amethyst Mod Manager installer
# Downloads latest AppImage, icon, and creates a .desktop entry
#
# Portable across Linux distros: uses XDG paths (~/.local/share) and
# creates ~/Applications if missing. Requires curl or wget.

set -e

REPO="ChrisDKN/Amethyst-Mod-Manager"
BASE_URL="https://raw.githubusercontent.com/${REPO}/main"
ICON_URL="${BASE_URL}/src/icons/title-bar.png"
RELEASES_API_URL="https://api.github.com/repos/${REPO}/releases/latest"

# ~/Applications: not standard on all distros; we create it (common on Steam Deck)
APPLICATIONS_DIR="${HOME}/Applications"
# XDG Base Dir: standard on all desktop Linux (Ubuntu, Fedora, Arch, etc.)
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
ICONS_DIR="${XDG_DATA}/icons"
APPLICATIONS_DESKTOP_DIR="${XDG_DATA}/applications"

# Local name is fixed so .desktop entry and updates overwrite the same file
APPIMAGE_NAME="AmethystModManager-x86_64.AppImage"
ICON_NAME="title-bar.png"
DESKTOP_NAME="amethyst-mod-manager.desktop"

echo "Amethyst Mod Manager installer"
echo "=============================="

# Discover latest AppImage from GitHub Releases
echo "Checking for latest version..."
if command -v curl &>/dev/null; then
    JSON="$(curl -sL "$RELEASES_API_URL")"
else
    JSON="$(wget -qO- "$RELEASES_API_URL")"
fi
LATEST_VERSION="$(echo "$JSON" | grep -o '"tag_name" *: *"[^"]*"' | sed 's/.*: *"v\{0,1\}\([^"]*\)"/\1/' | head -1)"
APPIMAGE_URL="$(echo "$JSON" | grep -o '"browser_download_url" *: *"[^"]*\.AppImage"' | sed 's/.*: *"\([^"]*\)"/\1/' | head -1)"
if [ -z "$APPIMAGE_URL" ]; then
    echo "Error: Could not find an AppImage asset in the latest release." >&2
    exit 1
fi
echo "Latest version: ${LATEST_VERSION}"
echo ""

# Create directories if they don't exist
mkdir -p "$APPLICATIONS_DIR"
mkdir -p "$ICONS_DIR"
mkdir -p "$APPLICATIONS_DESKTOP_DIR"

# Download AppImage
echo "Downloading AppImage..."
if command -v curl &>/dev/null; then
    curl -L -o "$APPLICATIONS_DIR/$APPIMAGE_NAME" "$APPIMAGE_URL"
elif command -v wget &>/dev/null; then
    wget -O "$APPLICATIONS_DIR/$APPIMAGE_NAME" "$APPIMAGE_URL"
else
    echo "Error: neither curl nor wget found. Please install one of them." >&2
    exit 1
fi

chmod +x "$APPLICATIONS_DIR/$APPIMAGE_NAME"
echo "AppImage installed to $APPLICATIONS_DIR/$APPIMAGE_NAME (executable)."

# Download icon
echo "Downloading icon..."
if command -v curl &>/dev/null; then
    curl -L -o "$ICONS_DIR/$ICON_NAME" "$ICON_URL"
elif command -v wget &>/dev/null; then
    wget -O "$ICONS_DIR/$ICON_NAME" "$ICON_URL"
fi
echo "Icon installed to $ICONS_DIR/$ICON_NAME."

# Create .desktop entry
DESKTOP_FILE="$APPLICATIONS_DESKTOP_DIR/$DESKTOP_NAME"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=${LATEST_VERSION}
Type=Application
Name=Amethyst Mod Manager
Comment=Linux Mod Manager
Exec=${APPLICATIONS_DIR}/${APPIMAGE_NAME}
Icon=${ICONS_DIR}/${ICON_NAME}
Categories=Game;Utility;
Terminal=false
EOF

echo "Desktop entry created at $DESKTOP_FILE."
echo ""
echo "Installation complete. You can launch Amethyst Mod Manager from your application menu."
