"""
backend/match_memory.py — the match data in Rugby 08's memory, decoded
=========================================================================
Pure decoding of the bytes R08_handler reads; no process access here.

MatchSetup block (getter 0x4215F0, config.memory_addresses['match_setup']),
reR08 source/game_sa/gameplay/TeamRecord.h:
  +0x0000 / +0x0C60  home / away team record (0xC60 bytes each)
  +0x18C0 / +0x18C7  home / away score (7 bytes each)
  +0x18F0 / +0x18F4  displayed clock / period (read by R08_handler)
The game zeroes the score and clock when its menu comes back (0x4F7330):
they are only meaningful while the match is played.

Team record: 30 player records of 100 bytes (0-14 starting XV, 15-29 bench),
then team DB id, captain, the substitution log and the set-piece counters.

On the pitch (pointers, not in the block): world = *(world_ptr), home team =
*(world+0x68), away = *(world+0x6C); team+0xD0+i*4 = the Player in position i
(1..15); Player+0x10 = its record (inside the block), Player+0x70 bit0 = off
the pitch (sin bin, sent off). A substitution points the Player of that
position at the incoming record (commit 0x61BD60).
"""
import struct

SETUP_SIZE = 0x18F8              # team records, scores, clock and period
TEAM_RECORDS = {'team_A': 0x0000, 'team_B': 0x0C60}
SCORE_BLOCKS = {'team_A': 0x18C0, 'team_B': 0x18C7}

PLAYER_RECORD_SIZE = 100
ROSTER_SLOTS = 30           # in a team record
SQUAD_SIZE = 22             # the mod's squads: the rows of a result

# Player record, per-match bytes (zeroed at match start by 0x5B7630 / 0x633170)
_PLAYER_BYTES = {
    'penalties_scored': 0x3E,       # 0x430B30 (kick made: made + attempted)
    'penalties_attempted': 0x3F,
    'conversions_scored': 0x40,
    'conversions_attempted': 0x41,
    'drop_goals': 0x42,
    'yellow_cards': 0x44,           # referee card decision (reR08 cards.cpp)
    'red_cards': 0x45,
    'man_of_the_match': 0x46,       # +1 at the final whistle (0x43E6D0 -> 0x64B850)
    'injury': 0x61,                 # injury state 0x60B470 sets it to 1
}
_PLAYER_WORDS = {
    'tries': 0x48,                  # u16, overlay "Tries scored:" 0x58E7A0
    'tackles': 0x4A,                # u16, overlay "Tackles:" 0x58E7A0
}
_NAME_OFFSET, _NAME_LEN = 0x04, 16

# Scoring counters by score type, for the live score timeline
SCORING_COUNTERS = {'try': ('tries', 5), 'conversion': ('conversions_scored', 2),
                    'penalty': ('penalties_scored', 3), 'drop_goal': ('drop_goals', 3)}

# Team record tail
_TEAM_DB_ID = 0xBB8                 # u32
_CAPTAIN_ID = 0xBBC                 # u16
_SUB_LOG, _SUB_LOG_ENTRIES = 0xBFC, 7       # {u16 off id, u16 pad, float displayed clock}
_TEAM_STATS = 0xC54                 # u16 each, in this order
TEAM_STATS = ('scrums_won', 'scrums_lost', 'lineouts_won', 'lineouts_lost',
              'ruck_turnovers_won', 'ruck_turnovers_lost')

# Score block bytes (.mis parser 0x4BF670 fills 0-3 from SS_TRY / SS_CONVERSION /
# SS_DROPGOAL / SS_PENALTY; byte 4 = goal kicks attempted, overlay 0x578470)
_SCORE_BYTES = ('tries', 'conversions', 'drop_goals', 'penalties', 'kicks_attempted')
POINTS = {'tries': 5, 'conversions': 2, 'drop_goals': 3, 'penalties': 3}


def _u16(block, pos):
    return int.from_bytes(block[pos:pos + 2], 'little')


def _name(raw):
    # The rdf names are single-byte (Latin-1); everything after the first NUL is junk
    return bytes(raw).split(b'\0', 1)[0].decode('latin-1')


def player_offset(team, slot):
    return TEAM_RECORDS[team] + slot * PLAYER_RECORD_SIZE


