"""backend/R08_handler.py: what is read from the game's memory while the
match is played — the displayed clock (80-minute scale whatever the half
length) and its period, the scores, the Man of the Match and who plays where —
and what it decides: the minute an interrupted match stopped at, whether the
match really went to full time, each player's time on the pitch."""
import struct

import pytest

from backend import R08_handler as H
from backend import match_memory as mm
from shared.config import config

WORLD = 0x01000000
TEAMS = {'team_A': 0x02000000, 'team_B': 0x02100000}
PLAYERS = {'team_A': 0x03000000, 'team_B': 0x03100000}    # Player objects, 0x100 apart


class FakeGame:
    """The game's memory as R08_handler reads it: the match object (world),
    the MatchSetup block, both teams' positions and their Player objects."""

    def __init__(self):
        self.real = 0.0                     # match object's clock, real seconds
        self.clock = 0.0                    # displayed clock
        self.period = 0
        self.setup = bytearray(mm.SETUP_SIZE)
        # position -> (roster slot, off the pitch)
        self.positions = {team: {pos: (pos - 1, False) for pos in range(1, 16)} for team in TEAMS}
        for team in TEAMS:
            for slot in range(mm.ROSTER_SLOTS):
                self.set(team, slot, 0x00, 1000 * (team == 'team_B') + 100 + slot, size=2)

    def set(self, team, slot, offset, value, size=1):
        pos = mm.player_offset(team, slot) + offset
        self.setup[pos:pos + size] = value.to_bytes(size, 'little')

    def get(self, team, slot, offset):
        return self.setup[mm.player_offset(team, slot) + offset]

    def _regions(self):
        a = config.memory_addresses
        yield a['world_ptr'], WORLD.to_bytes(4, 'little')
        yield WORLD + a['world_clock_offset'], struct.pack('<f', self.real)
        yield WORLD + H.WORLD_TEAMS, TEAMS['team_A'].to_bytes(4, 'little') + TEAMS['team_B'].to_bytes(4, 'little')
        yield a['match_clock'], struct.pack('<fB', self.clock, self.period)
        yield a['match_setup'], bytes(self.setup)
        for team, base in TEAMS.items():
            slots = bytearray(64)
            for pos in self.positions[team]:
                slots[4 * pos:4 * pos + 4] = (PLAYERS[team] + 0x100 * pos).to_bytes(4, 'little')
            yield base + H.TEAM_POSITIONS, bytes(slots)
            for pos, (slot, off) in self.positions[team].items():
                obj = bytearray(0x100)
                record = a['match_setup'] + mm.player_offset(team, slot)
                obj[H.PLAYER_RECORD_PTR:H.PLAYER_RECORD_PTR + 4] = record.to_bytes(4, 'little')
                obj[H.PLAYER_FLAGS] = 1 if off else 0
                yield PLAYERS[team] + 0x100 * pos, bytes(obj)

    def read(self, _handle, address, size):
        for base, data in self._regions():
            if base <= address and address + size <= base + len(data):
                return data[address - base:address - base + size]
        return None

    def dump(self, handle, start, end):
        return self.read(handle, start, end - start)

    def at(self, minute, period=None, real=None):
        self.clock = minute * 60.0
        self.period = period if period is not None else (0 if minute < 40 else 1)
        self.real = real if real is not None else self.clock / 8     # 5-minute halves
        return self


@pytest.fixture
def game(monkeypatch):
    fake = FakeGame()
    monkeypatch.setattr(H, "read_memory", fake.read)
    monkeypatch.setattr(H, "dump_memory", fake.dump)
    return fake


@pytest.fixture
def handler(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "simulation_mode", False)
    monkeypatch.setattr(config, "temp_directory", str(tmp_path))
    h = H.R08_handler()
    h.action_on_controller_selection_screen_reached()
    return h


# ── clock ──────────────────────────────────────────────────────────────────
def test_no_clock_before_play_starts(game, handler):
    game.at(0, real=0.0)
    assert handler.update_match_clock() is None
    assert handler.match_clock is None


def test_clock_is_the_displayed_one_not_real_time(game, handler):
    game.at(30, real=225.0)     # 30' on screen after 3m45s of 5-minute halves
    assert handler.update_match_clock() == pytest.approx(1800.0)
    assert handler.match_real_time == pytest.approx(225.0)


