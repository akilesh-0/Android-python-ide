"""A pygame-compatible layer for the IDE, in a single file.

Put this file next to main.py. It acts as the whole `pygame` package: `import
pygame`, `import pygame.draw` and `from pygame.locals import *` all work.

It runs on Kivy and has no native code. Surfaces are recorded as drawing
commands and replayed on the IDE's game screen (pygame_host.py) when
display.flip() is called.

Supported: Rect, Color, Surface pixel access (get_at/set_at/map_rgb), basic
pixel reads from images and draw commands, draw primitives, display, input,
font, image.load, transforms, mouse and multitouch finger events, masks
(from_surface/from_threshold/overlap), sprite groups and pixel-perfect
collide_mask. Pixel buffers and masks are
memory-capped to keep use practical on lower-memory Android devices.

Partial/unsupported: some advanced pixel blend flags, SDL pixel formats,
complex raster/text edge cases, advanced mixer features, joysticks, and several
platform-specific display features.
"""

import linecache as _linecache
import sys as _sys
import time as _time
import types as _types

# Make this single module behave like a package, so `import pygame.draw`,
# `from pygame.locals import *` etc. find the sub-modules registered below.
__path__ = []

_SOURCES = {}

# ----------------------------------------------------------------------
# pygame._core
# ----------------------------------------------------------------------
_SOURCES['_core'] = r'''"""Shared state between the pygame layer and the IDE (see pygame_host.py)."""

import time
from collections import deque

MAX_COMMANDS = 8000  # per-surface draw-command history cap


class error(RuntimeError):
    """pygame.error"""


host = None                      # set by the IDE (pygame_host.KivyHost)
events = deque(maxlen=2000)
keys_down = set()
mouse_pos = (0, 0)
mouse_buttons = [False, False, False]
mouse_rel = [0, 0]
timers = []                      # [event_or_type, interval_ms, due_ms, loops_left or None]
caption = "pygame window"
display_surface = None
initialized = False
start_time = time.perf_counter()
_notices = set()


def reset():
    """Forget everything from the previous run."""
    global mouse_pos, display_surface, initialized, caption, start_time
    events.clear()
    keys_down.clear()
    del timers[:]
    mouse_pos = (0, 0)
    mouse_buttons[:] = [False, False, False]
    mouse_rel[:] = [0, 0]
    display_surface = None
    initialized = False
    caption = "pygame window"
    start_time = time.perf_counter()
    _notices.clear()


def notice(message):
    """Print a one-time note to the console."""
    if message in _notices:
        return
    _notices.add(message)
    print("[pygame layer] " + message)


def push_event(event):
    events.append(event)


def check_timers():
    """Post events for any pygame.time.set_timer timers that are due."""
    if not timers:
        return
    from .event import Event
    now = time.perf_counter() * 1000.0
    for timer in list(timers):
        if now < timer[2]:
            continue
        source = timer[0]
        if isinstance(source, int):
            events.append(Event(source))
        else:
            events.append(Event(source.type, source.dict))
        if timer[3] is not None:
            timer[3] -= 1
            if timer[3] <= 0:
                timers.remove(timer)
                continue
        timer[2] += timer[1]
        if timer[2] < now:
            timer[2] = now + timer[1]
'''

# ----------------------------------------------------------------------
# pygame.constants
# ----------------------------------------------------------------------
_SOURCES['constants'] = r'''"""pygame constants (the commonly used subset of pygame 2)."""

import string as _string

# Event types
NOEVENT = 0
ACTIVEEVENT = 32768
QUIT = 256
KEYDOWN = 768
KEYUP = 769
TEXTEDITING = 770
TEXTINPUT = 771
MOUSEMOTION = 1024
MOUSEBUTTONDOWN = 1025
MOUSEBUTTONUP = 1026
MOUSEWHEEL = 1027
FINGERDOWN = 1792
FINGERUP = 1793
FINGERMOTION = 1794
JOYAXISMOTION = 1536
JOYBALLMOTION = 1537
JOYHATMOTION = 1538
JOYBUTTONDOWN = 1539
JOYBUTTONUP = 1540
VIDEORESIZE = 32769
VIDEOEXPOSE = 32770
USEREVENT = 32866
NUMEVENTS = 65535

# Display / surface flags
SWSURFACE = 0
HWSURFACE = 1
OPENGL = 2
RESIZABLE = 16
NOFRAME = 32
SHOWN = 64
HIDDEN = 128
SCALED = 512
SRCALPHA = 65536
DOUBLEBUF = 1073741824
FULLSCREEN = -2147483648

# Blend flags (accepted, ignored)
BLEND_ADD = 1
BLEND_SUB = 2
BLEND_MULT = 3
BLEND_MIN = 4
BLEND_MAX = 5
BLEND_RGBA_ADD = 6
BLEND_RGBA_SUB = 7
BLEND_RGBA_MULT = 8
BLEND_RGBA_MIN = 9
BLEND_RGBA_MAX = 10
BLEND_PREMULTIPLIED = 17

# Mouse buttons
BUTTON_LEFT = 1
BUTTON_MIDDLE = 2
BUTTON_RIGHT = 3
BUTTON_WHEELUP = 4
BUTTON_WHEELDOWN = 5
BUTTON_X1 = 6
BUTTON_X2 = 7

# Keys
K_UNKNOWN = 0
K_BACKSPACE = 8
K_TAB = 9
K_RETURN = 13
K_ESCAPE = 27
K_SPACE = 32
K_EXCLAIM = 33
K_QUOTEDBL = 34
K_HASH = 35
K_DOLLAR = 36
K_AMPERSAND = 38
K_QUOTE = 39
K_LEFTPAREN = 40
K_RIGHTPAREN = 41
K_ASTERISK = 42
K_PLUS = 43
K_COMMA = 44
K_MINUS = 45
K_PERIOD = 46
K_SLASH = 47
K_COLON = 58
K_SEMICOLON = 59
K_LESS = 60
K_EQUALS = 61
K_GREATER = 62
K_QUESTION = 63
K_AT = 64
K_LEFTBRACKET = 91
K_BACKSLASH = 92
K_RIGHTBRACKET = 93
K_CARET = 94
K_UNDERSCORE = 95
K_BACKQUOTE = 96
K_DELETE = 127
K_CAPSLOCK = 1073741881
K_INSERT = 1073741897
K_HOME = 1073741898
K_PAGEUP = 1073741899
K_END = 1073741901
K_PAGEDOWN = 1073741902
K_RIGHT = 1073741903
K_LEFT = 1073741904
K_DOWN = 1073741905
K_UP = 1073741906
K_LCTRL = 1073742048
K_LSHIFT = 1073742049
K_LALT = 1073742050
K_LMETA = 1073742051
K_RCTRL = 1073742052
K_RSHIFT = 1073742053
K_RALT = 1073742054
K_RMETA = 1073742055

for _i in range(12):
    globals()["K_F%d" % (_i + 1)] = 1073741882 + _i
for _ch in _string.ascii_lowercase + "0123456789":
    globals()["K_" + _ch] = ord(_ch)

# Key modifiers
KMOD_NONE = 0
KMOD_LSHIFT = 1
KMOD_RSHIFT = 2
KMOD_SHIFT = 3
KMOD_LCTRL = 64
KMOD_RCTRL = 128
KMOD_CTRL = 192
KMOD_LALT = 256
KMOD_RALT = 512
KMOD_ALT = 768
KMOD_LMETA = 1024
KMOD_RMETA = 2048
KMOD_META = 3072
KMOD_NUM = 4096
KMOD_CAPS = 8192

KEY_NAMES = {
    8: "backspace", 9: "tab", 13: "return", 27: "escape", 32: "space",
    33: "!", 34: '"', 35: "#", 36: "$", 38: "&", 39: "'", 40: "(", 41: ")",
    42: "*", 43: "+", 44: ",", 45: "-", 46: ".", 47: "/", 58: ":", 59: ";",
    60: "<", 61: "=", 62: ">", 63: "?", 64: "@", 91: "[", 92: "\\", 93: "]",
    94: "^", 95: "_", 96: "`", 127: "delete",
    1073741881: "caps lock", 1073741897: "insert", 1073741898: "home",
    1073741899: "page up", 1073741901: "end", 1073741902: "page down",
    1073741903: "right", 1073741904: "left", 1073741905: "down",
    1073741906: "up", 1073742048: "left ctrl", 1073742049: "left shift",
    1073742050: "left alt", 1073742051: "left meta", 1073742052: "right ctrl",
    1073742053: "right shift", 1073742054: "right alt", 1073742055: "right meta",
}
for _i in range(12):
    KEY_NAMES[1073741882 + _i] = "f%d" % (_i + 1)
for _ch in _string.ascii_lowercase + "0123456789":
    KEY_NAMES[ord(_ch)] = _ch

del _i, _ch
'''

# ----------------------------------------------------------------------
# pygame.color
# ----------------------------------------------------------------------
_SOURCES['color'] = r'''"""pygame.Color and colour parsing."""

import colorsys

THECOLORS = {
    "black": (0, 0, 0, 255), "white": (255, 255, 255, 255),
    "red": (255, 0, 0, 255), "green": (0, 255, 0, 255),
    "blue": (0, 0, 255, 255), "yellow": (255, 255, 0, 255),
    "cyan": (0, 255, 255, 255), "aqua": (0, 255, 255, 255),
    "magenta": (255, 0, 255, 255), "orange": (255, 165, 0, 255),
    "purple": (160, 32, 240, 255), "pink": (255, 192, 203, 255),
    "brown": (165, 42, 42, 255), "gray": (190, 190, 190, 255),
    "grey": (190, 190, 190, 255), "darkgray": (169, 169, 169, 255),
    "darkgrey": (169, 169, 169, 255), "lightgray": (211, 211, 211, 255),
    "lightgrey": (211, 211, 211, 255), "gold": (255, 215, 0, 255),
    "silver": (192, 192, 192, 255), "navy": (0, 0, 128, 255),
    "teal": (0, 128, 128, 255), "maroon": (176, 48, 96, 255),
    "lime": (0, 255, 0, 255), "olive": (128, 128, 0, 255),
    "skyblue": (135, 206, 235, 255), "violet": (238, 130, 238, 255),
    "indigo": (75, 0, 130, 255), "crimson": (220, 20, 60, 255),
    "coral": (255, 127, 80, 255), "salmon": (250, 128, 114, 255),
    "tan": (210, 180, 140, 255), "beige": (245, 245, 220, 255),
    "khaki": (240, 230, 140, 255), "turquoise": (64, 224, 208, 255),
    "darkgreen": (0, 100, 0, 255), "darkblue": (0, 0, 139, 255),
    "darkred": (139, 0, 0, 255), "lightblue": (173, 216, 230, 255),
    "lightgreen": (144, 238, 144, 255), "forestgreen": (34, 139, 34, 255),
    "royalblue": (65, 105, 225, 255), "transparent": (0, 0, 0, 0),
}


def _byte(value):
    value = int(value)
    if value < 0 or value > 255:
        raise ValueError("invalid color argument")
    return value


def _parse_string(text):
    key = text.strip().lower().replace(" ", "")
    if key in THECOLORS:
        return THECOLORS[key]
    if key.startswith("#"):
        key = key[1:]
    elif key.startswith("0x"):
        key = key[2:]
    else:
        raise ValueError("invalid color name")
    try:
        if len(key) == 6:
            return (int(key[0:2], 16), int(key[2:4], 16), int(key[4:6], 16), 255)
        if len(key) == 8:
            return (int(key[0:2], 16), int(key[2:4], 16),
                    int(key[4:6], 16), int(key[6:8], 16))
    except ValueError:
        pass
    raise ValueError("invalid color argument")


def rgba(color):
    """Convert any pygame colour argument to an (r, g, b, a) int tuple."""
    if isinstance(color, tuple) and len(color) == 4 and type(color[0]) is int:
        if 0 <= min(color) and max(color) <= 255:
            return color
    if isinstance(color, str):
        return _parse_string(color)
    if isinstance(color, int):
        if color <= 0xFFFFFF:
            return ((color >> 16) & 255, (color >> 8) & 255, color & 255, 255)
        return ((color >> 24) & 255, (color >> 16) & 255,
                (color >> 8) & 255, color & 255)
    try:
        seq = tuple(color)
    except TypeError:
        raise TypeError("invalid color argument")
    if len(seq) == 3:
        return (_byte(seq[0]), _byte(seq[1]), _byte(seq[2]), 255)
    if len(seq) == 4:
        return (_byte(seq[0]), _byte(seq[1]), _byte(seq[2]), _byte(seq[3]))
    raise ValueError("invalid color argument")


class Color(tuple):
    """pygame.Color: an immutable (r, g, b, a) tuple with a few helpers."""

    def __new__(cls, *args):
        if len(args) == 1:
            value = rgba(args[0])
        elif len(args) in (3, 4):
            value = rgba(args)
        else:
            raise ValueError("invalid color argument")
        return super().__new__(cls, value)

    r = property(lambda self: self[0])
    g = property(lambda self: self[1])
    b = property(lambda self: self[2])
    a = property(lambda self: self[3])

    def lerp(self, other, amount):
        other = rgba(other)
        return Color(*[int(self[i] + (other[i] - self[i]) * amount)
                       for i in range(4)])

    def normalize(self):
        return tuple(channel / 255.0 for channel in self)

    @property
    def hsva(self):
        h, s, v = colorsys.rgb_to_hsv(self[0] / 255.0, self[1] / 255.0,
                                      self[2] / 255.0)
        return (h * 360.0, s * 100.0, v * 100.0, self[3] / 255.0 * 100.0)

    def grayscale(self):
        gray = int(0.299 * self[0] + 0.587 * self[1] + 0.114 * self[2])
        return Color(gray, gray, gray, self[3])

    def __repr__(self):
        return "(%d, %d, %d, %d)" % tuple(self)
'''

