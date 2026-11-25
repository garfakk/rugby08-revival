"""The match referee: the referee store (app/referees.py), what a match's
match_data carries, the tournament draw, and the files put next to the exe
(backend/referee.py)."""
import hashlib
import json
import os
import struct
import types

import pytest
from PIL import Image

from shared.config import config
from backend import game_specific_variables as gsv
from backend import referee as B
from app import referees as R


def _md5(path, ext):
    return hashlib.md5(path.encode()).hexdigest() + ext


def test_game_filenames_are_the_referee_slots():
    names = gsv.game_filenames["referee"]
    assert names["head"] == _md5("players/heads/45000", ".big")
    assert names["kit_a"] == _md5("kit/kits/referee.a", ".big")
    assert names["kit_d"] == _md5("kit/kits/referee.d", ".big")
    assert names["numbers_a"] == _md5("kit/kits/referee.a.numbers", ".fsh")
    assert names["numbers_d"] == _md5("kit/kits/referee.d.numbers", ".fsh")


def test_referee_files_are_cleaned_before_each_match():
    from backend.game_files_processor import generated_game_filenames
    assert set(gsv.game_filenames["referee"].values()) <= generated_game_filenames()


# ── store ────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "referees").mkdir(parents=True)
    (data / "referees" / "referees.json").write_text(json.dumps({
        "zed": {"name": "Zed Ref", "face": "45001", "kit": "stock:d"},
        "amy": {"name": "Amy Ref", "face": "players/heads/amy.big", "kit": "referees/kits/amy.png",
                "rules": {"ref_whistle": 1.5}},
    }))
    monkeypatch.setattr(config, "mod_data_directory", str(data))
    monkeypatch.setattr(config, "directory_user_edits", str(tmp_path / "edits"))
    return data


def test_load_sorts_by_name_and_fills_defaults(store):
    refs = R.load()
    assert list(refs) == ["amy", "zed"]
    assert refs["zed"] == {"name": "Zed Ref", "face": "45001", "kit": "stock:d", "kit_back": "", "rules": {}}


def test_save_and_delete_are_the_users(store):
    R.save("zed", dict(R.load()["zed"], name="Zed Renamed"))
    R.save("new", {"name": "New One"})
    assert R.load()["zed"]["name"] == "Zed Renamed"
    assert R.load()["new"]["kit"] == "stock:a"
    assert json.loads((store / "referees" / "referees.json").read_text())["zed"]["name"] == "Zed Ref"
    R.delete("amy")
    R.delete("new")
    assert set(R.load()) == {"zed"}
    R.save("zed", R.pack()["zed"])            # back to the pack's: no edit kept
    assert "zed" not in json.loads(open(R.edits_file()).read())


def test_new_id_is_unique():
    assert R.new_id("Wayne Barnes", set()) == "wayne_barnes"
    assert R.new_id("Wayne Barnes", {"wayne_barnes"}) == "wayne_barnes_2"


def test_match_data_of_a_referee(store):
    refs = R.load()
    assert R.match_data(refs, None) == {}
    assert R.match_data(refs, "gone") == {}
    md = R.match_data(refs, "zed")
    assert md == {"id": "zed", "name": "Zed Ref", "face": 45001, "kit_front": "stock:d",
                  "kit_back": "", "rules": {}}
    assert R.match_data(refs, "amy")["face"] == "players/heads/amy.big"


def test_pick(store):
    refs = R.load()
    assert R.pick(refs, R.STOCK) is None
    assert R.pick(refs, "zed") == "zed"
    assert R.pick(refs, "gone") is None
    assert R.pick(refs, R.RANDOM) in refs


def test_builder_only_in_expert_mode(store, monkeypatch):
    from app.match_data_builder import _referee
    from shared.user_prefs import user_prefs
    ds = types.SimpleNamespace(referees=R.load())
    slot = types.SimpleNamespace(kit=lambda ds: {"color": "#ffffff"})
    cfg = types.SimpleNamespace(referee="zed", referee_kit="", home=slot, away=slot)
    monkeypatch.setattr(user_prefs, "expert_mode", False, raising=False)
    assert _referee(ds, cfg) == {}
    monkeypatch.setattr(user_prefs, "expert_mode", True, raising=False)
    assert _referee(ds, cfg)["name"] == "Zed Ref"
    cfg.referee_kit = "stock:a"
    assert _referee(ds, cfg)["kit_front"] == "stock:a"           # another kit on him
    cfg.referee = ""
    assert _referee(ds, cfg)["kit_front"] == "stock:a"           # on the game's own too
    assert _referee(ds, cfg)["face"] == ""
    cfg.referee_kit = ""
    assert _referee(ds, cfg) == {}


