#!/usr/bin/env python3
"""Rugby 08 Revival launcher, running from source.

The repo root mirrors the released program folder (see src/shared/app_paths.py):

  run.py       this launcher (R08Revival.exe in the released build)
  src/         the program and its assets
  data/        the data pack (teams, players, stadiums, tournaments)
  user_data/   config.ini, preferences, saves; created at first launch

    python run.py [options]      (same options as the released exe, see --help)
"""
import os
import runpy
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
FRONTEND = os.path.join(SRC, "frontend")
# Same import roots as `python src/frontend/main.py` and the PyInstaller build.
sys.path[:0] = [FRONTEND, SRC]
sys.argv[0] = os.path.join(FRONTEND, "main.py")
runpy.run_path(sys.argv[0], run_name="__main__")