# ----------------------------------------------------------------------
# pygame.rect
# ----------------------------------------------------------------------
_SOURCES['rect'] = r'''"""pygame.Rect (integer rectangle)."""


def _parse(args):
    if len(args) == 1:
        arg = args[0]
        if isinstance(arg, Rect):
            return arg.x, arg.y, arg.w, arg.h
        arg = tuple(arg)
        if len(arg) == 4:
            return arg
        if len(arg) == 2:
            (x, y), (w, h) = arg
            return x, y, w, h
    elif len(args) == 2:
        (x, y), (w, h) = args
        return x, y, w, h
    elif len(args) == 4:
        return args
    raise TypeError("Argument must be rect style object")


class Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, *args):
        x, y, w, h = _parse(args)
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    # -- aliases and derived attributes ---------------------------------
    def _alias(name):
        return property(lambda self: getattr(self, name),
                        lambda self, v: setattr(self, name, int(v)))

    width = _alias("w")
    height = _alias("h")
    left = _alias("x")
    top = _alias("y")
    del _alias

    @property
    def right(self):
        return self.x + self.w

    @right.setter
    def right(self, v):
        self.x = int(v) - self.w

    @property
    def bottom(self):
        return self.y + self.h

    @bottom.setter
    def bottom(self, v):
        self.y = int(v) - self.h

    @property
    def centerx(self):
        return self.x + self.w // 2

    @centerx.setter
    def centerx(self, v):
        self.x = int(v) - self.w // 2

    @property
    def centery(self):
        return self.y + self.h // 2

    @centery.setter
    def centery(self, v):
        self.y = int(v) - self.h // 2

    @property
    def center(self):
        return (self.centerx, self.centery)

    @center.setter
    def center(self, v):
        self.centerx, self.centery = v

    @property
    def topleft(self):
        return (self.x, self.y)

    @topleft.setter
    def topleft(self, v):
        self.x, self.y = int(v[0]), int(v[1])

    @property
    def topright(self):
        return (self.right, self.y)

    @topright.setter
    def topright(self, v):
        self.right, self.y = v

    @property
    def bottomleft(self):
        return (self.x, self.bottom)

    @bottomleft.setter
    def bottomleft(self, v):
        self.x, self.bottom = v

    @property
    def bottomright(self):
        return (self.right, self.bottom)

    @bottomright.setter
    def bottomright(self, v):
        self.right, self.bottom = v

    @property
    def midtop(self):
        return (self.centerx, self.y)

    @midtop.setter
    def midtop(self, v):
        self.centerx, self.y = v

    @property
    def midbottom(self):
        return (self.centerx, self.bottom)

    @midbottom.setter
    def midbottom(self, v):
        self.centerx, self.bottom = v

    @property
    def midleft(self):
        return (self.x, self.centery)

    @midleft.setter
    def midleft(self, v):
        self.x, self.centery = v

    @property
    def midright(self):
        return (self.right, self.centery)

    @midright.setter
    def midright(self, v):
        self.right, self.centery = v

    @property
    def size(self):
        return (self.w, self.h)

    @size.setter
    def size(self, v):
        self.w, self.h = int(v[0]), int(v[1])

    # -- sequence / comparison protocol --------------------------------
    def __iter__(self):
        yield self.x
        yield self.y
        yield self.w
        yield self.h

    def __len__(self):
        return 4

    def __getitem__(self, index):
        return (self.x, self.y, self.w, self.h)[index]

    def __eq__(self, other):
        try:
            return tuple(self) == tuple(Rect(other))
        except (TypeError, ValueError):
            return False

    __hash__ = None

    def __bool__(self):
        return self.w != 0 and self.h != 0

    def __repr__(self):
        return "<rect(%d, %d, %d, %d)>" % (self.x, self.y, self.w, self.h)

    # -- methods -------------------------------------------------------
    def copy(self):
        return Rect(self.x, self.y, self.w, self.h)

    __copy__ = copy

    def update(self, *args):
        self.x, self.y, self.w, self.h = [int(v) for v in _parse(args)]

    def move(self, *offset):
        dx, dy = offset[0] if len(offset) == 1 else offset
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def move_ip(self, *offset):
        dx, dy = offset[0] if len(offset) == 1 else offset
        self.x += int(dx)
        self.y += int(dy)

    def inflate(self, *amount):
        dx, dy = amount[0] if len(amount) == 1 else amount
        return Rect(self.x - dx // 2, self.y - dy // 2, self.w + dx, self.h + dy)

    def inflate_ip(self, *amount):
        self.update(self.inflate(*amount))

    def scale_by(self, *factors):
        fx = factors[0]
        fy = factors[1] if len(factors) > 1 else fx
        return Rect(self.centerx - self.w * fx / 2, self.centery - self.h * fy / 2,
                    self.w * fx, self.h * fy)

    def clamp(self, other):
        other = Rect(other)
        x, y = self.x, self.y
        if self.w >= other.w:
            x = other.x + other.w // 2 - self.w // 2
        elif x < other.x:
            x = other.x
        elif x + self.w > other.right:
            x = other.right - self.w
        if self.h >= other.h:
            y = other.y + other.h // 2 - self.h // 2
        elif y < other.y:
            y = other.y
        elif y + self.h > other.bottom:
            y = other.bottom - self.h
        return Rect(x, y, self.w, self.h)

    def clamp_ip(self, other):
        self.update(self.clamp(other))

    def clip(self, other):
        other = Rect(other)
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return Rect(self.x, self.y, 0, 0)
        return Rect(left, top, right - left, bottom - top)

    def union(self, other):
        other = Rect(other)
        left = min(self.x, other.x)
        top = min(self.y, other.y)
        return Rect(left, top, max(self.right, other.right) - left,
                    max(self.bottom, other.bottom) - top)

    def union_ip(self, other):
        self.update(self.union(other))

    def unionall(self, others):
        result = self.copy()
        for other in others:
            result = result.union(other)
        return result

    def fit(self, other):
        other = Rect(other)
        ratio = max(self.w / float(other.w or 1), self.h / float(other.h or 1))
        w, h = int(self.w / ratio), int(self.h / ratio)
        return Rect(other.x + (other.w - w) // 2, other.y + (other.h - h) // 2, w, h)

    def normalize(self):
        if self.w < 0:
            self.x += self.w
            self.w = -self.w
        if self.h < 0:
            self.y += self.h
            self.h = -self.h

    def contains(self, other):
        other = Rect(other)
        return (self.x <= other.x and self.y <= other.y
                and self.right >= other.right and self.bottom >= other.bottom
                and self.w > 0 and self.h > 0)

    def collidepoint(self, *point):
        px, py = point[0] if len(point) == 1 else point
        return self.x <= px < self.right and self.y <= py < self.bottom

    def colliderect(self, other):
        other = Rect(other)
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def collidelist(self, rects):
        for index, rect in enumerate(rects):
            if self.colliderect(rect):
                return index
        return -1

    def collidelistall(self, rects):
        return [i for i, rect in enumerate(rects) if self.colliderect(rect)]

    def collidedict(self, mapping, use_values=False):
        for key, value in mapping.items():
            if self.colliderect(value if use_values else key):
                return (key, value)
        return None

    def collidedictall(self, mapping, use_values=False):
        return [(k, v) for k, v in mapping.items()
                if self.colliderect(v if use_values else k)]
'''

# ----------------------------------------------------------------------
# pygame.math
# ----------------------------------------------------------------------
_SOURCES['math'] = r'''"""pygame.math: Vector2, Vector3 and helpers."""

import math as _m


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def _pair(value):
    try:
        return float(value[0]), float(value[1])
    except (TypeError, IndexError, KeyError):
        raise TypeError("expected a Vector2 or a sequence of 2 numbers")


class Vector2:
    __slots__ = ("x", "y")

    def __init__(self, x=0, y=None):
        if y is None:
            if isinstance(x, (int, float)):
                y = x
            else:
                x, y = _pair(x)
        self.x = float(x)
        self.y = float(y)

    # -- protocol ---------------------------------------------------------
    def __iter__(self):
        yield self.x
        yield self.y

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return (self.x, self.y)[index]

    def __setitem__(self, index, value):
        if index in (0, -2):
            self.x = float(value)
        elif index in (1, -1):
            self.y = float(value)
        else:
            raise IndexError("Vector2 index out of range")

    def __repr__(self):
        return "<Vector2(%g, %g)>" % (self.x, self.y)

    def __eq__(self, other):
        try:
            ox, oy = _pair(other)
        except TypeError:
            return False
        return abs(self.x - ox) < 1e-6 and abs(self.y - oy) < 1e-6

    def __ne__(self, other):
        return not self == other

    __hash__ = None

    def __bool__(self):
        return self.x != 0 or self.y != 0

    # -- arithmetic -------------------------------------------------------
    def __add__(self, other):
        ox, oy = _pair(other)
        return Vector2(self.x + ox, self.y + oy)

    __radd__ = __add__

    def __sub__(self, other):
        ox, oy = _pair(other)
        return Vector2(self.x - ox, self.y - oy)

    def __rsub__(self, other):
        ox, oy = _pair(other)
        return Vector2(ox - self.x, oy - self.y)

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return Vector2(self.x * other, self.y * other)
        ox, oy = _pair(other)
        return self.x * ox + self.y * oy  # dot product, like pygame

    __rmul__ = __mul__

    def __truediv__(self, other):
        return Vector2(self.x / other, self.y / other)

    def __floordiv__(self, other):
        return Vector2(self.x // other, self.y // other)

    def __neg__(self):
        return Vector2(-self.x, -self.y)

    def __pos__(self):
        return Vector2(self.x, self.y)

    def __abs__(self):
        return self.length()

    def __iadd__(self, other):
        ox, oy = _pair(other)
        self.x += ox
        self.y += oy
        return self

    def __isub__(self, other):
        ox, oy = _pair(other)
        self.x -= ox
        self.y -= oy
        return self

    def __imul__(self, other):
        self.x *= other
        self.y *= other
        return self

    def __itruediv__(self, other):
        self.x /= other
        self.y /= other
        return self

    # -- methods ----------------------------------------------------------
    @property
    def xy(self):
        return (self.x, self.y)

    def copy(self):
        return Vector2(self.x, self.y)

    __copy__ = copy

    def update(self, x=0, y=None):
        self.x, self.y = Vector2(x, y).xy

    def length(self):
        return _m.hypot(self.x, self.y)

    magnitude = length

    def length_squared(self):
        return self.x * self.x + self.y * self.y

    magnitude_squared = length_squared

    def normalize(self):
        n = self.length()
        if n == 0:
            raise ValueError("Can't normalize Vector of length Zero")
        return Vector2(self.x / n, self.y / n)

    def normalize_ip(self):
        self.update(self.normalize())

    def scale_to_length(self, length):
        n = self.length()
        if n == 0:
            raise ValueError("Cannot scale a vector with zero length")
        self.x, self.y = self.x * length / n, self.y * length / n

    def clamp_magnitude(self, max_length, min_length=0):
        n = self.length()
        if n == 0:
            return self.copy()
        target = clamp(n, min_length, max_length)
        return Vector2(self.x * target / n, self.y * target / n)

    def clamp_magnitude_ip(self, max_length, min_length=0):
        self.update(self.clamp_magnitude(max_length, min_length))

    def dot(self, other):
        ox, oy = _pair(other)
        return self.x * ox + self.y * oy

    def cross(self, other):
        ox, oy = _pair(other)
        return self.x * oy - self.y * ox

    def distance_to(self, other):
        ox, oy = _pair(other)
        return _m.hypot(self.x - ox, self.y - oy)

    def distance_squared_to(self, other):
        ox, oy = _pair(other)
        return (self.x - ox) ** 2 + (self.y - oy) ** 2

    def angle_to(self, other):
        ox, oy = _pair(other)
        return _m.degrees(_m.atan2(oy, ox) - _m.atan2(self.y, self.x))

    def rotate(self, angle):
        a = _m.radians(angle)
        c, s = _m.cos(a), _m.sin(a)
        return Vector2(self.x * c - self.y * s, self.x * s + self.y * c)

    def rotate_ip(self, angle):
        self.update(self.rotate(angle))

    def rotate_rad(self, angle):
        return self.rotate(_m.degrees(angle))

    def rotate_rad_ip(self, angle):
        self.update(self.rotate_rad(angle))

    def reflect(self, normal):
        n = Vector2(normal).normalize()
        d = self.dot(n)
        return Vector2(self.x - 2 * d * n.x, self.y - 2 * d * n.y)

    def lerp(self, other, t):
        ox, oy = _pair(other)
        return Vector2(self.x + (ox - self.x) * t, self.y + (oy - self.y) * t)

    def move_towards(self, target, max_distance):
        tx, ty = _pair(target)
        dx, dy = tx - self.x, ty - self.y
        dist = _m.hypot(dx, dy)
        if dist == 0 or dist <= max_distance:
            return Vector2(tx, ty)
        return Vector2(self.x + dx / dist * max_distance,
                       self.y + dy / dist * max_distance)

    def as_polar(self):
        return (self.length(), _m.degrees(_m.atan2(self.y, self.x)))

    def from_polar(self, coords):
        r, phi = coords
        self.x = r * _m.cos(_m.radians(phi))
        self.y = r * _m.sin(_m.radians(phi))


class Vector3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0, y=None, z=None):
        if y is None and z is None:
            if isinstance(x, (int, float)):
                y = z = x
            else:
                x, y, z = x[0], x[1], x[2]
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __len__(self):
        return 3

    def __getitem__(self, index):
        return (self.x, self.y, self.z)[index]

    def __repr__(self):
        return "<Vector3(%g, %g, %g)>" % (self.x, self.y, self.z)

    def __eq__(self, other):
        try:
            return all(abs(a - b) < 1e-6 for a, b in zip(self, other))
        except TypeError:
            return False

    __hash__ = None

    def __add__(self, other):
        return Vector3(self.x + other[0], self.y + other[1], self.z + other[2])

    __radd__ = __add__

    def __sub__(self, other):
        return Vector3(self.x - other[0], self.y - other[1], self.z - other[2])

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return Vector3(self.x * other, self.y * other, self.z * other)
        return self.dot(other)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return Vector3(self.x / other, self.y / other, self.z / other)

    def __neg__(self):
        return Vector3(-self.x, -self.y, -self.z)

    def copy(self):
        return Vector3(self.x, self.y, self.z)

    def length(self):
        return _m.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    magnitude = length

    def normalize(self):
        n = self.length()
        if n == 0:
            raise ValueError("Can't normalize Vector of length Zero")
        return Vector3(self.x / n, self.y / n, self.z / n)

    def dot(self, other):
        return self.x * other[0] + self.y * other[1] + self.z * other[2]

    def cross(self, other):
        return Vector3(self.y * other[2] - self.z * other[1],
                       self.z * other[0] - self.x * other[2],
                       self.x * other[1] - self.y * other[0])

    def distance_to(self, other):
        return (self - other).length()

    def lerp(self, other, t):
        return Vector3(self.x + (other[0] - self.x) * t,
                       self.y + (other[1] - self.y) * t,
                       self.z + (other[2] - self.z) * t)
'''

