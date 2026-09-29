#!/usr/bin/env bash
# Download the menu-music mp3s (kept out of git, see .gitignore) from a
# GitHub Release and verify them against packaging/audio_manifest.sha256.
#
#   ./fetch_audio.sh                              # uses AUDIO_URL below
#   AUDIO_URL=https://.../menu_music.zip ./fetch_audio.sh
#
# Safe to re-run: skips files that already match the manifest.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"
AUDIO_DIR="$SRC/assets/audio/menu"
MANIFEST="$HERE/audio_manifest.sha256"

# Set this once you've uploaded packaging/pack_audio.sh's zip to a GitHub
# Release (e.g. tag "menu-music-v1"):
AUDIO_URL="${AUDIO_URL:-}"

[ -f "$MANIFEST" ] || { echo "ERROR: $MANIFEST missing" >&2; exit 1; }

if (cd "$AUDIO_DIR" 2>/dev/null && sha256sum -c "$MANIFEST" --quiet) 2>/dev/null; then
  echo "menu music already present and verified in $AUDIO_DIR"
  exit 0
fi

[ -n "$AUDIO_URL" ] || {
  echo "ERROR: menu music missing/incomplete in $AUDIO_DIR and AUDIO_URL is not set." >&2
  echo "Set AUDIO_URL to the GitHub Release asset (see packaging/pack_audio.sh)." >&2
  exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "downloading $AUDIO_URL"
curl -fL "$AUDIO_URL" -o "$TMP/menu_music.zip"
unzip -q -o "$TMP/menu_music.zip" -d "$TMP/extracted"

mkdir -p "$AUDIO_DIR"
cp "$TMP"/extracted/*.mp3 "$AUDIO_DIR/"

if ! (cd "$AUDIO_DIR" && sha256sum -c "$MANIFEST" --quiet); then
  echo "ERROR: downloaded files don't match $MANIFEST" >&2
  exit 1
fi
echo "menu music installed and verified in $AUDIO_DIR"
