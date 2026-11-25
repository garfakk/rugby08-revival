"""The match referee: head and kit put over the stock referee's, and his
strictness rules for the .mis.

The engine builds the referee every match from DB record 45000. He always
wears head players/heads/45000 and kit slot 2: kit/kits/referee.a (orange) or
referee.d (green), whichever the game picks (config+0x18f8), with the matching
.numbers file on the back. A chosen referee goes over all of them as loose
files next to the exe. clean_generated_files removes them before every match
(they are in game_filenames["referee"]), so a match without a chosen referee
gets the stock one back.

match_data["referee"] (frontend app/match_data_builder._referee):
  {"id", "name",
   "face": stock face id (int) or a head .big in mod data,
   "kit_front": "stock:<a-f>" or a kit .png/.big in mod data,
   "kit_back": "" or a back .png/.fsh in mod data,
   "rules": {"ref_<key>": value}}  -> <MISSION> attributes, reR08 refrules.cpp
An empty dict (or no key) = the stock referee.

The referee's name is not in the game's roster (no record 45000 there), so it
only shows in the frontend.
"""
import hashlib
import os

from shared.config import config
from shared.log import get_logger
from backend import mod_utils
from backend.game_specific_variables import game_filenames

log = get_logger(__name__)

STOCK_FACES = (45000, 45001, 45002, 45003, 45004, 45005)
# referee.a/b/c are the same orange kit and d/e/f the same green one; only a
# and d have a .numbers file
STOCK_KITS = ("a", "d")


def _cache(name):
  return os.path.join(config.temp_directory, name)


def _from_gob(game_path, ext, cached):
  """Local copy of data.gob entry `game_path` (cached), or None."""
  if os.path.isfile(cached):
    return cached
  gob = config.R08_data_gob_filepath
  if not os.path.isfile(gob):
    return None
  entry = hashlib.md5(game_path.encode()).hexdigest() + "." + ext
  folder = os.path.dirname(cached)
  try:
    os.makedirs(folder, exist_ok=True)
    result = mod_utils.extract_files_from_big_archive(gob, entry, folder)
    if not result or not result.get(entry):
      return None
    os.replace(os.path.join(folder, entry), cached)
  except OSError as e:
    log.warning(f"stock {game_path}: {e}")
    return None
  return cached


def stock_kit_letter(kit):
  """'a' or 'd' for a "stock:<letter>" kit value, else None."""
  if isinstance(kit, str) and kit.startswith("stock:"):
    letter = kit[6:].strip().lower()[:1]
    if letter in "abc" and letter:
      return "a"
    if letter in "def" and letter:
      return "d"
  return None


def stock_kit_paths(letter, cache_dir=None):
  """(front .big, numbers .fsh) of stock referee kit `letter` ('a' or 'd'),
  extracted from data.gob; None for any it cannot get."""
  cache_dir = cache_dir or _cache("stock_referee")
  front = _from_gob(f"kit/kits/referee.{letter}", "big",
                    os.path.join(cache_dir, f"referee.{letter}.big"))
  numbers = _from_gob(f"kit/kits/referee.{letter}.numbers", "fsh",
                      os.path.join(cache_dir, f"referee.{letter}.numbers.fsh"))
  return front, numbers


def _mod_path(rel):
  return os.path.join(config.mod_data_directory, rel) if rel else ""


def _head_source(face):
  """The head .big to wear, or None to keep the stock referee's head."""
  if face in (None, ""):
    return None
  if isinstance(face, int) or (isinstance(face, str) and face.isdigit()):
    face = int(face)
    if face == 45000:
      return None
    return mod_utils.stock_head_path(face, _cache("stock_heads"))
  path = _mod_path(face)
  if not os.path.isfile(path):
    log.warning(f"referee head {face} not found, stock head kept")
    return None
  if mod_utils.head_too_heavy(path):
    log.warning(f"referee head {face} too heavy for the game, stock head kept")
    return None
  return path


