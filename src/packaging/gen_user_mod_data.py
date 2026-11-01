"""gen_user_mod_data.py <dir> — stage the empty user_data/mod_data/ tree
(shared/mod_overlay.py: STRUCTURE + README) that the installers and the portable
zip ship, so users see where to put their own heads, skins, kits..."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared import mod_overlay  # noqa: E402

if __name__ == "__main__":
    out = sys.argv[1]
    for rel in mod_overlay.STRUCTURE:
        os.makedirs(os.path.join(out, *rel.split("/")), exist_ok=True)
    with open(os.path.join(out, mod_overlay.README_NAME), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(mod_overlay.README)
