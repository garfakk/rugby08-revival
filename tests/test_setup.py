"""The test setup itself: the app is loaded on the fixture pack, never on the
user's own config, data or game."""
import os

from conftest import FAKE_GAME, FIXTURE_DATA, ROOT, USER_DATA
from shared.app_paths import user_data_directory
from shared.config import config


def test_config_is_isolated():
    assert user_data_directory() == USER_DATA
    assert not USER_DATA.startswith(ROOT)
    assert config.R08_directory == FAKE_GAME
    assert config.mod_data_directory == FIXTURE_DATA
    assert config.directory_teams == os.path.join(FIXTURE_DATA, "teams")


def test_fixture_pack_loads(ds):
    names = {seasons[s]["name"] for seasons in ds.teams.values() for s in seasons}
    assert names == {"England", "France", "South Africa", "New Zealand"}
    assert len(ds.players) > 100
    assert ds.stadiums
    assert ds.tournaments


def test_data_dir_is_a_writable_copy(data_dir):
    assert config.directory_teams == os.path.join(data_dir, "teams")
    assert data_dir != FIXTURE_DATA
    assert os.path.isfile(os.path.join(data_dir, "players", "players.json"))