def read_player(block, team, slot):
    pos = player_offset(team, slot)
    player = {'id': _u16(block, pos),
              'name': _name(block[pos + _NAME_OFFSET:pos + _NAME_OFFSET + _NAME_LEN])}
    for key, off in _PLAYER_BYTES.items():
        player[key] = block[pos + off]
    for key, off in _PLAYER_WORDS.items():
        player[key] = _u16(block, pos + off)
    return player


def read_players(block, team, count=SQUAD_SIZE):
    return [read_player(block, team, slot) for slot in range(count)]


def read_team_stats(block, team):
    pos = TEAM_RECORDS[team] + _TEAM_STATS
    return {key: _u16(block, pos + 2 * i) for i, key in enumerate(TEAM_STATS)}


def read_sub_log(block, team):
    """The game's own substitution log: [{"off_id", "clock"}], oldest first.
    It holds who went off and when (displayed clock), not who came on."""
    subs = []
    pos = TEAM_RECORDS[team] + _SUB_LOG
    for i in range(_SUB_LOG_ENTRIES):
        off_id = _u16(block, pos + 8 * i)
        if off_id:
            subs.append({'off_id': off_id,
                         'clock': round(struct.unpack_from('<f', block, pos + 8 * i + 4)[0], 1)})
    return subs


def read_team_info(block, team):
    pos = TEAM_RECORDS[team]
    return {'team_db_id': int.from_bytes(block[pos + _TEAM_DB_ID:pos + _TEAM_DB_ID + 4], 'little'),
            'captain_id': _u16(block, pos + _CAPTAIN_ID)}


def read_score(block, team):
    """The team's score as the game keeps it (includes the score a .mis starts
    on): counts per kind plus points. Only valid while the match is played."""
    pos = SCORE_BLOCKS[team]
    score = {key: block[pos + i] for i, key in enumerate(_SCORE_BYTES)}
    score['points'] = sum(score[k] * p for k, p in POINTS.items())
    return score


def man_of_the_match(block):
    """(team, roster slot) of the player the game named Man of the Match, or
    None. The game names one at every final whistle (never on a quit), so this
    also tells the match went to full time."""
    for team in TEAM_RECORDS:
        for slot in range(ROSTER_SLOTS):
            if block[player_offset(team, slot) + _PLAYER_BYTES['man_of_the_match']]:
                return team, slot
    return None


def scoring_snapshot(block):
    """Scoring counters of every player: {(team, slot): (roster id, {type: count})}"""
    snapshot = {}
    for team in TEAM_RECORDS:
        for slot in range(SQUAD_SIZE):
            player = read_player(block, team, slot)
            snapshot[(team, slot)] = (player['id'],
                                      {kind: player[key] for kind, (key, _p) in SCORING_COUNTERS.items()})
    return snapshot


def record_slot(setup_address, record_address):
    """(team, roster slot) of a player record pointer into the block, or None."""
    for team, base in TEAM_RECORDS.items():
        rel = record_address - (setup_address + base)
        if 0 <= rel < ROSTER_SLOTS * PLAYER_RECORD_SIZE and rel % PLAYER_RECORD_SIZE == 0:
            return team, rel // PLAYER_RECORD_SIZE
    return None


def score_from_players(players):
    score = {'tries': 0, 'conversions': 0, 'penalties': 0, 'drop_goals': 0}
    for p in players:
        score['tries'] += p['tries']
        score['conversions'] += p['conversions_scored']
        score['penalties'] += p['penalties_scored']
        score['drop_goals'] += p['drop_goals']
    score['points'] = sum(score[k] * pts for k, pts in POINTS.items())
    return score


def read_team(block, team, live_score=None):
    """One side of the result. `live_score` = read_score() from the last read
    during the match (the block's own score is zeroed by then); without it the
    score is summed from the players' counters."""
    players = read_players(block, team)
    score = dict(live_score) if live_score else score_from_players(players)
    for key in ('yellow_cards', 'red_cards', 'tackles'):
        score[key] = sum(p[key] for p in players)
    return {'score': score, 'players': players,
            'substitutions': read_sub_log(block, team),
            'stats': read_team_stats(block, team),
            **read_team_info(block, team)}
