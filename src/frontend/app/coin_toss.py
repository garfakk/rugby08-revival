"""
app/coin_toss.py — The pre-match coin toss (World Rugby Law 6.3 / Law 13.2)
==============================================================================
Law 6.3: "One of the captains tosses a coin and the other captain calls. The
winner of the toss decides whether to kick off or to choose an end. If the
winner of the toss decides to choose an end, the opponents must kick off and
vice versa."

Law 13.2: the team whose captain elected to kick off (or the opponents of a
captain who elected an end) kicks off the match; after half-time the other
team kicks off. The second half is the game's own business — only the start
of the match is decided here.

By custom the home captain tosses and the visiting captain calls.

Pure logic, no Qt: ui/coin_toss.py drives it step by step (who calls, the
flip, the winner's choice, the end) and asks for a human decision only for a
side the player controls; every other decision is the CPU captain's.
"""
import random
from dataclasses import dataclass
from typing import Optional

HEADS, TAILS = "heads", "tails"
KICK_OFF, CHOOSE_END = "kick off", "choose end"
LEFT, RIGHT = "left", "right"

TOSSER = "home"     # the captain who tosses the coin
CALLER = "away"     # the captain who calls it


def other(side: str) -> str:
    return "away" if side == "home" else "home"


@dataclass
class CoinToss:
    """One toss, filled in as it happens. `rng` is injectable for tests."""
    call: Optional[str] = None          # HEADS / TAILS, the caller's call
    face: Optional[str] = None          # what the coin landed on
    decision: Optional[str] = None      # KICK_OFF / CHOOSE_END, the winner's choice
    end: Optional[str] = None           # LEFT / RIGHT, the end the end-chooser takes
    rng: random.Random = None

    def __post_init__(self):
        if self.rng is None:
            self.rng = random.Random()

    # ── steps ────────────────────────────────────────────────────────────
    def cpu_call(self) -> str:
        return self.rng.choice((HEADS, TAILS))

    def flip(self) -> str:
        """Toss the coin; the call must already be made."""
        assert self.call in (HEADS, TAILS)
        self.face = self.rng.choice((HEADS, TAILS))
        return self.face

    def cpu_decision(self) -> str:
        return self.rng.choice((KICK_OFF, CHOOSE_END))

    def cpu_end(self) -> str:
        return self.rng.choice((LEFT, RIGHT))

    # ── derived ──────────────────────────────────────────────────────────
    @property
    def winner(self) -> Optional[str]:
        if self.face is None:
            return None
        return CALLER if self.face == self.call else TOSSER

    @property
    def end_chooser(self) -> Optional[str]:
        """Whoever picks the end: the winner if they elected to, otherwise
        the opponents of a winner who elected to kick off."""
        if self.decision is None:
            return None
        return self.winner if self.decision == CHOOSE_END else other(self.winner)

    @property
    def kicker(self) -> Optional[str]:
        """The side kicking off: never the end-chooser."""
        if self.decision is None:
            return None
        return other(self.end_chooser)

    def resolved(self) -> dict:
        """The MatchConfig fields the toss decides: kick_off ("home"/"away")
        and home_team_side ("left"/"right")."""
        assert self.end in (LEFT, RIGHT)
        home_end = self.end if self.end_chooser == "home" else (RIGHT if self.end == LEFT else LEFT)
        return {"kick_off": self.kicker, "home_team_side": home_end}
