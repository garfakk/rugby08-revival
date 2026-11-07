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
from . import bridge, engine, lineups, persistence, selection, trophy
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
        """Simulate whole rounds of AI fixtures until a user's match is due;
        returns them. The due round's earlier kick-offs wait for the user's
        match (begin_game / prepare), so one recap shows one round."""
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

    def simulate_to_title_match(self, for_title=False) -> list:
        """Expert mode: everything up to a user's final or title decider
        (engine.simulate_to_title_match); returns the fixtures simulated."""
        self._checkpoint()
        done = engine.simulate_to_title_match(self.t, for_title)
        self.save()
        return done

    def title_match_ahead(self) -> bool:
        """Whether a user's team still has matches before its title match
        (simulating to it would change something)."""
        due = self.human_fixture()
        if due is not None:
            return not engine.is_title_match(self.t, due)
        humans = [tid for tid, e in self.t.teams.items() if e.human]
        return not self.t.finished and any(not engine.is_eliminated(self.t, h) for h in humans)

    def simulate_to_end(self):
        self._checkpoint()
        engine.simulate_to_end(self.t)
        self.save()

    # ── playing in the game ──
    def begin_game(self, fixture):
        """Selections ready + crash snapshot; returns (MatchConfig, repairs).
        The round's AI matches kicking off earlier are played first."""
        engine.simulate_earlier(self.t)
        # a match that decides a competition with no final: the day's other
        # matches first, so the right team lifts the trophy (tournament/trophy.py)
        trophy.decider_prelude(self.t, fixture, engine.simulate_fixture)
        repairs = engine.prepare_fixture(self.t, fixture)
        self.save()
        persistence.snapshot(self.t, "prematch")
        cfg = bridge.to_match_config(self.ds, self.t, fixture)
        # Settings > Wind: Advanced has no match setup here to set it, so
        # the fixture gets its own wind (seeded: the same fixture always
        # gets the same wind, even after BACK). Standard leaves it None —
        # the game's stock random wind. A closed roof has set it to 0.
        from shared.user_prefs import user_prefs
        if user_prefs.wind_mode == "advanced" and cfg.wind_power is None:
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
        (the manual result form lists the players of both squads), after
        the round's earlier kick-offs."""
        engine.simulate_earlier(self.t)
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
        """`losing_team` None = double forfeit: both teams lose (a knockout
        tie still needs a team through, drawn at random; the other forfeits)."""
        self._checkpoint()
        if losing_team is None and fixture.knockout:
            losing_team = engine.fixture_rng(self.t, fixture, "forfeit").choice(
                [fixture.home, fixture.away])
        engine.record_result(self.t, fixture, bridge.forfeit_result(self.t, fixture, losing_team))
        done = [fixture] + engine.simulate_day(self.t)
        persistence.drop_snapshot(self.t.id, "prematch")
        self.save()
        return done

    # ── squad management ──
    # A human team's default lineup is what every match starts from (see
    # lineups.py); entry.selection is only the 22 of the next match.
    def _lineup(self, team_id, players, positions=None, roles=None, set_plays=None):
        entry = self.t.teams[team_id]
        base = lineups.default(entry) or entry.selection
        sel = {"players": list(players),
               "positions": list(positions or base.get("positions") or []),
               "set_plays": dict(set_plays if set_plays is not None
                                 else (base.get("set_plays") or entry.set_plays))}
        sel["roles"] = selection.pick_roles(self.t, team_id, sel["players"], roles)
        return sel

    def set_selection(self, team_id, players, positions=None, roles=None, set_plays=None):
        """The team's default lineup (also the next match's 22 until that
        match is prepared). Returns validate()'s (errors, warnings)."""
        entry = self.t.teams[team_id]
        sel = self._lineup(team_id, players, positions, roles, set_plays)
        lineups.set_default(entry, sel)
        entry.selection = dict(sel, manual=True)
        self.save()
        return selection.validate(self.t, team_id, sel)

    def set_match_selection(self, team_id, players, roles=None, set_plays=None):
        """This match only (match setup's squad editor): the default lineup
        is left as it is, and the next match starts from it again."""
        entry = self.t.teams[team_id]
        sel = self._lineup(team_id, players, entry.selection.get("positions"), roles,
                           set_plays if set_plays is not None else entry.selection.get("set_plays"))
        entry.selection = dict(sel, manual=True)
        self.save()

    def auto_select(self, team_id):
        """The best 22 now, made the default lineup (set plays kept)."""
        entry = self.t.teams[team_id]
        plays = (lineups.default(entry) or entry.selection).get("set_plays")
        sel = selection.auto_select(self.t, team_id)
        if plays:
            sel["set_plays"] = dict(plays)
        if entry.human:
            lineups.set_default(entry, sel)
            lineups.set_source(entry, None)      # not an edit of a saved lineup
            sel["manual"] = True
        entry.selection = sel
        self.save()
        return entry.selection

    def set_auto_lineup(self, team_id, on):
        """Pick the best 22 before every match instead of the default."""
        entry = self.t.teams[team_id]
        lineups.set_auto(entry, on)
        if not on and not lineups.default(entry).get("players"):
            lineups.set_default(entry, entry.selection)
        self.save()

    def load_lineup(self, team_id, lineup, source=None):
        """Make a saved or played lineup the default. Players no longer in
        the squad are dropped and the gaps filled with the best cover.
        `source`: the saved lineup's name (None: a played one)."""
        entry = self.t.teams[team_id]
        lineups.set_source(entry, source)
        squad = set(entry.squad)
        current = (lineups.default(entry) or entry.selection).get("players", [])
        pids = [p if p in squad else None for p in lineup.get("players", [])[:22]]
        spare = [p for p in dict.fromkeys(list(current) + list(entry.squad)) if p not in pids]
        pids = [p or spare.pop(0) for p in pids if p or spare]
        roles = lineup.get("roles") or {}
        return self.set_selection(team_id, pids, lineup.get("positions"), roles,
                                  lineup.get("set_plays"))

    def update_lineup(self, team_id, index):
        """Write the default lineup (its edits) back into saved lineup
        `index`, under its own name."""
        entry = self.t.teams[team_id]
        items = lineups.saved(entry)
        if 0 <= index < len(items):
            lineups.save_as(entry, items[index]["name"], lineups.default(entry) or entry.selection)
            self.save()

    def save_lineup(self, team_id, name, lineup=None) -> int:
        """Save `lineup` (default: the default lineup) under `name`."""
        entry = self.t.teams[team_id]
        i = lineups.save_as(entry, name, lineup or lineups.default(entry) or entry.selection)
        self.save()
        return i

    def rename_lineup(self, team_id, index, name):
        lineups.rename(self.t.teams[team_id], index, name)
        self.save()

    def delete_lineup(self, team_id, index):
        lineups.delete(self.t.teams[team_id], index)
        self.save()
