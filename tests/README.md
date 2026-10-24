# Tests

```
pip install -r tests/requirements-test.txt
pytest                       # everything (about 40 s)
pytest -m "not data"         # logic only: no dependency on data/ (works after the repo split)
pytest -m "not slow and not qt"   # quickest loop while coding
pytest tests/unit/test_challenges.py -k wind     # one area
pytest --cov=src --cov-report=term-missing      # what isn't covered yet
```

Nothing in the suite touches your own `user_data/`, your Rugby 08 install or
your Wine prefix: `conftest.py` loads the app on a throwaway config (an empty
fake `Rugby08.exe`, the fixture data pack, a temp `user_data/`), and any
attempt to edit the Wine registry or start the game fails the test.

## Layout

| Folder | What | Data used |
|---|---|---|
| `data/` | the real `data/` folder checked with the editors' own rules: every team folder, team season, kit asset, player, challenge and competition template is its own test case | real `data/` (skipped if absent) |
| `unit/` | pure logic: difficulty, coin toss, challenges and objectives, variants, team/player ops, ratings, names, tournament engine, game profile, FSH/BIG/RefPack codecs, 3D models, config, loaders, music download, match result decoding | fixture pack |
| `files/` | files written for the game (.mis, roster, game strings, clean-up) and the editors' JSON save path, against golden files; roster import | fixture pack |
| `pipeline/` | match setup → match_data → every game file, for quick match, challenges and a tournament fixture (and the result fed back), without the game | fixture pack |
| `qt/` | the real main window booted offscreen: every screen opens, editor save flows, start-up, `--selftest` | fixture pack |
| `regressions/` | one test per fixed bug, with its commit; index of the ones tested next to their feature | fixture pack |
| `MANUAL_CHECKLIST.md` | what only the real game can show | — |

Markers: `data`, `slow`, `qt`, `game` (always skipped: see the checklist).

## The fixture pack (`fixtures/data/`)

A small, stable data pack cut from the real data: England, France, South
Africa and New Zealand in 2007 (disabled), 2008 and 2024, their players,
stadiums, two competitions and three challenges; every image an 8×8
placeholder. Logic tests use it so they don't change with every season update.
Rebuild it only to change it (`python3 tests/fixtures/make_fixture_data.py`),
then update the golden files.

## Golden files (`golden/`)

Expected outputs: the mission file, match_data, the generated game files'
hashes, a seeded tournament, the stock roster summary. A difference fails the
test with a diff. When the change is intended:

```
pytest --update-golden
git diff tests/golden        # read it: this IS the behaviour change
```

## Known data issues (`data/known_issues.txt`)

The data problems present when the suite was written. A listed test xfails;
once the problem is fixed the test fails with "remove from known_issues" so
the list only shrinks. A problem that is not listed fails normally: fix the
data, or (if it is really accepted) add the test id with a comment.

## Suspected bugs found by the suite

Marked `xfail(strict=True)`, so they show as `x` until fixed — then they fail,
asking for the marker to be removed:

- `unit/test_codecs.py::test_fshlib_matches_mod_utils_on_a8r8g8b8`: the 3D
  preview's FSH reader swaps red and blue on A8R8G8B8 textures (stock kit).
- `files/test_game_files.py::test_roster_height_rounded_to_nearest_inch`: the
  roster writer truncates heights to the inch (178 cm is written as 176).

## Adding a feature or fixing a bug

- **Bug fix**: write the test first, in `regressions/` (or next to the
  feature), check it fails, fix, check it passes. Name it after the bug and
  cite the commit.
- **Feature**: test the logic in `unit/`; if it changes a file the game reads,
  extend `files/` or `pipeline/` and update the golden files; if it adds a
  screen, add it to `qt/test_screens.py::SCREENS`.
- **New data rule** (something the game needs from the data): add it to the
  editors' checks (`app/game_data.py`), the `data/` tests pick it up.
