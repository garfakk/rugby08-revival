"""
app/challenge_objectives.py — a challenge's own objectives, judged by the mod
================================================================================
The game's .mis objectives are never read back, so the objectives that decide
a challenge are judged here, from what R08_handler reads out of the game:
the per-player scoring lines at full time and the scores it timestamped with
the match clock while the match was played (result["events"]).

A challenge is won only if the side the player controls wins AND every
objective in its `match_objectives` passes. Each objective is a dict:

  {"type": "score", "event": "try", "player": 9, "before": 40, "count": 1}
      the player's side scores `count` × `event` (try / conversion /
      penalty / drop_goal / any), by shirt number `player` if given, before
      match minute `before` if given
  {"type": "restrict", "event": "try", "max": 0}
      the opponents score at most `max` × `event` ("points" counts points)
  {"type": "lead_at", "minute": 40, "margin": 1}
      the player's side leads by `margin` or more at that minute
  {"type": "never_trail"}
      the player's side is never behind on the scoreboard
  {"type": "win_by", "margin": 7}
      the player's side wins by `margin` or more

All of them count from the minute the challenge starts: the score it starts
on is history, not something the player did. "text" overrides the generated
description.
"""
from backend import game_specific_variables as gsv

EVENTS = ["any", "try", "conversion", "penalty", "drop_goal"]
TYPES = ["score", "restrict", "lead_at", "never_trail", "win_by"]
POINTS = {"try": 5, "conversion": 2, "penalty": 3, "drop_goal": 3}
# .mis score events (challenge score_events) by scoring type
_MIS_TYPE = {"SS_TRY": "try", "SS_CONVERSION": "conversion",
             "SS_PENALTY": "penalty", "SS_DROPGOAL": "drop_goal"}
_KEY = {"home": "team_A", "away": "team_B"}
_NOUN = {"any": ("score", "scores"), "try": ("try", "tries"),
         "conversion": ("conversion", "conversions"), "penalty": ("penalty", "penalties"),
         "drop_goal": ("drop goal", "drop goals"), "points": ("point", "points")}


def _other(side):
    return "away" if side == "home" else "home"


def _noun(event, n):
    one, many = _NOUN.get(event, _NOUN["any"])
    return one if n == 1 else many


def _minute(m):
    return f"{int(m)}'"


def describe(obj: dict, names: dict = None, team_names: dict = None,
             user_side: str = "home") -> str:
    """One line for `obj`. `names` = {side: {shirt: player name}},
    `team_names` = {side: team name} (both optional)."""
    if obj.get("text"):
        return obj["text"]
    names, team_names = names or {}, team_names or {}
    opp = team_names.get(_other(user_side), "the opponents")
    kind = obj.get("type")
    event = obj.get("event") or "any"
    if kind == "score":
        n = int(obj.get("count") or 1)
        if event == "any":
            text = "Score" if n == 1 else f"Score {n} times"
        else:
            verb = "Score" if event == "try" else "Kick"
            text = f"{verb} {'a' if n == 1 else n} {_noun(event, n)}"
        player = obj.get("player")
        who = ""
        if player:
            name = names.get(user_side, {}).get(int(player))
            who = f" with {name} (#{player})" if name else f" with #{player}"
        when = f" before {_minute(obj['before'])}" if obj.get("before") else ""
        return f"{text}{who}{when}"
    if kind == "restrict":
        n = int(obj.get("max") or 0)
        if n == 0:
            return f"Concede no {_noun(event, 2)}" if event != "any" else f"Keep {opp} scoreless"
        return f"Concede {n} {_noun(event, n)} or fewer"
    if kind == "lead_at":
        margin = int(obj.get("margin") or 1)
        lead = "Lead" if margin <= 1 else f"Lead by {margin}+"
        minute = obj.get("minute")
        return f"{lead} at half-time" if minute == 40 else f"{lead} at {_minute(minute)}"
    if kind == "never_trail":
        return f"Never let {opp} take the lead"
    if kind == "win_by":
        return f"Win by {int(obj.get('margin') or 1)} points or more"
    return kind or "?"


# ── the match as a list of scores ─────────────────────────────────────────
def _pre_scores(challenge):
    """{(side, shirt, type): n} the challenge starts with."""
    out = {}
    for ev in challenge.get("score_events") or []:
        kind = _MIS_TYPE.get(ev.get("type"))
        if kind and ev.get("team") in _KEY:
            key = (ev["team"], int(ev.get("player") or 0), kind)
            out[key] = out.get(key, 0) + 1
    return out


def _shirt(team_key, row, index):
    ids = gsv.players_roster_id.get(team_key, [])
    return (ids.index(row.get("id")) if row.get("id") in ids else index) + 1


