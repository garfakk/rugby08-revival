"""Shared test setup.

Importing the app is only safe once this module has run: shared.config builds
its singleton at import time from <user_data>/config.ini, and without a valid
one it opens a first-run dialog or exits. So, before any app module is
imported, this points shared.app_paths.user_data_directory() at a throwaway
folder holding a config.ini whose game is a fake (empty) Rugby08.exe and whose
data is the fixture pack (tests/fixtures/data). The user's own user_data/ and
game install are never read or written.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
TESTS = os.path.join(ROOT, "tests")
FIXTURE_DATA = os.path.join(TESTS, "fixtures", "data")
REAL_DATA = os.path.join(ROOT, "data")
GOLDEN = os.path.join(TESTS, "golden")

# Same import roots as run.py.
sys.path[:0] = [os.path.join(SRC, "frontend"), SRC]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = tempfile.mkdtemp(prefix="r08-tests-")
USER_DATA = os.path.join(_APP, "user_data")
FAKE_GAME = os.path.join(_APP, "game")


def _write_config():
    os.makedirs(USER_DATA)
    os.makedirs(FAKE_GAME)
    open(os.path.join(FAKE_GAME, "Rugby08.exe"), "wb").close()
    with open(os.path.join(USER_DATA, "config.ini"), "w", encoding="utf-8") as f:
        f.write("[Main]\n"
                f"R08_directory = {FAKE_GAME}\n"
                "R08_filename = Rugby08.exe\n"
                f"data_directory = {FIXTURE_DATA}\n"
                "[Options]\n"
                f"temp_directory = {os.path.join(_APP, 'tmp')}\n")


_write_config()
import shared.app_paths as _app_paths  # noqa: E402  (must follow the config above)
_app_paths.user_data_directory = lambda: USER_DATA

from shared.config import config  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true",
                     help="rewrite tests/golden/ with the current outputs")


def pytest_collection_modifyitems(config, items):
    skip_game = pytest.mark.skip(reason="needs the real game (see tests/MANUAL_CHECKLIST.md)")
    skip_data = pytest.mark.skip(reason=f"no data folder at {REAL_DATA}")
    has_data = os.path.isdir(os.path.join(REAL_DATA, "teams"))
    for item in items:
        if "game" in item.keywords:
            item.add_marker(skip_game)
        if "data" in item.keywords and not has_data:
            item.add_marker(skip_data)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_APP, ignore_errors=True)


# ── config / data fixtures ───────────────────────────────────────────────
DATA_DIR_ATTRS = {
    "directory_teams": "teams",
    "directory_players": "players",
    "directory_stadiums": "stadiums",
    "directory_competitions": "competitions",
    "directory_challenges": "challenges",
}


def point_config(monkeypatch, data_dir=None, game_dir=None):
    """Re-point the config singleton (and every path derived from it, which
    config.py computes only once) at another data and/or game folder."""
    if data_dir:
        monkeypatch.setattr(config, "mod_data_directory", data_dir)
        for attr, sub in DATA_DIR_ATTRS.items():
            monkeypatch.setattr(config, attr, os.path.join(data_dir, sub))
    if game_dir:
        monkeypatch.setattr(config, "R08_directory", game_dir)
        monkeypatch.setattr(config, "game_launcher_directory", game_dir)
        monkeypatch.setattr(config, "game_launcher_executable_filepath",
                            os.path.join(game_dir, config.R08_filename))
        monkeypatch.setattr(config, "R08_data_gob_filepath",
                            os.path.join(game_dir, "Data", "data.gob"))


@pytest.fixture(scope="session")
def fixture_raw():
    """The fixture pack parsed once (DataStore.read_files)."""
    from app.state import DataStore
    return DataStore.read_files()


@pytest.fixture
def ds(fixture_raw):
    """A DataStore on the fixture pack. Each test gets its own deep copy, so
    a test may mutate it freely."""
    import copy
    from app.state import DataStore
    return DataStore(copy.deepcopy(fixture_raw))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A writable copy of the fixture pack, with config pointed at it."""
    dst = str(tmp_path / "data")
    shutil.copytree(FIXTURE_DATA, dst)
    point_config(monkeypatch, data_dir=dst)
    monkeypatch.setattr(config, "directory_tournament_saves", str(tmp_path / "tournaments"))
    return dst


@pytest.fixture
def game_dir(tmp_path, monkeypatch):
    """An empty fake game folder (with Rugby08.exe) the file writers write into."""
    d = tmp_path / "game"
    d.mkdir()
    (d / "Rugby08.exe").write_bytes(b"")
    point_config(monkeypatch, game_dir=str(d))
    monkeypatch.setattr(config, "temp_directory", str(tmp_path / "tmp"))
    os.makedirs(config.temp_directory, exist_ok=True)
    return str(d)


@pytest.fixture(scope="session")
def real_raw():
    """The real data/ folder parsed once, for the `data` checks."""
    from app.state import DataStore
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=REAL_DATA)
    try:
        return DataStore.read_files()
    finally:
        mp.undo()


