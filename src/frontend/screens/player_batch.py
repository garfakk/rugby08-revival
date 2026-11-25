"""
screens/player_batch.py — the player editor's batch mode
==========================================================
SELECT in the player list puts a tick box on every row; the tabs give way
to one form whose fields all start at "keep". Whatever is changed there is
applied, in one go, to every ticked player (app/player_batch.py does the
work). The preview pane lists the ticked players with their overall now
and after the change; APPLY saves them all, UNDO puts them back.
"""
import copy

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QBoxLayout, QHBoxLayout, QVBoxLayout

from app import appearance as A
from app import player_batch as B
from app import player_ops as P
from app.game_data import FEET, SOCKS, TAPES, EditsOffError, SaveError, save_players
from app.ratings import GROUPS
from app.season import season_label
from backend import game_specific_variables as gsv
from ui.broadcast import Card, display_label, eyebrow_label
from ui.editor_kit import (
    ChoiceField, ConfirmDialog, FieldGrid, NumberField, SectionCard, SegmentField, TabPage,
    TextField, compact_button, load_pixmap,
)
from ui.form import SearchList
from ui.theme import DANGER_LITE, FG_SECONDARY, FG_TERTIARY, GREEN, INFO, T_LABEL, T_TITLE
from shared.config import config

KEEP = "keep"


class DeltaField(NumberField):
    """A rating change: blank = keep, else "+3" / "−3" (arrows, ←→)."""

    def __init__(self, label, span=30):
        super().__init__(label, lo=-span, hi=span, allow_blank=True, default=0,
                         formatter=lambda v: KEEP if v in ("0", "-0") else
                         (f"+{v}" if int(v) > 0 else f"−{v[1:]}"))

    def paint_blank(self, p, rect):
        self.draw_blank(p, rect, KEEP)

    def delta(self):
        return self.as_int() or 0


class SeasonField(NumberField):
    """A season year: blank = none; the arrows start from `default` (the
    season after the newest one)."""

    def __init__(self, label):
        super().__init__(label, lo=1900, hi=2100, allow_blank=True, formatter=season_label)

    def paint_blank(self, p, rect):
        self.draw_blank(p, rect, "none")