def match_scores(challenge: dict, result: dict):
    """(scores, timed): every score made from the challenge start, oldest
    first — [{"side": "home", "shirt": 10, "type": "try", "clock": s}] — and
    whether they carry the clock (False when the game's clock could not be
    read during the match: the scores then come from the full-time sheet,
    without a time)."""
    pre = _pre_scores(challenge)
    start = float(challenge.get("mission_mode_time") or 0)
    events = (result or {}).get("events")
    if events is not None:
        left = dict(pre)
        out = []
        for ev in sorted(events, key=lambda e: e.get("clock") or 0):
            side = "home" if ev.get("team") == "team_A" else "away"
            score = {"side": side, "shirt": int(ev.get("slot", 0)) + 1,
                     "type": ev.get("type"), "clock": float(ev.get("clock") or 0)}
            key = (side, score["shirt"], score["type"])
            # The starting score credited to the players after tracking began
            # shows up as scores at the very first second: not the player's.
            if left.get(key) and score["clock"] <= start + 1:
                left[key] -= 1
                continue
            out.append(score)
        return out, True
    out = []
    for side, key in _KEY.items():
        for i, row in enumerate(((result or {}).get(key) or {}).get("players") or []):
            shirt = _shirt(key, row, i)
            for kind, field in (("try", "tries"), ("conversion", "conversions_scored"),
                                ("penalty", "penalties_scored"), ("drop_goal", "drop_goals")):
                n = int(row.get(field) or 0) - pre.get((side, shirt, kind), 0)
                out += [{"side": side, "shirt": shirt, "type": kind, "clock": None}] * max(0, n)
    return out, False


def _score_at(challenge, scores, clock):
    """{"home": points, "away": points} once every score before `clock`
    (None = all of them) is in."""
    pts = {"home": 0, "away": 0}
    for ev in challenge.get("score_events") or []:
        if ev.get("team") in pts:
            pts[ev["team"]] += POINTS.get(_MIS_TYPE.get(ev.get("type")), 0)
    for s in scores:
        if clock is None or (s["clock"] is not None and s["clock"] < clock):
            pts[s["side"]] += POINTS.get(s["type"], 0)
    return pts


def _final(result):
    return {side: (((result or {}).get(key) or {}).get("score") or {}).get("points", 0)
            for side, key in _KEY.items()}


def judge(obj: dict, challenge: dict, result: dict, scores=None, timed=None):
    """(passed, note): True/False, or None when it could not be checked
    (counts as not passed). `note` says what happened, for the result screen."""
    if scores is None:
        scores, timed = match_scores(challenge, result)
    me = challenge.get("user_side", "home")
    opp = _other(me)
    kind = obj.get("type")
    event = obj.get("event") or "any"

    def matches(s, side):
        return s["side"] == side and (event in ("any", "points") or s["type"] == event)

    if kind == "score":
        before = obj.get("before")
        if before and not timed:
            return None, "match clock not read"
        hits = [s for s in scores if matches(s, me)
                and (not obj.get("player") or s["shirt"] == int(obj["player"]))
                and (not before or s["clock"] < before * 60)]
        need = int(obj.get("count") or 1)
        if len(hits) >= need:
            return True, "done"
        return False, f"{len(hits)} of {need}" if need > 1 else "not done"
    if kind == "restrict":
        if event == "points":
            n = sum(POINTS.get(s["type"], 0) for s in scores if s["side"] == opp)
        else:
            n = sum(1 for s in scores if matches(s, opp))
        limit = int(obj.get("max") or 0)
        return n <= limit, f"conceded {n} {_noun(event, n)}"
    if kind == "lead_at":
        if not timed:
            return None, "match clock not read"
        pts = _score_at(challenge, scores, float(obj.get("minute") or 0) * 60)
        diff = pts[me] - pts[opp]
        return diff >= int(obj.get("margin") or 1), f"{pts[me]}-{pts[opp]} then"
    if kind == "never_trail":
        if not timed:
            return None, "match clock not read"
        for s in scores:
            pts = _score_at(challenge, scores, s["clock"] + 0.01)
            if pts[opp] > pts[me]:
                return False, f"behind at {_minute(s['clock'] // 60)}"
        return True, "never behind"
    if kind == "win_by":
        pts = _final(result)
        diff = pts[me] - pts[opp]
        return diff >= int(obj.get("margin") or 1), f"won by {diff}" if diff > 0 else "not won"
    return None, "unknown objective"


def judge_all(challenge: dict, result: dict):
    """[(objective, passed, note)] for every match objective."""
    objectives = challenge.get("match_objectives") or []
    if not objectives:
        return []
    scores, timed = match_scores(challenge, result)
    return [(obj, *judge(obj, challenge, result, scores, timed)) for obj in objectives]
