"""
tournament/model.py — The tournament's saved state, as plain dataclasses.

Every class round-trips through JSON with to_dict()/from_dict(). from_dict()
ignores keys it does not know and lets dataclass defaults fill missing ones,
so a save written by an older build still loads. Features added later should
keep their state in a `components` dict (see effects.register_component)
rather than in new fields: the save format then never needs a migration
for them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Optional

SCHEMA_VERSION = 1


def _known(cls, data: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in (data or {}).items() if k in names}


# ── Players ───────────────────────────────────────────────────────────────

@dataclass
class Condition:
    """Something temporarily affecting a player: an injury, a ban... `kind`
    is looked up in effects' condition registry. `matches_left` counts the
    team's matches still to go; None = open-ended (removed explicitly)."""
    kind: str
    matches_left: Optional[int] = None
    since_day: int = 0
    data: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_known(cls, d))


@dataclass
class PlayerState:
    """One squad member. `base` is the player's flattened season record as it
    was when the tournament was created (DataStore.get_players format), so
    later edits to the data pack never change a running tournament."""
    pid: str
    team_id: str
    name: str = ""
    base: dict = field(default_factory=dict)
    conditions: list = field(default_factory=list)   # [Condition]
    components: dict = field(default_factory=dict)

    @property
    def position(self) -> str:
        return self.base.get("position1", "") or ""

    @property
    def positions(self) -> list:
        return [p for p in (self.base.get(k, "") for k in ("position1", "position2", "position3")) if p]

    def conditions_of(self, kind: str) -> list:
        return [c for c in self.conditions if c.kind == kind]

    def to_dict(self):
        d = asdict(self)
        d["conditions"] = [c.to_dict() for c in self.conditions]
        return d

    @classmethod
    def from_dict(cls, d):
        p = cls(**_known(cls, d))
        p.conditions = [Condition.from_dict(c) for c in (d.get("conditions") or [])]
        return p


# ── Teams ─────────────────────────────────────────────────────────────────

@dataclass
class TeamEntry:
    """A participant. `selection` is the 22 for the next match:
    {"players": [22 pids], "positions": [22 slot positions],
     "roles": {captain, viceCaptain, longGK, shortGK, longPunt, shortPunt,
     kickoff: pid}, "set_plays": {...}, "manual": bool}. `positions` is
    stored even though v1 only plays people where the slot says, so a later
    repositioning feature only has to read it."""
    team_id: str
    season: str
    name: str
    variant: str = ""            # competition variant of the season ("" = default squad)
    human: bool = False
    controller: int = 0          # controller slot when human (1 = keyboard)
    squad: list = field(default_factory=list)
    default_roles: dict = field(default_factory=dict)
    set_plays: dict = field(default_factory=dict)
    stadium_id: str = ""
    selection: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_known(cls, d))


# ── Results ───────────────────────────────────────────────────────────────

@dataclass
class PlayerLine:
    pid: str
    started: bool = True
    minutes: int = 80
    tries: int = 0
    conversions: int = 0
    conversions_attempted: int = 0
    penalties: int = 0
    penalties_attempted: int = 0
    drop_goals: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    tackles: int = 0
    injured: bool = False

    @property
    def points(self) -> int:
        return self.tries * 5 + self.conversions * 2 + self.penalties * 3 + self.drop_goals * 3

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_known(cls, d))


@dataclass
class SideResult:
    team_id: str
    players: list = field(default_factory=list)   # [PlayerLine]
    penalty_tries: int = 0                        # 7 points, no scorer, no kick
    stats: dict = field(default_factory=dict)     # scrums/lineouts... when known

    def _sum(self, key):
        return sum(getattr(p, key) for p in self.players)

    @property
    def tries(self):
        return self._sum("tries") + self.penalty_tries

    @property
    def points(self):
        return self._sum("points") + 7 * self.penalty_tries

    @property
    def yellow_cards(self):
        return self._sum("yellow_cards")

    @property
    def red_cards(self):
        return self._sum("red_cards")

    def line(self, pid) -> Optional[PlayerLine]:
        return next((p for p in self.players if p.pid == pid), None)

    def to_dict(self):
        d = asdict(self)
        d["players"] = [p.to_dict() for p in self.players]
        return d

    @classmethod
    def from_dict(cls, d):
        s = cls(**_known(cls, d))
        s.players = [PlayerLine.from_dict(p) for p in (d.get("players") or [])]
        return s