# ----------------------------------------------------------------------
# pygame.surface
# ----------------------------------------------------------------------
_SOURCES['surface'] = r'''"""pygame.Surface with lazy RGBA pixel access and replayable draw commands.

Normal drawing stays command-based for fast Kivy rendering. Pixel methods
materialize a software RGBA buffer only when requested. The buffer is rebuilt
from the command history after later drawing operations.
"""

import math as _m
import os as _os

from . import _core
from .color import Color, rgba
from .constants import SRCALPHA
from .rect import Rect

MAX_PIXEL_COUNT = 8 * 1024 * 1024  # cap lazy RGBA pixel buffers at 32 MiB
_IMAGE_CACHE = {}
_IMAGE_CACHE_BYTES = [0]
_IMAGE_CACHE_LIMIT = 16 * 1024 * 1024


def _pos(dest):
    if isinstance(dest, Rect):
        return dest.x, dest.y
    return dest[0], dest[1]


def _blank_pixels(width, height, opaque=False):
    count = width * height
    if count > MAX_PIXEL_COUNT:
        raise _core.error("Pixel access is limited to surfaces with at most %d pixels" % MAX_PIXEL_COUNT)
    if opaque:
        return bytearray((0, 0, 0, 255)) * count
    return bytearray(count * 4)


def _put(pixels, width, height, x, y, color, blend=False):
    x, y = int(x), int(y)
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    index = (y * width + x) * 4
    r, g, b, a = color
    if not blend or a >= 255:
        pixels[index:index + 4] = bytes((r, g, b, a))
    elif a > 0:
        da = pixels[index + 3]
        out_a = a + (da * (255 - a) + 127) // 255
        if out_a:
            inv = 255 - a
            dr, dg, db = pixels[index:index + 3]
            denom = out_a * 255
            pixels[index] = (r * a * 255 + dr * da * inv + denom // 2) // denom
            pixels[index + 1] = (g * a * 255 + dg * da * inv + denom // 2) // denom
            pixels[index + 2] = (b * a * 255 + db * da * inv + denom // 2) // denom
            pixels[index + 3] = out_a


def _get(pixels, width, x, y):
    index = (y * width + x) * 4
    return tuple(pixels[index:index + 4])


def _pixel_color(color, opaque):
    return tuple(color[:3]) + (255,) if opaque else color


def _load_image_pixels(path):
    """Decode image pixels with Pillow when available, otherwise Kivy's provider."""
    try:
        stamp = (_os.path.getmtime(path), _os.path.getsize(path))
    except OSError:
        stamp = None
    cached = _IMAGE_CACHE.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1], cached[2], cached[3]

    decoded = None
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(path) as image:
            image = image.convert("RGBA")
            decoded = (image.width, image.height, image.tobytes())
    except Exception:
        try:
            # ImageLoader retains decoded bytes without creating a GPU texture.
            # That matters because user games execute in NovaGame's worker thread.
            from kivy.core.image import ImageLoader as _ImageLoader
            loaded = _ImageLoader.load(path, keep_data=True)
            data = loaded._data[0]
            iw, ih = int(data.width), int(data.height)
            fmt = str(data.fmt).lower()
            raw = data.data
            rowlength = int(getattr(data, "rowlength", 0) or iw)
            formats = {
                "rgb": (3, (0, 1, 2, None)),
                "bgr": (3, (2, 1, 0, None)),
                "rgba": (4, (0, 1, 2, 3)),
                "bgra": (4, (2, 1, 0, 3)),
                "argb": (4, (1, 2, 3, 0)),
                "abgr": (4, (3, 2, 1, 0)),
            }
            spec = formats.get(fmt)
            if raw is None or spec is None:
                raise ValueError("image provider did not retain a supported raw pixel format")
            channels, order = spec
            if rowlength < iw:
                rowlength = iw
            result = bytearray(iw * ih * 4)
            for y in range(ih):
                for x in range(iw):
                    src = (y * rowlength + x) * channels
                    dst = (y * iw + x) * 4
                    result[dst] = raw[src + order[0]]
                    result[dst + 1] = raw[src + order[1]]
                    result[dst + 2] = raw[src + order[2]]
                    result[dst + 3] = 255 if order[3] is None else raw[src + order[3]]
            decoded = (iw, ih, bytes(result))
        except Exception as exc:
            # CoreImage is a compatibility fallback for providers that don't
            # expose raw data through ImageLoader. It may need a graphics context.
            try:
                from kivy.core.image import Image as _CoreImage
                image = _CoreImage(path, keep_data=True)
                data = image.image._data[0]
                iw, ih = int(data.width), int(data.height)
                result = bytearray(iw * ih * 4)
                for y in range(ih):
                    for x in range(iw):
                        color = image.read_pixel(x, y)
                        values = tuple(int(max(0, min(1, float(v))) * 255 + 0.5)
                                       for v in color)
                        if len(values) == 3:
                            values += (255,)
                        dst = (y * iw + x) * 4
                        result[dst:dst + 4] = bytes(values[:4])
                decoded = (iw, ih, bytes(result))
            except Exception as fallback_exc:
                raise _core.error("Unable to read image pixels: %s (%s)" % (exc, fallback_exc))

    if decoded is None:
        raise _core.error("Unable to read image pixels: " + str(path))
    iw, ih, pixels = decoded
    if len(pixels) <= _IMAGE_CACHE_LIMIT:
        while _IMAGE_CACHE and _IMAGE_CACHE_BYTES[0] + len(pixels) > _IMAGE_CACHE_LIMIT:
            old_path = next(iter(_IMAGE_CACHE))
            old = _IMAGE_CACHE.pop(old_path)
            _IMAGE_CACHE_BYTES[0] -= len(old[3])
        old = _IMAGE_CACHE.pop(path, None)
        if old is not None:
            _IMAGE_CACHE_BYTES[0] -= len(old[3])
        _IMAGE_CACHE[path] = (stamp, iw, ih, pixels)
        _IMAGE_CACHE_BYTES[0] += len(pixels)
    return iw, ih, pixels


def _line(pixels, width, height, color, a, b, stroke=1, blend=False):
    x1, y1 = float(a[0]), float(a[1])
    x2, y2 = float(b[0]), float(b[1])
    radius = max(0.5, float(stroke) / 2.0)
    min_x = max(0, int(_m.floor(min(x1, x2) - radius)))
    max_x = min(width - 1, int(_m.ceil(max(x1, x2) + radius)))
    min_y = max(0, int(_m.floor(min(y1, y2) - radius)))
    max_y = min(height - 1, int(_m.ceil(max(y1, y2) + radius)))
    vx, vy = x2 - x1, y2 - y1
    length2 = vx * vx + vy * vy
    limit = radius * radius
    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            qx, qy = px + 0.5, py + 0.5
            if length2:
                t = max(0.0, min(1.0, ((qx - x1) * vx + (qy - y1) * vy) / length2))
                dx, dy = qx - (x1 + t * vx), qy - (y1 + t * vy)
            else:
                dx, dy = qx - x1, qy - y1
            if dx * dx + dy * dy <= limit:
                _put(pixels, width, height, px, py, color, blend)


def _polygon_contains(points, x, y):
    inside = False
    count = len(points)
    j = count - 1
    for i in range(count):
        xi, yi = points[i]
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-20) + xi:
            inside = not inside
        j = i
    return inside


def _draw_image(pixels, width, height, path, x, y, draw_w, draw_h, region=None,
                alpha=255, colorkey=None):
    iw, ih, source = _load_image_pixels(path)
    if region is None:
        rx, ry, rw, rh = 0, 0, iw, ih
    else:
        rx, ry, rw, rh = [int(v) for v in region]
    if rw <= 0 or rh <= 0 or draw_w <= 0 or draw_h <= 0:
        return
    x0, y0 = int(_m.floor(x)), int(_m.floor(y))
    dw, dh = max(1, int(round(draw_w))), max(1, int(round(draw_h)))
    for dy in range(max(0, y0), min(height, y0 + dh)):
        sy = ry + min(rh - 1, max(0, int((dy - y) * rh / draw_h)))
        if sy < 0 or sy >= ih:
            continue
        for dx in range(max(0, x0), min(width, x0 + dw)):
            sx = rx + min(rw - 1, max(0, int((dx - x) * rw / draw_w)))
            if sx < 0 or sx >= iw:
                continue
            color = _get(source, iw, sx, sy)
            if colorkey is not None and color[:3] == tuple(colorkey[:3]):
                continue
            if alpha < 255:
                color = color[:3] + ((color[3] * alpha + 127) // 255,)
            _put(pixels, width, height, dx, dy, color, blend=True)


def _raster_commands(width, height, commands, opaque=False):
    pixels = _blank_pixels(width, height, opaque)
    for command in commands:
        if not command:
            continue
        kind = command[0]
        if kind == "pixels":
            raw = command[1]
            expected = width * height * 4
            if len(raw) == expected:
                pixels[:] = raw
        elif kind == "fill":
            color = _pixel_color(command[1], opaque)
            pixels[:] = bytes(color) * (width * height)
        elif kind == "rect":
            _, color, x, y, rw, rh, stroke, radius = command
            color = _pixel_color(color, opaque)
            x0, y0 = max(0, int(_m.floor(x))), max(0, int(_m.floor(y)))
            x1, y1 = min(width, int(_m.ceil(x + rw))), min(height, int(_m.ceil(y + rh)))
            for py in range(y0, y1):
                for px in range(x0, x1):
                    edge = (stroke <= 0 or px < x + stroke or px >= x + rw - stroke
                            or py < y + stroke or py >= y + rh - stroke)
                    if edge:
                        _put(pixels, width, height, px, py, color)
        elif kind == "circle":
            _, color, cx, cy, radius, stroke = command
            color = _pixel_color(color, opaque)
            r = float(radius)
            inner = max(0.0, r - max(1, int(stroke))) if stroke else -1
            for py in range(max(0, int(cy-r-1)), min(height, int(cy+r+2))):
                for px in range(max(0, int(cx-r-1)), min(width, int(cx+r+2))):
                    d2 = (px + 0.5 - cx) ** 2 + (py + 0.5 - cy) ** 2
                    if d2 <= r*r and (stroke <= 0 or d2 >= inner*inner):
                        _put(pixels, width, height, px, py, color)
        elif kind == "ellipse":
            _, color, x, y, rw, rh, stroke = command
            color = _pixel_color(color, opaque)
            if rw <= 0 or rh <= 0:
                continue
            cx, cy = x + rw / 2.0, y + rh / 2.0
            rx, ry = max(0.5, rw / 2.0), max(0.5, rh / 2.0)
            inset_x = max(0.0, (rx - stroke)) if stroke else -1
            inset_y = max(0.0, (ry - stroke)) if stroke else -1
            for py in range(max(0, int(y)), min(height, int(_m.ceil(y+rh)))):
                for px in range(max(0, int(x)), min(width, int(_m.ceil(x+rw)))):
                    nx = (px + 0.5 - cx) / rx
                    ny = (py + 0.5 - cy) / ry
                    outer = nx*nx + ny*ny <= 1.0
                    inner = (stroke <= 0 or inset_x <= 0 or inset_y <= 0
                             or ((px+0.5-cx)/inset_x)**2 + ((py+0.5-cy)/inset_y)**2 >= 1.0)
                    if outer and inner:
                        _put(pixels, width, height, px, py, color)
        elif kind == "line":
            _, color, x1, y1, x2, y2, stroke = command
            color = _pixel_color(color, opaque)
            _line(pixels, width, height, color, (x1, y1), (x2, y2), stroke)
        elif kind == "lines":
            _, color, points, closed, stroke = command
            color = _pixel_color(color, opaque)
            for i in range(len(points)-1):
                _line(pixels, width, height, color, points[i], points[i+1], stroke)
            if closed and len(points) > 1:
                _line(pixels, width, height, color, points[-1], points[0], stroke)
        elif kind == "polygon":
            _, color, points, stroke = command
            color = _pixel_color(color, opaque)
            if stroke:
                for i in range(len(points)):
                    _line(pixels, width, height, color, points[i], points[(i+1) % len(points)], stroke)
            else:
                min_x = max(0, int(_m.floor(min(p[0] for p in points))))
                max_x = min(width, int(_m.ceil(max(p[0] for p in points))) + 1)
                min_y = max(0, int(_m.floor(min(p[1] for p in points))))
                max_y = min(height, int(_m.ceil(max(p[1] for p in points))) + 1)
                for py in range(min_y, max_y):
                    for px in range(min_x, max_x):
                        if _polygon_contains(points, px + 0.5, py + 0.5):
                            _put(pixels, width, height, px, py, color)
        elif kind == "arc":
            _, color, x, y, rw, rh, start, stop, stroke = command
            color = _pixel_color(color, opaque)
            if rw <= 0 or rh <= 0:
                continue
            steps = max(2, int(abs(stop-start) * max(rw, rh) / 8))
            points = []
            for index in range(steps + 1):
                angle = start + (stop-start) * index / steps
                points.append((x + rw/2 + _m.cos(angle)*rw/2,
                               y + rh/2 - _m.sin(angle)*rh/2))
            for index in range(len(points)-1):
                _line(pixels, width, height, color, points[index], points[index+1], stroke)
        elif kind == "img":
            _, path, x, y, rw, rh, region = command
            _draw_image(pixels, width, height, path, x, y, rw, rh, region)
        elif kind == "text":
            # Use Kivy's text provider when available; pixel access remains
            # optional on environments without a text provider.
            try:
                _, color, fontkey, text, x, y = command
                color = _pixel_color(color, opaque)
                from kivy.core.text import Label as _CoreLabel
                from pygame_render import TTF_LOCK as _TTF_LOCK
                with _TTF_LOCK:
                    label = _CoreLabel(text=text, font_size=fontkey[1],
                                       bold=fontkey[2], italic=fontkey[3])
                    label.refresh()
                    texture = label.texture
                    raw = bytes(texture.pixels)
                    tw, th = texture.size
                for py in range(int(th)):
                    for px in range(int(tw)):
                        idx = ((th - 1 - py) * tw + px) * 4
                        a = raw[idx + 3]
                        if a:
                            _put(pixels, width, height, int(x)+px, int(y)+py,
                                 color[:3] + (a,))
            except Exception:
                pass
        elif kind == "group":
            _, nested, cx, cy, sw, sh, angle, sx, sy, alpha, colorkey = command
            if sw <= 0 or sh <= 0 or not sx or not sy:
                continue
            source = _raster_commands(max(1, int(sw)), max(1, int(sh)), nested, opaque=False)
            rad = _m.radians(angle)
            cs, sn = _m.cos(rad), _m.sin(rad)
            corners = []
            for ux, uy in ((-sw/2,-sh/2), (sw/2,-sh/2),
                           (sw/2,sh/2), (-sw/2,sh/2)):
                ux, uy = ux*sx, uy*sy
                corners.append((cx + cs*ux - sn*uy, cy + sn*ux + cs*uy))
            x0 = max(0, int(_m.floor(min(p[0] for p in corners))))
            x1 = min(width, int(_m.ceil(max(p[0] for p in corners))))
            y0 = max(0, int(_m.floor(min(p[1] for p in corners))))
            y1 = min(height, int(_m.ceil(max(p[1] for p in corners))))
            for py in range(y0, y1):
                for px in range(x0, x1):
                    dx, dy = px + 0.5 - cx, py + 0.5 - cy
                    ux = (cs*dx + sn*dy) / sx + sw/2
                    uy = (-sn*dx + cs*dy) / sy + sh/2
                    ix, iy = int(ux), int(uy)
                    if 0 <= ix < sw and 0 <= iy < sh:
                        color = _get(source, int(sw), ix, iy)
                        if colorkey is not None and color[:3] == tuple(colorkey[:3]):
                            continue
                        if alpha is not None:
                            color = color[:3] + ((color[3] * int(alpha) + 127)//255,)
                        _put(pixels, width, height, px, py, color, blend=True)
    return pixels


class Surface:
    def __init__(self, size=(0, 0), flags=0, depth=0, masks=None):
        try:
            width, height = int(size[0]), int(size[1])
        except (TypeError, IndexError):
            raise TypeError("Surface size must be a (width, height) pair")
        if width < 0 or height < 0:
            raise _core.error("Invalid resolution for Surface")
        self._w = width
        self._h = height
        self._flags = flags if isinstance(flags, int) else 0
        self._srcalpha = bool(self._flags & SRCALPHA)
        self._cmds = [] if self._srcalpha else [("fill", (0, 0, 0, 255))]
        self._snap = None
        self._pixels = None
        self._pixel_dirty = False
        self._revision = 0
        self._colorkey = None
        self._alpha = None
        self._img = None
        self._clip = None
        self._is_display = False

    def _flush_pixel_edits(self):
        """Collapse direct pixel edits into one replayable framebuffer command."""
        if self._pixel_dirty and self._pixels is not None:
            self._cmds = [("pixels", bytes(self._pixels), self._w, self._h)]
            self._pixel_dirty = False
            self._snap = None
            self._img = None

    def _add(self, command):
        # Preserve any get_at/set_at edits before recording later draw calls.
        self._flush_pixel_edits()
        self._cmds.append(command)
        self._snap = None
        self._pixels = None
        self._img = None
        self._revision += 1
        if len(self._cmds) > _core.MAX_COMMANDS:
            del self._cmds[:len(self._cmds) - _core.MAX_COMMANDS // 2]

    def _snapshot(self):
        self._flush_pixel_edits()
        if self._snap is None:
            self._snap = tuple(self._cmds)
        return self._snap

    def _pixel_data(self):
        if self._pixels is None:
            self._pixels = _raster_commands(self._w, self._h, self._cmds,
                                           opaque=not self._srcalpha)
        return self._pixels

    def get_size(self):
        return (self._w, self._h)

    def get_width(self):
        return self._w

    def get_height(self):
        return self._h

    def get_rect(self, **kwargs):
        rect = Rect(0, 0, self._w, self._h)
        for name, value in kwargs.items():
            setattr(rect, name, value)
        return rect

    def get_flags(self):
        return self._flags

    def get_bitsize(self):
        return 32

    def get_bytesize(self):
        return 4

    def get_masks(self):
        alpha_mask = 0xff000000 if self._srcalpha else 0
        return (0x00ff0000, 0x0000ff00, 0x000000ff, alpha_mask)

    def get_shifts(self):
        return (16, 8, 0, 24 if self._srcalpha else 0)

    def get_losses(self):
        return (0, 0, 0, 0)

    def map_rgb(self, color):
        r, g, b, a = rgba(color)
        value = (r << 16) | (g << 8) | b
        return value | (a << 24) if self._srcalpha else value

    def unmap_rgb(self, mapped):
        value = int(mapped) & 0xffffffff
        alpha = (value >> 24) & 255 if self._srcalpha else 255
        return Color((value >> 16) & 255, (value >> 8) & 255,
                     value & 255, alpha)

    def get_at_mapped(self, pos):
        return self.map_rgb(self.get_at(pos))

    def get_bounding_rect(self, min_alpha=1):
        pixels = self._pixel_data()
        key = self._colorkey
        threshold = max(0, int(min_alpha))
        left, top, right, bottom = self._w, self._h, -1, -1
        for y in range(self._h):
            for x in range(self._w):
                r, g, b, a = _get(pixels, self._w, x, y)
                if a >= threshold and (key is None or (r, g, b) != key):
                    left, top = min(left, x), min(top, y)
                    right, bottom = max(right, x), max(bottom, y)
        if right < left:
            return Rect(0, 0, 0, 0)
        return Rect(left, top, right-left+1, bottom-top+1)

    def get_clip(self):
        return self._clip or Rect(0, 0, self._w, self._h)

    def set_clip(self, rect=None):
        self._clip = None if rect is None else Rect(rect).clip(Rect(0, 0, self._w, self._h))

    def lock(self):
        self._pixel_data()

    def unlock(self):
        pass

    def mustlock(self):
        return False

    def get_locked(self):
        return False

    def set_colorkey(self, color, flags=0):
        self._colorkey = None if color is None else rgba(color)[:3]
        self._revision += 1

    def get_colorkey(self):
        return None if self._colorkey is None else self._colorkey + (255,)

    def set_alpha(self, value, flags=0):
        self._alpha = None if value is None else max(0, min(255, int(value)))
        self._revision += 1

    def get_alpha(self):
        return 255 if self._alpha is None else self._alpha

    def convert(self, *args):
        return self.copy()

    def convert_alpha(self, *args):
        other = self.copy()
        other._srcalpha = True
        other._flags |= SRCALPHA
        return other

    def copy(self):
        other = Surface((self._w, self._h), self._flags)
        other._cmds = list(self._cmds)
        other._colorkey = self._colorkey
        other._alpha = self._alpha
        other._img = self._img
        other._srcalpha = self._srcalpha
        other._pixels = None if self._pixels is None else bytearray(self._pixels)
        other._pixel_dirty = self._pixel_dirty
        other._revision = self._revision
        return other

    __copy__ = copy

    def fill(self, color, rect=None, special_flags=0):
        color = rgba(color)
        if not self._srcalpha:
            color = color[:3] + (255,)
        if rect is None:
            self._cmds[:] = []
            self._snap = None
            self._pixels = None
            self._pixel_dirty = False
            self._img = None
            self._revision += 1
            if not (color[3] == 0 and self._srcalpha):
                self._cmds.append(("fill", color))
            return Rect(0, 0, self._w, self._h)
        rect = Rect(rect)
        self._add(("rect", color, rect.x, rect.y, rect.w, rect.h, 0, 0))
        return rect

    def blit(self, source, dest, area=None, special_flags=0):
        dx, dy = _pos(dest)
        if (source._img is not None and source._alpha is None
                and source._colorkey is None):
            path, region = source._img
            if area is not None:
                ax, ay, aw, ah = Rect(area)
                if region is not None:
                    ax, ay = ax + region[0], ay + region[1]
                region = (ax, ay, aw, ah)
                width, height = aw, ah
            else:
                width, height = source._w, source._h
            self._add(("img", path, dx, dy, width, height, region))
            return Rect(dx, dy, width, height)

        snap = source._snapshot()
        width, height = source._w, source._h
        if len(snap) == 1 and snap[0][0] == "text" and source._alpha is None:
            cmd = snap[0]
            self._add(("text", cmd[1], cmd[2], cmd[3], dx + cmd[4], dy + cmd[5]))
        elif snap:
            self._add(("group", snap, dx + width / 2.0, dy + height / 2.0,
                       width, height, 0, 1, 1, source._alpha, source._colorkey))
        return Rect(dx, dy, width, height)

    def blits(self, blit_sequence, doreturn=True):
        results = []
        for item in blit_sequence:
            results.append(self.blit(*item))
        return results if doreturn else None

    def set_at(self, pos, color):
        x, y = int(pos[0]), int(pos[1])
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise IndexError("pixel index out of range")
        if not self.get_clip().collidepoint((x, y)):
            return
        color = rgba(color)
        if not self._srcalpha:
            color = color[:3] + (255,)
        pixels = self._pixel_data()
        _put(pixels, self._w, self._h, x, y, color)
        # Keep the pixel buffer authoritative. _snapshot() emits one compact
        # framebuffer command, rather than one drawing command per pixel.
        self._pixel_dirty = True
        self._snap = None
        self._img = None
        self._revision += 1

    def get_at(self, pos):
        x, y = int(pos[0]), int(pos[1])
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise IndexError("pixel index out of range")
        return Color(*_get(self._pixel_data(), self._w, x, y))

    def subsurface(self, *rect):
        rect = Rect(*rect)
        if rect.x < 0 or rect.y < 0 or rect.right > self._w or rect.bottom > self._h:
            raise ValueError("subsurface rectangle outside surface area")
        sub = Surface((rect.w, rect.h), self._flags | SRCALPHA)
        if self._img is not None:
            path, region = self._img
            if region is not None:
                rect = Rect(rect.x + region[0], rect.y + region[1], rect.w, rect.h)
            region = (rect.x, rect.y, rect.w, rect.h)
            sub._cmds = [("img", path, 0, 0, rect.w, rect.h, region)]
            sub._img = (path, region)
        else:
            sub._cmds = [("group", self._snapshot(),
                          self._w / 2.0 - rect.x, self._h / 2.0 - rect.y,
                          self._w, self._h, 0, 1, 1, None, None)]
        return sub

    def scroll(self, dx=0, dy=0):
        dx, dy = int(dx), int(dy)
        pixels = self._pixel_data()
        old_pixels = bytearray(pixels)
        pixels[:] = b"\x00" * len(pixels)
        for y in range(self._h):
            for x in range(self._w):
                sx, sy = x - dx, y - dy
                if 0 <= sx < self._w and 0 <= sy < self._h:
                    si, di = (sy*self._w+sx)*4, (y*self._w+x)*4
                    pixels[di:di+4] = old_pixels[si:si+4]
        self._cmds = []
        self._pixel_dirty = True
        self._snap = None
        self._img = None
        self._revision += 1

    def __repr__(self):
        return "<Surface(%dx%dx32 SW)>" % (self._w, self._h)
'''
# ----------------------------------------------------------------------
# pygame.draw
# ----------------------------------------------------------------------
_SOURCES['draw'] = r'''"""pygame.draw: records shapes as commands on the target Surface."""

import math as _m

from .color import rgba
from .rect import Rect


def _pt(point):
    return (float(point[0]), float(point[1]))


def _points(points):
    pts = tuple(_pt(p) for p in points)
    if len(pts) < 2:
        raise ValueError("points argument must contain 2 or more points")
    return pts


def _bounds(pts, width=1):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = max(0, int(width) // 2)
    return Rect(int(min(xs)) - pad, int(min(ys)) - pad,
                int(max(xs) - min(xs)) + 1 + 2 * pad,
                int(max(ys) - min(ys)) + 1 + 2 * pad)


def rect(surface, color, rect, width=0, border_radius=0, border_top_left_radius=-1,
         border_top_right_radius=-1, border_bottom_left_radius=-1,
         border_bottom_right_radius=-1):
    r = Rect(rect)
    radius = max(0, int(border_radius))
    surface._add(("rect", rgba(color), r.x, r.y, r.w, r.h, max(0, int(width)), radius))
    return r


def circle(surface, color, center, radius, width=0, draw_top_right=None,
           draw_top_left=None, draw_bottom_left=None, draw_bottom_right=None):
    cx, cy = _pt(center)
    radius = float(radius)
    if radius < 1:
        return Rect(int(cx), int(cy), 0, 0)
    surface._add(("circle", rgba(color), cx, cy, radius, max(0, int(width))))
    return Rect(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))


def ellipse(surface, color, rect, width=0):
    r = Rect(rect)
    surface._add(("ellipse", rgba(color), r.x, r.y, r.w, r.h, max(0, int(width))))
    return r


def line(surface, color, start_pos, end_pos, width=1):
    a, b = _pt(start_pos), _pt(end_pos)
    surface._add(("line", rgba(color), a[0], a[1], b[0], b[1], max(1, int(width))))
    return _bounds([a, b], width)


def aaline(surface, color, start_pos, end_pos, blend=1):
    return line(surface, color, start_pos, end_pos, 1)


def lines(surface, color, closed, points, width=1):
    pts = _points(points)
    surface._add(("lines", rgba(color), pts, bool(closed), max(1, int(width))))
    return _bounds(pts, width)


def aalines(surface, color, closed, points, blend=1):
    return lines(surface, color, closed, points, 1)


def polygon(surface, color, points, width=0):
    pts = _points(points)
    if len(pts) < 3:
        raise ValueError("points argument must contain more than 2 points")
    surface._add(("polygon", rgba(color), pts, max(0, int(width))))
    return _bounds(pts, width)


def arc(surface, color, rect, start_angle, stop_angle, width=1):
    r = Rect(rect)
    surface._add(("arc", rgba(color), r.x, r.y, r.w, r.h, float(start_angle),
                  float(stop_angle), max(1, int(width))))
    return r
'''

