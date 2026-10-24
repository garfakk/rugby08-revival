"""Simulated tournament results must look like rugby: the stronger side
usually wins, minnows don't beat the giants, scores and cards stay in a
plausible range, and surprises still happen.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
for path in (os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "frontend")):
    if path not in sys.path:
        sys.path.insert(0, path)

from app import variants as V  # noqa: E402
from app.tournament import calendar, engine, formats, reputation, simulator, weather  # noqa: E402
from stadium_data_loader import StadiumDataLoader  # noqa: E402
from team_data_loader import TeamDataLoader  # noqa: E402

TEMPLATES = os.path.join(ROOT, "src", "assets", "data", "competitions")


class Store:
    """The parts of app.state.DataStore the tournament engine reads, without
    the app's config (which needs a Rugby 08 install)."""

    def __init__(self):
        loader = TeamDataLoader(os.path.join(DATA, "teams"), os.path.join(DATA, "players"))
        self.teams = loader.load_teams()
        for seasons in self.teams.values():
            for info in seasons.values():
                V.migrate_season(info)
        self.players = loader.load_players()
        self.stadiums = StadiumDataLoader(os.path.join(DATA, "stadiums")).load_stadiums()

    def team_season(self, team_id, season, variant=V.DEFAULT, exact=True):
        return V.team_season(self.teams, team_id, season, variant, exact=exact)

    def variants_of(self, team_id, season):
        return V.variant_ids(self.teams.get(str(team_id), {}).get(str(season), {}))

    def get_players(self, player_ids, season):
        out = {}
        for pid in player_ids:
            p = self.players.get(pid)
            if not p or "stats" not in p:
                continue
            use = season if season in p["stats"] else str(
                min((int(y) for y in p["stats"]), key=lambda y: abs(y - int(season))))
            flat = {k: v for k, v in p.items() if k != "stats"}
            flat.update(p["stats"][use])
            out[int(pid)] = flat
        return out


NATIONS = ["New Zealand", "South Africa", "Ireland", "France", "England", "Argentina", "Scotland",
           "Australia", "Fiji", "Italy", "Wales", "Georgia", "Japan", "Samoa", "Tonga", "Portugal",
           "Uruguay", "USA", "Romania", "Namibia"]


class TournamentRealism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Store()
        cls.templates = formats.load_templates([TEMPLATES])
        cls.ids = {cls.ds.team_season(t, "2024").get("name"): t for t in cls.ds.teams}
        missing = [n for n in NATIONS if n not in cls.ids]
        if missing:
            raise unittest.SkipTest(f"teams not in the data: {missing}")
        pools = {g: [cls.ids[n] for n in NATIONS[i::4]] for i, g in enumerate("ABCD")}
        cls.parts = {"pools": pools}

    def _tournament(self, seed=1):
        return engine.create_tournament(self.ds, self.templates["world_cup"], "2024", self.parts, seed=seed)

    def _series(self, t, a, b, n):
        f = t.fixtures[0]
        f.home, f.away, f.neutral = self.ids[a], self.ids[b], True
        return [simulator.simulate(t, f, random.Random(f"{a}:{b}:{i}")) for i in range(n)]

    def test_reputation_lookup(self):
        self.assertEqual(reputation.lookup("New Zealand", "2024"), 90)
        self.assertEqual(reputation.lookup("Bordeaux-Bègles", "2024"), reputation.lookup("bordeaux begles", "2023"))
        self.assertIsNone(reputation.lookup("Some Custom XV", "2024"))
        self.assertGreater(reputation.lookup("Argentina", "2008"), reputation.lookup("Argentina", "2024"))

    def test_unknown_team_gets_the_field_average(self):
        t = self._tournament()
        tid = self.ids["Namibia"]
        t.teams[tid].name = "Some Custom XV"
        for e in t.teams.values():
            e.components.pop("reputation", None)
        known = [reputation.reputation(t, k) for k in t.teams if k != tid]
        self.assertAlmostEqual(reputation.reputation(t, tid), sum(known) / len(known), delta=0.1)

    def test_giants_beat_minnows(self):
        t = self._tournament()
        for a, b in (("New Zealand", "Namibia"), ("South Africa", "Romania"), ("Ireland", "Portugal")):
            results = self._series(t, a, b, 200)
            wins = sum(r.home.points > r.away.points for r in results)
            self.assertGreaterEqual(wins, 194, f"{a} v {b}: {a} won only {wins}/200")

    def test_close_sides_are_close(self):
        t = self._tournament()
        for a, b in (("Ireland", "South Africa"), ("Scotland", "Argentina"), ("Fiji", "Australia")):
            results = self._series(t, a, b, 300)
            share = sum(r.home.points > r.away.points for r in results) / len(results)
            self.assertTrue(0.25 < share < 0.75, f"{a} v {b}: {a} won {share:.0%}")

    def test_scores_and_cards_are_plausible(self):
        t = self._tournament()
        results = self._series(t, "Scotland", "Wales", 300)
        n = len(results)
        points = sum(r.home.points + r.away.points for r in results) / n
        tries = sum(r.home.tries + r.away.tries for r in results) / n
        yellows = sum(1 for r in results for e in r.events if e["kind"] == "yellow") / n
        reds = sum(1 for r in results for e in r.events if e["kind"] == "red") / n
        self.assertTrue(35 <= points <= 65, f"{points:.1f} points a match")
        self.assertTrue(3 <= tries <= 8, f"{tries:.1f} tries a match")
        self.assertLess(yellows, 2.0)
        self.assertLess(reds, 0.3)

    def test_win_probability_matches_the_simulator(self):
        t = self._tournament()
        for a, b in (("France", "Italy"), ("Scotland", "Wales"), ("New Zealand", "Namibia")):
            results = self._series(t, a, b, 300)
            actual = sum(r.home.points > r.away.points for r in results) / len(results)
            self.assertAlmostEqual(simulator.win_probability(t, t.fixtures[0]), actual, delta=0.12)

    def test_whole_tournaments(self):
        """Over a few World Cups: no tier-2 champion, surprises happen."""
        champions, upsets = [], 0
        for seed in range(6):
            t = self._tournament(seed)
            engine.simulate_to_end(t)
            champions.append(t.champion)
            upsets += sum(1 for n in t.news if n["kind"] == "upset")
        for tid in champions:
            self.assertGreaterEqual(reputation.reputation(t, tid), 80, f"{t.team_name(tid)} won a World Cup")
        self.assertGreater(upsets, 0)

    def test_old_saves_without_reputation_or_par(self):
        t = self._tournament()
        t.components.pop("sim_par", None)
        for e in t.teams.values():
            e.components.pop("reputation", None)
        engine.simulate_to_end(t)
        self.assertTrue(t.finished)
        self.assertIn("sim_par", t.components)


