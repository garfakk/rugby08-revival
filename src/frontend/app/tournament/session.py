"""
tournament/session.py — What the UI drives: one open tournament, with
saving, undo and the pre-match crash snapshot handled for it.

Typical flow:
  s = TournamentSession.new(ds, template, season, participants, humans, opts)
  s.advance_to_human()         # simulate AI fixtures up to the user's match
  f = s.human_fixture()
  s.begin_game(f) -> MatchConfig   (snapshot + selections ready)
  ... game ...
  s.finish_game(f, result_dict)    (or s.simulate(f), s.forfeit(f, team))
"""
from . import bridge, engine, persistence, selection
from .model import Tournament


class TournamentSession:
    def __init__(self, t: Tournament, ds=None):
        self.t = t
        self.ds = ds

    # ── lifecycle ──
    @classmethod
    def new(cls, ds, template, season, participants=None, humans=(), options=None,
            seed=None, name=None):
        from shared.config import config
        t = engine.create_tournament(ds, template, season, participants, humans, options, seed, name,
                                     data_version=str(getattr(config, "data_version", "") or ""))
        s = cls(t, ds)
        s.save()
        return s

    @classmethod
    def load(cls, tid, ds=None):
        return cls(persistence.load(tid), ds)

    def save(self):
        persistence.save(self.t)

    # ── undo ──
    def _checkpoint(self):
        persistence.snapshot(self.t, "undo")

    def can_undo(self) -> bool:
        return persistence.has_snapshot(self.t.id, "undo")

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self.t = persistence.restore_snapshot(self.t.id, "undo")
        persistence.drop_snapshot(self.t.id, "undo")
        self.save()
        return True

    # ── queries ──
    def human_fixture(self):
        return engine.next_human_fixture(self.t)

    def today(self):
        return self.t.fixtures_on(self.t.day)

    # ── simulation ──
    def advance_to_human(self) -> list:
        """Simulate AI fixtures until a user's match is due; returns them."""
        if self.t.finished or self.human_fixture():
            return []        # nothing to do: keep the undo point we have
        self._checkpoint()
        done = engine.simulate_until_human(self.t)
        self.save()
        return done

    def simulate(self, fixture) -> list:
        """Simulate a (user) fixture, then the rest of its matchday."""
        self._checkpoint()
        engine.simulate_fixture(self.t, fixture)
        done = [fixture] + engine.simulate_day(self.t)
        self.save()
        return done

    def simulate_to_end(self):
        self._checkpoint()
        engine.simulate_to_end(self.t)
        self.save()

    # ── playing in the game ──
    def begin_game(self, fixture):
        """Selections ready + crash snapshot; returns (MatchConfig, repairs)."""
        repairs = engine.prepare_fixture(self.t, fixture)
        self.save()
        persistence.snapshot(self.t, "prematch")
        cfg = bridge.to_match_config(self.ds, self.t, fixture)
        # Settings > Wind: Advanced has no match setup here to set it, so
        # the fixture gets its own wind (seeded: the same fixture always
        # gets the same wind, even after BACK). Standard leaves it None —
        # the game's stock random wind.
        from shared.user_prefs import user_prefs
        if user_prefs.wind_mode == "advanced":
            from app.game_data import random_wind
            cfg.wind_power, cfg.wind_dir_deg = random_wind(engine.fixture_rng(self.t, fixture, "wind"))
        return cfg, repairs

    def finish_game(self, fixture, game_result: dict) -> list:
        """Record the game's result, then simulate the rest of the day."""
        self._checkpoint()
        result = bridge.from_game_result(self.t, fixture, game_result,
                                         engine.fixture_rng(self.t, fixture, "game"))
        engine.record_result(self.t, fixture, result)
        done = [fixture] + engine.simulate_day(self.t)
        persistence.drop_snapshot(self.t.id, "prematch")
        self.save()
        return done

    def prepare(self, fixture):
        """Selections ready for a fixture without playing or simulating it
        (the manual result form lists the players of both squads)."""
        engine.prepare_fixture(self.t, fixture)
        self.save()

    def enter_result(self, fixture, result) -> list:
        """Record a result typed in by hand, then simulate the rest of the day."""
        self._checkpoint()
        engine.record_result(self.t, fixture, result)
        done = [fixture] + engine.simulate_day(self.t)
        self.save()
        return done

    def abandon_game(self):
        persistence.drop_snapshot(self.t.id, "prematch")

    def forfeit(self, fixture, losing_team) -> list:
        self._checkpoint()
        engine.record_result(self.t, fixture, bridge.forfeit_result(self.t, fixture, losing_team))
        done = [fixture] + engine.simulate_day(self.t)
        persistence.drop_snapshot(self.t.id, "prematch")
        self.save()
        return done

    # ── squad management ──
    def set_selection(self, team_id, players, positions=None, roles=None):
        entry = self.t.teams[team_id]
        sel = {"players": list(players),
               "positions": list(positions or entry.selection.get("positions") or []),
               "set_plays": dict(entry.selection.get("set_plays") or entry.set_plays),
               "manual": True}
        sel["roles"] = selection.pick_roles(self.t, team_id, sel["players"], roles)
        entry.selection = sel
        self.save()
        return selection.validate(self.t, team_id, sel)

    def auto_select(self, team_id):
        entry = self.t.teams[team_id]
        entry.selection = selection.auto_select(self.t, team_id)
        if entry.human:
            entry.selection["manual"] = True
        self.save()
        return entry.selection
