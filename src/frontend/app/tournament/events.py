"""
tournament/events.py — The event bus the tournament features hang off.

The engine only schedules fixtures, records results and advances the
calendar; everything that reacts to a result (injuries, bans, fatigue,
stats, news...) subscribes here. A new feature is a new module that
subscribes, never an edit to the engine.

Events and their keyword payloads:
  tournament_created  t
  pre_match           t, fixture
  match_completed     t, fixture, result, rng
  day_completed       t, day
  stage_completed     t, stage
  tournament_completed t

Subscribers run in ascending `priority`. Conventions used so far:
  10  bookkeeping that must see the state before this match changes it
      (conditions ticking down)
  50  things the match causes (injuries, bans, fatigue)
  80  aggregates (stats)
  90  news, which reads what the others wrote
"""
from collections import defaultdict

from shared.log import get_logger

log = get_logger(__name__)

EVENTS = ("tournament_created", "pre_match", "match_completed",
          "day_completed", "stage_completed", "tournament_completed")


class EventBus:
    def __init__(self):
        self._subs = defaultdict(list)   # event -> [(priority, order, name, fn)]
        self._order = 0

    def subscribe(self, event, fn, priority=50, name=None):
        if event not in EVENTS:
            raise ValueError(f"unknown tournament event: {event}")
        name = name or f"{fn.__module__}.{fn.__qualname__}"
        # Re-importing a plugin (tests, hot reload) must not double-subscribe.
        self._subs[event] = [s for s in self._subs[event] if s[2] != name]
        self._order += 1
        self._subs[event].append((priority, self._order, name, fn))
        self._subs[event].sort(key=lambda s: (s[0], s[1]))

    def emit(self, event, **payload):
        for _priority, _order, _name, fn in list(self._subs[event]):
            fn(**payload)

    def subscribers(self, event):
        return [s[2] for s in self._subs[event]]


bus = EventBus()


def on(event, priority=50):
    """Decorator: @on("match_completed", priority=50)."""
    def wrap(fn):
        bus.subscribe(event, fn, priority)
        return fn
    return wrap
