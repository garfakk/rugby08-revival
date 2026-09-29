"""Crude procedural animation for the Rugby 08 player body model.

The model ships in a bind pose (arms straight out sideways, legs together)
and its vertices carry only a per-mesh bone *palette* index — the skeleton
itself is not in the file. So instead of skinning, limbs are found by where
they are in the bind pose and rotated around estimated joints.

The segments are **rigid**: each vertex belongs wholly to one segment, so the
chest, sleeves and limbs keep their exact bind-pose shape and only pivot about
each other, interpenetrating at the joints. Blending a vertex between two
segments — skinning — is what dents the chest and flattens the sleeve into a
web across the armpit, so it is deliberately not done here.

Good enough for "the player is moving"; a real skeleton can replace this
later without touching the renderer (it consumes positions/normals only).
"""
import numpy as np


class PlayerRig:
    """Weights and joints derived from the bind pose, once, for all parts."""

    def __init__(self, parts):
        # Landmarks come from the body alone. A head sits above the shoulders,
        # so counting it would stretch `height` and drag every landmark that
        # is a fraction of it (hip, knee) up with it. The head still gets
        # weights below — it rides the torso.
        body = [p for p in parts if not getattr(p, 'is_head', False)] or parts
        allpos = np.concatenate([p.positions for p in body])
        self.lo = allpos.min(0)
        self.hi = allpos.max(0)
        height = float(self.hi[1] - self.lo[1])

        # Bind pose landmarks. Arms stick straight out sideways, so the torso
        # is the narrow column in the middle and the arms everything past it.
        self.hip_y = float(self.lo[1] + height * 0.47)
        self.shoulder_y = self._estimate_shoulder_y(allpos, self.hip_y, height)
        self.shoulder_x = float(np.percentile(np.abs(allpos[:, 0]), 62))
        self.torso_x = self.shoulder_x * 0.85
        self.knee_y = float(self.lo[1] + height * 0.24)
        self.hand_x = float(np.abs(allpos[:, 0]).max())
        self.elbow_x = self.shoulder_x + 0.46 * (self.hand_x - self.shoulder_x)
        self.hip_x = self.shoulder_x * 0.45
        self.height = height
        # The head sits on top of the body, so the neck is the body's own top.
        self.neck_y = float(self.hi[1])

        self.weights = [self._part_weights(p.positions, getattr(p, 'is_head', False))
                        for p in parts]

    def _estimate_shoulder_y(self, allpos, hip_y, height, n_bins=40):
        """Height of the arm's own centreline, measured off the mesh.

        The shoulder has to pivot on the arm's axis. Placing it below that —
        as a fixed head-to-toe proportion does on this *headless* model, where
        the top of the mesh is already the shoulder line — swings the arm from
        underneath, so its bind-pose top face ends up pointing outward and the
        shoulder reads as a flat facet instead of a rounded deltoid.

        In a T-pose the arm sticks out sideways at a roughly constant height,
        so slicing the model into height bands shows torso-scale width until
        the arm's band, which is several times wider. Take that band's centre.
        """
        y = allpos[:, 1]
        edges = np.linspace(self.lo[1], self.hi[1], n_bins + 1)
        idx = np.clip(np.digitize(y, edges) - 1, 0, n_bins - 1)
        widths = np.full(n_bins, np.nan)
        for i in range(n_bins):
            m = idx == i
            if np.any(m):
                widths[i] = np.abs(allpos[m, 0]).max()
        centers = (edges[:-1] + edges[1:]) / 2

        below_hip = centers < hip_y
        baseline = np.nanmedian(widths[below_hip]) if np.any(below_hip) else np.nanmedian(widths)
        plateau = ~np.isnan(widths) & (centers > hip_y) & (widths > baseline * 2.2)
        if not np.any(plateau):
            return float(self.lo[1] + height * 0.86)      # no T-pose arm found
        return float(centers[plateau].mean())

    def _part_weights(self, pos, is_head=False):
        """Hard 0/1 membership, one segment per joint — no blend weights.

        Every vertex belongs wholly to one segment, so each segment turns as a
        rigid body and the chest, sleeves and limbs keep their exact bind-pose
        shape. Segments simply pivot about each other and are allowed to
        interpenetrate at the joints; that overlap is the intended trade for
        never deforming the mesh. Any partial weight would reintroduce
        skinning, which is what dented the chest and flattened the sleeves.
        """
        x, y = pos[:, 0], pos[:, 1]

        # Arm: outboard of the shoulder joint, up in the shoulder band (the
        # band keeps the hips, which are about as wide, out of it).
        arm = (np.abs(x) >= self.shoulder_x) & (y >= self.shoulder_y - self.height * 0.12)
        arm_l = arm & (x > 0)
        arm_r = arm & (x < 0)
        # Elbow: the forearm, outboard of the elbow joint.
        elbow = np.abs(x) >= self.elbow_x

        # Leg: below the hip, split by side. Knee segment below the knee.
        leg = y <= self.hip_y
        leg_l = leg & (x > 0)
        leg_r = leg & (x <= 0)
        knee = y <= self.knee_y

        # Torso: everything above the hip, arms and head included — they are
        # its children, so they ride along with the twist.
        torso = y > self.hip_y

        # Head: a whole part at a time, so it can turn on the neck.
        head = np.full(len(pos), bool(is_head))

        return dict(arm_l=arm_l.astype(np.float32), arm_r=arm_r.astype(np.float32),
                    elbow=elbow.astype(np.float32),
                    leg_l=leg_l.astype(np.float32), leg_r=leg_r.astype(np.float32),
                    knee=knee.astype(np.float32),
                    torso=torso.astype(np.float32),
                    head=head.astype(np.float32))