@dataclass
class MatchResult:
    """One played fixture, the same shape whether it came from the game or the
    simulator. `winner` is only set when the points do not decide it (a
    knockout draw settled on tries or kicks, a forfeit)."""
    home: SideResult
    away: SideResult
    source: str = "sim"            # sim | game | forfeit
    winner: Optional[str] = None
    decided_by: str = ""           # "" | tries | kicks | forfeit
    shootout: list = field(default_factory=list)   # [home goals, away goals]
    events: list = field(default_factory=list)     # [{minute, team, kind, pid}]
    extra: dict = field(default_factory=dict)

    def winner_id(self) -> Optional[str]:
        if self.winner:
            return self.winner
        if self.home.points > self.away.points:
            return self.home.team_id
        if self.away.points > self.home.points:
            return self.away.team_id
        return None

    def loser_id(self) -> Optional[str]:
        w = self.winner_id()
        if w is None:
            return None
        return self.away.team_id if w == self.home.team_id else self.home.team_id

    def side(self, team_id) -> Optional[SideResult]:
        if self.home.team_id == team_id:
            return self.home
        if self.away.team_id == team_id:
            return self.away
        return None

    def opponent(self, team_id) -> Optional[SideResult]:
        if self.home.team_id == team_id:
            return self.away
        if self.away.team_id == team_id:
            return self.home
        return None

    def score_text(self) -> str:
        text = f"{self.home.points}-{self.away.points}"
        if self.decided_by == "kicks" and self.shootout:
            text += f" ({self.shootout[0]}-{self.shootout[1]} kicks)"
        elif self.decided_by == "tries":
            text += " (on tries)"
        elif self.decided_by == "forfeit":
            text += " (forfeit)"
        return text

    def to_dict(self):
        d = asdict(self)
        d["home"] = self.home.to_dict()
        d["away"] = self.away.to_dict()
        return d

    @classmethod
    def from_dict(cls, d):
        r = cls(**_known(cls, d))
        r.home = SideResult.from_dict(d.get("home"))
        r.away = SideResult.from_dict(d.get("away"))
        return r


# ── Structure ─────────────────────────────────────────────────────────────

@dataclass
class Fixture:
    """A match on the calendar. Knockout fixtures are created up front with
    `home_ref`/`away_ref` ("pools:A1", "W:qf1"...) and their teams filled in
    once those resolve (engine.resolve_refs)."""
    id: str
    stage_id: str
    day: int
    home: Optional[str] = None
    away: Optional[str] = None
    group: str = ""
    round_id: str = ""
    round_name: str = ""
    label: str = ""
    home_ref: str = ""
    away_ref: str = ""
    knockout: bool = False
    neutral: bool = False
    stadium_id: str = ""
    match_subtype: str = "none"
    final: bool = False
    result: Optional[MatchResult] = None

    @property
    def played(self) -> bool:
        return self.result is not None

    @property
    def ready(self) -> bool:
        return bool(self.home and self.away)

    def involves(self, team_id) -> bool:
        return team_id in (self.home, self.away)

    def to_dict(self):
        d = asdict(self)
        d["result"] = self.result.to_dict() if self.result else None
        return d

    @classmethod
    def from_dict(cls, d):
        f = cls(**_known(cls, d))
        f.result = MatchResult.from_dict(d["result"]) if d.get("result") else None
        return f


@dataclass
class Group:
    id: str
    name: str
    teams: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**_known(cls, d))