class BatchPanel:
    """The batch form (a page of the shell's stack) and its preview list
    (in the preview pane), driven by the player editor screen."""

    def __init__(self, screen):
        self.screen = screen
        self.active = False
        self.undo_records = None       # {pid: record before the last APPLY}
        self.undo_label = ""
        self._fields = []
        self._build_page()
        self._build_preview()

    # ── building ─────────────────────────────────────────────────────────
    def _reg(self, field, edited=True):
        self.screen.focus.register(field)
        if edited:
            field.edited.connect(lambda _v: self.changed())
        self._fields.append(field)
        return field

    def _build_page(self):
        self.page = TabPage()
        body = self.page.layout_

        top = QHBoxLayout()
        top.setSpacing(14)
        self.title = display_label("", T_TITLE, QFont.Bold, track=0.6, upper=False)
        top.addWidget(self.title)
        self.moves = display_label("", T_LABEL, QFont.DemiBold, track=0.6, color=FG_SECONDARY,
                                   upper=False)
        top.addWidget(self.moves)
        top.addStretch(1)
        self.scope = ChoiceField("Seasons", ["all", "latest"], allow_blank=False,
                                 display=self._scope_label)
        self.scope.label_width = 80
        self.scope.setFixedWidth(300)
        self.scope.set_value("all")
        self.scope.popup_title = "seasons"
        self._reg(self.scope)
        top.addWidget(self.scope)
        body.addLayout(top)

        # two columns of cards, one in a narrow window (fit())
        self.cols = row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)

        # ── ratings ──────────────────────────────────────────────────────
        ratings = SectionCard("ratings")
        g = FieldGrid(columns=1)
        self.level = self._reg(ChoiceField(
            "Level", [k for k, _l, _o in P.LEVELS], allow_blank=True, blank_label=KEEP,
            clearable=True,
            display=lambda v: next(f"{lab} · {o}" for k, lab, o in P.LEVELS if k == v)))
        self.level.popup_title = "level"
        g.add(self.level)
        self.shift = self._reg(DeltaField("All ratings"))
        g.add(self.shift)
        ratings.add(g)
        self.groups_grid = g2 = FieldGrid(columns=2, v_spacing=4)
        self.groups = {}
        for name, _keys in GROUPS:
            f = self._reg(DeltaField(name))
            f.label_width = 90
            g2.add(f)
            self.groups[name] = f
        ratings.add(g2)
        left.addWidget(ratings)

        # ── profile ──────────────────────────────────────────────────────
        profile = SectionCard("profile")
        g = FieldGrid(columns=1)
        self.nationality = self._reg(TextField("Nationality", placeholder=KEEP))
        g.add(self.nationality)
        self.foot = self._reg(SegmentField("Stronger foot", FEET, allow_blank=True,
                                           blank_label=KEEP,
                                           display=lambda v: v.replace("_footed", "")))
        g.add(self.foot)
        profile.add(g)
        self._profile = profile

        # ── gear ─────────────────────────────────────────────────────────
        gear = SectionCard("gear")
        g = FieldGrid(columns=1)
        self.boots = self._reg(ChoiceField("Boots", allow_blank=True, blank_label=KEEP,
                                           clearable=True))
        self.boots.popup_title = "boots"
        self.boots.display = lambda v: f"Style {v}" if str(v).isdigit() else A.label_of(v)
        self.boots.icon_for = lambda v: (None if str(v).isdigit() else
                                         load_pixmap(A.abs_path(config.mod_data_directory, v), 52))
        self.boots.off_list_badge = False
        g.add(self.boots)
        self.kick = self._reg(ChoiceField(
            "Goal-kick style", list(gsv.goal_kicking_style_values), allow_blank=True,
            blank_label=KEEP, clearable=True, display=lambda v: v.replace("_", " ").title()))
        g.add(self.kick)
        gear.add(g)
        g3 = FieldGrid(columns=1)
        self.socks = self._reg(SegmentField("Socks", SOCKS, allow_blank=True, blank_label=KEEP))
        g3.add(self.socks)
        self.tapes = {}
        for key, label in (("wrist_tape", "Wrist tape"), ("tight_tape", "Thigh tape"),
                           ("finger_tape", "Finger tape")):
            f = self._reg(SegmentField(label, TAPES, allow_blank=True, blank_label=KEEP))
            g3.add(f)
            self.tapes[key] = f
        gear.add(g3)
        right.addWidget(gear)
        left.addWidget(profile)
        left.addStretch(1)

        # ── seasons ──────────────────────────────────────────────────────
        seasons = SectionCard("seasons")
        g = FieldGrid(columns=1)
        self.add_season = self._reg(SeasonField("Add season"))
        g.add(self.add_season)
        self.delete_season = self._reg(ChoiceField("Delete season", allow_blank=True,
                                                   blank_label="none", clearable=True,
                                                   display=season_label))
        self.delete_season.popup_title = "delete season"
        g.add(self.delete_season)
        seasons.add(g)
        right.addWidget(seasons)

        players = SectionCard("players")
        self.delete_btn = compact_button("DELETE PLAYERS…", "danger")
        self.delete_btn.clicked.connect(self.confirm_delete)
        self.screen.focus.register(self.delete_btn)
        players.add(self.delete_btn)
        right.addWidget(players)
        right.addStretch(1)

        row.addLayout(left, stretch=1)
        row.addLayout(right, stretch=1)
        body.addLayout(row)
        body.addStretch(1)
        self.screen.shell.stack.addWidget(self.page)

    def _build_preview(self):
        self.preview = Card()
        v = QVBoxLayout(self.preview)
        v.setContentsMargins(14, 14, 14, 12)
        v.setSpacing(8)
        self.preview_title = eyebrow_label("", color=FG_TERTIARY, size=11)
        v.addWidget(self.preview_title)
        self.preview_list = SearchList(show_filter=False)
        self.preview_list.activated.connect(self._preview_open)
        v.addWidget(self.preview_list, stretch=1)
        self.screen.shell.preview_layout.addWidget(self.preview, stretch=1)
        self.preview.hide()
        self._preview_timer = QTimer(self.preview)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._refresh_preview)

    # ── state ────────────────────────────────────────────────────────────
    def pids(self):
        return [p for p in self.screen.list.checked_data() if p in self.screen.ds.players]

    def records(self):
        return [self.screen.ds.players[p] for p in self.pids()]

    def _scope_label(self, v):
        if v == "all":
            return "All seasons"
        if v == "latest":
            return "Latest season"
        n = self._season_counts.get(v, 0)
        return f"{season_label(v)} · {n} of {len(self.pids())}"

    _season_counts = {}

    def changes(self):
        c = {}
        if self.level.value():
            c["level"] = self.level.value()
        if self.shift.delta():
            c["shift"] = self.shift.delta()
        groups = {name: f.delta() for name, f in self.groups.items() if f.delta()}
        if groups:
            c["groups"] = groups
        values = {"nationality": self.nationality.value().strip(), "foot": self.foot.value(),
                  "boot_style": self.boots.value(), "goal_kicking_style": self.kick.value(),
                  "socks": self.socks.value(),
                  **{k: f.value() for k, f in self.tapes.items()}}
        values = {k: v for k, v in values.items() if v}
        if values:
            c["set"] = values
        if self.add_season.value():
            c["add_season"] = self.add_season.value()
        if self.delete_season.value():
            c["delete_season"] = self.delete_season.value()
        return c

    def change_count(self):
        """How many fields are set (what SAVE's count shows)."""
        c = self.changes()
        return (bool(c.get("level")) + bool(c.get("shift")) + len(c.get("groups") or {})
                + len(c.get("set") or {}) + bool(c.get("add_season"))
                + bool(c.get("delete_season")))

    def is_dirty(self):
        return bool(self.pids()) and not B.is_empty(self.changes())

    def clear(self):
        for f in self._fields:
            if f is not self.scope:
                f.set_value("")
        self.changed()

    # ── showing ──────────────────────────────────────────────────────────
    def enter(self):
        self.active = True
        sh = self.screen.shell
        sh.tabs.hide()
        self.screen.season_row.hide()
        if sh.identity_pane is not None:
            sh.identity_pane.hide()
        sh.stack.setCurrentWidget(self.page)
        self.screen._preview_card.hide()
        self.preview.show()
        self.refresh()

    def leave(self):
        self.active = False
        self.clear()
        self.undo_records = None
        self.preview.hide()
        self.screen._preview_card.show()
        sh = self.screen.shell
        if sh.identity_pane is not None:
            sh.identity_pane.show()

    def refresh(self):
        """The ticked players changed (or the data did)."""
        if not self.active:
            return
        pids = self.pids()
        n = len(pids)
        self.title.setText(f"{n} player{'s' if n != 1 else ''}" if n else "Tick players in the list")
        self._season_counts = B.seasons_of(self.records())
        years = list(self._season_counts)
        self.scope.set_options(["all", "latest"] + years[::-1])
        if self.scope.value() not in self.scope.options:
            self.scope.set_value("all")
        self.delete_season.set_options(years[::-1])
        # the arrows start from the newest season: one up is the next one
        self.add_season.default = years[-1] if years else None
        sections = A.boot_sections(config.mod_data_directory)
        self.boots.set_options([v for _, values in sections for v in values])
        self.boots.section_for = (lambda v, s={v: t for t, vals in sections for v in vals}:
                                  s.get(v, A.CUSTOM_SECTION))
        self.delete_btn.setText(f"DELETE {n} PLAYER{'S' if n != 1 else ''}…" if n
                                else "DELETE PLAYERS…")
        self.delete_btn.setEnabled(bool(n))
        for f in self._fields:
            f.setEnabled(bool(n))
        self.changed()

    def fit(self):
        """Cards side by side when the page is wide enough, else one column."""
        w = self.page.viewport().width()
        pane = self.screen.shell.preview_pane
        self.moves.setVisible(not pane.isVisibleTo(self.screen))
        self.cols.setDirection(QBoxLayout.LeftToRight if w >= 820 else QBoxLayout.TopToBottom)
        cols = 2 if w >= 820 or w >= 560 else 1
        g = self.groups_grid
        if g.columns != cols:
            fields = g.fields()
            for f in fields:
                g.grid.removeWidget(f)
            g.columns, g._row, g._col, g._fields = cols, 0, 0, []
            for f in fields:
                g.add(f)

    def changed(self):
        self._preview_timer.start()
        self.screen._refresh_chrome()

    CHUNK_SECONDS = 0.008      # per timer tick: thousands of players never freeze the window

    def _refresh_preview(self):
        """Work out every ticked player's overall before / after, a few
        players per event-loop turn, then show the list."""
        if not self.active:
            return
        changes = self.changes()
        self._job = (iter(self.pids()), changes, self.scope.value(), not B.is_empty(changes),
                     [], [0, 0])
        self._preview_step()

    _job = None

    def _preview_step(self):
        import time
        if self._job is None or not self.active:
            return
        pids, changes, scope, busy, items, counts = self._job
        end = time.perf_counter() + self.CHUNK_SECONDS
        players = self.screen.ds.players
        for pid in pids:
            record = players[pid]
            now, after = B.overall_change(record, changes, scope)
            name = record.get("display_name") or record.get("last_name") or pid
            if now is None and after is None:
                tag, color = "—", FG_TERTIARY
            elif busy and after != now:
                up = (after or 0) > (now or 0)
                tag, color = f"{now} → {after}", (None if up else DANGER_LITE)
                counts[0 if up else 1] += 1
            else:
                tag, color = f"{now if now is not None else '—'}", FG_TERTIARY
            items.append((pid, name, tag, color, False))
            if time.perf_counter() > end:
                QTimer.singleShot(0, self._preview_step)
                return
        self._job = None
        self.preview_list.set_items(items)
        raised, lowered = counts
        moves = (([f"{raised} up"] if raised else []) + ([f"{lowered} down"] if lowered else []))
        self.preview_title.setText(" · ".join([f"{len(items)} selected" if items
                                               else "nothing selected"] + moves).upper())
        self.moves.setText(" · ".join(moves))

    def _preview_open(self, pid):
        """A row of the preview list: back to the list, on that player."""
        self.screen.list.select_data(pid)
        self.screen.list.setFocus()

    # ── footer ───────────────────────────────────────────────────────────
    def refresh_footer(self):
        f = self.screen.shell.footer
        n = len(self.pids())
        dirty = self.is_dirty()
        f.save_btn.setEnabled(dirty)
        f.save_btn.setText(f"APPLY TO {n}" if dirty else "APPLY")
        if dirty:
            f.revert_btn.setText("CLEAR")
            f.revert_btn.setEnabled(True)
        else:
            f.revert_btn.setText("UNDO")
            f.revert_btn.setEnabled(self.undo_records is not None)
        f.target.setText("")
        self.screen.shell.header.set_dirty(self.change_count() if dirty else 0)

    def revert_or_undo(self):
        if self.is_dirty():
            self.clear()
        elif self.undo_records is not None:
            self.undo()

    # ── apply / undo ─────────────────────────────────────────────────────
    def _write(self, records):
        """Save {pid: record}, one write per players file."""
        ds = self.screen.ds
        by_file = {}
        for pid, record in records.items():
            by_file.setdefault(ds.players_file_path.get(pid), {})[pid] = record
        for path, recs in by_file.items():
            save_players(path, recs)
            for pid, record in recs.items():
                ds.players[pid] = record
        for pid in records:
            ds.events.player_changed.emit(pid)

    def apply(self):
        if not self.is_dirty():
            return True
        changes, scope = self.changes(), self.scope.value()
        ds = self.screen.ds
        before, after = {}, {}
        for pid in self.pids():
            record = copy.deepcopy(ds.players[pid])
            if B.apply(record, changes, scope):
                before[pid] = ds.players[pid]
                after[pid] = record
        footer = self.screen.shell.footer
        if not after:
            footer.set_status("Nothing to change for these players", FG_SECONDARY)
            self.clear()
            return True
        try:
            self._write(after)
        except EditsOffError:
            # once on, apply again: the changes land on the kept edits
            self.screen.ask_edits_on(self.apply, replaces=False)
            return False
        except (SaveError, OSError) as e:
            footer.set_status(f"Save failed: {e}", DANGER_LITE)
            return False
        self.undo_records = before
        n = len(after)
        self.undo_label = f"{n} player{'s' if n != 1 else ''}"
        skipped = len(self.pids()) - n
        self.clear()
        self.screen.after_batch(list(after))
        footer.set_status(f"Updated {self.undo_label}"
                          + (f" · {skipped} unchanged" if skipped else ""), GREEN)
        return True

    def undo(self):
        if not self.undo_records:
            return
        records = self.undo_records
        try:
            self._write({pid: copy.deepcopy(r) for pid, r in records.items()})
        except (SaveError, OSError) as e:
            self.screen.shell.footer.set_status(f"Undo failed: {e}", DANGER_LITE)
            return
        self.undo_records = None
        self.screen.after_batch(list(records))
        self.screen.shell.footer.set_status(f"Undid the change to {self.undo_label}", FG_SECONDARY)

    # ── delete ───────────────────────────────────────────────────────────
    def confirm_delete(self):
        pids = self.pids()
        if not pids:
            return
        n = len(pids)
        ds = self.screen.ds
        names = [ds.players[p].get("display_name") or p for p in pids[:4]]
        squads = sum(1 for p in pids if ds.memberships(p, with_variants=True))
        text = ", ".join(names) + (f" and {n - 4} more" if n > 4 else "") + " will be deleted."
        if squads:
            text += f" {squads} of them are taken out of their squads."

        def done(role):
            self.screen._dialog = None
            if role == "delete":
                self.delete(pids)

        self.screen.show_dialog(ConfirmDialog(
            self.screen, f"Delete {n} player{'s' if n != 1 else ''}?", text,
            [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "delete")], done))

    def delete(self, pids):
        ds = self.screen.ds
        teams, done = set(), 0
        for pid in pids:
            try:
                _files, changed, _skipped = P.delete_everywhere(ds, pid, True)
            except (SaveError, OSError) as e:
                self.screen.shell.footer.set_status(f"Delete failed: {e}", DANGER_LITE)
                break
            teams.update(changed)
            ds.unregister_player(pid)
            done += 1
        for tid in teams:
            ds.events.team_changed.emit(tid)
        self.undo_records = None
        self.screen.after_batch_delete(pids[:done])
        self.screen.shell.footer.set_status(
            f"Deleted {done} player{'s' if done != 1 else ''}", INFO if done else DANGER_LITE)
