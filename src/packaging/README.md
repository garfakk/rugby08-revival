# Release pipeline (Windows build on Linux via wine)

    ./release.sh          # all artifacts + smoke test  -> ~/r08-build/out/
    ./release.sh app      # program only
    ./release.sh data     # data pack only (reuses last program build)
    DATA_VERSION=2027.01 ./release.sh data     # e.g. new season

Versions: program = `APP_VERSION` in `shared/version.py`; data = `DATA_VERSION` env
(default: today). Bump `DATA_SCHEMA` there only when the data layout changes in a way
old programs/new data (or vice versa) can't handle — the app warns on mismatch.

## Kit previews
Every build first regenerates each kit's preview image (`previewFile`, the
picture the menus show without the live 3D player) from the 3D model: same
mannequin for all, facing the camera, transparent background, 512×512. Existing
previews are overwritten; a kit without one gets `<kit>_preview.png` beside its
front texture, written into its team file. It writes into the data folder
(`$DATA`), so commit the result in the data repo. Needs the game (generic
textures from its `data.gob`, folder from `user_data/config.ini`) and OpenGL.

    python3 src/packaging/gen_kit_previews.py                 # by hand, all teams
    python3 src/packaging/gen_kit_previews.py --team England  # one team
    python3 src/packaging/gen_kit_previews.py --dry-run -v    # list only
    SKIP_KIT_PREVIEWS=1 ./release.sh                          # build without it

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

## Publishing updates (online updates in the mod)
The mod checks GitHub Releases (Tools › Updates, and once a day at startup: Settings ›
Check For Updates). Program and data have separate life cycles and tags:

| channel | tag | assets | what the mod does |
|---|---|---|---|
| program | `v<APP_VERSION>` | `R08Revival_<v>_program_only.exe`, `SHA256SUMS`, `manifest.json` (+ full setup, portable zip) | downloads the program-only installer, checks it against `SHA256SUMS`, closes itself and runs it visibly (`/SILENT /DIR=<install> /RELAUNCH=1`); the installer reopens the mod |
| data | `data-<DATA_VERSION>` | `data_manifest.json` (+ data setup) | downloads **only the files that differ** from the install, each verified against its sha256, from `raw.githubusercontent.com/<repo>/<commit>/<prefix>/<path>`, then applies them with backups (undoable) |

    ./release.sh                 # builds; the data step writes data_manifest.json + mod_data/MANIFEST.json
    ./publish.sh program         # gh release create v<ver> ...
    ./publish.sh data            # gh release create data-<ver> ... --target <data commit>

- `gen_data_manifest.py` refuses data that is not exactly the committed data (git blob ids
  compared with `git ls-tree`): commit **and push** the data before building, since users fetch
  files from that commit. `publish.sh` checks the commits are pushed.
- A data release is offered only to programs with the same `DATA_SCHEMA`; set
  `DATA_MIN_PROGRAM=<ver>` for `release.sh` when a data release needs a newer program.
  Bumping `DATA_SCHEMA` means: publish the program first, then the data for it.
- An install's `mod_data/MANIFEST.json` records what it has; installs from before it are hashed
  once by the mod (only files of the expected size).
- Data updates never write executables or scripts (`.exe .dll .bat .ps1 ...` are refused) nor
  outside `mod_data/`; program DLLs/assets only travel with the program installer.
- **Splitting the data into its own repository**: change `data.repo` in
  `src/update_sources.json` (shipped with the next program; users can also set
  `[Updates] data_repo = owner/name` in `user_data/config.ini`) and point `release.sh` at it
  (`R08_DATA=`). The manifest's `source` (repo, commit, prefix = the data folder's path inside
  its repo, "" at the root) is written from that repository, and the mod follows the manifest.
- Draft and pre-release releases are never offered: `DRAFT=1 ./publish.sh ...` to check a
  release before making it public.

### Antivirus
What the updater does to stay clear of heuristics: the running exe never rewrites itself or
drops scripts/helpers; program updates run the same Inno installer users run by hand, visibly,
after a click and a SHA-256 check; only HTTPS to GitHub, with an honest User-Agent; nothing
written outside the install folder; no PowerShell, scheduled task or Run key. PyInstaller
is already built without UPX and with a version resource. What only you can do, in order of
effect:
1. **Sign** `R08Revival.exe` and the installers (Authenticode): free for open source through
   SignPath.io (Foundation) or a Certum Open Source certificate; add `SignTool=` to
   `installer.iss` so Inno signs the setup and the uninstaller.
2. Submit each new release to the Microsoft Defender false-positive portal
   (https://www.microsoft.com/wdsi/filesubmission) before announcing it.
3. Optionally build PyInstaller's bootloader from source (generic "PyInstaller" signatures
   target the prebuilt one).

Test on the Win10 VM: an in-app program update (installer runs, mod reopens) and a data
update + undo, with Defender on.

## Layout
`R08Revival.spec` PyInstaller · `installer.iss` one Inno script, 3 variants ·
`gen_data_inc.py` staged-data-pack file list · `gen_data_manifest.py` online data-update manifest ·
`publish.sh` GitHub Releases · `gen_game_includes.py` game-copy includes ·
`fetch_audio.sh`/`pack_audio.sh` menu music (release asset, not in git) ·
`smoke_test.sh` · `RELEASE_README.txt` (shipped)

`assets/static_files/` holds the prebuilt `d3d8.dll` / `rugby08patches.dll` copied from the
reR08 repo — refresh them there before releasing.

`gen_game_includes.py` reads `shared.config.ORIGINAL_GAME_FILES` /
`ORIGINAL_GAME_FOLDERS` into `game_includes.inc`, so the installer's "copy the
original game" step copies exactly that whitelist and nothing else — copying a
folder that already has the mod (or another patch) installed won't bake stale
files into the fresh copy, since anything not on the list is never copied.
