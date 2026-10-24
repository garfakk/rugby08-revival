"""Every challenge of the real data can be played as it stands (the same
check challenge mode makes before offering it)."""
import pytest

from app import challenges as C

from realdata import challenge_files, load_json, store

pytestmark = pytest.mark.data


@pytest.mark.parametrize("path", challenge_files())
def test_challenge_playable(path, known_issue):
    known_issue(C.problems(store(), C.normalise(load_json(path))))
