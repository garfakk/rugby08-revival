# Release pipeline (Windows build on Linux via wine)

    ./release.sh          # all artifacts + smoke test  -> ~/r08-build/out/
    ./release.sh app      # program only
    ./release.sh data     # data pack only (reuses last program build)
    DATA_VERSION=2027.01 ./release.sh data     # e.g. new season

Versions: program = `APP_VERSION` in `shared/version.py`; data = `DATA_VERSION` env
(default: today). Bump `DATA_SCHEMA` there only when the data layout changes in a way
old programs/new data (or vice versa) can't handle — the app warns on mismatch.

## Artifacts
| file | for |
|---|---|
| `R08Revival_<ver>_setup.exe` | first install: program + data, always a full install (no component picker), defaults into the user's Documents. One install folder holds `app_data\ mod_data\ user_data\ game_files\` + the exe (`shared/app_paths.py`). Asks the original game folder, then (default, recommended) whether to **copy the game into `<app>\game_files`** — the mod works on that copy, original untouched — or patch in place. Protected folders (Program Files, Windows, drive roots, anything not writable) are refused, also in silent mode |
| `R08Revival_<ver>_program_only.exe` | program upgrade, data untouched |
| `R08Revival_data_<dver>_setup.exe` | data pack (new season...). Destination = `mod_data` of the installed program (prefilled from `HKCU\Software\R08Revival\InstallDir`). Editable json/xml/ini are copied to `<mod_data>\_backup\<date>` first |
| `R08Revival_<ver>_portable.zip` | no installer; `portable.txt` marks it; same folder layout |
| `SHA256SUMS`, `manifest.json` | integrity + versions |

Silent install (used by the smoke test): `setup.exe /VERYSILENT /DIR=<install folder> /GAMEDIR=<original game>`
(`/DATADIR` only applies to the data-only installer.)
`/COPYGAME=0` = patch the original in place. config.ini gets `R08_directory` (copy) and `R08_original_directory`.
The installer is separate from `R08Revival.exe`: without a valid config the exe tells the user to run the installer (portable zip keeps its own first-run prompt).

## What the smoke test proves (and doesn't)
Installs the full setup silently in the wine prefix, runs `R08Revival.exe --selftest` (builds the
whole UI, exits), checks a Program Files install is refused, applies the data pack over an edited `mod_data` and checks the backup.
It does **not** prove real-Windows behaviour (game launch, memory reading, window
embedding) — test on the Win10 VM before publishing.

## One-time build prefix (`~/r08-build/prefix`, isolated from ~/.wine)
    export WINEPREFIX=~/r08-build/prefix WINEARCH=win64
    wine python-3.11.9-amd64.exe /quiet InstallAllUsers=0 TargetDir='C:\Python311'
    wine 'C:\Python311\python.exe' -m pip install -r <requirements.txt without PyQt5 line> \
         PyQt5==5.15.11 PyQt5-Qt5==5.15.2 pywin32 pyinstaller
    wine innosetup-6.7.3.exe /VERYSILENT
Wine quirk: always run with `</dev/null` and pipe output (`| cat`), never `> file`
(python fails with "Invalid handle").

## Layout
`R08Revival.spec` PyInstaller · `installer.iss` one Inno script, 3 variants ·
`gen_data_inc.py` staged-data-pack file list · `gen_game_includes.py` game-copy includes ·
`fetch_audio.sh`/`pack_audio.sh` menu music (release asset, not in git) ·
`smoke_test.sh` · `RELEASE_README.txt` (shipped)

`assets/static_files/` holds the prebuilt `d3d8.dll` / `rugby08patches.dll` copied from the
reR08 project — refresh them there before releasing.

`gen_game_includes.py` reads `shared.config.ORIGINAL_GAME_FILES` /
`ORIGINAL_GAME_FOLDERS` into `game_includes.inc`, so the installer's "copy the
original game" step copies exactly that whitelist and nothing else — copying a
folder that already has the mod (or another patch) installed won't bake stale
files into the fresh copy, since anything not on the list is never copied.
