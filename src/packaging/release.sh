#!/usr/bin/env bash
# Build every release artifact with wine (Windows Python + PyInstaller + Inno Setup).
#
#   ./release.sh              build all, run smoke tests
#   ./release.sh app          program-only artifacts (skip data installer)
#   ./release.sh data         data pack only (no PyInstaller run: reuses out/program)
#   ./release.sh full         only the full installer (no program-only/data installers, zip or smoke test)
#
# Env: DATA_VERSION (default: today, e.g. 2026.09.19)  R08_DATA (data folder)
#      OUT (default ~/r08-build/out)  SKIP_SMOKE=1
# Program version comes from shared/version.py (APP_VERSION).
#
# One-time setup of the isolated wine prefix: see packaging/README.md.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"
TARGET="${1:-all}"
export WINEPREFIX="${WINEPREFIX:-$HOME/r08-build/prefix}" WINEDEBUG=-all
OUT="${OUT:-$HOME/r08-build/out}"
DATA="${R08_DATA:-$SRC/../R08-mod-data}"
DATA_VERSION="${DATA_VERSION:-$(date +%Y.%m.%d)}"
APP_VERSION="$(sed -n 's/^APP_VERSION *= *"\(.*\)"/\1/p' "$SRC/shared/version.py")"
DATA_SCHEMA="$(sed -n 's/^DATA_SCHEMA *= *\([0-9]*\)/\1/p' "$SRC/shared/version.py")"
ISCC="$WINEPREFIX/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"
PY='C:\Python311\python.exe'
winpath() { winepath -w "$1" 2>/dev/null; }
step() { printf '\n== %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

step "preflight (program $APP_VERSION, data $DATA_VERSION, schema $DATA_SCHEMA)"
[ -n "$APP_VERSION" ] && [ -n "$DATA_SCHEMA" ] || die "cannot read shared/version.py"
[ -f "$ISCC" ] || die "Inno Setup missing in wine prefix"
(wine "$PY" -c "import PyInstaller" </dev/null 2>&1 | cat >/dev/null; exit "${PIPESTATUS[0]}") || die "PyInstaller missing in wine prefix"
[ -f "$DATA/players/players.json" ] && [ -d "$DATA/teams" ] || die "data folder incomplete: $DATA"
for f in d3d8.dll rugby08patches.dll; do [ -f "$SRC/assets/static_files/$f" ] || die "assets/static_files/$f missing"; done
( cd "$SRC/assets/audio/menu" && sha256sum -c "$HERE/audio_manifest.sha256" --quiet ) 2>/dev/null \
  || "$HERE/fetch_audio.sh" || die "menu music missing/invalid, see packaging/fetch_audio.sh"
if git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
  echo "git: $(git -C "$SRC" rev-parse --short HEAD)$(git -C "$SRC" diff --quiet HEAD -- . 2>/dev/null || echo ' (+uncommitted changes)')"
fi
mkdir -p "$OUT"
PROG="$OUT/R08Revival"; DATASTAGE="$OUT/data_pack"; INC="$OUT/inc"

if [ "$TARGET" != data ]; then
  step "game-copy includes"
  python3 "$HERE/gen_game_includes.py" "$INC"

  step "PyInstaller"
  rm -rf "$OUT/work" "$PROG"
  wine "$PY" -m PyInstaller --noconfirm --distpath "$(winpath "$OUT")" \
    --workpath "$(winpath "$OUT/work")" "$(winpath "$HERE/R08Revival.spec")" </dev/null 2>&1 | tail -2
  [ -f "$PROG/R08Revival.exe" ] || die "PyInstaller produced no exe"
  mkdir -p "$PROG/app_data"
  rsync -a --exclude='*_old.dll' --exclude='__pycache__' --exclude='*.example' "$SRC/assets" "$PROG/app_data/"
  cp "$SRC/config.ini.example" "$PROG/app_data/config.ini.example"
  cp "$SRC/CREDITS.MD" "$PROG/app_data/CREDITS.MD"
  cp "$HERE/RELEASE_README.txt" "$PROG/app_data/README.txt"
fi
[ -f "$PROG/R08Revival.exe" ] || die "no built program in $PROG (run without 'data' first)"

if [ "$TARGET" != app ]; then
  step "data pack"
  rm -rf "$DATASTAGE"; mkdir -p "$DATASTAGE"
  rsync -a --exclude='other/' --exclude='*.bak' --exclude='*(copy)*' --exclude='user_prefs.ini' --exclude='game_profile.ini' \
    --exclude='_backup/' --exclude='__pycache__' "$DATA/" "$DATASTAGE/"
  printf 'data_version=%s\nschema=%s\n' "$DATA_VERSION" "$DATA_SCHEMA" > "$DATASTAGE/VERSION"
  python3 "$HERE/gen_data_inc.py" "$DATASTAGE" "$INC"
fi
[ -d "$DATASTAGE" ] || DATASTAGE="$OUT/data_pack"

iscc() {  # variant, extra defines...
  local variant="$1"; shift
  wine "$ISCC" "/DVariant=$variant" "/DAppVersion=$APP_VERSION" "/DDataVersion=$DATA_VERSION" \
    "/DProgramDir=$(winpath "$PROG")" "/DDataDir=$(winpath "$DATASTAGE")" \
    "/DOutDir=$(winpath "$OUT")" "/DIncDir=$(winpath "$INC")" "$@" \
    "$(winpath "$HERE/installer.iss")" </dev/null 2>&1 | grep -E "Successful|Error|error|Warning" || true
}
step "installers"
if [ "$TARGET" = full ]; then rm -f "$OUT"/R08Revival_[0-9]*_setup.exe; else rm -f "$OUT"/R08Revival_*.exe "$OUT"/R08Revival_*.zip; fi
if [ "$TARGET" = all ] || [ "$TARGET" = full ]; then iscc full; fi
if [ "$TARGET" = all ] || [ "$TARGET" = app ]; then iscc app; fi
if [ "$TARGET" = all ] || [ "$TARGET" = data ]; then iscc data; fi

if [ "$TARGET" = all ]; then
  step "portable zip"
  P="$OUT/portable/R08Revival"; rm -rf "$OUT/portable"; mkdir -p "$OUT/portable"
  cp -al "$PROG" "$P"; cp -al "$DATASTAGE" "$P/mod_data"; : > "$P/portable.txt"
  ( cd "$OUT/portable" && zip -qr "$OUT/R08Revival_${APP_VERSION}_portable.zip" R08Revival )
  rm -rf "$OUT/portable"
fi

if [ "$TARGET" = all ] && [ -z "${SKIP_SMOKE:-}" ]; then
  step "smoke test"
  "$HERE/smoke_test.sh" "$OUT" "$APP_VERSION" "$DATA_VERSION"
fi

step "checksums"
( cd "$OUT" && sha256sum R08Revival_*.exe R08Revival_*.zip 2>/dev/null | tee SHA256SUMS )
cat > "$OUT/manifest.json" <<JSON
{"program_version": "$APP_VERSION", "data_version": "$DATA_VERSION", "data_schema": $DATA_SCHEMA,
 "built": "$(date -u +%FT%TZ)", "git": "$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo none)"}
JSON
echo; ls -la "$OUT"/R08Revival_*.exe "$OUT"/R08Revival_*.zip 2>/dev/null
