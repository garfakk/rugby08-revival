#!/usr/bin/env python3
"""Generate the Inno include file for a staged data pack: one entry that
copies the whole staged data directory (players, teams, stadiums,
tournaments, VERSION...) unconditionally -- the installer always does a
full install, there is no per-team selection.
usage: gen_data_inc.py <staged data dir> <output dir>"""
import os
import sys

_data_dir, out_dir = sys.argv[1], sys.argv[2]

files = [
    'Source: "{#DataDir}\\*"; DestDir: "{code:DataDir}"; '
    'Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall',
]

os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, "data_files.inc"), "w", encoding="utf-8").write("\n".join(files) + "\n")
print("data_files.inc written")
