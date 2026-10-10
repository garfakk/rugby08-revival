"""
ui/kickoff_transition.py — the "kick off" animation, shared by every screen
that starts a match
=============================================================================
Quick match's sequence — the screen's chrome fades, the two players dolly
in, the crests fly to their places on the loading screen which fades in
behind them — now plays whatever the mode (quick match, challenge,
tournament).

A host screen (a Screen with `on_play_begin` / `on_play_reveal` callbacks and
a `play_btn`) mixes this in and provides:

    kt_columns()       (home, away): objects with .card (a ui.broadcast.Card),
                       .stage (a KitStage), .crest_lbl (the crest QLabel) and
                       restore_stage() — put .stage back into .card's layout
    kt_fade_widgets()  everything else that vanishes (header, hints, button…)

and calls start_kickoff_sequence(match_data) to play, reset_kickoff_visuals()
when it is shown again.
"""
import random

from PyQt5.QtWidgets import QWidget, QLabel, QGraphicsOpacityEffect
from PyQt5.QtCore import (
    Qt, QPoint, QRect, QTimer, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
)

from ui.pixmap_utils import trim_transparent

# How long the kickoff sequence's run-off takes. Deliberately long: this
# time is hidden real backend work (see start_kickoff_sequence) — the
# longer the run, the more of the game's slow prep steps finish before the
# loading screen is ever shown, which is what actually fixes a loading bar
# that otherwise visibly stalls partway through.
WALKOFF_MS = 2200

# Gap between the players' 3D zoom-in starting and the crest flight kicking
# off, so the crests visibly follow the players rather than moving with them.
CREST_DELAY_MS = 200

# Duration of the loading screen's own fade-in (names, wheel...). Scheduled
# to START early enough that it reaches full opacity exactly when the crest
# flight (which begins CREST_DELAY_MS after zoom-in) lands.
LOADING_FADE_MS = 1200