# ----------------------------------------------------------------------
# pygame.event
# ----------------------------------------------------------------------
_SOURCES['event'] = r'''"""pygame.event: a queue filled by the IDE's game screen."""

import time as _time

from . import _core
from .constants import (ACTIVEEVENT, FINGERDOWN, FINGERMOTION, FINGERUP,
                        KEYDOWN, KEYUP, MOUSEBUTTONDOWN, MOUSEBUTTONUP,
                        MOUSEMOTION, MOUSEWHEEL, NOEVENT, QUIT, TEXTINPUT,
                        USEREVENT, VIDEORESIZE)

_NAMES = {
    NOEVENT: "NoEvent", QUIT: "Quit", ACTIVEEVENT: "ActiveEvent",
    KEYDOWN: "KeyDown", KEYUP: "KeyUp", MOUSEMOTION: "MouseMotion",
    MOUSEBUTTONDOWN: "MouseButtonDown", MOUSEBUTTONUP: "MouseButtonUp",
    MOUSEWHEEL: "MouseWheel", FINGERDOWN: "FingerDown",
    FINGERUP: "FingerUp", FINGERMOTION: "FingerMotion",
    TEXTINPUT: "TextInput", VIDEORESIZE: "VideoResize",
}
_next_custom = [USEREVENT + 1]


def event_name(event_type):
    if event_type >= USEREVENT:
        return "UserEvent"
    return _NAMES.get(event_type, "Unknown")


class Event:
    def __init__(self, type, dict=None, **kwargs):
        self.type = type
        if dict:
            self.__dict__.update(dict)
        self.__dict__.update(kwargs)

    @property
    def dict(self):
        return {k: v for k, v in self.__dict__.items() if k != "type"}

    def __eq__(self, other):
        return (isinstance(other, Event) and self.type == other.type
                and self.dict == other.dict)

    __hash__ = None

    def __repr__(self):
        attrs = ", ".join("%s: %r" % (k, v) for k, v in self.dict.items())
        return "<Event(%d-%s {%s})>" % (self.type, event_name(self.type), attrs)


EventType = Event


def custom_type():
    value = _next_custom[0]
    _next_custom[0] += 1
    return value


def _matcher(eventtype):
    if eventtype is None:
        return lambda ev: True
    if isinstance(eventtype, int):
        return lambda ev: ev.type == eventtype
    wanted = set(eventtype)
    return lambda ev: ev.type in wanted


def pump():
    _core.check_timers()


def get(eventtype=None, pump=True, exclude=None):
    _core.check_timers()
    wanted = _matcher(eventtype)
    unwanted = _matcher(exclude) if exclude is not None else (lambda ev: False)
    taken, kept = [], []
    queue = _core.events
    while queue:
        try:
            ev = queue.popleft()
        except IndexError:
            break
        if wanted(ev) and not unwanted(ev):
            taken.append(ev)
        else:
            kept.append(ev)
    queue.extend(kept)
    return taken


def poll():
    _core.check_timers()
    try:
        return _core.events.popleft()
    except IndexError:
        return Event(NOEVENT)


def wait(timeout=0):
    start = _time.perf_counter()
    while True:
        _core.check_timers()
        try:
            return _core.events.popleft()
        except IndexError:
            pass
        if timeout and (_time.perf_counter() - start) * 1000.0 >= timeout:
            return Event(NOEVENT)
        _time.sleep(0.005)


def peek(eventtype=None, pump=True):
    _core.check_timers()
    wanted = _matcher(eventtype)
    return any(wanted(ev) for ev in list(_core.events))


def clear(eventtype=None, pump=True):
    wanted = _matcher(eventtype)
    kept = [ev for ev in list(_core.events) if not wanted(ev)]
    _core.events.clear()
    _core.events.extend(kept)


def post(event):
    _core.events.append(event)
    return True


def set_blocked(*args, **kwargs):
    pass


def set_allowed(*args, **kwargs):
    pass


def get_blocked(*args, **kwargs):
    return False


def set_grab(grab):
    pass


def get_grab():
    return False
'''

