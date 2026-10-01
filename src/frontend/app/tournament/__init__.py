"""
app.tournament — Tournament mode engine (no Qt).

Importing the package registers the built-in features on the event bus and
in the effect registries. A new feature is a module that registers itself
the same way and is added to FEATURES below; nothing else changes.

  model        saved state (dataclasses <-> JSON)
  engine       create / simulate / record / advance
  session      the facade the UI talks to (adds saving and undo)
  bridge       fixture <-> game (MatchConfig, game result)
  formats      competition templates
  persistence  save files, snapshots, migrations
"""
from importlib import import_module

FEATURES = (
    "conditions",   # condition ticking (must be first: priority 10)
    "injuries",
    "discipline",
    "fatigue",
    "stats",
    "news",
)

for _name in FEATURES:
    import_module(f"{__name__}.{_name}")
