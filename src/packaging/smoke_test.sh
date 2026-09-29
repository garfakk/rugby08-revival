#!/usr/bin/env bash
# Install the built full installer silently (in the wine build prefix), run the
# frozen exe's --selftest, then apply the data-only installer and check that
# edited data files were backed up. usage: smoke_test.sh <out dir> <app ver> <data ver>
set -euo pipefail
# Inno Setup creates windows even when silent; without a display it dies with
# "Error reading FPreparingMemo.Lines.Strings ... Invalid window handle".
if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
  exec xvfb-run -a "$0" "$@"
fi
OUT="$1"; AV="$2"; DV="$3"
export WINEPREFIX="${WINEPREFIX:-$HOME/r08-build/prefix}" WINEDEBUG=-all
T="$(mktemp -d "$HOME/r08-build/smoke.XXXXXX")"
trap 'rm -rf "$T"' EXIT
wp() { winepath -w "$1" 2>/dev/null; }
CFG="$T/app/user_data"   # everything lives under the install folder
mkdir -p "$T/game/Data" && : > "$T/game/Rugby08.exe" && echo x > "$T/game/Data/data.gob"
fail() { echo "SMOKE FAIL: $*"; exit 1; }

wine "$OUT/R08Revival_${AV}_setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART \
  "/DIR=$(wp "$T/app")" "/GAMEDIR=$(wp "$T/game")" </dev/null >/dev/null 2>&1 || true
[ -f "$T/app/R08Revival.exe" ] || fail "program not installed"
# one root folder: app_data/ mod_data/ user_data/ game_files/ under the install dir
[ -f "$T/app/app_data/assets/static_files/d3d8.dll" ] || fail "app_data not installed"
[ -f "$T/app/mod_data/players/players.json" ] || fail "data not installed"
[ -f "$T/app/mod_data/VERSION" ] || fail "data VERSION missing"
[ -f "$CFG/config.ini" ] || fail "config.ini not written to user_data"
grep -qi "R08_directory" "$CFG/config.ini" || fail "config.ini lacks game dir"
# the original game is copied, the copy is what the config points at
[ -f "$T/app/game_files/Rugby08.exe" ] && [ -f "$T/app/game_files/Data/data.gob" ] || fail "game copy missing"
grep -qi "R08_directory.*game_files" "$CFG/config.ini" || fail "config.ini does not point at the game copy"
grep -qi "R08_original_directory.*game" "$CFG/config.ini" || fail "config.ini lacks original game dir"
echo "install OK"

# protected folders are refused (silent install too): nothing gets installed there
PF="C:\\Program Files\\R08RevivalSmoke"
wine "$OUT/R08Revival_${AV}_setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART \
  "/DIR=$PF" "/GAMEDIR=$(wp "$T/game")" </dev/null >/dev/null 2>&1 || true
[ ! -e "$WINEPREFIX/drive_c/Program Files/R08RevivalSmoke/R08Revival.exe" ] || fail "installed into Program Files"
echo "protected folder refused OK"

res="$(cd "$T/app" && timeout 90 wine R08Revival.exe --selftest </dev/null 2>&1 | cat)" || true
echo "$res" | grep -q "SELFTEST OK" || { echo "$res" | tail -20; fail "selftest did not pass"; }
echo "$res" | grep -q "Traceback" && { echo "$res" | tail -20; fail "traceback during selftest"; }
echo "selftest OK"

# data update: edit a shipped file, install the data pack over it
echo " " >> "$T/app/mod_data/players/players.json"
wine "$OUT/R08Revival_data_${DV}_setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART \
  "/DIR=$(wp "$T/app/mod_data")" </dev/null >/dev/null 2>&1 || true
ls "$T"/app/mod_data/_backup/*/players/players.json >/dev/null 2>&1 || fail "edited players.json was not backed up"
cmp -s "$T/app/mod_data/players/players.json" "$OUT/data_pack/players/players.json" || fail "data pack did not restore players.json"
echo "data update + backup OK"

# uninstall: everything goes except user_data (kept unless /DELETEUSERDATA=1 / the checkbox)
UNINS="$(ls "$T"/app/unins*.exe 2>/dev/null | head -1)"
[ -n "$UNINS" ] || fail "no uninstaller"
wine "$UNINS" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART </dev/null >/dev/null 2>&1 || true
sleep 3   # the uninstaller finishes itself from a temp copy
for d in _internal app_data mod_data game_files; do
  [ ! -e "$T/app/$d" ] || fail "uninstall left $d"
done
[ ! -e "$T/app/R08Revival.exe" ] || fail "uninstall left the exe"
[ -f "$T/app/user_data/config.ini" ] || fail "uninstall removed user_data without being asked"
[ -f "$T/game/Rugby08.exe" ] || fail "uninstall touched the original game"
echo "uninstall OK"
rm -rf "$CFG"
