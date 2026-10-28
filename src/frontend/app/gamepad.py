"""
app/gamepad.py — gamepads drive the menus
==========================================
Polls the pads (XInput on Windows, the joystick device on Linux; nothing to
install) and turns their buttons into the keys app.input.KEYMAP already maps
to actions, so every screen that works with the keyboard works with a pad:

    D-pad / left stick  arrows (held: repeats)    A      Enter   (CONFIRM)
    LB / RB             Page Up / Page Down       B      Escape  (BACK)
    Start               F       (ADVANCED)        X / Y  X / Y   (ALT / AUX)
    View (Back/Select)  Delete  (clear a field, remove a layer)

A key goes to the focused widget, else to the current screen (`fallback`).
The keys carry no text, so X or Y on a text field acts on the screen instead
of typing a letter. Nothing is sent while `enabled()` says no: in a match the
game reads the pads itself.
"""
import ctypes
import os
import struct
import sys
import time

from PyQt5.QtCore import QObject, QTimer, QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication

from shared.log import get_logger

log = get_logger(__name__)

KEYS = {
    "up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right,
    "a": Qt.Key_Return, "b": Qt.Key_Escape, "x": Qt.Key_X, "y": Qt.Key_Y,
    "lb": Qt.Key_PageUp, "rb": Qt.Key_PageDown, "start": Qt.Key_F, "select": Qt.Key_Delete,
}
DIRECTIONS = ("up", "down", "left", "right")
REPEAT_DELAY = 0.40         # s held before a direction repeats...
REPEAT_INTERVAL = 0.11      # ...then every this long
POLL_MS = 16
STICK_PRESS, STICK_RELEASE = 0.55, 0.35     # of full tilt (hysteresis: no flicker)


def stick_directions(x, y, held=()):
    """Directions a stick at (x, y) in [-1, 1] (y up) presses: past
    STICK_PRESS, or past STICK_RELEASE for one already `held`. Only the
    stronger axis, so a diagonal never moves focus twice."""
    out = set()
    if abs(x) >= abs(y):
        name = "right" if x > 0 else "left"
        if abs(x) >= (STICK_RELEASE if name in held else STICK_PRESS):
            out.add(name)
    else:
        name = "up" if y > 0 else "down"
        if abs(y) >= (STICK_RELEASE if name in held else STICK_PRESS):
            out.add(name)
    return out


# ── XInput (Windows) ──────────────────────────────────────────────────────────
class _XInputGamepad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", _XInputGamepad)]


_XINPUT_BUTTONS = {0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right",
                   0x0010: "start", 0x0020: "select", 0x0100: "lb", 0x0200: "rb",
                   0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y"}


class XInputSource:
    """Up to four XInput pads, merged. A slot found empty is asked again only
    every few seconds: XInputGetState on an empty slot is slow."""
    RECHECK = 3.0

    def __init__(self):
        self._dll = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self._dll = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if self._dll is None:
            raise OSError("no XInput DLL")
        self._empty_until = [0.0] * 4
        self._stick_held = set()

    def pressed(self):
        out = set()
        now = time.monotonic()
        state = _XInputState()
        sticks = set()
        for slot in range(4):
            if now < self._empty_until[slot]:
                continue
            if self._dll.XInputGetState(slot, ctypes.byref(state)) != 0:
                self._empty_until[slot] = now + self.RECHECK
                continue
            pad = state.Gamepad
            out |= {name for bit, name in _XINPUT_BUTTONS.items() if pad.wButtons & bit}
            sticks |= stick_directions(pad.sThumbLX / 32767, pad.sThumbLY / 32767, self._stick_held)
        self._stick_held = sticks
        return out | sticks


# ── Linux joystick API (/dev/input/js*) ───────────────────────────────────────
_JS_EVENT = struct.Struct("<IhBB")          # time, value, type, number
_JS_BUTTON, _JS_AXIS, _JS_INIT = 0x01, 0x02, 0x80
# The xpad layout (Xbox pads, and most others under Linux)
_JS_BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "select", 7: "start"}