# ----------------------------------------------------------------------
# pygame.key
# ----------------------------------------------------------------------
_SOURCES['key'] = r'''"""pygame.key: keyboard state from the game screen (pad buttons or hardware keys)."""

from . import _core
from .constants import (KEY_NAMES, KMOD_LALT, KMOD_LCTRL, KMOD_LSHIFT, KMOD_RALT,
                        KMOD_RCTRL, KMOD_RSHIFT, K_LALT, K_LCTRL, K_LSHIFT,
                        K_RALT, K_RCTRL, K_RSHIFT)


class _KeyState:
    def __getitem__(self, key):
        return key in _core.keys_down

    def __iter__(self):
        return iter(sorted(_core.keys_down))

    def __bool__(self):
        return bool(_core.keys_down)


def get_pressed():
    return _KeyState()


def get_mods():
    mods = 0
    for key, flag in ((K_LSHIFT, KMOD_LSHIFT), (K_RSHIFT, KMOD_RSHIFT),
                      (K_LCTRL, KMOD_LCTRL), (K_RCTRL, KMOD_RCTRL),
                      (K_LALT, KMOD_LALT), (K_RALT, KMOD_RALT)):
        if key in _core.keys_down:
            mods |= flag
    return mods


def name(key, use_compat=True):
    return KEY_NAMES.get(key, "unknown key")


def key_code(name):
    for code, label in KEY_NAMES.items():
        if label == name.lower():
            return code
    raise ValueError("unknown key name")


def set_repeat(delay=0, interval=0):
    pass


def get_repeat():
    return (0, 0)


def get_focused():
    return True


def start_text_input():
    pass


def stop_text_input():
    pass


def set_text_input_rect(rect):
    pass
'''

# ----------------------------------------------------------------------
# pygame.mouse
# ----------------------------------------------------------------------
_SOURCES['mouse'] = r'''"""pygame.mouse: the first finger on the game screen acts as the mouse."""

from . import _core


def get_pos():
    return tuple(_core.mouse_pos)


def get_pressed(num_buttons=3, *args):
    buttons = tuple(_core.mouse_buttons)
    if num_buttons == 5:
        return buttons + (False, False)
    return buttons


def get_rel():
    rel = tuple(_core.mouse_rel)
    _core.mouse_rel[:] = [0, 0]
    return rel


def set_pos(*pos):
    pass


def set_visible(visible):
    return True


def get_visible():
    return True


def get_focused():
    return True


def set_cursor(*args, **kwargs):
    pass


def get_cursor():
    return None
'''

# ----------------------------------------------------------------------
# pygame.time
# ----------------------------------------------------------------------
_SOURCES['time'] = r'''"""pygame.time"""

import time as _time
from collections import deque

from . import _core


def get_ticks():
    return int((_time.perf_counter() - _core.start_time) * 1000)


def wait(milliseconds):
    _time.sleep(max(0, milliseconds) / 1000.0)
    return int(milliseconds)


delay = wait


def set_timer(event, millis, loops=0):
    for timer in list(_core.timers):
        same = timer[0] is event or (isinstance(event, int) and timer[0] == event)
        if same:
            _core.timers.remove(timer)
    if millis > 0:
        due = _time.perf_counter() * 1000.0 + millis
        _core.timers.append([event, float(millis), due, loops if loops > 0 else None])


class Clock:
    def __init__(self):
        self._last = _time.perf_counter()
        self._ms = 0
        self._samples = deque(maxlen=10)

    def tick(self, framerate=0):
        if framerate and framerate > 0:
            wanted = 1.0 / framerate
            elapsed = _time.perf_counter() - self._last
            if elapsed < wanted:
                _time.sleep(wanted - elapsed)
        else:
            _time.sleep(0)
        now = _time.perf_counter()
        delta = now - self._last
        self._last = now
        self._ms = int(delta * 1000)
        self._samples.append(delta)
        _core.check_timers()
        return self._ms

    tick_busy_loop = tick

    def get_time(self):
        return self._ms

    def get_rawtime(self):
        return self._ms

    def get_fps(self):
        total = sum(self._samples)
        return len(self._samples) / total if total > 0 else 0.0
'''

# ----------------------------------------------------------------------
# pygame.display
# ----------------------------------------------------------------------
_SOURCES['display'] = r'''"""pygame.display: opens the IDE's game screen."""

from . import _core
from .surface import Surface


def init():
    pass


def quit():
    host = _core.host
    if host is not None:
        host.close()
    _core.display_surface = None


def get_init():
    return True


def _need_host():
    host = _core.host
    if host is None:
        raise _core.error("The IDE's game screen is not available")
    return host


def set_mode(size=(0, 0), flags=0, depth=0, display=0, vsync=0):
    host = _need_host()
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        width, height = host.screen_size()
    host.open((width, height), _core.caption)
    surface = Surface((width, height))
    surface._is_display = True
    _core.display_surface = surface
    return surface


def get_surface():
    return _core.display_surface


def flip():
    surface = _core.display_surface
    if surface is None:
        raise _core.error("video system not initialized")
    _core.check_timers()
    _need_host().present(surface._snapshot(), surface._w, surface._h)


def update(rectangle=None):
    flip()


def set_caption(title, icontitle=None):
    _core.caption = str(title)
    if _core.host is not None:
        _core.host.set_caption(_core.caption)


def get_caption():
    return (_core.caption, _core.caption)


def set_icon(surface):
    pass


class _Info:
    def __init__(self, width, height):
        self.current_w = width
        self.current_h = height
        self.hw = 0
        self.wm = 1
        self.video_mem = 0


def Info():
    surface = _core.display_surface
    if surface is not None:
        return _Info(surface._w, surface._h)
    size = _need_host().screen_size()
    return _Info(size[0], size[1])


def get_window_size():
    surface = _core.display_surface
    return surface.get_size() if surface is not None else (0, 0)


def get_desktop_sizes():
    return [_need_host().screen_size()]


def list_modes(depth=0, flags=0, display=0):
    return [_need_host().screen_size()]


def toggle_fullscreen():
    return 1


def set_allow_screensaver(value=True):
    pass


def get_active():
    return True


def iconify():
    return True


def get_driver():
    return "android"


def get_wm_info():
    return {}
'''

# ----------------------------------------------------------------------
# pygame.font
# ----------------------------------------------------------------------
_SOURCES['font'] = r'''"""pygame.font: text is measured by the host and drawn by the game screen."""

from . import _core
from .color import rgba
from .constants import SRCALPHA
from .surface import Surface

_measure_cache = {}
_initialized = [True]


def init():
    _initialized[0] = True


def quit():
    _initialized[0] = False


def get_init():
    return _initialized[0]


def get_default_font():
    return "freesansbold.ttf"


def get_fonts():
    return ["arial", "courier", "monospace", "roboto"]


def match_font(name, bold=False, italic=False):
    return None


def _measure(fontkey, text):
    cached = _measure_cache.get((fontkey, text))
    if cached is not None:
        return cached
    size = None
    host = _core.host
    if host is not None:
        try:
            size = host.measure_text(fontkey, text)
        except Exception:
            size = None
    if size is None:
        px = fontkey[1]
        size = (int(len(text) * px * 0.55), int(px * 1.2))
    if len(_measure_cache) > 4000:
        _measure_cache.clear()
    _measure_cache[(fontkey, text)] = size
    return size


class Font:
    def __init__(self, name=None, size=20, _px=None):
        self._name = name
        self._size = int(size)
        # pygame's default font is smaller than a Roboto font of the same number
        self._px = int(_px if _px is not None else
                       (max(6, round(size * 0.65)) if name is None else size))
        self._bold = False
        self._italic = False

    @property
    def _key(self):
        return (self._name, self._px, self._bold, self._italic)

    def render(self, text, antialias=True, color=(255, 255, 255), background=None):
        text = str(text)
        width, height = _measure(self._key, text) if text else (0, self.get_height())
        surface = Surface((max(1, width), height), SRCALPHA)
        if background is not None:
            surface._cmds.append(("rect", rgba(background), 0, 0,
                                  max(1, width), height, 0, 0))
        if text:
            surface._cmds.append(("text", rgba(color), self._key, text, 0, 0))
        return surface

    def size(self, text):
        return _measure(self._key, str(text))

    def get_height(self):
        return _measure(self._key, "Ag")[1]

    def get_linesize(self):
        return self.get_height()

    def get_ascent(self):
        return int(self.get_height() * 0.8)

    def get_descent(self):
        return -int(self.get_height() * 0.2)

    def set_bold(self, value):
        self._bold = bool(value)

    def get_bold(self):
        return self._bold

    def set_italic(self, value):
        self._italic = bool(value)

    def get_italic(self):
        return self._italic

    def set_underline(self, value):
        pass

    def get_underline(self):
        return False

    def set_strikethrough(self, value):
        pass


def SysFont(name, size, bold=False, italic=False):
    wanted = str(name).split(",")[0].strip().lower()
    mono = wanted in ("courier", "couriernew", "courier new", "monospace",
                      "consolas", "monaco", "menlo", "lucidaconsole")
    font = Font("mono" if mono else None, size, _px=int(size))
    font._bold = bool(bold)
    font._italic = bool(italic)
    return font
'''

