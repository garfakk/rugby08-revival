"""
shared/game_profile.py — the game's own settings (user_profile.pro)
=====================================================================
Rugby 08 keeps its options (volumes, camera, HUD, video, gameplay sliders...)
in a binary profile. At every launch the template assets/templates/
user_profile.pro is copied to the game folder as user_profile.pro and the
settings the user changed in the mod's Settings screen are written into it.

The user's choices live in game_profile.ini (next to user_prefs.ini). Only the
values the user actually changed are stored: everything else keeps what the
template holds.

Format and field map: reverse-engineered from the game's profile.pro
(offsets below are payload offsets; the file adds a 0x1C-byte header).
"""
import configparser
import os
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

from shared.config import config
from shared.log import get_logger
from shared.user_prefs import PREFS_DIR

log = get_logger(__name__)

TEMPLATE_NAME = "user_profile.pro"
GAME_FILE_NAME = "user_profile.pro"
SETTINGS_FILE = os.path.join(PREFS_DIR, "game_profile.ini")
_SECTION = "profile"

_MAGIC = 0x4D433032
_HEADER = 0x1C
_PAYLOAD = 0x2D8


# ── file format (header + CRC) ───────────────────────────────────────────────

# MSB-first CRC-32, polynomial 0x04C11DB7, as computed by the game
_CRC_TABLE = []
for _i in range(256):
    _c = _i << 24
    for _ in range(8):
        _c = ((_c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if _c & 0x80000000 else (_c << 1) & 0xFFFFFFFF
    _CRC_TABLE.append(_c)


def _crc(data: bytes) -> int:
    if len(data) < 4:
        return 0
    acc = ~int.from_bytes(data[:4], "big") & 0xFFFFFFFF
    for byte in data[4:]:
        acc = (((acc << 8) | byte) & 0xFFFFFFFF) ^ _CRC_TABLE[acc >> 24]
    return ~acc & 0xFFFFFFFF


def split_profile(raw: bytes) -> Optional[bytearray]:
    """Payload of a valid profile file, None if the file is not a valid profile."""
    if len(raw) != _HEADER + _PAYLOAD:
        return None
    magic, size, len1, len2, _crc1, crc2, header_crc = struct.unpack_from("<7I", raw, 0)
    if magic != _MAGIC or size != len(raw) or len1 != 0 or len2 != _PAYLOAD:
        return None
    payload = raw[_HEADER:_HEADER + _PAYLOAD]
    if _crc(raw[:0x18]) != header_crc or _crc(payload) != crc2:
        return None
    return bytearray(payload)


def build_profile(payload: bytes) -> bytes:
    """Payload -> complete file with valid CRCs (the game rejects any mismatch)."""
    header = struct.pack("<6I", _MAGIC, _HEADER + _PAYLOAD, 0, _PAYLOAD, 0, _crc(payload))
    return header + struct.pack("<I", _crc(header)) + bytes(payload)


# ── settings catalogue ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Setting:
    """One value in the payload: `bits` bits at `shift` inside the `size`-byte
    little-endian integer at `offset`. Shown as an ON/OFF switch (kind "bool"),
    a list of choices, or a slider (kind "range")."""
    key: str
    label: str
    offset: int
    kind: str                                   # "bool" | "choice" | "range"
    size: int = 1
    shift: int = 0
    bits: int = 8
    signed: bool = False
    choices: Tuple[Tuple[str, int], ...] = ()   # (label, value)
    minimum: int = 0
    maximum: int = 100
    step: int = 1
    note: str = ""


def _choices(*labels):
    return tuple((label, i) for i, label in enumerate(labels))


# 640x480 is the boot backbuffer size: the game then reaches the menu without
# a D3D Reset, the d3d8 proxy never detects the frontend and the window is
# never resized, so it cannot be embedded.
UNSAFE_RESOLUTIONS = frozenset({(640, 480)})
RESOLUTIONS = ((800, 600), (1024, 768), (1280, 720), (1280, 960),
               (1600, 900), (1600, 1200), (1920, 1080), (2560, 1440), (3840, 2160))

def resolution_choices(screen_w: int, screen_h: int):
    """(sizes, recommended) for a screen of screen_w x screen_h physical pixels:
    RESOLUTIONS plus the screen's own size; recommended = the screen's size,
    or the closest one when it can't be offered (unsafe / unknown)."""
    sizes = list(RESOLUTIONS)
    native = (screen_w, screen_h)
    if screen_w > 0 and screen_h > 0 and native not in sizes and native not in UNSAFE_RESOLUTIONS:
        sizes.append(native)
        sizes.sort()
    if native in sizes:
        return sizes, native
    return sizes, min(sizes, key=lambda s: abs(s[0] - screen_w) + abs(s[1] - screen_h))


# Preset cameras: name, type, ((open zoom, open height, breakdown zoom, breakdown height) x 5 variants)
_CAMERA_TYPES = (0, 1, 2, 3, 3, 3)
_CAMERA_ZOOM = {
    0: ((12, 2), (16, 6), (20, 8), (8, 2), (4, 0)),
    1: ((12, 2), (16, 6), (20, 8), (8, 2), (4, 0)),
    2: ((12, 2), (16, 6), (20, 8), (8, 2), (4, 0)),
}
_CAMERA_TALL = {
    3: ((-3, -400, -8, -600), (0, -400, -5, -600), (5, -400, 0, -600),
        (-5, -400, -10, -600), (-8, -400, -12, -600)),
    4: ((4, -200, -4, -200), (8, -200, -2, -200), (14, -200, 0, -200),
        (0, -200, -8, -200), (-4, -200, -10, -200)),
    5: ((-6, 1800, -10, 1800), (-2, 1800, -6, 1800), (4, 1800, 0, 1800),
        (-10, 1800, -14, 1800), (-14, 1800, -20, 1800)),
}

_OFF_CAMERA_TYPE = 0x230
_OFF_CAMERA_SYSTEM = 0x234
_OFF_CAMERA_PRESET = 0x238

SECTIONS = (
    ("AUDIO", (
        Setting("vol_menu", "Menu Sounds", 0x21C, "range", size=2, bits=16, step=5),
        Setting("vol_commentary", "Commentary", 0x21E, "range", size=2, bits=16, step=5),
        Setting("vol_crowd", "Crowd", 0x220, "range", size=2, bits=16, step=5),
        Setting("vol_field", "Field", 0x222, "range", size=2, bits=16, step=5),
        Setting("vol_music", "Music", 0x224, "range", size=2, bits=16, step=5),
    )),
    ("GAMEPLAY", (
        Setting("knock_ons", "Knock-ons", 0x22D, "range", step=5),
        Setting("injuries", "Injuries", 0x22E, "range", step=5),
        Setting("fatigue", "Fatigue", 0x22F, "range", step=5),
        Setting("lineout", "Line-out Control", 0x258, "choice", shift=1, bits=1,
                choices=_choices("Basic", "Advanced")),
        Setting("offload", "Offload Mode", 0x259, "choice",
                choices=_choices("Simulation", "Arcade")),
    )),
    ("CAMERA", (
        Setting("camera", "Camera", _OFF_CAMERA_PRESET, "choice", bits=4,
                choices=_choices("Truck", "Sideline", "Broadcast", "Chase", "End On", "Hover")),
        Setting("camera_variant", "Camera Distance", _OFF_CAMERA_PRESET, "choice", shift=4, bits=3,
                choices=_choices("Standard", "Wide", "Super Wide", "Near", "Super Near")),
        Setting("camera_zoom", "Breakdown Zoom Camera", _OFF_CAMERA_PRESET, "bool", shift=7, bits=1),
        Setting("defensive_cam", "Defensive Camera", 0x23C, "choice", size=4, bits=32,
                choices=_choices("Off", "Forward Play")),
    )),
    ("HUD", (
        Setting("player_display", "Player Display", 0x25C, "choice", size=4, shift=1, bits=2,
                choices=_choices("None", "Names", "Numbers")),
        Setting("radar", "Radar", 0x25C, "bool", size=4, shift=3, bits=1),
        Setting("game_help", "Game Help", 0x25C, "bool", size=4, shift=4, bits=1),
        Setting("player_info", "Player Info", 0x25C, "choice", size=4, shift=5, bits=1,
                choices=_choices("Player", "Position")),
        Setting("impact_markers", "Impact Player Markers", 0x25C, "bool", size=4, shift=6, bits=1),
        Setting("offside_marker", "Offside Marker", 0x25C, "choice", size=4, shift=7, bits=2,
                choices=(("Normal", 0), ("Always On", 1), ("Always Off", 2))),
    )),
    ("VIDEO", (
        Setting("shadows", "Shadows", 0x25C, "choice", size=4, shift=9, bits=1,
                choices=(("Simple", 0), ("Complex", 1))),
        Setting("texture_filter", "Texture Filter", 0x25C, "choice", size=4, shift=10, bits=1,
                choices=(("Bilinear", 0), ("Trilinear", 1))),
        Setting("force_lod", "Force LOD", 0x25C, "choice", size=4, shift=11, bits=4,
                choices=_choices("No", "Low", "Medium", "High")),
        Setting("antialiasing", "Antialiasing", 0x25C, "choice", size=4, shift=15, bits=3,
                choices=_choices("Off", "2x", "4x", "8x")),
        Setting("gamma", "Gamma", 0x260, "range"),
        Setting("screen_x", "Screen Centre Horizontal", 0x218, "range", size=2, bits=16,
                signed=True, minimum=-32, maximum=32),
        Setting("screen_y", "Screen Centre Vertical", 0x21A, "range", size=2, bits=16,
                signed=True, minimum=-32, maximum=32),
    )),
)

SETTINGS = {s.key: s for _title, group in SECTIONS for s in group}

# Resolution: two consecutive u16 (width, height)
_OFF_RES_W, _OFF_RES_H = 0x262, 0x264
RESOLUTION_KEY = "resolution"


def _read(payload, s: Setting) -> int:
    raw = int.from_bytes(payload[s.offset:s.offset + s.size], "little")
    value = (raw >> s.shift) & ((1 << s.bits) - 1)
    if s.signed and value >= 1 << (s.bits - 1):
        value -= 1 << s.bits
    return value


def _write(payload, s: Setting, value: int):
    mask = (1 << s.bits) - 1
    raw = int.from_bytes(payload[s.offset:s.offset + s.size], "little")
    raw = (raw & ~(mask << s.shift)) | ((value & mask) << s.shift)
    payload[s.offset:s.offset + s.size] = raw.to_bytes(s.size, "little")


def _clamp(s: Setting, value: int) -> int:
    if s.kind == "bool":
        return 1 if value else 0
    if s.kind == "choice":
        valid = [v for _l, v in s.choices]
        return value if value in valid else valid[0]
    return max(s.minimum, min(s.maximum, int(value)))


def _apply_camera(payload):
    """Write the bytes the game derives from the camera choice (spec §2.5): the
    game recomputes them at load from the selection alone, but keeping them
    consistent makes the file identical to one the game saves itself."""
    preset = payload[_OFF_CAMERA_PRESET]
    index = min(preset & 0xF, 5)
    variant = min((preset >> 4) & 7, 4)
    cam_type = _CAMERA_TYPES[index]
    payload[_OFF_CAMERA_TYPE] = (payload[_OFF_CAMERA_TYPE] & 0xF0) | cam_type
    payload[_OFF_CAMERA_SYSTEM] |= 1
    if cam_type == 3:
        op_zoom, op_height, bd_zoom, bd_height = _CAMERA_TALL[index][variant]
        struct.pack_into("<bbhh", payload, 0x246, op_zoom, bd_zoom, op_height, bd_height)
    else:
        op_zoom, bd_zoom = _CAMERA_ZOOM[index][variant]
        struct.pack_into("<bbhh", payload, 0x240, op_zoom, bd_zoom, 0, 0)


class GameProfile:
    """The user's overrides of the template profile, persisted in game_profile.ini."""

    def __init__(self):
        self._overrides = {}
        self._template = None       # payload of the template, read on demand
        self._load()

    # ── persistence ──
    def _load(self):
        cp = configparser.ConfigParser()
        try:
            cp.read(SETTINGS_FILE)
        except (OSError, configparser.Error):
            return
        if not cp.has_section(_SECTION):
            return
        for key, text in cp.items(_SECTION):
            try:
                if key == RESOLUTION_KEY:
                    w, h = text.lower().split("x")
                    if (int(w), int(h)) in UNSAFE_RESOLUTIONS:
                        log.warning(f"ignoring unsafe resolution {text}")
                        continue
                    self._overrides[key] = (int(w), int(h))
                elif key in SETTINGS:
                    self._overrides[key] = _clamp(SETTINGS[key], int(text))
            except ValueError:
                log.warning(f"ignoring bad game setting {key}={text!r}")

    def save(self):
        cp = configparser.ConfigParser()
        cp[_SECTION] = {
            key: (f"{v[0]}x{v[1]}" if key == RESOLUTION_KEY else str(v))
            for key, v in self._overrides.items()
        }
        try:
            with open(SETTINGS_FILE, "w") as fh:
                cp.write(fh)
        except OSError as e:
            log.warning(f"could not save {SETTINGS_FILE}: {e}")

    # ── template ──
    def template_filepath(self) -> str:
        return os.path.join(config.templates_directory, TEMPLATE_NAME)

    def _template_payload(self) -> Optional[bytearray]:
        if self._template is None:
            try:
                with open(self.template_filepath(), "rb") as fh:
                    self._template = split_profile(fh.read())
            except OSError as e:
                log.error(f"cannot read profile template {self.template_filepath()}: {e}")
                return None
            if self._template is None:
                log.error(f"profile template {self.template_filepath()} is not a valid profile")
        return self._template

    # ── values ──
    def get(self, key: str) -> int:
        """Current value: the user's override, else the template's."""
        if key in self._overrides:
            return self._overrides[key]
        setting = SETTINGS[key]
        payload = self._template_payload()
        if payload is None:
            return setting.choices[0][1] if setting.choices else setting.minimum
        return _clamp(setting, _read(payload, setting))

    def set(self, key: str, value: int):
        self._overrides[key] = _clamp(SETTINGS[key], value)

    def get_resolution(self) -> Tuple[int, int]:
        if RESOLUTION_KEY in self._overrides:
            return self._overrides[RESOLUTION_KEY]
        payload = self._template_payload()
        if payload is None:
            return 640, 480
        return (struct.unpack_from("<H", payload, _OFF_RES_W)[0],
                struct.unpack_from("<H", payload, _OFF_RES_H)[0])

    def has_resolution(self) -> bool:
        """True once the user has picked a resolution (Settings or first launch)."""
        return RESOLUTION_KEY in self._overrides

    def set_resolution(self, width: int, height: int):
        size = (max(1, min(65535, width)), max(1, min(65535, height)))
        if size in UNSAFE_RESOLUTIONS:
            log.warning(f"refusing unsafe resolution {size[0]}x{size[1]}")
            return
        self._overrides[RESOLUTION_KEY] = size

    def reset(self):
        """Back to the template's values."""
        self._overrides.clear()
        self.save()

    # ── deployment ──
    def deploy(self, game_dir: str = None) -> bool:
        """Copy the template to the game folder as user_profile.pro and write the
        user's settings into it. Called at every game launch."""
        payload = self._template_payload()
        if payload is None:
            return False
        payload = bytearray(payload)
        for key, value in self._overrides.items():
            if key == RESOLUTION_KEY:
                struct.pack_into("<HH", payload, _OFF_RES_W, value[0], value[1])
            else:
                _write(payload, SETTINGS[key], value)
        _apply_camera(payload)

        destination = os.path.join(game_dir or config.game_launcher_directory, GAME_FILE_NAME)
        try:
            with open(destination, "wb") as fh:
                fh.write(build_profile(payload))
        except OSError as e:
            log.error(f"cannot write game profile {destination}: {e}")
            return False
        w, h = struct.unpack_from("<HH", payload, _OFF_RES_W)
        log.info(f"Game profile written to {destination}: {w}x{h}, {len(self._overrides)} user settings")
        return True


game_profile = GameProfile()