class LinuxJoystickSource:
    def __init__(self):
        self._fds = []
        for n in range(4):
            try:
                self._fds.append(os.open(f"/dev/input/js{n}", os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                continue
        if not self._fds:
            raise OSError("no joystick device")
        self._buttons = set()
        self._axes = {}
        self._stick_held = set()

    def pressed(self):
        for fd in self._fds:
            while True:
                try:
                    data = os.read(fd, _JS_EVENT.size * 32)
                except BlockingIOError:
                    break
                except OSError:
                    break                   # unplugged
                if not data:
                    break
                for i in range(0, len(data) - _JS_EVENT.size + 1, _JS_EVENT.size):
                    _t, value, kind, number = _JS_EVENT.unpack_from(data, i)
                    kind &= ~_JS_INIT
                    if kind == _JS_BUTTON and number in _JS_BUTTONS:
                        (self._buttons.add if value else self._buttons.discard)(_JS_BUTTONS[number])
                    elif kind == _JS_AXIS:
                        self._axes[number] = value / 32767
        out = set(self._buttons)
        hat_x, hat_y = self._axes.get(6, 0), self._axes.get(7, 0)
        if hat_x:
            out.add("right" if hat_x > 0 else "left")
        if hat_y:
            out.add("down" if hat_y > 0 else "up")
        self._stick_held = stick_directions(self._axes.get(0, 0), -self._axes.get(1, 0),
                                            self._stick_held)
        return out | self._stick_held


def open_source():
    """This platform's pad source, None when there is none."""
    try:
        return XInputSource() if sys.platform == "win32" else LinuxJoystickSource()
    except (OSError, AttributeError) as e:
        log.info(f"gamepad: none ({e})")
        return None


def key_target(fallback=None):
    """Where a key goes: the open popup's focus, else the focused widget, else
    `fallback()` (the current screen)."""
    popup = QApplication.activePopupWidget()
    if popup is not None:
        return popup.focusWidget() or popup
    widget = QApplication.focusWidget()
    if widget is not None and widget.isVisible():
        return widget
    return fallback() if fallback else None


def send_key(key, fallback=None, repeat=False):
    """A key press and release, as from the keyboard but without text."""
    target = key_target(fallback)
    if target is None:
        return False
    QApplication.sendEvent(target, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", repeat))
    target = key_target(fallback)           # the press may have moved focus
    if target is not None:
        QApplication.sendEvent(target, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, "", repeat))
    return True


class GamepadNavigator(QObject):
    """Polls `source` and sends the keys of newly pressed buttons (and held
    directions, repeated) while `enabled()`."""

    def __init__(self, source, fallback=None, enabled=None, parent=None):
        super().__init__(parent)
        self._source = source
        self._fallback = fallback
        self._enabled = enabled or (lambda: True)
        self._held = set()
        self._next_repeat = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(POLL_MS)

    def poll(self):
        try:
            pressed = self._source.pressed()
        except OSError as e:
            log.warning(f"gamepad: stopped ({e})")
            self._timer.stop()
            return
        if not self._enabled():
            # Buttons held when it comes back (the A that started a match)
            # don't fire then.
            self._held = pressed
            self._next_repeat.clear()
            return
        self.feed(pressed, time.monotonic())

    def feed(self, pressed, now):
        """One poll's pressed buttons: new ones fire; held directions repeat."""
        for name in sorted(pressed - self._held):
            if name in KEYS:
                send_key(KEYS[name], self._fallback)
                if name in DIRECTIONS:
                    self._next_repeat[name] = now + REPEAT_DELAY
        for name in pressed & self._held:
            due = self._next_repeat.get(name)
            if due is not None and now >= due:
                send_key(KEYS[name], self._fallback, repeat=True)
                self._next_repeat[name] = now + REPEAT_INTERVAL
        for name in self._held - pressed:
            self._next_repeat.pop(name, None)
        self._held = set(pressed)