def test_tournament_draw(store):
    from app.tournament.bridge import fixture_referee
    refs = R.load()
    ds = types.SimpleNamespace(referees=refs)
    t = types.SimpleNamespace(options={}, seed=7)
    fixtures = [types.SimpleNamespace(id=f"f{i}") for i in range(30)]
    assert fixture_referee(ds, t, fixtures[0]) == ""            # the game's own
    t.options["referee"] = "zed"
    assert fixture_referee(ds, t, fixtures[0]) == "zed"
    t.options["referee"] = "gone"
    assert fixture_referee(ds, t, fixtures[0]) == ""
    t.options["referee"] = R.RANDOM
    drawn = [fixture_referee(ds, t, f) for f in fixtures]
    assert set(drawn) == {"amy", "zed"}                           # both get matches
    assert drawn == [fixture_referee(ds, t, f) for f in fixtures]   # the same every time
    assert R.draw(["zed", "gone"], refs, 1) == "zed"
    assert R.draw(["gone"], refs, 1) is None


# ── kits ─────────────────────────────────────────────────────────────────

@pytest.fixture
def kit_files(store):
    kits = store / "referees" / "kits"
    kits.mkdir()
    Image.new("RGB", (32, 32), (250, 230, 0)).save(kits / "yellow.png")
    Image.new("RGB", (32, 32), (0, 0, 0)).save(kits / "black.png")
    Image.new("RGB", (32, 32), (0, 0, 0)).save(kits / "black_back.png")
    return kits


def test_kits_are_stock_then_mod_files(kit_files):
    assert R.kits() == ["stock:a", "stock:d", "referees/kits/black.png", "referees/kits/yellow.png"]
    assert R.kit_label("stock:d") == "green" and R.kit_label("referees/kits/yellow.png") == "yellow"
    assert R.kit_back("referees/kits/black.png") == "referees/kits/black_back.png"
    assert R.kit_back("referees/kits/yellow.png") == "" == R.kit_back("stock:a")
    assert R.kit_colour("referees/kits/yellow.png") == (250, 230, 0)


def test_best_kit_stands_out_from_both_teams(kit_files):
    black, yellow = "referees/kits/black.png", "referees/kits/yellow.png"
    assert R.best_kit([black, yellow], ["#000000", "#101010"]) == yellow     # All Blacks
    assert R.best_kit([black, yellow], ["#ffff00", "#f0e000"]) == black      # two yellow sides
    assert R.best_kit(["stock:a", "stock:d"], ["#ff8000", "#ffffff"]) == "stock:d"
    assert R.best_kit([], ["#000000"]) is None
    assert R.best_kit([black], []) == black
    assert R.resolve_kit("", ["#000000"]) is None
    assert R.resolve_kit(R.AUTO_KIT, ["#000000", "#ffffff"]) in R.kits()
    assert R.resolve_kit("stock:d", ["#3c9646"]) == "stock:d"                # asked for: kept


def test_match_data_with_another_kit(kit_files):
    refs = R.load()
    md = R.match_data(refs, "zed", "referees/kits/black.png")
    assert md["face"] == 45001 and md["kit_front"] == "referees/kits/black.png"
    assert md["kit_back"] == "referees/kits/black_back.png"
    assert R.match_data(refs, None, "stock:d") == {"id": "", "name": "", "face": "", "kit_front": "stock:d",
                                                   "kit_back": "", "rules": {}}


def test_tournament_kits_per_fixture(kit_files):
    from app.tournament.bridge import fixture_referee_kit
    ds = types.SimpleNamespace(referees=R.load())
    t = types.SimpleNamespace(options={}, seed=3)
    f = types.SimpleNamespace(id="f1")
    black, yellow = "referees/kits/black.png", "referees/kits/yellow.png"
    assert fixture_referee_kit(ds, t, f, ["#000000", "#ffffff"]) == ""        # their own
    t.options["referee_kits"] = [black, yellow, "referees/kits/gone.png"]
    assert fixture_referee_kit(ds, t, f, ["#000000", "#202020"]) == yellow
    assert fixture_referee_kit(ds, t, f, ["#ffff00", "#ffffff"]) == black
    t.options["referee_kits"] = ["stock:a", "stock:d"]
    picks = {fixture_referee_kit(ds, t, types.SimpleNamespace(id=f"f{i}"), []) for i in range(20)}
    assert picks == {"stock:a", "stock:d"}                                     # no colours: drawn


# ── backend ──────────────────────────────────────────────────────────────

def _big(entries):
    """A BIGF archive of {name: bytes} (the layout extract_files_from_big_archive reads)."""
    names = list(entries)
    header = 16 + sum(8 + len(n) + 1 for n in names)
    out, offset, body = b"", header, b""
    for n in names:
        out += struct.pack(">II", offset, len(entries[n])) + n.encode() + b"\0"
        offset += len(entries[n])
        body += entries[n]
    total = header + len(body)
    return b"BIGF" + struct.pack("<I", total) + struct.pack(">II", len(names), header) + out + body