# ----------------------------------------------------------------------
# pygame.image
# ----------------------------------------------------------------------
_SOURCES['image'] = r'''"""Image loading, byte conversion, and PNG/JPEG saving helpers."""

import io
import os
import struct
import tempfile
import zlib
import binascii

from . import _core
from .constants import SRCALPHA
from .surface import Surface, MAX_PIXEL_COUNT, _load_image_pixels


def _image_size(path):
    """Read image dimensions without decoding the full image."""
    with open(path, "rb") as handle:
        head = handle.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:4] == b"GIF8":
            return struct.unpack("<HH", head[6:10])
        if head[:2] == b"BM":
            width, height = struct.unpack("<ii", head[18:26])
            return width, abs(height)
        if head[:2] == b"\xff\xd8":
            handle.seek(2)
            while True:
                marker = handle.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                code = marker[1]
                if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) < 2:
                    break
                length = struct.unpack(">H", length_bytes)[0]
                if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                    data = handle.read(5)
                    if len(data) == 5:
                        height, width = struct.unpack(">HH", data[1:5])
                        return width, height
                    break
                handle.seek(max(0, length - 2), 1)
    raise _core.error("Unsupported image format (use PNG, JPG, GIF or BMP): " + str(path))


def _surface_from_rgba(width, height, pixels):
    width, height = int(width), int(height)
    expected = width * height * 4
    if width < 0 or height < 0 or width * height > MAX_PIXEL_COUNT:
        raise _core.error("Image exceeds NovaGame's pixel memory limit")
    if len(pixels) != expected:
        raise ValueError("RGBA image data has the wrong size")
    surface = Surface((width, height), SRCALPHA)
    surface._pixels = bytearray(pixels)
    surface._pixel_dirty = True
    surface._cmds = []
    surface._snap = None
    surface._img = None
    return surface


def _guess_suffix(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if data.startswith(b"\xff\xd8"): return ".jpg"
    if data.startswith(b"GIF8"): return ".gif"
    if data.startswith(b"BM"): return ".bmp"
    return ".img"


def _decode_bytes(data, suffix=None):
    """Decode image bytes to top-down RGBA without relying on a GL context."""
    suffix = suffix or _guess_suffix(data)
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXEL_COUNT:
                raise _core.error("Image exceeds NovaGame's pixel memory limit")
            image.load()
            image = image.convert("RGBA")
            return image.width, image.height, image.tobytes()
    except _core.error:
        raise
    except Exception as pillow_error:
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(data)
                path = handle.name
            width, height, pixels = _load_image_pixels(path)
            return width, height, pixels
        except Exception as fallback_error:
            raise _core.error("Unable to decode image data: %s (%s)" %
                              (pillow_error, fallback_error))
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def load(filename, namehint=""):
    """Load an image path, bytes object, or readable binary file object."""
    if isinstance(filename, (bytes, bytearray, memoryview)):
        data = bytes(filename)
        suffix = str(namehint or _guess_suffix(data))
        width, height, pixels = _decode_bytes(data, suffix)
        return _surface_from_rgba(width, height, pixels)

    if hasattr(filename, "read"):
        data = filename.read()
        if isinstance(data, str):
            raise TypeError("image file object must be opened in binary mode")
        filename_hint = getattr(filename, "name", "")
        suffix = str(namehint or os.path.splitext(str(filename_hint))[1] or _guess_suffix(bytes(data)))
        width, height, pixels = _decode_bytes(bytes(data), suffix)
        return _surface_from_rgba(width, height, pixels)

    path = os.path.abspath(os.fspath(filename))
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "No file '%s' found in working directory '%s'." % (filename, os.getcwd()))
    # Validate the image header here; pixel decode and GPU texture upload remain
    # lazy for path-based loads so ordinary image blits stay inexpensive.
    with open(path, "rb") as handle:
        head = handle.read(32)
    if not (head[:8] == b"\x89PNG\r\n\x1a\n" or head[:4] == b"GIF8" or
            head[:2] == b"BM" or head[:2] == b"\xff\xd8"):
        raise _core.error("Unsupported image format: " + path)
    try:
        width, height = _image_size(path)
    except Exception as exc:
        raise _core.error("Unable to read image: %s" % exc)
    surface = Surface((width, height), SRCALPHA)
    surface._cmds = [("img", path, 0, 0, width, height, None)]
    surface._img = (path, None)
    return surface


load_extended = load


def _png_chunk(kind, payload):
    checksum = binascii.crc32(kind + payload) & 0xffffffff
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _write_png(surface, fileobj):
    width, height = surface.get_size()
    if width <= 0 or height <= 0:
        raise ValueError("PNG images must have positive width and height")
    pixels = surface._pixel_data()
    row_bytes = width * 4
    raw = bytearray()
    for y in range(height):
        start = y * row_bytes
        raw.append(0)  # PNG filter: None
        raw.extend(pixels[start:start + row_bytes])
    fileobj.write(b"\x89PNG\r\n\x1a\n")
    fileobj.write(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
    compressed = zlib.compress(bytes(raw), 6)
    fileobj.write(_png_chunk(b"IDAT", compressed))
    fileobj.write(_png_chunk(b"IEND", b""))


def save(surface, filename, namehint=""):
    """Save a Surface. PNG is always supported; Pillow enables other formats."""
    if not isinstance(surface, Surface):
        raise TypeError("image.save expects a Surface")
    fileobj = filename if hasattr(filename, "write") else None
    path = None if fileobj is not None else os.fspath(filename)
    ext = (str(namehint) or os.path.splitext(str(path or getattr(fileobj, "name", "")))[1]).lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    if ext in ("", ".png"):
        if fileobj is not None:
            _write_png(surface, fileobj)
        else:
            with open(path, "wb") as handle:
                _write_png(surface, handle)
        return
    try:
        from PIL import Image as _PILImage
    except Exception as exc:
        raise _core.error("Saving %s requires Pillow; PNG saving is built in" % ext) from exc
    width, height = surface.get_size()
    image = _PILImage.frombytes("RGBA", (width, height), bytes(surface._pixel_data()))
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP", ".gif": "GIF"}.get(ext)
    if fmt is None:
        raise _core.error("Unsupported output image format: " + ext)
    if fmt == "JPEG":
        image = image.convert("RGB")
    if fileobj is not None:
        image.save(fileobj, format=fmt)
    else:
        image.save(path, format=fmt)


def tostring(surface, format, flipped=False):
    fmt = str(format).upper()
    if fmt not in ("RGB", "RGBA", "ARGB", "BGRA", "RGBX"):
        raise ValueError("unsupported image byte format: " + fmt)
    width, height = surface.get_size()
    pixels = surface._pixel_data()
    rows = range(height - 1, -1, -1) if flipped else range(height)
    result = bytearray()
    for y in rows:
        for x in range(width):
            i = (y * width + x) * 4
            r, g, b, a = pixels[i:i+4]
            if fmt == "RGB": result.extend((r, g, b))
            elif fmt == "RGBA": result.extend((r, g, b, a))
            elif fmt == "ARGB": result.extend((a, r, g, b))
            elif fmt == "BGRA": result.extend((b, g, r, a))
            else: result.extend((r, g, b, 255))
    return bytes(result)


tobytes = tostring


def fromstring(data, size, format, flipped=False):
    fmt = str(format).upper()
    if fmt not in ("RGB", "RGBA", "ARGB", "BGRA", "RGBX"):
        raise ValueError("unsupported image byte format: " + fmt)
    width, height = int(size[0]), int(size[1])
    if width < 0 or height < 0:
        raise ValueError("image size must be non-negative")
    if width * height > MAX_PIXEL_COUNT:
        raise _core.error("Image exceeds NovaGame's pixel memory limit")
    channels = 3 if fmt == "RGB" else 4
    raw = bytes(data)
    if len(raw) != width * height * channels:
        raise ValueError("byte data length does not match image size")
    pixels = bytearray(width * height * 4)
    source_rows = range(height - 1, -1, -1) if flipped else range(height)
    cursor = 0
    for y in source_rows:
        for x in range(width):
            if fmt == "RGB": r, g, b = raw[cursor:cursor+3]; a = 255
            elif fmt == "RGBA": r, g, b, a = raw[cursor:cursor+4]
            elif fmt == "ARGB": a, r, g, b = raw[cursor:cursor+4]
            elif fmt == "BGRA": b, g, r, a = raw[cursor:cursor+4]
            else: r, g, b, _x = raw[cursor:cursor+4]; a = 255
            cursor += channels
            dst = (y * width + x) * 4
            pixels[dst:dst+4] = bytes((r, g, b, a))
    return _surface_from_rgba(width, height, pixels)


frombytes = fromstring
frombuffer = fromstring


def get_extended():
    return True
'''

# ----------------------------------------------------------------------
# pygame.transform
# ----------------------------------------------------------------------
_SOURCES['transform'] = r'''"""pygame.transform: scale, rotate and flip are applied when the frame is drawn."""

import math as _m

from . import _core
from .constants import SRCALPHA
from .surface import Surface


def _wrap(surface, width, height, angle=0, sx=1, sy=1):
    out = Surface((max(0, width), max(0, height)), SRCALPHA)
    out._cmds = []
    snap = surface._snapshot()
    if snap and surface._w > 0 and surface._h > 0 and width > 0 and height > 0:
        out._cmds.append(("group", snap, width / 2.0, height / 2.0,
                          surface._w, surface._h, angle, sx, sy,
                          surface._alpha, surface._colorkey))
    return out


def scale(surface, size, dest_surface=None):
    width, height = int(size[0]), int(size[1])
    out = _wrap(surface, width, height,
                0, width / float(surface._w or 1), height / float(surface._h or 1))
    if dest_surface is not None:
        dest_surface._cmds = out._cmds
        dest_surface._snap = None
        return dest_surface
    return out


def smoothscale(surface, size, dest_surface=None):
    """Bilinearly resize a Surface into a new RGBA pixel buffer."""
    width, height = int(size[0]), int(size[1])
    if width < 0 or height < 0:
        raise ValueError("smoothscale size must be non-negative")
    if width * height > 8 * 1024 * 1024:
        raise _core.error("smoothscale output exceeds NovaGame's pixel limit")
    out = Surface((width, height), SRCALPHA)
    if width and height and surface._w and surface._h:
        source = surface._pixel_data()
        target = bytearray(width * height * 4)
        for y in range(height):
            fy = max(0.0, min(surface._h - 1.0,
                              (y + 0.5) * surface._h / float(height) - 0.5))
            y0 = int(_m.floor(fy))
            y1 = min(surface._h - 1, y0 + 1)
            wy = fy - y0
            for x in range(width):
                fx = max(0.0, min(surface._w - 1.0,
                                  (x + 0.5) * surface._w / float(width) - 0.5))
                x0 = int(_m.floor(fx))
                x1 = min(surface._w - 1, x0 + 1)
                wx = fx - x0
                i00 = (y0 * surface._w + x0) * 4
                i10 = (y0 * surface._w + x1) * 4
                i01 = (y1 * surface._w + x0) * 4
                i11 = (y1 * surface._w + x1) * 4
                oi = (y * width + x) * 4
                for channel in range(4):
                    top = source[i00 + channel] * (1.0 - wx) + source[i10 + channel] * wx
                    bottom = source[i01 + channel] * (1.0 - wx) + source[i11 + channel] * wx
                    target[oi + channel] = max(0, min(255, int(
                        top * (1.0 - wy) + bottom * wy + 0.5)))
        out._pixels = target
        out._pixel_dirty = True
        out._cmds = []
    if dest_surface is not None:
        if dest_surface.get_size() != (width, height):
            raise ValueError("destination Surface has the wrong size")
        dest_surface._pixels = bytearray(out._pixel_data())
        dest_surface._pixel_dirty = True
        dest_surface._cmds = []
        dest_surface._snap = None
        dest_surface._img = None
        dest_surface._revision += 1
        return dest_surface
    return out


def scale_by(surface, factor, dest_surface=None):
    fx, fy = (factor, factor) if isinstance(factor, (int, float)) else factor
    return scale(surface, (int(surface._w * fx), int(surface._h * fy)), dest_surface)


def smoothscale_by(surface, factor, dest_surface=None):
    fx, fy = (factor, factor) if isinstance(factor, (int, float)) else factor
    return smoothscale(surface, (int(surface._w * fx), int(surface._h * fy)), dest_surface)


def flip(surface, flip_x, flip_y):
    return _wrap(surface, surface._w, surface._h, 0,
                 -1 if flip_x else 1, -1 if flip_y else 1)


def rotate(surface, angle):
    a = _m.radians(angle)
    c, s = abs(_m.cos(a)), abs(_m.sin(a))
    width = int(round(surface._w * c + surface._h * s))
    height = int(round(surface._w * s + surface._h * c))
    return _wrap(surface, width, height, angle)


def rotozoom(surface, angle, scale):
    a = _m.radians(angle)
    c, s = abs(_m.cos(a)), abs(_m.sin(a))
    w, h = surface._w * scale, surface._h * scale
    width = int(round(w * c + h * s))
    height = int(round(w * s + h * c))
    return _wrap(surface, width, height, angle, scale, scale)


def scale2x(surface, dest_surface=None):
    return scale(surface, (surface._w * 2, surface._h * 2), dest_surface)
'''


