"""A pygame-compatible layer for the IDE, in a single file.

Put this file next to main.py. It acts as the whole `pygame` package: `import
pygame`, `import pygame.draw` and `from pygame.locals import *` all work.

It runs on Kivy and has no native code. Surfaces are recorded as drawing
commands and replayed on the IDE's game screen (pygame_host.py) when
display.flip() is called.

Supported: Rect, Color, Surface (fill/blit/convert/subsurface, colorkey, alpha),
draw (rect, circle, ellipse, line(s), polygon, arc), display, event, key,
mouse (first finger), time (Clock, set_timer), font (Font, SysFont), image.load
(PNG/JPG/GIF/BMP from the workspace), transform (scale, rotate, flip), sprite,
math (Vector2/Vector3).

Not supported: pixel access (get_at), masks, sound (silent stubs), joysticks,
clipping to blit areas of drawn (non-image) surfaces, fullscreen/resizing.
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
_SOURCES['surface'] = r'''"""pygame.Surface, recorded as a list of draw commands.

Instead of pixels, a Surface keeps the commands that were drawn on it. The IDE's
game screen replays them with Kivy when display.flip() is called. A full
fill() clears the history, so games that redraw every frame stay small.

Command formats (colours are (r, g, b, a) int tuples):
  ("fill", color)
  ("rect", color, x, y, w, h, width, radius)
  ("ellipse", color, x, y, w, h, width)
  ("circle", color, cx, cy, r, width)
  ("line", color, x1, y1, x2, y2, width)
  ("lines", color, points, closed, width)
  ("polygon", color, points, width)
  ("arc", color, x, y, w, h, start, stop, width)
  ("text", color, fontkey, text, x, y)
  ("img", path, x, y, w, h, region)
  ("group", commands, cx, cy, w, h, angle, sx, sy, alpha, colorkey)
"""

from . import _core
from .color import rgba
from .constants import SRCALPHA
from .rect import Rect


def _pos(dest):
    if isinstance(dest, Rect):
        return dest.x, dest.y
    return dest[0], dest[1]


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
        self._colorkey = None
        self._alpha = None
        self._img = None          # (absolute path, region or None) for loaded images
        self._clip = None
        self._is_display = False

    # -- command recording ----------------------------------------------------
    def _add(self, command):
        cmds = self._cmds
        cmds.append(command)
        self._snap = None
        if len(cmds) > _core.MAX_COMMANDS:
            del cmds[:len(cmds) - _core.MAX_COMMANDS // 2]

    def _snapshot(self):
        if self._snap is None:
            self._snap = tuple(self._cmds)
        return self._snap

    # -- basic information ---------------------------------------------------
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

    def get_bounding_rect(self, min_alpha=1):
        return Rect(0, 0, self._w, self._h)

    def get_clip(self):
        return self._clip or Rect(0, 0, self._w, self._h)

    def set_clip(self, rect=None):
        self._clip = None if rect is None else Rect(rect)

    def lock(self):
        pass

    def unlock(self):
        pass

    def mustlock(self):
        return False

    def get_locked(self):
        return False

    # -- colour key / alpha ------------------------------------------------------
    def set_colorkey(self, color, flags=0):
        self._colorkey = None if color is None else rgba(color)[:3]

    def get_colorkey(self):
        return None if self._colorkey is None else self._colorkey + (255,)

    def set_alpha(self, value, flags=0):
        self._alpha = None if value is None else max(0, min(255, int(value)))

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
        return other

    __copy__ = copy

    # -- drawing ---------------------------------------------------------------------
    def fill(self, color, rect=None, special_flags=0):
        color = rgba(color)
        if rect is None:
            del self._cmds[:]
            self._snap = None
            if not (color[3] == 0 and self._srcalpha):
                self._cmds.append(("fill", color))
            return Rect(0, 0, self._w, self._h)
        rect = Rect(rect)
        self._add(("rect", color, rect.x, rect.y, rect.w, rect.h, 0, 0))
        return rect

    def blit(self, source, dest, area=None, special_flags=0):
        dx, dy = _pos(dest)
        if source._img is not None and source._alpha is None:
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
        self._add(("rect", rgba(color), pos[0], pos[1], 1, 1, 0, 0))

    def get_at(self, pos):
        raise _core.error(
            "get_at() isn't supported by the IDE's pygame layer "
            "(surfaces are recorded as drawing commands, not pixels)")

    def subsurface(self, *rect):
        rect = Rect(*rect)
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
        _core.notice("Surface.scroll() isn't supported and was ignored.")

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
_SOURCES['image'] = r'''"""pygame.image: loads files from the working folder (the IDE's workspace)."""

import os
import struct

from . import _core
from .constants import SRCALPHA
from .surface import Surface


def _image_size(path):
    """Read (width, height) from an image file header (PNG, JPEG, GIF, BMP)."""
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
                    height, width = struct.unpack(">HH", data[1:5])
                    return width, height
                handle.seek(length - 2, 1)
    raise _core.error("Unsupported image format (use PNG, JPG, GIF or BMP): " + path)


def load(filename, namehint=""):
    if hasattr(filename, "read"):
        raise _core.error("Loading images from file objects isn't supported")
    path = os.path.abspath(str(filename))
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "No file '%s' found in working directory '%s'." % (filename, os.getcwd()))
    width, height = _image_size(path)
    surface = Surface((width, height), SRCALPHA)
    surface._cmds = [("img", path, 0, 0, width, height, None)]
    surface._img = (path, None)
    return surface


