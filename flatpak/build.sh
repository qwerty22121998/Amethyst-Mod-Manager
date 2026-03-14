#!/bin/bash
# Build Amethyst Mod Manager as a Flatpak
#
# Prerequisites:
#   - Flatpak and flatpak-builder installed
#   - GNOME runtime: flatpak install flathub org.gnome.Platform//49 org.gnome.Sdk//49
#
# Usage:
#   ./flatpak/build.sh           # Build and install locally
#   ./flatpak/build.sh --export  # Build only (no install)
#   ./flatpak/build.sh --bundle  # Build and create .flatpak bundle file
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MANIFEST="${SCRIPT_DIR}/io.github.Amethyst.ModManager.yml"
BUILD_DIR="${SCRIPT_DIR}/build"
REPO_DIR="${SCRIPT_DIR}/repo"
BUNDLE_FILE="${PROJECT_DIR}/AmethystModManager.flatpak"
APP_ID="io.github.Amethyst.ModManager"

INSTALL_FLAG="--install"
[ "${1:-}" = "--export" ] && INSTALL_FLAG=""
BUNDLE_MODE=false
[ "${1:-}" = "--bundle" ] && { INSTALL_FLAG=""; BUNDLE_MODE=true; }

cd "$PROJECT_DIR"

echo "=== Building Amethyst Mod Manager Flatpak ==="
echo "  Manifest: $MANIFEST"
echo "  Project:  $PROJECT_DIR"
echo ""

flatpak-builder \
  --verbose \
  --user \
  --install-deps-from=flathub \
  --repo="${REPO_DIR}" \
  $INSTALL_FLAG \
  "${BUILD_DIR}" \
  "${MANIFEST}"

if [ "$BUNDLE_MODE" = true ]; then
  echo ""
  echo "=== Creating .flatpak bundle ==="
  flatpak build-bundle \
    "${REPO_DIR}" \
    "${BUNDLE_FILE}" \
    "${APP_ID}" \
    --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
  echo ""
  echo "=== Bundle created: ${BUNDLE_FILE} ==="
  echo "Install with: flatpak install --user ${BUNDLE_FILE}"
elif [ "${1:-}" != "--export" ]; then
  echo ""
  echo "=== Build and install complete ==="
  echo "Run with: flatpak run ${APP_ID}"
else
  echo ""
  echo "=== Build complete ==="
  echo "Build directory: ${BUILD_DIR}"
fi