def _bend(pos, nrm, weight, pivot, axis, angle):
    """Rotate `pos`/`nrm` about `pivot`, each vertex turning `weight * angle`.

    Scaling the *angle* per vertex keeps every vertex on its own rotation arc.
    Interpolating the position instead — lerping between the bind pose and the
    fully rotated pose, which is what linear blend skinning does — moves partly
    weighted vertices along the chord of that arc, i.e. inwards, and a sleeve
    or a shorts leg collapses from a tube into a flat sheet across the joint
    (worst at the shoulder, where the drop angle is ~90°).
    """
    sel = weight > 1e-3
    if not np.any(sel):
        return
    theta = weight[sel] * angle
    c, s = np.cos(theta), np.sin(theta)

    # Axis-aligned rotation, done per vertex with its own angle.
    if axis == 'x':
        i, j = 1, 2
    elif axis == 'y':
        i, j = 2, 0
    else:
        i, j = 0, 1

    local = pos[sel] - pivot
    a, b = local[:, i].copy(), local[:, j].copy()
    local[:, i] = c * a - s * b
    local[:, j] = s * a + c * b
    pos[sel] = local + pivot

    n = nrm[sel]
    a, b = n[:, i].copy(), n[:, j].copy()
    n[:, i] = c * a - s * b
    n[:, j] = s * a + c * b
    nrm[sel] = n


