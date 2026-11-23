# Commentary voices

Makes new player-name clips for the match commentary, in the voice of the
stock commentator, for the surnames the game has no clip for.

The voice comes from the game itself: F5-TTS (zero-shot voice cloning) is
given a few of the stock name clips from `Audio/dat_eng.big` as the voice
reference and says the new name the same way. No training step: the stock
clips are read from your game install on first start.

## Setup

Needs the game folder set in `user_data/config.ini` (the mod's first run does
it) and, for usable speed, an NVIDIA GPU (a GTX 1650 makes a take in ~6 s).

    python3 -m venv tools/voicegen/.venv
    tools/voicegen/.venv/bin/pip install -r tools/voicegen/requirements.txt
    tools/voicegen/.venv/bin/python tools/voicegen/app.py

The first start downloads the model (~1.4 GB, Hugging Face cache).

## Use

- **To make**: the players' surnames with no clip saying them, most used
  first. Pick one, *Make takes*, listen, *Use* the good one.
- **Say it as**: spell the name the way it sounds when a take gets it
  wrong (`Ntamack` -> `Un-ta-mack`), then make takes again.
- **Made**: the clips made so far (*auto* = kept by *Make all* without
  listening).
- **Make all**: goes down the list and keeps the best take of each.

Clips are written to the data pack, `data/commentary/<id>_<Name>.dat`
(ids from 3000), with `voicegen.json` noting how each was made. Before a
match the mod adds them to the game's speech archives
(`src/backend/commentary_deploy.py`, originals kept as `*.big.stock`) and a
player whose clip is none or a sound-alike gets the one saying their surname
(`shared/commentary.match_clip`).
