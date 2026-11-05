"""The head turns on its own neck and rides the torso: its neck stays centred
in the collar however the idles move it (it used to slide through the side
of the collar — the stock head's neck sits forward of the body's axis)."""
import numpy as np
import pytest

from ui import player_anim as A


class _Part:
    def __init__(self, pos, is_head=False):
        self.positions = np.asarray(pos, dtype=np.float32)
        self.normals = np.tile(np.float32([0, 1, 0]), (len(self.positions), 1))
        self.is_head = is_head


def _ring(y, r, z=0.0, n=16):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([r * np.cos(a), np.full(n, y), z + r * np.sin(a)], 1)


@pytest.fixture
def figure():
    ys = np.linspace(0, 95, 20)
    body = np.concatenate([_ring(y, 12) for y in ys] + [_ring(88, 50)])   # T-pose arms
    head = np.concatenate([_ring(y, 4, z=3.8) for y in np.linspace(89, 108, 8)])
    parts = [_Part(body), _Part(head, is_head=True)]
    return parts, A.PlayerRig(parts)


@pytest.mark.parametrize("cls", [A.IdleAnimation, A.RelaxedWaitAnimation])
def test_neck_stays_in_the_collar(figure, cls):
    parts, rig = figure
    assert rig.neck[2] == pytest.approx(3.8, abs=0.01)
    body, head = parts
    wb, wh = rig.weights
    collar = body.positions[:, 1] > 90
    stub = head.positions[:, 1] < 95
    anim = cls(rig)
    for t in np.linspace(0, cls.LOOP, 60, endpoint=False):
        b = anim.pose(body, wb, t)[0][collar].mean(0)
        h = anim.pose(head, wh, t)[0][stub].mean(0)
        # the stub's offset from the collar centre only turns with the torso
        assert np.hypot(*(h - b)[[0, 2]]) == pytest.approx(3.8, abs=0.15), t