@pytest.fixture(autouse=True)
def _no_system_side_effects(monkeypatch):
    """Nothing in a test may edit the user's Wine registry or start the game."""
    from backend import mod_utils
    from backend.R08_handler import R08_handler

    def forbidden(*args, **kwargs):
        raise AssertionError("a test tried to touch Wine or start the game")
    for name in ("ensure_wine_d3d8_native_override", "disable_wine_virtual_desktop",
                 "_wine_reg_add", "_wine_reg_delete"):
        monkeypatch.setattr(mod_utils, name, forbidden)
    monkeypatch.setattr(R08_handler, "start_R08_executable", forbidden)


@pytest.fixture(autouse=True)
def _fresh_globals():
    """Module-level caches that would leak between tests."""
    yield
    try:
        from app import plugin_lookup
        plugin_lookup._plugin = None
    except ImportError:
        pass
    # the user's edits (app/user_edits.py): each test starts with none, and
    # saves go nowhere until a DataStore is built
    assert config.directory_user_edits.startswith(_APP)    # never the real user_data
    shutil.rmtree(config.directory_user_edits, ignore_errors=True)
    try:
        from app import game_data
        game_data.set_edit_store(None)
    except ImportError:
        pass


# ── golden files ─────────────────────────────────────────────────────────
@pytest.fixture
def golden(request):
    """golden(name, value): compare `value` with tests/golden/<name>.

    str -> text file; dict/list -> JSON (sorted keys); bytes -> stored as its
    sha256 (the files are large binaries). --update-golden rewrites the file
    instead; review the diff in git before committing it."""
    update = request.config.getoption("--update-golden")

    def check(name, value):
        path = os.path.join(GOLDEN, name)
        if isinstance(value, bytes):
            text = hashlib.sha256(value).hexdigest() + "\n"
            path += ".sha256"
        elif isinstance(value, (dict, list)):
            text = json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        else:
            text = str(value)
        if update or not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            if not update:
                pytest.fail(f"golden file created: {os.path.relpath(path, ROOT)} "
                            "(review it, then re-run)")
            return
        with open(path, encoding="utf-8") as f:
            expected = f.read()
        if text != expected:
            import difflib
            diff = "".join(difflib.unified_diff(
                expected.splitlines(True), text.splitlines(True),
                "golden", "actual", n=2))
            pytest.fail(f"{os.path.relpath(path, ROOT)} differs "
                        f"(pytest --update-golden if intended):\n{diff[:4000]}")
    return check


# ── known data issues ────────────────────────────────────────────────────
def _load_known_issues():
    path = os.path.join(TESTS, "data", "known_issues.txt")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.split("#", 1)[0].strip() for line in f} - {""}


KNOWN_ISSUES = _load_known_issues()


@pytest.fixture
def known_issue(request):
    """Call with the test's problems (list of strings). Data problems listed in
    tests/data/known_issues.txt (by test id) are expected: the test xfails
    while they remain, and FAILS once they're fixed so the line gets removed.
    Anything not listed fails normally."""
    path, _, name = request.node.nodeid.partition("::")
    test_id = f"{os.path.basename(path)}::{name}"

    def check(problems):
        listed = test_id in KNOWN_ISSUES
        if problems and listed:
            pytest.xfail("known issue: " + "; ".join(problems)[:300])
        if not problems and listed:
            pytest.fail(f"fixed! remove '{test_id}' from tests/data/known_issues.txt")
        assert not problems, "\n" + "\n".join(problems)
    return check


# ── a match on the fixture pack ──────────────────────────────────────────
def make_match_config(ds, home=("10002", "2024"), away=("10001", "2024"), **fields):
    """A complete MatchConfig: England v France 2024 (fixture pack), the
    keyboard on the home side, fixed kick-off and ends so the output is
    deterministic. `fields` override any MatchConfig attribute."""
    from app.state import MatchConfig
    cfg = MatchConfig()
    for slot, (tid, season) in ((cfg.home, home), (cfg.away, away)):
        slot.team_id, slot.season = tid, season
        slot.lineup = ds.get_lineup(tid, season)
        slot.players = ds.get_players(slot.lineup["players_id"], season)
    sid = sorted(ds.stadiums, key=lambda s: int(s) if str(s).isdigit() else 0)[0]
    info = ds.stadiums[sid]
    cfg.stadium = {"stadium_id": int(info.get("game_id", sid)), "data": info}
    cfg.kick_off, cfg.home_team_side = "home", "left"
    cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    for key, value in fields.items():
        setattr(cfg, key, value)
    return cfg


@pytest.fixture
def match_data(ds):
    """build_match_data for make_match_config(ds) with a set wind."""
    from app.match_data_builder import build_match_data
    return build_match_data(ds, make_match_config(ds, wind_power=2, wind_dir_deg=90.0))