class JogAnimation:
    """A gross jog-on-the-spot: arms come down out of the T-pose and swing,
    legs stride, the whole body bobs and twists."""

    #: seconds per full stride cycle
    PERIOD = 0.9

    def __init__(self, rig: PlayerRig):
        self.rig = rig

    def pose(self, part, weights, t: float):
        """Transforms are applied child-joint first (elbow before shoulder,
        knee before hip, everything before the torso twist): a child rotation
        expressed around its bind-pose pivot stays correct only while the
        parent has not moved yet. Doing it the other way round flings the
        forearm across the pitch."""
        rig = self.rig
        phase = 2.0 * np.pi * (t / self.PERIOD)
        swing = float(np.sin(phase))

        pos = part.positions.copy()
        nrm = part.normals.copy()

        arm_l, arm_r = weights['arm_l'], weights['arm_r']
        leg_l, leg_r = weights['leg_l'], weights['leg_r']

        # ── Elbows (bind pose: arms along ±X, so bending forward is about Y).
        # The bend tightens as the arm comes forward, like a real arm carriage,
        # and never gets big enough to bury the hand in the chest.
        bend = np.deg2rad(34.0 + 16.0 * swing)
        el_l = np.array([rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        el_r = np.array([-rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, arm_l * weights['elbow'], el_l, 'y', -bend)
        _bend(pos, nrm, arm_r * weights['elbow'], el_r, 'y', bend)

        # ── Shoulders: out of the T-pose, then swinging fore/aft
        drop = np.deg2rad(72.0)
        fore = np.deg2rad(26.0) * swing
        splay = np.deg2rad(8.0)           # keep the hands clear of the hips
        sh_l = np.array([rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        sh_r = np.array([-rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        # Composed as Rx @ Rz in matrix form, so the Z drop is applied first.
        _bend(pos, nrm, arm_l, sh_l, 'z', -drop + splay)
        _bend(pos, nrm, arm_l, sh_l, 'x', fore)
        _bend(pos, nrm, arm_r, sh_r, 'z', drop - splay)
        _bend(pos, nrm, arm_r, sh_r, 'x', -fore)

        # ── Knees: heels kick backwards on the leg's backswing
        knee_l = leg_l * weights['knee'] * max(0.0, -swing)
        knee_r = leg_r * weights['knee'] * max(0.0, swing)
        kn_l = np.array([rig.hip_x, rig.knee_y, 0.0], dtype=np.float32)
        kn_r = np.array([-rig.hip_x, rig.knee_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, knee_l, kn_l, 'x', np.deg2rad(70.0))
        _bend(pos, nrm, knee_r, kn_r, 'x', np.deg2rad(70.0))

        # ── Hips: opposite phase to the arms
        stride = np.deg2rad(28.0) * swing
        hip_l = np.array([rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        hip_r = np.array([-rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, leg_l, hip_l, 'x', -stride)
        _bend(pos, nrm, leg_r, hip_r, 'x', stride)

        # ── Torso: counter-twist plus a runner's forward lean (parent of all).
        # Composed as Ry @ Rx in matrix form, so the lean is applied first.
        waist = np.array([0.0, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, weights['torso'], waist, 'x', np.deg2rad(5.0))
        _bend(pos, nrm, weights['torso'], waist, 'y', np.deg2rad(8.0) * -swing)

        # ── Whole-body bob, twice per stride
        pos[:, 1] += rig.height * 0.010 * (1.0 - np.cos(phase * 2.0))

        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1))[:, None]
        return pos.astype(np.float32), nrm.astype(np.float32)


class IdleAnimation:
    """Standing idle: breathing, a slow weight shift, and the odd glance.

    Nothing here is meant to read as a step — the feet stay planted, so the
    legs only take the small counter-lean that a weight shift puts through
    them. The motions run on periods that do not divide into each other, so
    the loop never lands in a visibly repeating beat.
    """

    #: seconds per breath — the shortest cycle, so it sets the felt tempo
    PERIOD = 3.72
    SWAY_PERIOD = 6.2
    GLANCE_PERIOD = 9.3
    #: the three periods share this multiple (5, 3 and 2 cycles), so a clip
    #: of exactly this long loops without a jump
    LOOP = 18.6

    def __init__(self, rig: PlayerRig):
        self.rig = rig

    def pose(self, part, weights, t: float):
        rig = self.rig
        breath = float(np.sin(2.0 * np.pi * t / self.PERIOD))
        sway = float(np.sin(2.0 * np.pi * t / self.SWAY_PERIOD))
        glance = float(np.sin(2.0 * np.pi * t / self.GLANCE_PERIOD))

        pos = part.positions.copy()
        nrm = part.normals.copy()
        arm_l, arm_r = weights['arm_l'], weights['arm_r']
        leg_l, leg_r = weights['leg_l'], weights['leg_r']

        # ── Elbows: a slight, near-constant carry, opening a touch on the
        # breath in — arms hanging dead straight read as a mannequin.
        bend = np.deg2rad(12.0 + 3.0 * breath)
        el_l = np.array([rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        el_r = np.array([-rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, arm_l * weights['elbow'], el_l, 'y', -bend)
        _bend(pos, nrm, arm_r * weights['elbow'], el_r, 'y', bend)

        # ── Shoulders: hanging, drifting fore/aft with the sway. The chest
        # lifting on the breath pushes the arms out a degree or two.
        drop = np.deg2rad(72.0)
        splay = np.deg2rad(8.0 + 1.5 * breath)
        fore = np.deg2rad(3.0) * sway
        sh_l = np.array([rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        sh_r = np.array([-rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, arm_l, sh_l, 'z', -drop + splay)
        _bend(pos, nrm, arm_l, sh_l, 'x', fore)
        _bend(pos, nrm, arm_r, sh_r, 'z', drop - splay)
        _bend(pos, nrm, arm_r, sh_r, 'x', -fore)

        # ── Legs: feet planted, so only the shift's small counter-lean.
        lean = np.deg2rad(1.2) * sway
        hip_l = np.array([rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        hip_r = np.array([-rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, leg_l, hip_l, 'z', lean)
        _bend(pos, nrm, leg_r, hip_r, 'z', lean)

        # ── Torso: weight shifting hip to hip, with a slight settled lean.
        waist = np.array([0.0, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, weights['torso'], waist, 'x', np.deg2rad(2.0))
        _bend(pos, nrm, weights['torso'], waist, 'z', np.deg2rad(2.2) * sway)
        _bend(pos, nrm, weights['torso'], waist, 'y', np.deg2rad(3.0) * -sway)

        # ── Head: looks around slowly, off the torso's own beat.
        head = weights.get('head')
        if head is not None:
            neck = np.array([0.0, rig.neck_y, 0.0], dtype=np.float32)
            _bend(pos, nrm, head, neck, 'y', np.deg2rad(9.0) * glance)
            _bend(pos, nrm, head, neck, 'x', np.deg2rad(2.5) * breath)

        # ── Chest rising on the breath, and the whole body with it.
        pos[:, 1] += rig.height * 0.0035 * breath

        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1))[:, None]
        return pos.astype(np.float32), nrm.astype(np.float32)


def _ease_smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _dwell(t, period, move=0.22, phase=0.0, settle=0.0):
    """[-1,1] square-ish wave that HOLDS at each end and eases between.

    `settle` adds a damped overshoot as it arrives: a body that shifts its
    weight does not glide to a stop, it drops onto the leg and rebounds once.
    """
    u = ((t / period) + phase) % 1.0
    half, sign = (u, 1.0) if u < 0.5 else (u - 0.5, -1.0)
    start = 0.5 - move
    if half <= start:
        k, since = 0.0, half + move          # time held since arriving
    else:
        k, since = _ease_smooth((half - start) / move), 0.0
    v = sign * (1.0 - 2.0 * k)
    if settle and since > 0.0:
        # ring down over roughly a second after the move completes
        v += sign * settle * np.exp(-3.2 * since) * np.sin(7.0 * since)
    return float(v)


def _wobble(t, periods, amps, phases=None):
    """Sum of slow sines on periods that all divide LOOP — reads as drift
    rather than a beat, but still returns to its start at the loop point."""
    phases = phases or [0.0] * len(periods)
    return float(sum(a * np.sin(2 * np.pi * (t / p + ph))
                     for p, a, ph in zip(periods, amps, phases)))


def _breath_curve(t, period):
    """Asymmetric breath: quicker in, slower out. A plain sine breathes like
    a metronome; lungs do not."""
    u = (t / period) % 1.0
    if u < 0.4:
        return float(np.sin(np.pi * (u / 0.4) * 0.5))          # rise
    return float(np.cos(np.pi * ((u - 0.4) / 0.6) * 0.5))      # longer fall


class RelaxedWaitAnimation:
    """A player standing about, waiting — the polished pass over
    `IdleAnimation`, approved over two other idle directions that read as
    too busy or too stiff.

    The weight sits on one leg and *stays* there for several seconds before
    moving — the holds are what read as waiting, not the motion itself. The
    feet stay planted: the legs pivot about the ankles and the hips travel
    to match, rather than the whole body sliding sideways. Every periodic
    component's period divides `LOOP`, so a clip that long loops seamlessly;
    two players sharing this class still read as independent as long as
    each is given a different time origin (see KitStage, which randomises
    it per instance — sharing one clock is what makes two idling players
    look robotic, not the animation itself).
    """

    LOOP = 24.0

    SHIFT_PERIOD = 8.0        # weight changes leg
    BREATH_PERIOD = 4.0
    GLANCE_PERIOD = 12.0
    ARM_LAG = 0.28            # seconds the arms trail the hips by

    def __init__(self, rig: PlayerRig):
        self.rig = rig
        self.ankle_y = float(rig.lo[1])
        self.leg_len = max(1.0, rig.hip_y - self.ankle_y)

    def _shift(self, t):
        return _dwell(t, self.SHIFT_PERIOD, move=0.26, settle=0.16)

    def pose(self, part, weights, t: float):
        rig, w = self.rig, weights
        shift = self._shift(t)
        shift_lag = self._shift(t - self.ARM_LAG)      # arms trail the body
        breath = _breath_curve(t, self.BREATH_PERIOD)
        # head: its own slow look-about, plus drift so it never repeats cleanly
        glance = _dwell(t - 0.5, self.GLANCE_PERIOD, move=0.16, phase=0.13)
        drift_y = _wobble(t, [24.0, 8.0, 6.0], [3.2, 1.4, 0.8], [0.0, 0.31, 0.62])
        drift_x = _wobble(t, [12.0, 4.8], [1.1, 0.6], [0.2, 0.7])

        pos = part.positions.copy()
        nrm = part.normals.copy()

        # ── Legs pivot about the ankles, so the boots stay planted.
        tilt = np.deg2rad(1.6) * shift
        ank_l = np.array([rig.hip_x, self.ankle_y, 0.0], dtype=np.float32)
        ank_r = np.array([-rig.hip_x, self.ankle_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['leg_l'], ank_l, 'z', tilt)
        _bend(pos, nrm, w['leg_r'], ank_r, 'z', tilt)

        # Free leg softens: knee eases off and the thigh rolls out slightly.
        free_l, free_r = max(0.0, -shift), max(0.0, shift)
        kn_l = np.array([rig.hip_x, rig.knee_y, 0.0], dtype=np.float32)
        kn_r = np.array([-rig.hip_x, rig.knee_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['leg_l'] * w['knee'], kn_l, 'x', np.deg2rad(1.8) * free_l)
        _bend(pos, nrm, w['leg_r'] * w['knee'], kn_r, 'x', np.deg2rad(1.8) * free_r)
        hip_l = np.array([rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        hip_r = np.array([-rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['leg_l'], hip_l, 'z', np.deg2rad(1.2) * free_l)
        _bend(pos, nrm, w['leg_r'], hip_r, 'z', -np.deg2rad(1.2) * free_r)

        # ── Arms hang and trail the hips; the loaded side sits closer in.
        drop = np.deg2rad(74.0)
        splay = np.deg2rad(1.8) * shift_lag
        fore = np.deg2rad(2.4) * shift_lag
        el_l = np.array([rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        el_r = np.array([-rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['arm_l'] * w['elbow'], el_l, 'y', -np.deg2rad(15.0 + 2.0 * breath))
        _bend(pos, nrm, w['arm_r'] * w['elbow'], el_r, 'y', np.deg2rad(12.0 - 2.0 * breath))
        sh_l = np.array([rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        sh_r = np.array([-rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['arm_l'], sh_l, 'z', -(drop + splay))
        _bend(pos, nrm, w['arm_l'], sh_l, 'x', fore)
        _bend(pos, nrm, w['arm_r'], sh_r, 'z', (drop - splay))
        _bend(pos, nrm, w['arm_r'], sh_r, 'x', -fore)

        # ── Torso: hip drops over the loaded leg, chest counter-leans to keep
        # the head over the middle, chest opens on the breath.
        waist = np.array([0.0, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, w['torso'], waist, 'x', np.deg2rad(2.2 - 0.8 * breath))
        _bend(pos, nrm, w['torso'], waist, 'z', np.deg2rad(3.4) * shift)
        _bend(pos, nrm, w['torso'], waist, 'y', np.deg2rad(3.0) * -shift_lag)

        # ── Head: looks about on its own clock, and stays level against the
        # shoulder roll rather than tipping with it.
        head = w.get('head')
        if head is not None:
            neck = np.array([0.0, rig.neck_y, 0.0], dtype=np.float32)
            _bend(pos, nrm, head, neck, 'y',
                  np.deg2rad(14.0) * glance + np.deg2rad(drift_y) - np.deg2rad(2.5) * shift_lag)
            _bend(pos, nrm, head, neck, 'z', np.deg2rad(-3.2) * shift)
            _bend(pos, nrm, head, neck, 'x', np.deg2rad(1.6) * breath + np.deg2rad(drift_x))

        # ── Hips travel with the ankle tilt, so the body stays over the feet.
        dx = self.leg_len * np.sin(tilt)
        pos[:, 0] += float(dx) * w['torso']
        # settle onto the loaded leg, and rise with the breath
        pos[:, 1] += (rig.height * 0.0026 * breath
                      - rig.height * 0.0022 * abs(shift)) * w['torso']

        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1))[:, None]
        return pos.astype(np.float32), nrm.astype(np.float32)


class WalkAnimation:
    """An unhurried walk, not the jog.

    The jog was built to read at a glance on a static preview: big arm
    carriage, heels kicking up, a runner's forward lean. Walking off a
    team-select screen wants the opposite — a shorter stride, arms hanging
    and swinging from the shoulder rather than pumping, an upright back,
    and the small heel lift a walking foot actually makes as it leaves the
    ground. Cadence is one full two-step cycle per PERIOD.
    """

    #: seconds per full cycle (both feet) — roughly 110 steps/min
    PERIOD = 1.1

    def __init__(self, rig: PlayerRig):
        self.rig = rig

    def pose(self, part, weights, t: float):
        # Child joints first (elbow before shoulder, knee before hip, torso
        # last) — see JogAnimation.pose for why the order matters.
        rig = self.rig
        phase = 2.0 * np.pi * (t / self.PERIOD)
        swing = float(np.sin(phase))

        pos = part.positions.copy()
        nrm = part.normals.copy()

        arm_l, arm_r = weights['arm_l'], weights['arm_r']
        leg_l, leg_r = weights['leg_l'], weights['leg_r']

        # ── Elbows: a soft, near-constant carry. A walking arm is not a
        # pumping arm; it stays mostly straight and just breaks a little at
        # the top of its forward swing.
        bend = np.deg2rad(14.0 + 7.0 * max(0.0, swing))
        el_l = np.array([rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        el_r = np.array([-rig.elbow_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, arm_l * weights['elbow'], el_l, 'y', -bend)
        _bend(pos, nrm, arm_r * weights['elbow'], el_r, 'y', bend)

        # ── Shoulders: hanging out of the T-pose, swinging opposite the legs
        # and only about half as far as the jog's.
        drop = np.deg2rad(74.0)
        fore = np.deg2rad(13.0) * swing
        splay = np.deg2rad(6.0)
        sh_l = np.array([rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        sh_r = np.array([-rig.shoulder_x, rig.shoulder_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, arm_l, sh_l, 'z', -drop + splay)
        _bend(pos, nrm, arm_l, sh_l, 'x', fore)
        _bend(pos, nrm, arm_r, sh_r, 'z', drop - splay)
        _bend(pos, nrm, arm_r, sh_r, 'x', -fore)

        # ── Knees: the trailing leg's heel lifts as it comes through, the
        # leading one stays nearly straight to plant. A walk never kicks the
        # heel up to the backside the way a jog does.
        knee_l = leg_l * weights['knee'] * max(0.0, -swing)
        knee_r = leg_r * weights['knee'] * max(0.0, swing)
        _bend(pos, nrm, knee_l,
              np.array([rig.hip_x, rig.knee_y, 0.0], dtype=np.float32), 'x', np.deg2rad(32.0))
        _bend(pos, nrm, knee_r,
              np.array([-rig.hip_x, rig.knee_y, 0.0], dtype=np.float32), 'x', np.deg2rad(32.0))

        # ── Hips: the stride itself, opposite phase to the arms.
        stride = np.deg2rad(17.0) * swing
        hip_l = np.array([rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        hip_r = np.array([-rig.hip_x, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, leg_l, hip_l, 'x', -stride)
        _bend(pos, nrm, leg_r, hip_r, 'x', stride)

        # ── Torso: upright (no runner's lean), with a small counter-twist.
        waist = np.array([0.0, rig.hip_y, 0.0], dtype=np.float32)
        _bend(pos, nrm, weights['torso'], waist, 'x', np.deg2rad(1.5))
        _bend(pos, nrm, weights['torso'], waist, 'y', np.deg2rad(4.0) * -swing)

        # ── Bob: twice per cycle, shallower than the jog's, and the body is
        # at its lowest as each foot plants.
        pos[:, 1] += rig.height * 0.0045 * (1.0 - np.cos(phase * 2.0))

        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1))[:, None]
        return pos.astype(np.float32), nrm.astype(np.float32)


class BlendAnimation:
    """Crossfades one animation into another over `duration` seconds.

    Swapping `renderer.anim` outright snaps the whole body between two
    unrelated poses in a single frame — an idling player with his weight on
    one leg becomes a mid-stride walker instantly. Blending the two poses'
    vertices instead carries the body from wherever it happens to be into
    the new cycle. Once the blend is done it forwards straight to the
    target animation, so there is no lasting cost.
    """

    def __init__(self, from_anim, to_anim, start_t: float, duration: float = 0.45):
        self.from_anim = from_anim
        self.to_anim = to_anim
        self.start_t = float(start_t)
        self.duration = max(1e-3, float(duration))

    @property
    def rig(self):
        return self.to_anim.rig

    def pose(self, part, weights, t: float):
        k = (t - self.start_t) / self.duration
        if k >= 1.0:
            return self.to_anim.pose(part, weights, t)
        if k <= 0.0:
            return self.from_anim.pose(part, weights, t)
        k = k * k * (3.0 - 2.0 * k)          # smoothstep, so it eases in and out
        a_pos, a_nrm = self.from_anim.pose(part, weights, t)
        b_pos, b_nrm = self.to_anim.pose(part, weights, t)
        pos = a_pos + (b_pos - a_pos) * k
        nrm = a_nrm + (b_nrm - a_nrm) * k
        nrm /= np.maximum(1e-6, np.linalg.norm(nrm, axis=1))[:, None]
        return pos.astype(np.float32), nrm.astype(np.float32)