class TournamentWeather(unittest.TestCase):
    """Fixtures get real dates, and the weather follows the season and the
    ground."""

    @classmethod
    def setUpClass(cls):
        cls.ds = Store()
        cls.templates = formats.load_templates([TEMPLATES])

    def _six_nations(self, seed=1):
        return engine.create_tournament(self.ds, self.templates["six_nations"], "2024", seed=seed)

    def test_calendar_follows_the_season(self):
        t = self._six_nations()
        dates = sorted({calendar.fixture_date(t, f) for f in t.fixtures})
        self.assertEqual([d.isoformat() for d in dates],
                         ["2024-02-03", "2024-02-10", "2024-02-24", "2024-03-09", "2024-03-16"])
        self.assertTrue(all(d.weekday() == 5 for d in dates))
        top14 = self.templates["top_14"]
        clubs = [tid for tid, ss in self.ds.teams.items()
                 if any(isinstance(s, dict) and s.get("category") == "Top 14" for s in ss.values())]
        t = engine.create_tournament(self.ds, top14, "2024", {"league": {"A": clubs[:10]}}, seed=1)
        days = sorted(calendar.fixture_date(t, f) for f in t.fixtures)
        self.assertEqual((days[0].year, days[0].month), (2023, 9))
        self.assertEqual((days[-1].year, days[-1].month), (2024, 6))

    def test_old_saves_get_dates(self):
        t = self._six_nations()
        for f in t.fixtures:
            f.date = ""
        self.assertEqual(calendar.fixture_date(t, t.fixtures[0]).isoformat(), "2024-02-03")

    def test_forecast_is_consistent(self):
        t = self._six_nations()
        for f in t.fixtures:
            fc = weather.forecast(t, f, self.ds)
            self.assertEqual(fc, weather.forecast(t, f, self.ds))
            self.assertEqual(fc, weather.forecast(t, f))          # without the data store too
            envs = self.ds.stadiums[f.stadium_id].get("environments") or ["day"]
            self.assertIn(fc["environment"], envs)
            self.assertIn(fc["pitch"], weather.textures() | {"default"})
            if fc["environment"] in ("day", "night"):        # the lighting decides the kick-off
                self.assertEqual(fc["night"], fc["environment"] == "night")

    def test_winter_is_colder_than_summer(self):
        t = self._six_nations()
        f = t.fixtures[0]
        murrayfield = next(sid for sid, s in self.ds.stadiums.items() if s.get("name") == "Murrayfield")

        def mean(date, sid):
            out = []
            for seed in range(40):
                t.seed = seed
                f.stadium_id, f.date = sid, date
                out.append(weather.forecast(t, f)["temp"])
            return sum(out) / len(out)

        self.assertLess(mean("2024-02-10", murrayfield), 8)
        self.assertGreater(mean("2024-08-10", murrayfield), 12)
        johannesburg = next(sid for sid, s in self.ds.stadiums.items() if s.get("name") == "Johannesburg")
        self.assertGreater(mean("2024-01-10", johannesburg), mean("2024-07-10", johannesburg))

    def test_home_grounds(self):
        t = self._six_nations()
        names = {e.name: self.ds.stadiums.get(e.stadium_id, {}).get("name") for e in t.teams.values()}
        self.assertEqual(names["Scotland"], "Murrayfield")
        self.assertEqual(names["Wales"], "Millennium Stadium")
        self.assertEqual(names["Italy"], "Rome")


if __name__ == "__main__":
    unittest.main()
