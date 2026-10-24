"""Runs the app (run.py) with the same isolated config as the tests: fake
game, fixture data, throwaway user_data. Used by test_startup.py for
`--selftest`; never touches the user's own settings or data."""
import os
import runpy
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import conftest  # noqa: E402  (sets up the isolated config on import)

try:
    sys.argv = [os.path.join(conftest.SRC, "frontend", "main.py")] + sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    shutil.rmtree(conftest._APP, ignore_errors=True)
