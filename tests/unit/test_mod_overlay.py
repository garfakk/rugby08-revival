"""user_data/mod_data/: the user's own files laid over the data pack."""
import os

from shared import mod_overlay as M


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _read(path):
    with open(path) as f:
        return f.read()


def _setup(tmp_path):
    pack, user = str(tmp_path / "pack"), str(tmp_path / "user")
    _write(os.path.join(pack, "VERSION"), "data_version=1")
    _write(os.path.join(pack, "players", "skins", "a.png"), "pack-a")
    _write(os.path.join(pack, "teams", "Agen", "kits_2024", "home_front.webp"), "pack-kit")
    return pack, user


def test_structure_and_readme_created(tmp_path):
    _pack, user = _setup(tmp_path)
    M.ensure_structure(user)
    for rel in M.STRUCTURE:
        assert os.path.isdir(os.path.join(user, "mod_data", *rel.split("/")))
    assert os.path.isfile(os.path.join(user, "mod_data", M.README_NAME))


def test_empty_overlay_reads_the_pack_itself(tmp_path):
    pack, user = _setup(tmp_path)
    M.ensure_structure(user)
    assert M.effective_directory(pack, user) == pack
    assert not os.path.exists(os.path.join(user, "cache"))


def test_user_files_replace_and_add(tmp_path):
    pack, user = _setup(tmp_path)
    M.ensure_structure(user)
    ov = os.path.join(user, "mod_data")
    _write(os.path.join(ov, "players", "skins", "a.png"), "mine-a")                 # replaces
    _write(os.path.join(ov, "players", "heads", "new.big"), "head")                 # adds
    _write(os.path.join(ov, "teams", "Mine", "mine.json"), "{}")                    # new team
    eff = M.effective_directory(pack, user)
    assert eff != pack
    assert _read(os.path.join(eff, "players", "skins", "a.png")) == "mine-a"
    assert _read(os.path.join(eff, "players", "heads", "new.big")) == "head"
    assert _read(os.path.join(eff, "teams", "Agen", "kits_2024", "home_front.webp")) == "pack-kit"
    assert os.path.isfile(os.path.join(eff, "teams", "Mine", "mine.json"))
    assert _read(os.path.join(eff, "VERSION")) == "data_version=1"
    # the pack is untouched
    assert _read(os.path.join(pack, "players", "skins", "a.png")) == "pack-a"


def test_changes_are_picked_up_and_never_written_through_to_the_pack(tmp_path):
    pack, user = _setup(tmp_path)
    M.ensure_structure(user)
    ov = os.path.join(user, "mod_data")
    mine = os.path.join(ov, "players", "skins", "a.png")
    _write(mine, "v1")
    eff = M.effective_directory(pack, user)
    _write(mine, "version-two")                     # size changes: seen
    assert M.effective_directory(pack, user) == eff
    assert _read(os.path.join(eff, "players", "skins", "a.png")) == "version-two"
    assert _read(os.path.join(pack, "players", "skins", "a.png")) == "pack-a"
    os.remove(mine)                                 # back to the pack's own file
    _write(os.path.join(ov, "players", "heads", "x.big"), "x")
    eff = M.effective_directory(pack, user)
    assert _read(os.path.join(eff, "players", "skins", "a.png")) == "pack-a"


def test_new_pack_content_reaches_the_mirror(tmp_path):
    pack, user = _setup(tmp_path)
    M.ensure_structure(user)
    _write(os.path.join(user, "mod_data", "players", "heads", "x.big"), "x")
    eff = M.effective_directory(pack, user)
    _write(os.path.join(pack, "players", "skins", "b.png"), "pack-b")      # an update adds a file
    eff = M.effective_directory(pack, user)
    assert _read(os.path.join(eff, "players", "skins", "b.png")) == "pack-b"
