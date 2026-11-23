"""
backend/commentary_deploy.py — put the new commentary name clips in the game
==============================================================================
The game reads its commentary from Audio/dat_eng.big + Audio/hdr_eng.big
(shared/speech_bank.py). The new clips of the mod data (shared/commentary.py
custom_clips: clips made with tools/voicegen and the user's own recordings,
converted here) are added to copies of the stock archives:

    Audio/dat_eng.big.stock, hdr_eng.big.stock   the originals, kept once
    Audio/dat_eng.big, hdr_eng.big               stock + the new clips
    Audio/commentary.stamp                       which clips they hold

In the archives the new clips are numbered from 3000 in id order
(commentary.game_ids), which the match data uses too (commentary.in_game).

The archives are rebuilt only when the set of clips changed, and put back to
the originals when there are no new clips.

    deploy(game_dir=None) -> "built" | "unchanged" | "restored" | "none" | "skipped"
"""
import hashlib
import os
import shutil

from shared import commentary, speech_bank
from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

ARCHIVES = ("dat_eng.big", "hdr_eng.big")
STOCK_SUFFIX = ".stock"
STAMP = "commentary.stamp"


#: bump when what is written for the same clips changes
LAYOUT = "2"


def _stamp(clips):
    """What the archives were built from: the clips and the ids the game
    knows them by."""
    h = hashlib.sha1(f"layout {LAYOUT}\n".encode())
    ids = commentary.game_ids(clips)
    for cid in sorted(clips):
        name, path = clips[cid]
        st = os.stat(path)
        h.update(f"{cid}>{ids[cid]}|{name}|{st.st_size}|{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _has_custom(entries):
    return any(cid >= commentary.CUSTOM_BASE for cid in speech_bank.clip_ids(entries))


def deploy(game_dir=None, clips=None):
    audio = os.path.join(game_dir or config.R08_directory, "Audio")
    live = [os.path.join(audio, n) for n in ARCHIVES]
    stock = [p + STOCK_SUFFIX for p in live]
    stamp_path = os.path.join(audio, STAMP)
    clips = commentary.custom_clips() if clips is None else clips
    if not all(os.path.isfile(p) for p in live):
        if clips:
            log.warning("Audio/dat_eng.big or hdr_eng.big missing: new commentary clips not added")
        return "skipped"

    if not clips:
        if all(os.path.isfile(p) for p in stock):
            for s, p in zip(stock, live):
                shutil.copy2(s, p)
            if os.path.exists(stamp_path):
                os.remove(stamp_path)
            log.info("Commentary archives back to the stock ones")
            return "restored"
        return "none"

    stamp = _stamp(clips)
    if _read(stamp_path) == stamp and all(os.path.isfile(p) for p in stock):
        return "unchanged"

    try:
        for s, p in zip(stock, live):
            if not os.path.isfile(s):
                if _has_custom(speech_bank.read_big(p)):
                    raise ValueError(f"{os.path.basename(p)} already holds new clips "
                                     "and its original is missing")
                shutil.copy2(p, s)
        dat, hdr = speech_bank.read_big(stock[0]), speech_bank.read_big(stock[1])
        new = []
        ids = commentary.game_ids(clips)
        for cid in sorted(clips):
            name, path = clips[cid]
            try:
                new.append((ids[cid], name, commentary.clip_data(path)))
            except (OSError, ValueError) as e:
                log.warning(f"Commentary clip {os.path.basename(path)} left out: {e}")
        dat, hdr = speech_bank.add_clips(dat, hdr, new)
        for path, entries, marker in ((live[0], dat, False), (live[1], hdr, True)):
            tmp = path + ".tmp"
            speech_bank.write_big(tmp, entries, marker=marker)
            os.replace(tmp, path)
        with open(stamp_path, "w", encoding="utf-8") as f:
            f.write(stamp + "\n")
    except (OSError, ValueError) as e:
        log.error(f"New commentary clips not added: {e}")
        return "skipped"
    log.info(f"Commentary: {len(new)} new name clips added to the game's archives")
    return "built"