# ----------------------------------------------------------------------
# pygame.mask
# ----------------------------------------------------------------------
_SOURCES['mask'] = r'''"""pygame.mask: binary pixel masks and pixel-perfect overlap tests."""

import math as _m
from array import array as _array

from .rect import Rect
from .color import rgba
from .surface import Surface, _put

MAX_MASK_PIXELS = 8 * 1024 * 1024
MAX_COMPONENT_MASK_BYTES = 32 * 1024 * 1024


class Mask:
    def __init__(self, size, fill=False):
        width, height = int(size[0]), int(size[1])
        if width < 0 or height < 0:
            raise ValueError("invalid mask size")
        if width * height > MAX_MASK_PIXELS:
            raise MemoryError("mask is too large")
        self._w, self._h = width, height
        self._bits = bytearray([1 if fill else 0]) * (width * height)

    def get_size(self):
        return (self._w, self._h)

    def get_at(self, pos):
        x, y = int(pos[0]), int(pos[1])
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise IndexError("mask index out of range")
        return int(self._bits[y * self._w + x])

    def set_at(self, pos, value=1):
        x, y = int(pos[0]), int(pos[1])
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise IndexError("mask index out of range")
        self._bits[y * self._w + x] = 1 if value else 0

    def fill(self):
        self._bits[:] = b"\x01" * len(self._bits)

    def clear(self):
        self._bits[:] = b"\x00" * len(self._bits)

    def invert(self):
        for i, value in enumerate(self._bits):
            self._bits[i] = 0 if value else 1

    def count(self):
        return self._bits.count(1)

    def copy(self):
        other = Mask((self._w, self._h))
        other._bits[:] = self._bits
        return other

    def overlap(self, other, offset):
        ox, oy = int(offset[0]), int(offset[1])
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(self._w, ox + other._w), min(self._h, oy + other._h)
        if x0 >= x1 or y0 >= y1:
            return None
        for y in range(y0, y1):
            a = y * self._w + x0
            b = (y - oy) * other._w + (x0 - ox)
            for x in range(x1 - x0):
                if self._bits[a + x] and other._bits[b + x]:
                    return (x0 + x, y)
        return None

    def overlap_area(self, other, offset):
        ox, oy = int(offset[0]), int(offset[1])
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(self._w, ox + other._w), min(self._h, oy + other._h)
        total = 0
        if x0 >= x1 or y0 >= y1:
            return 0
        span = x1 - x0
        for y in range(y0, y1):
            a = y * self._w + x0
            b = (y - oy) * other._w + (x0 - ox)
            for x in range(span):
                total += bool(self._bits[a+x] and other._bits[b+x])
        return total

    def overlap_mask(self, other, offset):
        ox, oy = int(offset[0]), int(offset[1])
        result = Mask((self._w, self._h))
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(self._w, ox + other._w), min(self._h, oy + other._h)
        for y in range(y0, y1):
            a = y * self._w + x0
            b = (y - oy) * other._w + (x0 - ox)
            for x in range(x1 - x0):
                if self._bits[a+x] and other._bits[b+x]:
                    result._bits[a+x] = 1
        return result

    def draw(self, other, offset):
        ox, oy = int(offset[0]), int(offset[1])
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(self._w, ox + other._w), min(self._h, oy + other._h)
        for y in range(y0, y1):
            a = y * self._w + x0
            b = (y - oy) * other._w + (x0 - ox)
            for x in range(x1 - x0):
                if other._bits[b+x]:
                    self._bits[a+x] = 1

    def erase(self, other, offset):
        ox, oy = int(offset[0]), int(offset[1])
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(self._w, ox + other._w), min(self._h, oy + other._h)
        for y in range(y0, y1):
            a = y * self._w + x0
            b = (y - oy) * other._w + (x0 - ox)
            for x in range(x1 - x0):
                if other._bits[b+x]:
                    self._bits[a+x] = 0

    def outline(self, every=1):
        step = max(1, int(every))
        points = []
        boundary_index = 0
        for y in range(self._h):
            row = y * self._w
            for x in range(self._w):
                index = row + x
                if not self._bits[index]:
                    continue
                if (x == 0 or x == self._w-1 or y == 0 or y == self._h-1
                        or not self._bits[index-1] or not self._bits[index+1]
                        or not self._bits[index-self._w] or not self._bits[index+self._w]):
                    if boundary_index % step == 0:
                        points.append((x, y))
                    boundary_index += 1
        return points

    def centroid(self):
        count = sx = sy = 0
        for y in range(self._h):
            row = y * self._w
            for x in range(self._w):
                if self._bits[row+x]:
                    count += 1
                    sx += x
                    sy += y
        return (int(sx/count), int(sy/count)) if count else (-1, -1)

    def angle(self):
        count = sx = sy = 0
        for y in range(self._h):
            row = y * self._w
            for x in range(self._w):
                if self._bits[row+x]:
                    count += 1
                    sx += x
                    sy += y
        if count < 2:
            return 0.0
        cx, cy = sx / count, sy / count
        xx = yy = xy = 0.0
        for y in range(self._h):
            row = y * self._w
            for x in range(self._w):
                if self._bits[row+x]:
                    dx, dy = x-cx, y-cy
                    xx += dx*dx
                    yy += dy*dy
                    xy += dx*dy
        return _m.degrees(0.5 * _m.atan2(2*xy, xx-yy))

    def get_bounding_rects(self, threshold=1):
        """Return one bounding rectangle per 4-connected component."""
        minimum = max(1, int(threshold))
        seen = bytearray(len(self._bits))
        rects = []
        for start, value in enumerate(self._bits):
            if not value or seen[start]:
                continue
            stack = _array("I", [start])
            seen[start] = 1
            count = 0
            left = right = start % self._w
            top = bottom = start // self._w
            while stack:
                index = stack.pop()
                count += 1
                x, y = index % self._w, index // self._w
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
                for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                    if 0 <= nx < self._w and 0 <= ny < self._h:
                        ni = ny*self._w+nx
                        if self._bits[ni] and not seen[ni]:
                            seen[ni] = 1
                            stack.append(ni)
            if count >= minimum:
                rects.append(Rect(left, top, right-left+1, bottom-top+1))
        return rects

    def get_bounding_rect(self):
        left, top, right, bottom = self._w, self._h, -1, -1
        for y in range(self._h):
            row = y * self._w
            for x in range(self._w):
                if self._bits[row+x]:
                    left, top = min(left, x), min(top, y)
                    right, bottom = max(right, x), max(bottom, y)
        if right < left:
            return Rect(0, 0, 0, 0)
        return Rect(left, top, right-left+1, bottom-top+1)

    def connected_components(self, min=0):
        """Return separate 4-connected component masks, with a memory guard."""
        minimum = max(0, int(min))
        seen = bytearray(len(self._bits))
        components = []
        mask_bytes = len(self._bits)
        for start, value in enumerate(self._bits):
            if not value or seen[start]:
                continue
            stack = _array("I", [start])
            seen[start] = 1
            component_bits = bytearray(mask_bytes)
            component_bits[start] = 1
            count = 0
            while stack:
                index = stack.pop()
                count += 1
                x, y = index % self._w, index // self._w
                for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                    if 0 <= nx < self._w and 0 <= ny < self._h:
                        ni = ny*self._w+nx
                        if self._bits[ni] and not seen[ni]:
                            seen[ni] = 1
                            component_bits[ni] = 1
                            stack.append(ni)
            if count >= minimum:
                if (len(components) + 1) * mask_bytes > MAX_COMPONENT_MASK_BYTES:
                    raise MemoryError(
                        "connected_components() result exceeds NovaGame's memory limit")
                component = Mask((self._w, self._h))
                component._bits[:] = component_bits
                components.append(component)
        return components

    def connected_component(self, pos):
        x, y = int(pos[0]), int(pos[1])
        if not (0 <= x < self._w and 0 <= y < self._h) or not self._bits[y*self._w+x]:
            return Mask((self._w, self._h))
        result = Mask((self._w, self._h))
        start = y*self._w+x
        stack = _array("I", [start])
        result._bits[start] = 1
        while stack:
            index = stack.pop()
            px, py = index % self._w, index // self._w
            for nx, ny in ((px-1,py), (px+1,py), (px,py-1), (px,py+1)):
                if 0 <= nx < self._w and 0 <= ny < self._h:
                    ni = ny*self._w+nx
                    if self._bits[ni] and not result._bits[ni]:
                        result._bits[ni] = 1
                        stack.append(ni)
        return result

    def scale(self, size):
        nw, nh = max(0, int(size[0])), max(0, int(size[1]))
        out = Mask((nw, nh))
        if not self._w or not self._h or not nw or not nh:
            return out
        for y in range(nh):
            sy = min(self._h-1, int(y * self._h / nh))
            for x in range(nw):
                sx = min(self._w-1, int(x * self._w / nw))
                out._bits[y*nw+x] = self._bits[sy*self._w+sx]
        return out

    def to_surface(self, surface=None, setcolor=(255,255,255,255),
                   unsetcolor=None, dest=None):
        if surface is None:
            surface = Surface((self._w, self._h), 65536)
        ox, oy = (0, 0) if dest is None else (int(dest[0]), int(dest[1]))
        set_rgba = rgba(setcolor) if setcolor is not None else None
        unset_rgba = rgba(unsetcolor) if unsetcolor is not None else None
        pixels = surface._pixel_data()
        for y in range(self._h):
            x = 0
            while x < self._w:
                value = self._bits[y*self._w+x]
                color = set_rgba if value else unset_rgba
                run = x + 1
                while run < self._w and self._bits[y*self._w+run] == value:
                    run += 1
                if color is not None:
                    for px in range(x, run):
                        tx, ty = ox+px, oy+y
                        if 0 <= tx < surface._w and 0 <= ty < surface._h:
                            _put(pixels, surface._w, surface._h, tx, ty, color)
                x = run
        surface._pixels = pixels
        surface._pixel_dirty = True
        surface._snap = None
        surface._img = None
        surface._revision += 1
        return surface

    def __repr__(self):
        return "<Mask(%d, %d) set=%d>" % (self._w, self._h, self.count())


def from_surface(surface, threshold=127):
    mask = Mask(surface.get_size())
    pixels = surface._pixel_data()
    key = surface._colorkey
    threshold = int(threshold)
    for y in range(surface._h):
        for x in range(surface._w):
            index = (y*surface._w+x)*4
            r, g, b, a = pixels[index:index+4]
            opaque = ((r, g, b) != key) if key is not None else (a > threshold)
            if opaque:
                mask._bits[y*surface._w+x] = 1
    return mask


def from_threshold(surface, color, threshold=(0,0,0,0), othersurface=None,
                   palette_colors=1):
    target = tuple(color) if hasattr(color, "__iter__") else (color,)
    if len(target) == 3:
        target = target + (255,)
    target = tuple(int(v) for v in target[:4])
    if isinstance(threshold, (int, float)):
        limits = (int(threshold),) * 4
    else:
        limits = tuple(int(v) for v in threshold)
        if len(limits) == 3:
            limits += (255,)
        if len(limits) < 4:
            limits = limits + (0,) * (4-len(limits))
    first = surface._pixel_data()
    second = othersurface._pixel_data() if othersurface is not None else None
    if othersurface is not None and othersurface.get_size() != surface.get_size():
        raise ValueError("surfaces must have the same size")
    mask = Mask(surface.get_size())
    for index in range(surface._w * surface._h):
        p = tuple(first[index*4:index*4+4])
        if second is not None:
            q = tuple(second[index*4:index*4+4])
            candidate = tuple(abs(p[i]-q[i]) for i in range(4))
        else:
            candidate = p
        if all(abs(candidate[i]-target[i]) <= max(0, limits[i]) for i in range(4)):
            mask._bits[index] = 1
    return mask
'''
# ----------------------------------------------------------------------
# pygame.sprite
# ----------------------------------------------------------------------
_SOURCES['sprite'] = r'''"""pygame.sprite: Sprite, groups and collision helpers."""

import math as _m

from .rect import Rect
from .mask import from_surface as _mask_from_surface


class Sprite:
    def __init__(self, *groups):
        self.image = getattr(self, "image", None)
        self.rect = getattr(self, "rect", None)
        if groups:
            self.add(*groups)

    def _g(self):
        return self.__dict__.setdefault("_groups", {})

    def add_internal(self, group):
        self._g()[group] = 0

    def remove_internal(self, group):
        self._g().pop(group, None)

    def add(self, *groups):
        for group in groups:
            if hasattr(group, "add_internal"):
                if not group.has_internal(self):
                    group.add_internal(self)
                    self.add_internal(group)
            else:
                self.add(*list(group))

    def remove(self, *groups):
        for group in groups:
            if hasattr(group, "remove_internal"):
                if group.has_internal(self):
                    group.remove_internal(self)
                    self.remove_internal(group)
            else:
                self.remove(*list(group))

    def kill(self):
        for group in list(self._g()):
            group.remove_internal(self)
        self._g().clear()

    def groups(self):
        return list(self._g())

    def alive(self):
        return bool(self._g())

    def update(self, *args, **kwargs):
        pass

    def __repr__(self):
        return "<%s Sprite(in %d groups)>" % (type(self).__name__, len(self._g()))


DirtySprite = Sprite


class AbstractGroup:
    def __init__(self):
        self.spritedict = {}

    def sprites(self):
        return list(self.spritedict)

    def add_internal(self, sprite, layer=None):
        self.spritedict[sprite] = None

    def remove_internal(self, sprite):
        self.spritedict.pop(sprite, None)

    def has_internal(self, sprite):
        return sprite in self.spritedict

    def add(self, *sprites):
        for sprite in sprites:
            if isinstance(sprite, Sprite):
                if not self.has_internal(sprite):
                    self.add_internal(sprite)
                    sprite.add_internal(self)
            else:
                try:
                    items = list(sprite)
                except TypeError:
                    raise TypeError("Sprite groups can only hold Sprites, got %r"
                                    % (sprite,))
                self.add(*items)

    def remove(self, *sprites):
        for sprite in sprites:
            if isinstance(sprite, Sprite):
                if self.has_internal(sprite):
                    self.remove_internal(sprite)
                    sprite.remove_internal(self)
            else:
                self.remove(*list(sprite))

    def has(self, *sprites):
        for sprite in sprites:
            if isinstance(sprite, Sprite):
                if not self.has_internal(sprite):
                    return False
            elif not self.has(*list(sprite)):
                return False
        return True

    def update(self, *args, **kwargs):
        for sprite in self.sprites():
            sprite.update(*args, **kwargs)

    def draw(self, surface, bgsurf=None, special_flags=0):
        rects = []
        for sprite in self.sprites():
            if sprite.image is None or sprite.rect is None:
                continue
            rects.append(surface.blit(sprite.image, sprite.rect))
            self.spritedict[sprite] = Rect(sprite.rect)
        return rects

    def clear(self, surface, bgd):
        for sprite in self.sprites():
            rect = self.spritedict.get(sprite) or sprite.rect
            if rect is None:
                continue
            if callable(bgd):
                bgd(surface, rect)
            else:
                surface.blit(bgd, rect, rect)

    def empty(self):
        for sprite in self.sprites():
            self.remove_internal(sprite)
            sprite.remove_internal(self)

    def copy(self):
        return type(self)(*self.sprites())

    def __iter__(self):
        return iter(self.sprites())

    def __len__(self):
        return len(self.spritedict)

    def __bool__(self):
        return len(self.spritedict) > 0

    def __contains__(self, sprite):
        return self.has(sprite)

    def __repr__(self):
        return "<%s(%d sprites)>" % (type(self).__name__, len(self))


class Group(AbstractGroup):
    def __init__(self, *sprites):
        AbstractGroup.__init__(self)
        self.add(*sprites)


RenderPlain = Group
RenderClear = Group


class RenderUpdates(Group):
    def draw(self, surface, bgsurf=None, special_flags=0):
        return Group.draw(self, surface, bgsurf, special_flags)


class OrderedUpdates(RenderUpdates):
    pass


class GroupSingle(AbstractGroup):
    def __init__(self, sprite=None):
        AbstractGroup.__init__(self)
        if sprite is not None:
            self.add(sprite)

    def add_internal(self, sprite, layer=None):
        for old in list(self.spritedict):
            old.remove_internal(self)
        self.spritedict.clear()
        self.spritedict[sprite] = None

    @property
    def sprite(self):
        for sprite in self.spritedict:
            return sprite
        return None


class LayeredUpdates(AbstractGroup):
    def __init__(self, *sprites, **kwargs):
        AbstractGroup.__init__(self)
        self._layers = {}
        self._default_layer = kwargs.get("default_layer", 0)
        self.add(*sprites, **kwargs)

    def add_internal(self, sprite, layer=None):
        if layer is None:
            layer = getattr(sprite, "_layer", self._default_layer)
        self._layers[sprite] = layer
        sprite._layer = layer
        self.spritedict[sprite] = None

    def remove_internal(self, sprite):
        self._layers.pop(sprite, None)
        self.spritedict.pop(sprite, None)

    def add(self, *sprites, **kwargs):
        layer = kwargs.get("layer")
        for sprite in sprites:
            if isinstance(sprite, Sprite):
                if not self.has_internal(sprite):
                    self.add_internal(sprite, layer)
                    sprite.add_internal(self)
            else:
                self.add(*list(sprite), **kwargs)

    def sprites(self):
        order = list(self.spritedict)
        return sorted(order, key=lambda s: self._layers.get(s, 0))

    def get_layer_of_sprite(self, sprite):
        return self._layers.get(sprite, self._default_layer)

    def change_layer(self, sprite, new_layer):
        if sprite in self._layers:
            self._layers[sprite] = new_layer
            sprite._layer = new_layer

    def get_sprites_from_layer(self, layer):
        return [s for s in self.sprites() if self._layers.get(s) == layer]

    def layers(self):
        return sorted(set(self._layers.values()))

    def get_top_layer(self):
        return max(self._layers.values())

    def get_bottom_layer(self):
        return min(self._layers.values())

    def move_to_front(self, sprite):
        self.change_layer(sprite, self.get_top_layer())

    def move_to_back(self, sprite):
        self.change_layer(sprite, self.get_bottom_layer() - 1)

    def get_top_sprite(self):
        return self.sprites()[-1]

    def get_sprites_at(self, pos):
        return [s for s in self.sprites() if s.rect and s.rect.collidepoint(pos)]


# -- collisions --------------------------------------------------------------
def collide_rect(left, right):
    return left.rect.colliderect(right.rect)


class collide_rect_ratio:
    def __init__(self, ratio):
        self.ratio = ratio

    def __call__(self, left, right):
        def scaled(rect):
            return rect.inflate(rect.w * (self.ratio - 1), rect.h * (self.ratio - 1))
        return scaled(left.rect).colliderect(scaled(right.rect))


def _radius(sprite):
    if hasattr(sprite, "radius"):
        return sprite.radius
    rect = sprite.rect
    return _m.hypot(rect.w, rect.h) / 2.0


def collide_circle(left, right):
    dx = left.rect.centerx - right.rect.centerx
    dy = left.rect.centery - right.rect.centery
    return dx * dx + dy * dy <= (_radius(left) + _radius(right)) ** 2


class collide_circle_ratio:
    def __init__(self, ratio):
        self.ratio = ratio

    def __call__(self, left, right):
        dx = left.rect.centerx - right.rect.centerx
        dy = left.rect.centery - right.rect.centery
        return dx * dx + dy * dy <= ((_radius(left) + _radius(right)) * self.ratio) ** 2


def collide_mask(left, right):
    """Pixel-perfect collision; returns the first overlap point or None."""
    if left.rect is None or right.rect is None or not left.rect.colliderect(right.rect):
        return None
    left_mask = getattr(left, "mask", None)
    right_mask = getattr(right, "mask", None)
    if left_mask is None:
        image = getattr(left, "image", None)
        if image is None:
            return None
        cache = getattr(left, "_novagame_mask_cache", None)
        revision = getattr(image, "_revision", None)
        if cache is None or cache[0] is not image or cache[1] != revision:
            cache = (image, revision, _mask_from_surface(image))
            left._novagame_mask_cache = cache
        left_mask = cache[2]
    if right_mask is None:
        image = getattr(right, "image", None)
        if image is None:
            return None
        cache = getattr(right, "_novagame_mask_cache", None)
        revision = getattr(image, "_revision", None)
        if cache is None or cache[0] is not image or cache[1] != revision:
            cache = (image, revision, _mask_from_surface(image))
            right._novagame_mask_cache = cache
        right_mask = cache[2]
    offset = (int(right.rect.x - left.rect.x), int(right.rect.y - left.rect.y))
    return left_mask.overlap(right_mask, offset)


def spritecollide(sprite, group, dokill, collided=None):
    check = collided or collide_rect
    hits = [other for other in group.sprites() if check(sprite, other)]
    if dokill:
        for other in hits:
            other.kill()
    return hits


def groupcollide(group1, group2, dokill1, dokill2, collided=None):
    result = {}
    for sprite in group1.sprites():
        hits = spritecollide(sprite, group2, dokill2, collided)
        if hits:
            result[sprite] = hits
            if dokill1:
                sprite.kill()
    return result


def spritecollideany(sprite, group, collided=None):
    check = collided or collide_rect
    for other in group.sprites():
        if check(sprite, other):
            return other
    return None
'''

