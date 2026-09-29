#!/usr/bin/env python3
"""Generate the Inno include listing exactly what to copy for the installer's
"copy the original game" step: config.original_game_files and
config.original_game_folders, and nothing else.

Copying by explicit whitelist (instead of copying everything and excluding
what the mod is known to write) means a game folder that already has the mod
- or another patch - installed can't bake stale/foreign files into what's
supposed to be a clean copy: anything not on the list is simply never copied.

usage: gen_game_includes.py <output dir>
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from shared.original_game_files import ORIGINAL_GAME_FILES, ORIGINAL_GAME_FOLDERS  # noqa: E402

out_dir = sys.argv[1]


def q(s):  # Inno string quoting
    return s.replace('"', '""')


lines = []
for name in ORIGINAL_GAME_FILES:
    lines.append(
        'Source: "{code:GameSrcDir}\\%s"; DestDir: "{code:GameDestDir}"; '
        'Flags: external skipifsourcedoesntexist onlyifdoesntexist uninsneveruninstall; '
        'Check: WantCopy' % q(name)
    )
for name in ORIGINAL_GAME_FOLDERS:
    lines.append(
        'Source: "{code:GameSrcDir}\\%s\\*"; DestDir: "{code:GameDestDir}\\%s"; '
        'Flags: external recursesubdirs createallsubdirs skipifsourcedoesntexist onlyifdoesntexist uninsneveruninstall; '
        'Check: WantCopy' % (q(name), q(name))
    )

os.makedirs(out_dir, exist_ok=True)
with open(os.path.join(out_dir, "game_includes.inc"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"{len(ORIGINAL_GAME_FILES)} files, {len(ORIGINAL_GAME_FOLDERS)} folders to copy")