def preview_files(face, kit, kit_back=""):
  """(head, front, back) files to show referee `face` in `kit` on a 3D
  stage (ui.player_stage.KitStage); each "" when there is none."""
  face = str(face if face is not None else "")
  if face.isdigit():
    head = mod_utils.stock_head_path(int(face), _cache("stock_heads")) or ""
  else:
    head = _mod_path(face) if face and os.path.isfile(_mod_path(face)) else ""
  letter = stock_kit_letter(kit or "stock:a")
  if letter:
    front, numbers = stock_kit_paths(letter)
  else:
    front, numbers = _mod_path(kit), stock_kit_paths("a")[1]
  if kit_back and os.path.isfile(_mod_path(kit_back)):
    numbers = _mod_path(kit_back)
  return head, front or "", numbers or ""


def _kit_files(kit_front, kit_back, work_dir):
  """(front .big, numbers .fsh) built for this referee, or (None, None)."""
  letter = stock_kit_letter(kit_front)
  if letter:
    return stock_kit_paths(letter)
  if not kit_front:
    return None, None
  source = _mod_path(kit_front)
  if not os.path.isfile(source):
    log.warning(f"referee kit {kit_front} not found, stock kit kept")
    return None, None
  base_front, base_numbers = stock_kit_paths("a")
  if source.lower().endswith(".big"):
    front = source
  else:
    if base_front is None:
      log.warning("referee kit: no stock referee kit to build on (game not found?)")
      return None, None
    os.makedirs(work_dir, exist_ok=True)
    front = os.path.join(work_dir, "referee_front.big")
    kit_fsh = os.path.join(work_dir, "kit.fsh")
    mod_utils.copy_file(base_front, front)
    if not _extract_big_entry(front, "kit.fsh", kit_fsh):
      return None, None
    if not mod_utils.replace_asset_in_fsh_file(kit_fsh, source, index=0):
      return None, None
    if not mod_utils.add_file_to_big_archive(front, kit_fsh):
      return None, None
  numbers = base_numbers
  back = _mod_path(kit_back)
  if kit_back and os.path.isfile(back):
    if back.lower().endswith(".fsh"):
      numbers = back
    elif base_numbers is not None:
      os.makedirs(work_dir, exist_ok=True)
      numbers = os.path.join(work_dir, "referee_numbers.fsh")
      mod_utils.copy_file(base_numbers, numbers)
      if not mod_utils.replace_asset_in_fsh_file(numbers, back, index=0):
        numbers = base_numbers
  return front, numbers


def _extract_big_entry(big, name, out_path):
  folder = os.path.dirname(out_path)
  result = mod_utils.extract_files_from_big_archive(big, name, folder, decompress=True)
  if not result or not result.get(name):
    log.warning(f"referee kit: no {name} in {big}")
    return False
  extracted = os.path.join(folder, name)
  if extracted != out_path:
    os.replace(extracted, out_path)
  return True


def deploy(match_data, game_dir=None):
  """Put the chosen referee's head and kit next to the exe. Returns the game
  file names written (nothing for the stock referee)."""
  referee = match_data.get("referee") or {}
  game_dir = game_dir or config.game_launcher_directory
  names = game_filenames["referee"]
  written = []
  head = _head_source(referee.get("face"))
  if head and mod_utils.copy_texture_file(head, os.path.join(game_dir, names["head"])):
    written.append(names["head"])
  front, numbers = _kit_files(referee.get("kit_front"), referee.get("kit_back"),
                              os.path.join(config.temp_directory, "referee_kit"))
  if front:
    for key in ("kit_a", "kit_d"):
      if mod_utils.copy_file(front, os.path.join(game_dir, names[key])):
        written.append(names[key])
  if front and numbers:
    for key in ("numbers_a", "numbers_d"):
      if mod_utils.copy_file(numbers, os.path.join(game_dir, names[key])):
        written.append(names[key])
  if written:
    log.info(f"Referee: {referee.get('name') or referee.get('id') or '?'}")
  return written


def mission_rules(match_data):
  """The referee's ref_* rules as <MISSION> attribute strings (reR08
  refrules.cpp reads them); any other key is dropped."""
  out = {}
  for key, value in ((match_data.get("referee") or {}).get("rules") or {}).items():
    if not (isinstance(key, str) and key.startswith("ref_")) or value is None:
      continue
    if isinstance(value, bool):
      value = int(value)
    if isinstance(value, (list, tuple)):
      value = ",".join(str(v) for v in value)
    out[key] = str(value)
  return out