def _fsh(tag, size):
    """One DXT1 entry FSH of `size`x`size`."""
    pixels = b"\0" * (size * size // 2)
    entry = struct.pack("<IHHHHHH", 0x60, size, size, 0, 0, 0, 0) + pixels
    head = 16 + 8
    return (b"SHPI" + struct.pack("<I", head + len(entry)) + struct.pack("<I", 1) + b"G359"
            + tag.encode() + struct.pack("<I", head) + entry)


@pytest.fixture
def game(tmp_path, monkeypatch, store):
    """A game folder and a stock referee kit cache standing in for data.gob."""
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    monkeypatch.setattr(config, "game_launcher_directory", str(game_dir))
    monkeypatch.setattr(config, "temp_directory", str(tmp_path / "tmp"))
    cache = tmp_path / "tmp" / "stock_referee"
    cache.mkdir(parents=True)
    for letter in "ad":
        (cache / f"referee.{letter}.big").write_bytes(
            _big({"config.bin": b"\0" * 8, "kit.fsh": _fsh("kit0", 64)}))
        (cache / f"referee.{letter}.numbers.fsh").write_bytes(_fsh("jbck", 32) + letter.encode())
    heads = tmp_path / "tmp" / "stock_heads"
    heads.mkdir()
    (heads / "45003.big").write_bytes(b"BIGF-head-45003")
    (store / "players" / "heads").mkdir(parents=True)
    (store / "players" / "heads" / "amy.big").write_bytes(b"BIGF-head-amy")
    (store / "referees" / "kits").mkdir()
    Image.new("RGB", (64, 64), (255, 0, 0)).save(store / "referees" / "kits" / "amy.png")
    return game_dir


def test_stock_referee_writes_nothing(game):
    assert B.deploy({}) == []
    assert B.deploy({"referee": {}}) == []
    assert B.deploy({"referee": {"face": 45000}}) == []
    assert os.listdir(game) == []


def test_stock_head_and_kit(game):
    names = gsv.game_filenames["referee"]
    written = B.deploy({"referee": {"face": 45003, "kit_front": "stock:e"}})
    assert set(written) == set(names.values())
    assert (game / names["head"]).read_bytes() == b"BIGF-head-45003"
    green = open(os.path.join(config.temp_directory, "stock_referee", "referee.d.big"), "rb").read()
    assert (game / names["kit_a"]).read_bytes() == green == (game / names["kit_d"]).read_bytes()
    assert (game / names["numbers_a"]).read_bytes().endswith(b"d")


def test_custom_head_and_kit(game, monkeypatch):
    from backend import mod_utils
    monkeypatch.setattr(mod_utils, "head_too_heavy", lambda p: False)
    names = gsv.game_filenames["referee"]
    B.deploy({"referee": {"face": "players/heads/amy.big", "kit_front": "referees/kits/amy.png"}})
    assert (game / names["head"]).read_bytes() == b"BIGF-head-amy"
    stock = open(os.path.join(config.temp_directory, "stock_referee", "referee.a.big"), "rb").read()
    built = (game / names["kit_a"]).read_bytes()
    assert built[:4] == b"BIGF" and built != stock          # the image went into kit.fsh
    assert (game / names["numbers_a"]).read_bytes().endswith(b"a")


def test_too_heavy_head_is_left_out(game, monkeypatch):
    from backend import mod_utils
    monkeypatch.setattr(mod_utils, "head_too_heavy", lambda p: True)
    assert B.deploy({"referee": {"face": "players/heads/amy.big"}}) == []


def test_mission_rules_keep_ref_keys_only():
    md = {"referee": {"rules": {"ref_whistle": 1.5, "ref_knock_on": True, "anthem": "1",
                                "ref_offside_rand": [-1, 2], "ref_none": None}}}
    assert B.mission_rules(md) == {"ref_whistle": "1.5", "ref_knock_on": "1", "ref_offside_rand": "-1,2"}
    assert B.mission_rules({}) == {}


def test_rules_reach_the_mis(game):
    from backend import game_files_processor as GFP
    md = {"referee": {"rules": {"ref_whistle": 1.5}}, "team_A": {}, "team_B": {}}
    GFP.create_mission_file(md)
    text = open(os.path.join(config.game_launcher_directory, gsv.game_filenames["missionFile"])).read()
    assert 'ref_whistle="1.5"' in text


def test_shipped_referees_have_stock_heads_and_kits():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "referees", "referees.json")
    if not os.path.isfile(path):
        pytest.skip("no data/")
    refs = {rid: R.normalise(r) for rid, r in json.load(open(path)).items()}
    assert refs
    data = os.path.dirname(path)[:-len("referees")]
    for r in refs.values():
        assert r["name"]
        assert r["face"].isdigit() or os.path.isfile(os.path.join(data, r["face"]))
        assert r["kit"] in R.STOCK_KITS or os.path.isfile(os.path.join(data, r["kit"]))
        assert not r["kit_back"] or os.path.isfile(os.path.join(data, r["kit_back"]))
