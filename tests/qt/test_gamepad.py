"""Gamepads drive the menus through the keys the screens already handle
(app/gamepad.py): sticks, repeats, what each pad source reads."""
import os
import struct

import pytest
from PyQt5.QtCore import Qt

import app.gamepad as gp

pytestmark = pytest.mark.qt


def test_stick_directions():
    assert gp.stick_directions(0.0, 0.0) == set()
    assert gp.stick_directions(0.9, 0.1) == {"right"}
    assert gp.stick_directions(-0.2, -0.8) == {"down"}
    assert gp.stick_directions(0.7, 0.6) == {"right"}            # a diagonal: one move
    assert gp.stick_directions(0.45, 0.0) == set()               # not past the press point...
    assert gp.stick_directions(0.45, 0.0, held={"right"}) == {"right"}   # ...but held: no flicker


@pytest.fixture
def sent(monkeypatch):
    keys = []
    monkeypatch.setattr(gp, "send_key", lambda key, fallback=None, repeat=False: keys.append((key, repeat)))
    return keys


def _navigator(qapp, enabled=lambda: True):
    class Idle:
        def pressed(self):
            return set()
    nav = gp.GamepadNavigator(Idle(), enabled=enabled)
    nav._timer.stop()
    return nav


def test_presses_fire_once_and_directions_repeat(qapp, sent):
    nav = _navigator(qapp)
    nav.feed({"a"}, 0.0)
    nav.feed({"a"}, 1.0)                                  # held A: once
    assert sent == [(Qt.Key_Return, False)]
    sent.clear()
    nav.feed({"down"}, 2.0)
    nav.feed({"down"}, 2.0 + gp.REPEAT_DELAY - 0.01)      # not yet
    nav.feed({"down"}, 2.0 + gp.REPEAT_DELAY)             # repeats...
    nav.feed({"down"}, 2.0 + gp.REPEAT_DELAY + gp.REPEAT_INTERVAL)
    assert sent == [(Qt.Key_Down, False), (Qt.Key_Down, True), (Qt.Key_Down, True)]
    sent.clear()
    nav.feed(set(), 5.0)
    nav.feed(set(), 6.0)                                  # released: stops
    assert sent == []


def test_buttons_held_while_disabled_do_not_fire(qapp, sent):
    """The A that started a match is still down when the menus come back."""
    on = {"value": False}
    nav = _navigator(qapp, enabled=lambda: on["value"])
    nav._source.pressed = lambda: {"a"}
    nav.poll()
    on["value"] = True
    nav.poll()
    assert sent == []


def test_pad_buttons_map_to_the_action_keys():
    from app.input import KEYMAP, Action
    assert KEYMAP[gp.KEYS["a"]] == Action.CONFIRM
    assert KEYMAP[gp.KEYS["b"]] == Action.BACK
    assert KEYMAP[gp.KEYS["lb"]] == Action.TAB_PREV and KEYMAP[gp.KEYS["rb"]] == Action.TAB_NEXT
    assert KEYMAP[gp.KEYS["x"]] == Action.ALT and KEYMAP[gp.KEYS["y"]] == Action.AUX
    assert KEYMAP[gp.KEYS["start"]] == Action.ADVANCED


def test_linux_joystick_events():
    read, write = os.pipe()
    os.set_blocking(read, False)
    src = gp.LinuxJoystickSource.__new__(gp.LinuxJoystickSource)
    src._fds, src._buttons, src._axes, src._stick_held = [read], set(), {}, set()
    event = struct.Struct("<IhBB")
    os.write(write, event.pack(0, 1, 0x01 | 0x80, 0)      # A down (initial state)
             + event.pack(0, 32767, 0x02, 7)              # d-pad down
             + event.pack(0, -30000, 0x02, 1))            # left stick up
    assert src.pressed() == {"a", "down", "up"}
    os.write(write, event.pack(0, 0, 0x01, 0) + event.pack(0, 0, 0x02, 7) + event.pack(0, 0, 0x02, 1))
    assert src.pressed() == set()
    os.close(read)
    os.close(write)


def test_layer_stack_moves_a_layer_without_shift(qapp):
    """X picks the layer up, Up/Down move it, A drops it: a pad has no Shift."""
    from PyQt5.QtTest import QTest
    from ui.editor_kit import LayerStackField
    stack = LayerStackField()
    stack.set_layers([{"value": "a", "label": "a"}, {"value": "b", "label": "b"}])
    stack.cursor = 1                    # rows top-first: "b", then "a"
    edits = []
    stack.edited.connect(edits.append)
    QTest.keyClick(stack, Qt.Key_X)
    assert stack.carrying
    QTest.keyClick(stack, Qt.Key_Up)    # "a" goes on top
    assert edits == [["b", "a"]] and stack.selected_layer() == 1
    QTest.keyClick(stack, Qt.Key_Return)
    assert not stack.carrying
    QTest.keyClick(stack, Qt.Key_Down)  # just moves the cursor again
    assert edits == [["b", "a"]]


def test_kit_list_moves_a_kit_without_alt(qapp):
    from PyQt5.QtTest import QTest
    from screens.team_tabs import KitList
    kits = KitList()
    kits.set_kits(["home", "away", "third"], 0, {})
    moves = []
    kits.moved.connect(lambda a, b: moves.append((a, b)))
    QTest.keyClick(kits, Qt.Key_X)
    QTest.keyClick(kits, Qt.Key_Down)
    assert moves == [(0, 1)]
    QTest.keyClick(kits, Qt.Key_Escape)      # drops it; doesn't leave the screen
    assert not kits.carrying