load_extended = load


def save(surface, filename, namehint=""):
    _core.notice("image.save() isn't supported and was ignored.")


def get_extended():
    return True
'''

# ----------------------------------------------------------------------
# pygame.transform
# ----------------------------------------------------------------------
_SOURCES['transform'] = r'''"""pygame.transform: scale, rotate and flip are applied when the frame is drawn."""

import math as _m

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


smoothscale = scale


def scale_by(surface, factor, dest_surface=None):
    fx, fy = (factor, factor) if isinstance(factor, (int, float)) else factor
    return scale(surface, (int(surface._w * fx), int(surface._h * fy)), dest_surface)


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
# pygame.sprite
# ----------------------------------------------------------------------
_SOURCES['sprite'] = r'''"""pygame.sprite: Sprite, groups and collision helpers."""

import math as _m

from .rect import Rect


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
    return left.rect.colliderect(right.rect)


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
_SOURCES['mixer'] = r'''"""pygame.mixer: silent stand-ins, so games that play sounds still run."""

import sys as _sys

from . import _core

_initialized = [True]


def _silent():
    _core.notice("Audio isn't supported in the IDE; sounds and music are silent.")


def init(*args, **kwargs):
    _initialized[0] = True


def pre_init(*args, **kwargs):
    pass


def quit():
    _initialized[0] = False


def get_init():
    return (44100, -16, 2) if _initialized[0] else None


def set_num_channels(count):
    pass


def get_num_channels():
    return 8


def stop():
    pass


def pause():
    pass


def unpause():
    pass


def fadeout(time):
    pass


def get_busy():
    return False


class Channel:
    def __init__(self, id=0):
        self.id = id

    def play(self, sound, loops=0, maxtime=0, fade_ms=0):
        pass

    def stop(self):
        pass

    def pause(self):
        pass

    def unpause(self):
        pass

    def set_volume(self, *volume):
        pass

    def get_volume(self):
        return 1.0

    def get_busy(self):
        return False

    def fadeout(self, time):
        pass


class Sound:
    def __init__(self, file=None, buffer=None):
        _silent()
        self._volume = 1.0

    def play(self, loops=0, maxtime=0, fade_ms=0):
        _silent()
        return Channel()

    def stop(self):
        pass

    def fadeout(self, time):
        pass

    def set_volume(self, value):
        self._volume = value

    def get_volume(self):
        return self._volume

    def get_length(self):
        return 0.0

    def get_num_channels(self):
        return 0

    def get_raw(self):
        return b""


def find_channel(force=False):
    return Channel()


class _Music:
    def __init__(self):
        self._volume = 1.0

    def load(self, filename, namehint=""):
        _silent()

    def unload(self):
        pass

    def play(self, loops=0, start=0.0, fade_ms=0):
        _silent()

    def stop(self):
        pass

    def pause(self):
        pass

    def unpause(self):
        pass

    def rewind(self):
        pass

    def fadeout(self, time):
        pass

    def set_volume(self, value):
        self._volume = value

    def get_volume(self):
        return self._volume

    def get_busy(self):
        return False

    def get_pos(self):
        return -1

    def set_pos(self, pos):
        pass

    def queue(self, filename, namehint="", loops=0):
        pass


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


_ORDER = ['_core', 'constants', 'color', 'rect', 'math', 'surface', 'draw', 'event', 'key', 'mouse', 'time', 'display', 'font', 'image', 'transform', 'sprite', 'mixer', 'version', 'locals']
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
    return (5, 0)


def quit():
    _core.initialized = False
    display.quit()
    font.quit()
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