@dataclass
class Stage:
    id: str
    name: str
    kind: str                       # round_robin | knockout
    spec: dict = field(default_factory=dict)
    groups: list = field(default_factory=list)   # [Group], round_robin only
    status: str = "pending"         # pending | active | done

    def group(self, gid) -> Optional[Group]:
        return next((g for g in self.groups if g.id == gid), None)

    def to_dict(self):
        d = asdict(self)
        d["groups"] = [g.to_dict() for g in self.groups]
        return d

    @classmethod
    def from_dict(cls, d):
        s = cls(**_known(cls, d))
        s.groups = [Group.from_dict(g) for g in (d.get("groups") or [])]
        return s


# ── Root ──────────────────────────────────────────────────────────────────

@dataclass
class Tournament:
    id: str
    name: str
    template_id: str
    season: str
    seed: int
    template: dict = field(default_factory=dict)   # full copy: rules can't drift
    options: dict = field(default_factory=dict)
    teams: dict = field(default_factory=dict)      # team_id -> TeamEntry
    players: dict = field(default_factory=dict)    # pid -> PlayerState
    stages: list = field(default_factory=list)     # [Stage]
    fixtures: list = field(default_factory=list)   # [Fixture], calendar order
    day: int = 0                                   # next matchday to play
    news: list = field(default_factory=list)       # [{day, kind, text, teams, pid}]
    stats: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)
    champion: Optional[str] = None
    created: str = ""
    updated: str = ""
    data_version: str = ""
    schema_version: int = SCHEMA_VERSION

    # ── lookups ──
    def stage(self, sid) -> Optional[Stage]:
        return next((s for s in self.stages if s.id == sid), None)

    def fixture(self, fid) -> Optional[Fixture]:
        return next((f for f in self.fixtures if f.id == fid), None)

    def fixtures_on(self, day) -> list:
        return [f for f in self.fixtures if f.day == day]

    def team_fixtures(self, team_id) -> list:
        return [f for f in self.fixtures if f.involves(team_id)]

    def last_day(self) -> int:
        return max((f.day for f in self.fixtures), default=-1)

    def human_teams(self) -> list:
        return [t for t in self.teams.values() if t.human]

    def team_name(self, team_id) -> str:
        entry = self.teams.get(team_id)
        return entry.name if entry else (team_id or "TBD")

    def player_name(self, pid) -> str:
        p = self.players.get(pid)
        return (p.name if p else "") or str(pid)

    @property
    def finished(self) -> bool:
        return self.champion is not None

    def add_news(self, kind, text, teams=(), pid=None):
        self.news.append({"day": self.day, "kind": kind, "text": text,
                          "teams": list(teams), "pid": pid})

    # ── serialisation ──
    def to_dict(self):
        return {
            "schema_version": self.schema_version,
            "id": self.id, "name": self.name, "template_id": self.template_id,
            "season": self.season, "seed": self.seed, "template": self.template,
            "options": self.options,
            "teams": {k: v.to_dict() for k, v in self.teams.items()},
            "players": {k: v.to_dict() for k, v in self.players.items()},
            "stages": [s.to_dict() for s in self.stages],
            "fixtures": [f.to_dict() for f in self.fixtures],
            "day": self.day, "news": self.news, "stats": self.stats,
            "components": self.components, "champion": self.champion,
            "created": self.created, "updated": self.updated,
            "data_version": self.data_version,
        }

    @classmethod
    def from_dict(cls, d):
        t = cls(**_known(cls, d))
        t.teams = {k: TeamEntry.from_dict(v) for k, v in (d.get("teams") or {}).items()}
        t.players = {k: PlayerState.from_dict(v) for k, v in (d.get("players") or {}).items()}
        t.stages = [Stage.from_dict(s) for s in (d.get("stages") or [])]
        t.fixtures = [Fixture.from_dict(f) for f in (d.get("fixtures") or [])]
        return t
