"""
app/roster_import/reader.py — read Rugby 08 roster files
==========================================================
Two containers hold the same roster:

  * .rdf — the game's raw roster file (what backend/game_files_processor
    writes): a u32 header, 2001 player records of 0x64 bytes from 0x04, then
    142 team blocks of 0x68 bytes from 0x30DA8.
  * .ros — a roster saved by the game or a community patch: a 0x80-byte
    "20CMTX" header, then the TEAM section, then a copy of the .rdf image
    starting with its player records. No cipher and no compression — the two
    sections are simply in the other order.

Team names are not stored in a roster (they live in the game's string
files); the stock names come from Rugeditor's teams.csv, bundled in
assets/data. Team block index + 1 is the game's team id.
"""
import csv
import os
import struct

from shared.app_paths import assets_directory

PLAYER_COUNT = 2001
PLAYER_SIZE = 0x64
TEAM_COUNT = 142
TEAM_SIZE = 0x68
RDF_PLAYERS = 0x04
RDF_TEAMS = 0x30DA8
ROS_MAGIC = b"20CMTX"
ROS_TEAMS = 0x80
ROS_BODY = 0x3A30          # where the .rdf image (offset 0) starts inside a .ros

POSITIONS = {1: "loosehead_prop", 2: "hooker", 3: "tighthead_prop", 4: "second_row",
             5: "blindside_flanker", 6: "openside_flanker", 7: "number_eight", 8: "scrum_half",
             9: "fly_half", 10: "winger", 11: "centre", 12: "fullback"}
RATINGS_1 = ["attack", "defense", "speed", "acceleration", "agility", "handling", "passing",
             "kicking", "kicking_power", "goal_kicking", "tackling", "strength", "rucking",
             "scrummaging", "hooking", "lineout", "discipline", "aggression"]
RATINGS_2 = ["stamina", "consitance", "temperament", "creativity", "bravery", "fitness",
             "crashball", "gap_defense"]
TENDENCIES = ["default", "scrum", "lineout", "tackler", "runner", "passer", "kicker", "crasher",
              "ruck", "goalkicker", "playmaker"]
# Bit order of the two special-skill bytes, named as the backend's ss_* keys.
SKILL_BITS_1 = ["command", "passer", "play_maker", "scoring", "goal_kicker", "tactical_kicking",
                "crashball", "tackle_breaker"]
SKILL_BITS_2 = ["tackling", "ball_winner", "defensive_organisation", "scrummager", "jumper"]
NATIONALITY_BITS = [
    ("Argentina", 0, 1), ("Australia", 0, 2), ("Canada", 0, 4), ("England", 0, 16),
    ("Fiji", 0, 32), ("France", 0, 64), ("Georgia", 0, 128),
    ("Ireland", 1, 1), ("Italy", 1, 2), ("Japan", 1, 4), ("Namibia", 1, 8),
    ("New Zealand", 1, 16), ("Romania", 1, 32), ("Russia", 1, 64), ("Samoa", 1, 128),
    ("Scotland", 2, 1), ("South Africa", 2, 2), ("Tonga", 2, 8), ("Pacific Islands", 2, 16),
    ("Uruguay", 2, 32), ("USA", 2, 64), ("Wales", 2, 128),
]
SKIN_TONES = ["light", "l_medium", "d_medium", "dark"]
TAPES = ["none", "left", "right", "both"]
SET_PLAYS = ["classic", "pivot", "pocket", "dummy_switch", "miss", "cross_kick", "loop", "miss_pivot"]
ROLE_KEYS = ["captain", "viceCaptain", "longGK", "shortGK", "longPunt", "shortPunt", "kickoff"]
TEAM_PERFORMANCE = ["attack", "defence", "scrums", "lineouts", "rucking", "kicking", "technique",
                    "stamina", "flair", "rating"]

TEAMS_CSV = os.path.join(assets_directory(), "data", "rugby08_teams.csv")


class RosterError(Exception):
    pass


def load_sections(path):
    """-> (players_bytes, teams_bytes, kind)"""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise RosterError(str(e)) from e
    if data[:6] == ROS_MAGIC:
        kind = "ros"
        teams = data[ROS_TEAMS:ROS_TEAMS + TEAM_COUNT * TEAM_SIZE]
        start = ROS_BODY + RDF_PLAYERS
    else:
        kind = "rdf"
        teams = data[RDF_TEAMS:RDF_TEAMS + TEAM_COUNT * TEAM_SIZE]
        start = RDF_PLAYERS
    players = data[start:start + PLAYER_COUNT * PLAYER_SIZE]
    if len(players) < PLAYER_COUNT * PLAYER_SIZE or len(teams) < TEAM_COUNT * TEAM_SIZE:
        raise RosterError(f"{os.path.basename(path)} is too small to be a Rugby 08 roster "
                          f"({len(data)} bytes)")
    return players, teams, kind