class KickoffTransition:
    _kickoff_running = False

    def kt_columns(self):
        raise NotImplementedError

    def kt_fade_widgets(self):
        raise NotImplementedError

    def reset_kickoff_visuals(self):
        if not self._kickoff_running:
            return
        for eff in getattr(self, '_fade_effects', []):
            eff.setOpacity(1.0)
        for widget in self.kt_fade_widgets():
            widget.setGraphicsEffect(None)
        for col in self.kt_columns():
            col.card.bg_opacity = 1.0
            col.crest_lbl.setGraphicsEffect(None)
        self._drop_overlay()

        from ui.player_anim import IdleAnimation
        for col in self.kt_columns():
            stage = col.stage
            if stage.parentWidget() is self:
                stage.setParent(col.card)
                col.restore_stage()
                stage.show()
            if stage.player_view is not None:
                rnd = stage.player_view.renderer
                rnd.anim = IdleAnimation(rnd.rig)
                stage.reset_yaw()
                rnd._t0 -= random.uniform(0.0, IdleAnimation.LOOP)
                stage.unfreeze()
                stage.player_view.resume()

        self.play_btn.setEnabled(True)
        self._kickoff_running = False

    # ── kickoff sequence: vanish chrome, walk the players off, reveal ────
    def start_kickoff_sequence(self, match_data):
        self._kickoff_running = True
        self.play_btn.setEnabled(False)

        # Real backend work (file prep, launching the game process) starts
        # now, hidden behind the animation — by the time the loading ring
        # is actually shown it already has a head start. The ring's own
        # display is forced back to 0 on reveal regardless (see
        # on_play_reveal / GameWidget.restart_loading_display), so what the
        # player sees is a normal-looking 0->100 climb that is quietly
        # ahead of schedule the whole way — the "trick" that makes the wait
        # feel shorter without lying about a fixed duration.
        self.on_play_begin(match_data)
        self._make_crest_flyers()

        fade_targets = self.kt_fade_widgets()
        group = QParallelAnimationGroup(self)
        self._fade_effects = []
        for w in fade_targets:
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            self._fade_effects.append(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(450)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            group.addAnimation(anim)
        # The team cards' own panel (fill, border, stripe) fades too — not
        # via QGraphicsOpacityEffect, which would also dim the 3D player
        # stage living inside it, but via the card's own bg_opacity so the
        # player stays fully opaque while its bordered box disappears
        # around it instead of sitting there empty through the whole
        # walk-off / zoom.
        for col in self.kt_columns():
            anim = QPropertyAnimation(col.card, b"bg_opacity", self)
            anim.setDuration(450)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(anim)

        self._fade_group = group
        # The camera dollies in past the players.
        group.finished.connect(self._begin_zoom_in)
        group.start()

    # ── crest flight: match-setup crests -> loading-screen crests ────────
    def _make_crest_flyers(self):
        """From the moment Kick off is pressed, draw each team crest on a
        window-level overlay, on top of the real one (which is hidden), so it
        can later fly to its place on the loading screen."""
        self._overlay = None
        self._flyers = {}
        win = self.window()
        if getattr(win, "screen_ingame", None) is None:
            return
        overlay = QWidget(win)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setStyleSheet("background: transparent;")
        overlay.setGeometry(win.rect())
        for side, col in zip(("home", "away"), self.kt_columns()):
            pix = col.crest_lbl.pixmap()
            if pix is None or pix.isNull():
                continue
            trimmed, kept = trim_transparent(pix)
            dpr = pix.devicePixelRatio()
            w, h = int(pix.width() / dpr), int(pix.height() / dpr)
            label_box = QRect(col.crest_lbl.mapTo(win, QPoint(0, 0)), col.crest_lbl.size())
            origin = QPoint(label_box.x() + (label_box.width() - w) // 2,
                            label_box.y() + (label_box.height() - h) // 2)
            start = QRect(origin.x() + int(kept.x() / dpr), origin.y() + int(kept.y() / dpr),
                          max(1, int(kept.width() / dpr)), max(1, int(kept.height() / dpr)))
            fly = QLabel(overlay)
            fly.setScaledContents(True)
            fly.setPixmap(trimmed)
            fly.setStyleSheet("background: transparent;")
            fly.setGeometry(start)
            fly.show()
            self._flyers[side] = fly
            eff = QGraphicsOpacityEffect(col.crest_lbl)
            eff.setOpacity(0.0)
            col.crest_lbl.setGraphicsEffect(eff)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _drop_overlay(self):
        overlay = getattr(self, "_overlay", None)
        if overlay is None:
            return
        for col in self.kt_columns():
            stage = col.stage
            if stage.parentWidget() is overlay:
                stage.setParent(self)     # what reset_kickoff_visuals expects
                stage.hide()
        overlay.hide()
        overlay.deleteLater()
        self._overlay = None
        self._flyers = {}

    def _begin_zoom_in(self):
        # Players keep their idle loop — only the "camera" moves, dollying
        # in on the point between the two of them. A zoom into that
        # barycentre pushes everything away from it in the frame, so each
        # player grows *and* slides toward whichever edge is already on
        # their side — home left, away right — until they run off it,
        # rather than the two of them converging into one blob at centre.
        #
        # The loading screen is switched to at the START of the zoom: the
        # players (moved onto the window-level overlay) keep zooming over it,
        # the crests fly to their places and the rest of the loading screen
        # fades in. Without a loading screen to hand it falls back to the old
        # behaviour (reveal it once the zoom is over).
        win = self.window()
        ingame = getattr(win, "screen_ingame", None)
        overlay = getattr(self, "_overlay", None)
        transition = ingame is not None and overlay is not None
        parent, offset = (overlay, self.mapTo(win, QPoint(0, 0))) if transition else (self, QPoint(0, 0))

        rects = {}
        home_col, away_col = self.kt_columns()
        for col in (home_col, away_col):
            stage = col.stage
            top_left = stage.mapTo(self, QPoint(0, 0))
            rect = stage.geometry()
            rect.moveTopLeft(top_left + offset)
            rects[col] = rect
        barycentre = QPoint(
            (rects[home_col].center().x() + rects[away_col].center().x()) // 2,
            (rects[home_col].center().y() + rects[away_col].center().y()) // 2)

        group = QParallelAnimationGroup(self)
        scale = 3.4
        for col in (home_col, away_col):
            stage = col.stage
            rect = rects[col]
            stage.freeze(scale)     # animate one finished image, not a live 3D render
            layout = stage.parentWidget().layout()
            if layout is not None:
                layout.removeWidget(stage)
            stage.setParent(parent)
            stage.setMinimumHeight(0)
            stage.setMaximumHeight(16777215)
            stage.setGeometry(rect)
            stage.show()
            stage.raise_()

            end_w, end_h = int(rect.width() * scale), int(rect.height() * scale)
            end_cx = barycentre.x() + (rect.center().x() - barycentre.x()) * scale
            end_cy = barycentre.y() + (rect.center().y() - barycentre.y()) * scale
            end_rect = QRect(int(end_cx - end_w / 2), int(end_cy - end_h / 2), end_w, end_h)
            anim = QPropertyAnimation(stage, b"geometry", self)
            anim.setDuration(WALKOFF_MS)
            anim.setStartValue(rect)
            anim.setEndValue(end_rect)
            # Accelerating, unlike the walk-off's steady InQuad — a dolly-in
            # starts slow and rushes at the end.
            anim.setEasingCurve(QEasingCurve.InCubic)
            group.addAnimation(anim)
        self._walkoff_group = group

        if not transition:
            group.finished.connect(self._finish_kickoff)
            group.start()
            return

        ingame.prepare_intro_transition()
        self.on_play_reveal()                 # loading screen on, match setup off

        def start_animations():
            # Players start zooming (and, over the run, fading out) right away.
            group.start()

            # The crests follow CREST_DELAY_MS later, in their own group, so
            # they visibly trail the players instead of moving in lockstep.
            crest_group = QParallelAnimationGroup(self)
            for side, fly in self._flyers.items():
                target, _pix = ingame.crest_display_rect(side, win)
                if target.isEmpty():
                    fly.hide()
                    continue
                anim = QPropertyAnimation(fly, b"geometry", self)
                anim.setDuration(WALKOFF_MS)
                anim.setStartValue(fly.geometry())
                anim.setEndValue(target)
                anim.setEasingCurve(QEasingCurve.InOutCubic)
                crest_group.addAnimation(anim)
            self._crest_group = crest_group
            crest_group.finished.connect(self._finish_zoom_transition)

            def start_crest_group():
                # Kickoff may have been reset (e.g. game exited) while we
                # were waiting out the delay — the flyers are gone by then.
                if self._kickoff_running and self._flyers:
                    crest_group.start()
            QTimer.singleShot(CREST_DELAY_MS, start_crest_group)

            # The rest of the loading screen (names, wheel...) fades in so its
            # own end lines up with the crests landing, not starting from there.
            fade_start = max(0, CREST_DELAY_MS + WALKOFF_MS - LOADING_FADE_MS)

            def start_loading_fade():
                if self._kickoff_running:
                    # Re-triggers the ring's 0%-start climb (see
                    # ingame._run_intro_climb) right as it becomes visible —
                    # otherwise the climb that began back when this screen
                    # was first switched to has already run ahead by the
                    # time the fade reveals it.
                    ingame.restart_loading_display()
                    ingame.play_intro_fade(LOADING_FADE_MS)
            QTimer.singleShot(fade_start, start_loading_fade)
        QTimer.singleShot(0, start_animations)

    def _finish_zoom_transition(self):
        ingame = getattr(self.window(), "screen_ingame", None)
        if ingame is not None:
            ingame.show_crests()
        self._drop_overlay()

    def _finish_kickoff(self):
        self.on_play_reveal()
