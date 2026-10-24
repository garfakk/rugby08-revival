# Manual checks (real game)

What the automated suite cannot see, because it needs Rugby08.exe running.
Run before each release, on Windows and on Linux/Wine. The last column says
which automated test already covers the offline part, so a failure here
points at the game side.

| # | Check | How | Offline part covered by |
|---|---|---|---|
| 1 | The game launches, loads the match and is embedded (or revealed fullscreen) | Quick match, windowed then fullscreen mod | `pipeline/test_match_pipeline.py::test_quick_match_writes_every_game_file` |
| 2 | The d3d8 proxy is active (no resolution switch, window embeddable) | `rugby08_patches.log` next to the exe has a new session; game window inside the mod | — |
| 3 | Teams, names, kits, crests, ball, banners are the ones picked | England v France, check shirts/names/scoreboard | `files/test_game_files.py` (roster read back, team names), pipeline golden hashes |
| 4 | Wind blows the chosen way (0° = tailwind for home in the 1st half) | Advanced: wind strong, 0°, kick a high ball; `HOME_ATTACKS_Z_FIRST_HALF` is not yet confirmed in-game | `unit/test_game_data.py::test_wind_world_xz`, `pipeline/...::test_wind_uses_attack_sign` |
| 5 | Crowd sound plays in game and follows the Crowd volume setting | Settings > Audio > Crowd, then a match | `unit/test_game_profile.py::test_vol_crowd_set_deploy_read` |
| 6 | A carded player starts in the sin bin (needs the patches DLL) | Challenge with `cards` | `files/test_game_files.py::test_advanced_fields_written` (`<EVENTS><CARD>`) |
| 7 | No crash when loading is slow | Slow-CPU recipe (memory note: `taskset` to one core); Xvfb crashes are a false lead | `regressions/test_fixed_bugs.py::test_804d31ee_*` |
| 8 | Full-time result read back: post-match stats, challenge objectives judged, tournament result recorded | Play a short (2 min) match to the end in each mode | `unit/test_match_result.py`, `unit/test_challenge_objectives.py`, `pipeline/...::test_tournament_fixture_to_game_and_back` |
| 9 | In-game option changes (pause menu) are kept for the next match | Change camera/volume in game, quit, start another match | `unit/test_game_profile.py::test_import_ingame_keeps_changed_settings` |
| 10 | Difficulty legend/immortal: CPU side visibly stronger, human side tires | Legend vs a weak team | `unit/test_difficulty.py` |
| 11 | Challenge restart (penalty/lineout) starts at the right spot and half | Penalty challenge | `unit/test_challenges.py` (geometry) |
| 12 | Installer: silent install, data pack backup/restore, uninstall keeps user_data | `src/packaging/smoke_test.sh` (Wine) | `qt/test_startup.py::test_selftest_subprocess` |