# ----------------------------------------------------------------------
# pygame.mixer
# ----------------------------------------------------------------------
_SOURCES['mixer'] = r'''"""Kivy-backed pygame.mixer compatibility."""

import os as _os
import sys as _sys
import tempfile as _tempfile

from . import _core

_initialized = [True]
_frequency = [44100]
_size = [-16]
_channels_count = [2]
_master_volume = [1.0]
_channels = []
_sounds = set()
_temp_paths = set()


def _host():
    host = _core.host
    if host is None or not hasattr(host, "audio_load"):
        raise _core.error("Audio playback is unavailable: pygame_host audio support is missing")
    return host


def _path_for_source(source, buffer=None, suffix=None):
    if buffer is not None:
        raw = bytes(buffer)
        suffix = suffix or ".wav"
        path = None
        try:
            with _tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(raw)
                path = handle.name
            _temp_paths.add(path)
            return path
        except Exception:
            if path:
                try: _os.unlink(path)
                except OSError: pass
            raise
    if hasattr(source, "read"):
        raw = source.read()
        suffix = _os.path.splitext(str(getattr(source, "name", "")))[1] or ".wav"
        return _path_for_source(None, raw, suffix=suffix)
    if source is None:
        raise TypeError("Sound requires a filename or buffer")
    return _os.path.abspath(_os.fspath(source))


def init(frequency=None, size=None, channels=None, buffer=512, devicename=None):
    _frequency[0] = int(_frequency[0] if frequency is None else frequency)
    _size[0] = int(_size[0] if size is None else size)
    _channels_count[0] = max(1, int(_channels_count[0] if channels is None else channels))
    _initialized[0] = True
    set_num_channels(8)


def pre_init(frequency=44100, size=-16, channels=2, buffer=512, devicename=None):
    _frequency[0], _size[0], _channels_count[0] = int(frequency), int(size), int(channels)


def quit():
    _initialized[0] = False
    music.unload()
    for channel in list(_channels):
        channel.stop()
    for sound in list(_sounds):
        sound._unload()
    for path in list(_temp_paths):
        try: _os.unlink(path)
        except OSError: pass
    _temp_paths.clear()


def get_init():
    return (_frequency[0], _size[0], _channels_count[0]) if _initialized[0] else None


def set_num_channels(count):
    count = max(0, int(count))
    while len(_channels) < count:
        _channels.append(Channel(len(_channels)))
    while len(_channels) > count:
        _channels.pop().stop()


def get_num_channels():
    return len(_channels)


def set_reserved(count):
    pass


def stop():
    for channel in list(_channels): channel.stop()


def pause():
    for channel in list(_channels): channel.pause()


def unpause():
    for channel in list(_channels): channel.unpause()


def fadeout(milliseconds):
    for channel in list(_channels): channel.fadeout(milliseconds)


def get_busy():
    return any(channel.get_busy() for channel in _channels)


class Channel:
    def __new__(cls, id=0):
        try:
            index = int(id)
            if 0 <= index < len(_channels) and isinstance(_channels[index], cls):
                return _channels[index]
        except Exception:
            pass
        return super().__new__(cls)

    def __init__(self, id=0):
        if getattr(self, "_channel_initialized", False):
            return
        self.id = int(id)
        self._sound = None
        self._handle = None
        self._owns_handle = False
        self._volume = 1.0
        self._paused = False
        self._channel_initialized = True

    def play(self, sound, loops=0, maxtime=0, fade_ms=0):
        if not _initialized[0]:
            raise _core.error("mixer not initialized")
        if not isinstance(sound, Sound):
            raise TypeError("Channel.play expects a mixer.Sound")
        self.stop()
        host = _host()
        # pygame allows one Sound to play on several channels simultaneously.
        # Kivy Sound instances represent one playback, so give overlapping
        # channels their own provider instance while keeping the first on the
        # Sound's reusable base handle.
        already_active = any(
            channel is not self and channel._handle is not None and
            (channel._paused or host.audio_is_busy(channel._handle))
            for channel in list(sound._channels)
        )
        handle = host.audio_load(sound._path) if already_active else sound._handle
        if handle is None:
            raise _core.error("Unable to create an audio playback channel")
        self._sound = sound
        self._handle = handle
        self._owns_handle = handle is not sound._handle
        sound._channels.add(self)
        volume = max(0.0, min(1.0, sound._volume * self._volume * _master_volume[0]))
        try:
            host.audio_set_volume(handle, volume)
            host.audio_play(handle, loops=int(loops), maxtime=int(maxtime),
                            fade_ms=int(fade_ms), start=0.0)
        except Exception:
            sound._channels.discard(self)
            if self._owns_handle:
                try: host.audio_unload(handle)
                except Exception: pass
            self._sound = None
            self._handle = None
            self._owns_handle = False
            raise
        self._paused = False
        return self

    def stop(self):
        if self._sound is not None:
            handle = self._handle
            try:
                if handle is not None:
                    _host().audio_stop(handle)
                    if self._owns_handle:
                        _host().audio_unload(handle)
            except Exception:
                pass
            self._sound._channels.discard(self)
        self._sound = None
        self._handle = None
        self._owns_handle = False
        self._paused = False

    def pause(self):
        if self._handle is not None:
            _host().audio_pause(self._handle)
            self._paused = True

    def unpause(self):
        if self._handle is not None and self._paused:
            _host().audio_unpause(self._handle)
            self._paused = False

    def set_volume(self, *volume):
        if not volume: return
        self._volume = max(0.0, min(1.0, sum(float(v) for v in volume) / len(volume)))
        if self._handle is not None and self._sound is not None:
            _host().audio_set_volume(self._handle,
                self._volume * self._sound._volume * _master_volume[0])

    def get_volume(self):
        return self._volume

    def get_busy(self):
        if self._handle is None: return False
        return _host().audio_is_busy(self._handle)

    def get_sound(self):
        return self._sound

    def get_queue(self):
        return None

    def fadeout(self, milliseconds):
        if self._handle is not None:
            _host().audio_fadeout(self._handle, int(milliseconds))

    def get_id(self):
        return self.id


class Sound:
    def __init__(self, file=None, buffer=None):
        if not _initialized[0]:
            raise _core.error("mixer not initialized")
        self._path = _path_for_source(file, buffer)
        self._volume = 1.0
        self._channels = set()
        self._handle = _host().audio_load(self._path)
        if self._handle is None:
            raise _core.error("Unable to load audio file: " + self._path)
        _sounds.add(self)

    def play(self, loops=0, maxtime=0, fade_ms=0):
        channel = find_channel()
        if channel is None:
            return None
        return channel.play(self, loops, maxtime, fade_ms)

    def stop(self):
        for channel in list(self._channels): channel.stop()
        if not self._channels:
            _host().audio_stop(self._handle)

    def fadeout(self, milliseconds):
        for channel in list(self._channels): channel.fadeout(milliseconds)

    def set_volume(self, value):
        self._volume = max(0.0, min(1.0, float(value)))
        for channel in list(self._channels):
            channel.set_volume(channel._volume)

    def get_volume(self):
        return self._volume

    def get_length(self):
        return float(_host().audio_length(self._handle))

    def get_num_channels(self):
        return sum(1 for channel in self._channels if channel.get_busy())

    def get_raw(self):
        try:
            with open(self._path, "rb") as handle: return handle.read()
        except OSError:
            return b""

    def _unload(self):
        for channel in list(self._channels): channel.stop()
        if self._handle is not None:
            try: _host().audio_unload(self._handle)
            except Exception: pass
            self._handle = None
        _sounds.discard(self)


_channels[:] = [Channel(i) for i in range(8)]


def find_channel(force=False):
    for channel in _channels:
        if not channel.get_busy():
            return channel
    return _channels[0] if force and _channels else None


def set_volume(value):
    _master_volume[0] = max(0.0, min(1.0, float(value)))
    for channel in _channels:
        if channel._sound is not None:
            channel.set_volume(channel._volume)


def get_sdl_mixer_version(linked=True):
    return (2, 6, 0)


def get_sdl_audio_driver():
    return "kivy"


class _Music:
    def __init__(self):
        self._sound = None
        self._channel = Channel(-1)
        self._volume = 1.0
        self._queue_sound = None
        self._queue_loops = 0

    def load(self, filename, namehint=""):
        self.stop()
        if self._sound is not None: self._sound._unload()
        if self._queue_sound is not None: self._queue_sound._unload()
        self._queue_sound = None
        self._sound = Sound(filename)
        self._sound.set_volume(self._volume)

    def unload(self):
        self.stop()
        if self._sound is not None:
            self._sound._unload()
            self._sound = None
        if self._queue_sound is not None:
            self._queue_sound._unload()
            self._queue_sound = None

    def _play_queued(self):
        queued = self._queue_sound
        if queued is None:
            return
        loops = self._queue_loops
        old = self._sound
        self._queue_sound = None
        self._sound = queued
        self._sound.set_volume(self._volume)
        self._channel.play(self._sound, loops=loops)
        if old is not None and old is not queued:
            old._unload()
        if self._queue_sound is not None and self._channel._handle is not None:
            _host().audio_set_on_complete(self._channel._handle, self._play_queued)

    def play(self, loops=0, start=0.0, fade_ms=0):
        if self._sound is None:
            raise _core.error("music.load() must be called before music.play()")
        self._channel.play(self._sound, loops=loops, fade_ms=fade_ms)
        if self._channel._handle is not None:
            _host().audio_set_on_complete(
                self._channel._handle,
                self._play_queued if self._queue_sound is not None else None)
            if start:
                _host().audio_seek(self._channel._handle, float(start))

    def stop(self):
        if self._channel._handle is not None:
            try: _host().audio_set_on_complete(self._channel._handle, None)
            except Exception: pass
        self._channel.stop()

    def pause(self):
        self._channel.pause()

    def unpause(self):
        self._channel.unpause()

    def rewind(self):
        if self._sound is not None:
            self._channel.stop()
            self.play()

    def fadeout(self, milliseconds):
        self._channel.fadeout(milliseconds)

    def set_volume(self, value):
        self._volume = max(0.0, min(1.0, float(value)))
        if self._sound is not None:
            self._sound.set_volume(self._volume)

    def get_volume(self):
        return self._volume

    def get_busy(self):
        return self._channel.get_busy()

    def get_pos(self):
        if self._sound is None or self._channel._handle is None or not self.get_busy(): return -1
        return int(_host().audio_position(self._channel._handle) * 1000)

    def set_pos(self, pos):
        if self._channel._handle is not None:
            _host().audio_seek(self._channel._handle, float(pos))

    def queue(self, filename, namehint="", loops=0):
        if self._queue_sound is not None:
            self._queue_sound._unload()
        self._queue_sound = Sound(filename)
        self._queue_sound.set_volume(self._volume)
        self._queue_loops = int(loops)
        if self._sound is not None and self._channel._handle is not None and self.get_busy():
            _host().audio_set_on_complete(self._channel._handle, self._play_queued)


music = _Music()
_sys.modules[__name__ + ".music"] = music
'''

# ----------------------------------------------------------------------
# pygame.version
# ----------------------------------------------------------------------
_SOURCES['version'] = r'''"""pygame.version"""

from collections import namedtuple

_Version = namedtuple("PygameVersion", "major minor patch")

ver = "2.6.1"
vernum = _Version(2, 6, 1)
rev = ""
SDL = _Version(2, 30, 0)
'''

# ----------------------------------------------------------------------
# pygame.locals
# ----------------------------------------------------------------------
_SOURCES['locals'] = r'''"""pygame.locals: constants and the commonly star-imported names."""

from .constants import *  # noqa: F401,F403
from .color import Color  # noqa: F401
from .rect import Rect  # noqa: F401
from .surface import Surface  # noqa: F401
'''


_ORDER = ['_core', 'constants', 'color', 'rect', 'math', 'surface', 'draw', 'event', 'key', 'mouse', 'time', 'display', 'font', 'image', 'transform', 'mask', 'sprite', 'mixer', 'version', 'locals']
_self = _sys.modules[__name__]


def _load_submodules():
    for _name in _ORDER:
        _full = "pygame." + _name
        _mod = _types.ModuleType(_full)
        _mod.__package__ = "pygame"
        _mod.__file__ = "pygame.py[%s]" % _name
        _source = _SOURCES[_name]
        _linecache.cache[_mod.__file__] = (
            len(_source), None, _source.splitlines(True), _mod.__file__)
        _sys.modules[_full] = _mod
        setattr(_self, _name, _mod)
        exec(compile(_source, _mod.__file__, "exec"), _mod.__dict__)


_load_submodules()

from pygame._core import error  # noqa: E402
from pygame.constants import *  # noqa: E402,F401,F403
from pygame.rect import Rect  # noqa: E402
from pygame.color import Color  # noqa: E402
from pygame.surface import Surface  # noqa: E402
from pygame.math import Vector2, Vector3  # noqa: E402

__version__ = version.ver
IDE_LAYER = True          # True when running on the IDE's pygame layer

_quit_callbacks = []


def init():
    _core.start_time = _time.perf_counter()
    _core.initialized = True
    display.init()
    font.init()
    mixer.init()
    return (6, 0)


def quit():
    _core.initialized = False
    display.quit()
    font.quit()
    mixer.quit()
    for callback in list(_quit_callbacks):
        callback()


def get_init():
    return _core.initialized


def register_quit(callback):
    _quit_callbacks.append(callback)


def get_error():
    return ""


def set_error(message):
    pass


def get_sdl_version(linked=True):
    return tuple(version.SDL)


def get_sdl_byteorder():
    return 1234
