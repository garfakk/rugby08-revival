"""Original game files/folders (relative to the game install folder).

Kept in its own module, separate from shared.config, so build-time tooling
(packaging/gen_game_includes.py) can read the list without importing
shared.config, which instantiates a live Config() at module load and requires
a config.ini / app runtime to already exist.
"""

ORIGINAL_GAME_FILES = ["Rugby08.exe", "rugby.ico", "readme.en-uk.txt", "readme.fr-fr.txt"]
ORIGINAL_GAME_FOLDERS = ["Audio", "Data"]
