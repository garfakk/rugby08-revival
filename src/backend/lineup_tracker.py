"""
backend/lineup_tracker.py — who played where, and for how long
=================================================================
Fed by R08_handler with a snapshot of both teams' positions at every poll
during the match. The tracker does not care which game code path made a
change (human or CPU substitution, injury replacement, re-entry from the
reR08 resub patch, positional swap, card): it compares each snapshot with the
previous one.

Snapshot, per team: {position 1..15: {"id": roster id, "off": bool}}, "off" =
the Player is off the pitch (sin bin, sent off); plus per team {id: {"red":
red cards, "injury": 0/1}} from the player records.

Time between two polls is credited to every player on the pitch, in the
position held at the earlier poll, on the displayed clock (the one on
screen: 80-minute scale) and on real time. A stopped clock (pause menu,
period end) credits nothing on the displayed clock — substitutions are made
from the pause menu, so their timing costs no polling error.
"""


class LineupTracker:
    def __init__(self):
        self.lineups = None         # last snapshot {team: {pos: {"id", "off"}}}
        self.starting = None        # first snapshot
        self.events = []
        self.time = {}              # {team: {id: {pos: seconds}}} displayed clock
        self.real_time = {}         # same, real seconds
        self._records = {}
        self._subbed_off = {}       # {team: set(ids)} replaced by someone
        self._removed = {}          # {team: set(ids)} left with nobody replacing them
        self._last_clock = None
        self._last_real = None

    def update(self, clock, period, real, lineups, records):
        if self.lineups is not None:
            self._credit(clock, real)
            for team, positions in lineups.items():
                self._diff(team, positions, records.get(team, {}), clock, period)
        else:
            self.starting = {team: {pos: dict(p) for pos, p in positions.items()}
                             for team, positions in lineups.items()}
        self.lineups = {team: {pos: dict(p) for pos, p in positions.items()}
                        for team, positions in lineups.items()}
        self._records = {team: {pid: dict(r) for pid, r in recs.items()}
                         for team, recs in records.items()}
        self._last_clock, self._last_real = clock, real

    def _credit(self, clock, real):
        dc = max(0.0, clock - self._last_clock) if clock is not None and self._last_clock is not None else 0.0
        dr = max(0.0, real - self._last_real) if real is not None and self._last_real is not None else 0.0
        for team, positions in self.lineups.items():
            for pos, p in positions.items():
                if p['off']:
                    continue
                for store, delta in ((self.time, dc), (self.real_time, dr)):
                    by_pos = store.setdefault(team, {}).setdefault(p['id'], {})
                    by_pos[pos] = by_pos.get(pos, 0.0) + delta

    def _event(self, team, kind, clock, period, **fields):
        self.events.append({'team': team, 'type': kind,
                            'clock': round(clock, 1) if clock is not None else None,
                            'period': period, **fields})

    def _diff(self, team, positions, records, clock, period):
        before = self.lineups.get(team, {})
        old_pos = {p['id']: pos for pos, p in before.items()}
        new_pos = {p['id']: pos for pos, p in positions.items()}
        old_records = self._records.get(team, {})
        subbed_off = self._subbed_off.setdefault(team, set())
        removed = self._removed.setdefault(team, set())

        left = [pid for pid in old_pos if pid not in new_pos]
        # Someone who left from the position a newcomer takes is the one he replaced
        for pid, pos in sorted(new_pos.items(), key=lambda x: x[1]):
            if pid in old_pos:
                if old_pos[pid] != pos:
                    self._event(team, 'move', clock, period, id=pid, **{'from': old_pos[pid]}, to=pos)
                continue
            replaced = before.get(pos, {}).get('id')
            if replaced not in left:
                replaced = left[0] if len(left) == 1 else None
            if replaced is not None:
                left.remove(replaced)
                subbed_off.add(replaced)
            if pid in removed and replaced is None:
                # back after being taken off with nobody in the position (sin bin)
                removed.discard(pid)
                self._event(team, 'return', clock, period, id=pid, position=pos)
                continue
            injured = bool(replaced is not None and (records.get(replaced) or {}).get('injury'))
            self._event(team, 'reentry' if pid in subbed_off else 'sub', clock, period,
                        on_id=pid, off_id=replaced, position=pos, injury=injured)
            subbed_off.discard(pid)
        for pid in left:
            # taken off and nobody in the position: card, or a sub still to come
            removed.add(pid)
            red = records.get(pid, {}).get('red', 0) > old_records.get(pid, {}).get('red', 0)
            self._event(team, 'red_card' if red else 'off', clock, period, id=pid, position=old_pos[pid])

        # Off the pitch without leaving the position: sin bin / red card
        for pid, pos in new_pos.items():
            if pid not in old_pos:
                continue
            was_off, is_off = before[old_pos[pid]]['off'], positions[pos]['off']
            if is_off and not was_off:
                red = (records.get(pid, {}).get('red', 0)
                       > old_records.get(pid, {}).get('red', 0))
                self._event(team, 'red_card' if red else 'sin_bin', clock, period, id=pid, position=pos)
            elif was_off and not is_off:
                self._event(team, 'return', clock, period, id=pid, position=pos)

        for pid, rec in records.items():
            if rec.get('injury') and not old_records.get(pid, {}).get('injury'):
                self._event(team, 'injury', clock, period, id=pid, position=new_pos.get(pid))

    def summary(self, team):
        """{id: {"seconds", "real_seconds", "positions": {pos: seconds},
        "real_positions": {pos: seconds}}} of every player who was on the pitch."""
        out = {}
        for pid, by_pos in self.time.get(team, {}).items():
            real = self.real_time.get(team, {}).get(pid, {})
            out[pid] = {'seconds': round(sum(by_pos.values()), 1),
                        'real_seconds': round(sum(real.values()), 1),
                        'positions': {pos: round(s, 1) for pos, s in sorted(by_pos.items())},
                        'real_positions': {pos: round(s, 1) for pos, s in sorted(real.items())}}
        return out