def test_clock_ignores_the_reset_on_the_way_out(game, handler):
    game.at(55)
    handler.update_match_clock()
    game.at(0, period=0, real=1.0)          # menu zeroes the displayed clock
    handler.update_match_clock()
    assert handler.match_clock == pytest.approx(3300.0)
    assert handler.match_period == 1


def test_shootout_period_is_read(game, handler):
    game.at(110, period=H.SHOOTOUT_PERIOD)
    assert handler.update_match_clock() == pytest.approx(6600.0)
    assert handler.match_period == H.SHOOTOUT_PERIOD


# ── full time ──────────────────────────────────────────────────────────────
def test_finished_when_a_man_of_the_match_was_named(game, handler):
    game.at(80)
    handler.poll_match()
    assert handler.is_match_finished() is False         # quit at 80:00, before the whistle
    game.set('team_A', 9, 0x46, 1)                      # the final whistle names him
    handler.poll_match()
    assert handler.man_of_the_match == ('team_A', 9)
    assert handler.is_match_finished() is True


def test_full_time_screen_alone_is_not_full_time(game, handler):
    game.at(80)
    handler.poll_match()
    handler.match_finished = True
    assert handler.is_match_finished() is False


def test_shootout_finishes_on_the_full_time_screen(game, handler):
    game.at(110, period=H.SHOOTOUT_PERIOD)
    handler.poll_match()
    assert handler.is_match_finished() is False
    handler.match_finished = True
    assert handler.is_match_finished() is True


def test_not_finished_without_match_setup(handler):
    handler.screen_controller_selection_reached = False
    handler.man_of_the_match = ('team_A', 0)
    assert handler.is_match_finished() is False


# ── during the match ───────────────────────────────────────────────────────
def test_poll_timestamps_scores_with_displayed_clock(game, handler):
    game.at(10)
    handler.poll_match()                    # baseline
    game.set('team_A', 9, 0x48, 1)
    game.at(35, real=262.5)
    handler.poll_match()
    assert [(e['slot'], e['type'], e['clock']) for e in handler.score_timeline] == [(9, 'try', 2100.0)]


def test_poll_keeps_the_team_score_the_menu_zeroes(game, handler):
    game.setup[mm.SCORE_BLOCKS['team_A']:mm.SCORE_BLOCKS['team_A'] + 5] = bytes([2, 1, 0, 3, 6])
    game.at(60)
    handler.poll_match()
    game.setup[mm.SCORE_BLOCKS['team_A']:mm.SCORE_BLOCKS['team_A'] + 5] = bytes(5)
    assert handler.live_score['team_A']['points'] == 10 + 2 + 9
    assert handler.live_score['team_A']['kicks_attempted'] == 6


def test_poll_follows_lineups_and_time(game, handler):
    game.at(0, period=0, real=0.5)
    handler.poll_match()
    game.at(20)
    game.positions['team_A'][10], game.positions['team_A'][12] = (11, False), (9, False)   # 10 <-> 12
    handler.poll_match()
    game.at(30)
    game.positions['team_A'][1] = (15, False)                                            # 16 on for 1
    handler.poll_match()
    game.at(40)
    handler.poll_match()
    kinds = [(e['type'], e.get('id') or e.get('on_id')) for e in handler.lineup.events if e['team'] == 'team_A']
    assert kinds == [('move', 111), ('move', 109), ('sub', 115)]
    played = handler.lineup.summary('team_A')
    assert played[100]['seconds'] == pytest.approx(30 * 60)       # prop off at 30'
    assert played[115]['positions'] == {1: pytest.approx(600)}
    assert played[109]['positions'] == {10: pytest.approx(1200), 12: pytest.approx(1200)}


def test_result_carries_the_tracking(game, handler):
    game.at(0, period=0, real=0.5)
    handler.poll_match()
    game.set('team_B', 13, 0x46, 1)
    game.set('team_B', 13, 0x04, int.from_bytes('Ñandú'.encode('latin-1'), 'little'), size=5)
    game.at(80)
    handler.poll_match()
    result = handler.read_match_result(handler.read_setup())
    assert result['man_of_the_match'] == {'team': 'team_B', 'id': 1113, 'name': 'Ñandú'}
    assert result['minute'] == 80 and result['lineup_events'] == []
    wing = result['team_B']['players'][13]
    assert wing['seconds_on_field'] == pytest.approx(4800) and wing['positions'] == {14: pytest.approx(4800)}
    assert result['team_A']['starting_lineup'][1] == 100
    assert result['team_A']['players'][20]['seconds_on_field'] == 0.0
