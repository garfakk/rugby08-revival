"""Single source of truth for the program version (read by packaging/release.sh).

DATA_SCHEMA is the layout version of the data folder (players.json / teams /
stadiums / tournaments shapes). Bump it when the program can no longer read data
packs built for the previous value; data packs record the schema they were built
for in data/VERSION and the app warns on mismatch."""
APP_VERSION = "0.2.0"
DATA_SCHEMA = 1
