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

Each pad is also told apart (its index: connection order, the order the game
numbers them): `pad_pressed` reports which pad pressed what, and a `claim`
callback can keep a pad's press for itself instead of the key (the
controllers board: every pad moves its own icon).
"""
import ctypes
import os
import struct
import sys
import time

from PyQt5 import sip
from PyQt5.QtCore import QObject, QTimer, QEvent, Qt, pyqtSignal
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
        self._stick_held = {}

    def pads(self):
        """{slot: buttons pressed} for each connected pad."""
        out = {}
        now = time.monotonic()
        state = _XInputState()
        for slot in range(4):
            if now < self._empty_until[slot]:
                continue
            if self._dll.XInputGetState(slot, ctypes.byref(state)) != 0:
                self._empty_until[slot] = now + self.RECHECK
                continue
            pad = state.Gamepad
            held = self._stick_held.get(slot, set())
            sticks = stick_directions(pad.sThumbLX / 32767, pad.sThumbLY / 32767, held)
            self._stick_held[slot] = sticks
            out[slot] = {name for bit, name in _XINPUT_BUTTONS.items() if pad.wButtons & bit} | sticks
        return out

    def pressed(self):
        return set().union(*self.pads().values())


# ── Linux joystick API (/dev/input/js*) ───────────────────────────────────────
_JS_EVENT = struct.Struct("<IhBB")          # time, value, type, number
_JS_BUTTON, _JS_AXIS, _JS_INIT = 0x01, 0x02, 0x80
# The xpad layout (Xbox pads, and most others under Linux)
_JS_BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "select", 7: "start"}


def _is_pad(n):
    """Whether /dev/input/js<n> is a gamepad. Absolute mice, tablets and
    touch devices (VM and remote-desktop passthrough) show up as joysticks
    too, sit at a corner of their range, and read as a stick held left."""
    base = f"/sys/class/input/js{n}/device/capabilities/key"
    try:
        with open(base) as f:
            words = [int(w, 16) for w in f.read().split()]
    except (OSError, ValueError):
        return True                         # can't tell: keep the old behaviour

    def has(code):
        i = code // 64
        return i < len(words) and bool(words[-1 - i] >> (code % 64) & 1)
    return has(0x130) or has(0x120)         # BTN_SOUTH (pads) / BTN_TRIGGER (sticks)


class LinuxJoystickSource:
    """/dev/input/js0..js3; a node not there (or unplugged) is looked for
    again every few seconds, so a pad plugged in later shows up."""
    RECHECK = 2.0

    def __init__(self):
        if not os.path.isdir("/dev/input"):
            raise OSError("no /dev/input")
        self._fds = {}                      # js number: fd
        self._buttons = {}
        self._axes = {}
        self._stick_held = {}
        self._next_scan = 0.0

    def _scan(self):
        now = time.monotonic()
        if now < self._next_scan:
            return
        self._next_scan = now + self.RECHECK
        for n in range(4):
            if n in self._fds:
                continue
            if not _is_pad(n):
                continue
            try:
                self._fds[n] = os.open(f"/dev/input/js{n}", os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._buttons[n], self._axes[n], self._stick_held[n] = set(), {}, set()

    def _drop(self, n):
        try:
            os.close(self._fds.pop(n))
        except OSError:
            pass
        for state in (self._buttons, self._axes, self._stick_held):
            state.pop(n, None)

    def pads(self):
        """{js number: buttons pressed} for each connected pad."""
        self._scan()
        out = {}
        for n, fd in list(self._fds.items()):
            buttons, axes = self._buttons[n], self._axes[n]
            gone = False
            while True:
                try:
                    data = os.read(fd, _JS_EVENT.size * 32)
                except BlockingIOError:
                    break
                except OSError:
                    gone = True             # unplugged
                    break
                if not data:
                    break
                for i in range(0, len(data) - _JS_EVENT.size + 1, _JS_EVENT.size):
                    _t, value, kind, number = _JS_EVENT.unpack_from(data, i)
                    kind &= ~_JS_INIT
                    if kind == _JS_BUTTON and number in _JS_BUTTONS:
                        (buttons.add if value else buttons.discard)(_JS_BUTTONS[number])
                    elif kind == _JS_AXIS:
                        axes[number] = value / 32767
            if gone:
                self._drop(n)
                continue
            pressed = set(buttons)
            hat_x, hat_y = axes.get(6, 0), axes.get(7, 0)
            if hat_x:
                pressed.add("right" if hat_x > 0 else "left")
            if hat_y:
                pressed.add("down" if hat_y > 0 else "up")
            self._stick_held[n] = stick_directions(axes.get(0, 0), -axes.get(1, 0),
                                                   self._stick_held[n])
            out[n] = pressed | self._stick_held[n]
        return out

    def pressed(self):
        return set().union(*self.pads().values())


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


_navigator = None


def navigator():
    """The running GamepadNavigator, None without pads support (or once its
    window is gone)."""
    if _navigator is not None and sip.isdeleted(_navigator):
        return None
    return _navigator


class GamepadNavigator(QObject):
    """Polls `source` and sends the keys of newly pressed buttons (and held
    directions, repeated) while `enabled()`.

    Per pad: `pad_pressed(pad, button)` for each new press, `pads_changed`
    with the connected pads' indices when one comes or goes. `claim`, when
    set, is offered each new press first: True keeps it (no key is sent
    while that button stays down)."""
    pad_pressed = pyqtSignal(int, str)
    pads_changed = pyqtSignal(tuple)

    def __init__(self, source, fallback=None, enabled=None, parent=None):
        global _navigator
        super().__init__(parent)
        self._source = source
        self._fallback = fallback
        self._enabled = enabled or (lambda: True)
        self._held = set()
        self._next_repeat = {}
        self._pad_held = {}
        self._claimed = {}
        self._connected = ()
        self.claim = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(POLL_MS)
        _navigator = self

    def connected(self):
        """Indices of the pads connected, in order."""
        return self._connected

    def poll(self):
        try:
            pads = self._source.pads()
        except OSError as e:
            log.warning(f"gamepad: stopped ({e})")
            self._timer.stop()
            return
        connected = tuple(sorted(pads))
        if connected != self._connected:
            self._connected = connected
            self.pads_changed.emit(connected)
        if not self._enabled():
            # Buttons held when it comes back (the A that started a match)
            # don't fire then.
            self._pad_held = {n: set(b) for n, b in pads.items()}
            self._claimed.clear()
            self._held = set().union(*pads.values())
            self._next_repeat.clear()
            return
        self.feed_pads(pads, time.monotonic())

    def feed_pads(self, pads, now):
        """One poll's buttons per pad: reported, offered to `claim`, and the
        rest sent as keys (feed)."""
        merged = set()
        for n, pressed in pads.items():
            held = self._pad_held.get(n, set())
            claimed = self._claimed.setdefault(n, set())
            claimed &= pressed
            for name in sorted(pressed - held):
                self.pad_pressed.emit(n, name)
                if self.claim is not None and self.claim(n, name):
                    claimed.add(name)
            self._pad_held[n] = set(pressed)
            merged |= pressed - claimed
        for n in set(self._pad_held) - set(pads):
            self._pad_held.pop(n)
            self._claimed.pop(n, None)
        self.feed(merged, now)

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
