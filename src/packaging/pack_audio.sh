#!/usr/bin/env bash
# Build the menu-music release asset from the local, already-encoded mp3s in
# assets/audio/menu/, and refresh packaging/audio_manifest.sha256 to match.
#
# Run this after adding/re-encoding a track, then attach the zip it prints
# to a GitHub Release (tag e.g. menu-music-v1) and update AUDIO_URL at the
# top of fetch_audio.sh to point at that asset.
#
#   ./pack_audio.sh                # -> ~/r08-build/out/menu_music.zip
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"
AUDIO_DIR="$SRC/assets/audio/menu"
OUT="${OUT:-$HOME/r08-build/out}"
ZIP="$OUT/menu_music.zip"

shopt -s nullglob
mp3s=("$AUDIO_DIR"/*.mp3)
[ ${#mp3s[@]} -gt 0 ] || { echo "ERROR: no mp3 files in $AUDIO_DIR" >&2; exit 1; }

mkdir -p "$OUT"
rm -f "$ZIP"
( cd "$AUDIO_DIR" && zip -q -9 "$ZIP" *.mp3 )
( cd "$AUDIO_DIR" && sha256sum *.mp3 > "$HERE/audio_manifest.sha256" )

echo "wrote $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "refreshed $HERE/audio_manifest.sha256"
echo "next: upload $ZIP to a GitHub Release, then point AUDIO_URL (fetch_audio.sh) at it"