def parse_player(r):
    rid, commentary = struct.unpack_from("<HH", r, 0)
    raw_name = r[0x04:0x12].split(b"\0")[0]
    s1, s2 = r[0x54], r[0x55]
    return {
        "roster_id": rid,
        "name": raw_name.decode("latin-1").strip(),
        "commentary": commentary,
        "positions": [POSITIONS.get(r[0x14] & 0x0F, ""), POSITIONS.get(r[0x14] >> 4, ""),
                      POSITIONS.get(r[0x15], "")],
        "weight_kg": round((r[0x16] + 100) * 0.453),
        "nationalities": [n for n, byte, bit in NATIONALITY_BITS if r[0x18 + byte] & bit],
        "height_cm": round((r[0x1C] + 59.2126) * 2.54),
        "birth": (1900 + r[0x1D], r[0x1E], r[0x1F] & 0x7F),
        "foot": "right_footed" if r[0x1F] & 0x80 else "left_footed",
        "tendency": r[0x20] if r[0x20] < len(TENDENCIES) else 0,
        "ratings": {**{k: r[0x21 + i] for i, k in enumerate(RATINGS_1)},
                    **{k: r[0x36 + i] for i, k in enumerate(RATINGS_2)}},
        "skills": [k for i, k in enumerate(SKILL_BITS_1) if s1 & (1 << i)]
                  + [k for i, k in enumerate(SKILL_BITS_2) if s2 & (1 << i)],
        "boot_style": r[0x58] & 0x0F,
        "finger_tape": {16: "left", 8: "right", 24: "both"}.get(r[0x59] & 0x18, "none"),
        "socks": "up" if r[0x59] & 0x04 else "down",
        "face_id": struct.unpack_from("<H", r, 0x5A)[0],
        "skin_tone": SKIN_TONES[r[0x5D] & 0x03],
        "wrist_tape": TAPES[(r[0x5D] >> 5) & 0x03],
        "gloves": bool(r[0x5E] & 0x08),
        "thigh_tape": TAPES[r[0x5E] & 0x03],
    }


def parse_team(b, team_id, names):
    squad = list(struct.unpack_from("<30H", b, 0x04))
    roles = struct.unpack_from("<7H", b, 0x44)
    row = names.get(team_id, {})
    return {
        "team_id": team_id,
        "name": row.get("name", f"Team {team_id}"),
        "type": row.get("type", ""),
        "squad": [p for p in squad if p],
        "roles": dict(zip(ROLE_KEYS, roles)),
        "set_plays": dict(zip(["up", "down", "left", "right"],
                              (SET_PLAYS[v] if v < len(SET_PLAYS) else "" for v in b[0x60:0x64]))),
        "performance": dict(zip(TEAM_PERFORMANCE, b[0x52:0x5C])),
    }


def load_team_names(path=None):
    path = path or TEAMS_CSV
    names = {}
    if os.path.isfile(path):
        with open(path, encoding="latin-1") as fh:
            for row in csv.reader(fh):
                if len(row) >= 4 and row[0].strip().isdigit():
                    names[int(row[0])] = {"type": row[2].strip(), "name": row[3].strip()}
    return names


def read_roster(path, teams_csv=None):
    """{"kind", "path", "players": {roster_id: player}, "teams": {team_id: team}}.
    Empty player slots (id 0) and teams without a squad are dropped."""
    players_b, teams_b, kind = load_sections(path)
    names = load_team_names(teams_csv)
    players = {}
    for i in range(PLAYER_COUNT):
        rec = parse_player(players_b[i * PLAYER_SIZE:(i + 1) * PLAYER_SIZE])
        if rec["roster_id"] and rec["name"]:
            players[rec["roster_id"]] = rec
    teams = {}
    for i in range(TEAM_COUNT):
        team = parse_team(teams_b[i * TEAM_SIZE:(i + 1) * TEAM_SIZE], i + 1, names)
        if team["squad"]:
            teams[i + 1] = team
    if not players:
        raise RosterError(f"{os.path.basename(path)}: no players found — not a Rugby 08 roster?")
    return {"kind": kind, "path": path, "players": players, "teams": teams}
