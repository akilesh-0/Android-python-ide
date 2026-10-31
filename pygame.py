"""NovaGame: a small Pygame-compatible layer for the Android Python IDE.

This is an intentionally limited compatibility layer, not the full Pygame
library. It provides a Kivy-backed display, basic rectangle drawing, a small
event queue, and FPS-limited clocks.

Place this single file beside main.py in the IDE project. User programs can
then use `import pygame` and the usual `pygame.display`, `pygame.draw`,
`pygame.event`, and `pygame.time` interfaces.
"""

from __future__ import annotations

import sys
import threading
import time as _time
import types
from collections import deque
from dataclasses import dataclass


__version__ = "0.1.0-novagame"

# ---------------------------------------------------------------------------
# Pygame-style constants
# ---------------------------------------------------------------------------

NOEVENT = 0
QUIT = 256
KEYDOWN = 768
KEYUP = 769
MOUSEMOTION = 1024
MOUSEBUTTONDOWN = 1025
MOUSEBUTTONUP = 1026

K_UNKNOWN = 0
K_BACKSPACE = 8
K_TAB = 9
K_RETURN = 13
K_ESCAPE = 27
K_SPACE = 32
K_RIGHT = 1073741903
K_LEFT = 1073741904
K_DOWN = 1073741905
K_UP = 1073741906

SRCALPHA = 1
FULLSCREEN = 2
RESIZABLE = 4


# ---------------------------------------------------------------------------
# Shared runtime and surface
# ---------------------------------------------------------------------------

@dataclass
class DrawRect:
    color: tuple[float, float, float, float]
    rect: tuple[float, float, float, float]


def normalize_color(color):
    """Convert RGB/RGBA values in either 0..255 or 0..1 range to Kivy RGBA."""
    if isinstance(color, str):
        named = {
            "black": (0, 0, 0),
            "white": (255, 255, 255),
            "red": (255, 0, 0),
            "green": (0, 128, 0),
            "blue": (0, 0, 255),
        }
        if color.lower() not in named:
            raise ValueError(f"Unsupported color name: {color!r}")
        color = named[color.lower()]

    values = tuple(color)
    if len(values) not in (3, 4):
        raise ValueError("A color must contain 3 (RGB) or 4 (RGBA) values")

    integer_channels = all(
        isinstance(v, int) and not isinstance(v, bool) for v in values
    )
    scale = (
        255.0
        if integer_channels or any(float(v) > 1.0 for v in values)
        else 1.0
    )
    normalized = [max(0.0, min(1.0, float(v) / scale)) for v in values]
    if len(normalized) == 3:
        normalized.append(1.0)
    return tuple(normalized)


class Surface:
    """A lightweight Pygame-like surface that records drawing commands."""

    def __init__(self, size):
        self.width = max(1, int(size[0]))
        self.height = max(1, int(size[1]))
        self._lock = threading.RLock()
        self._background = (0.0, 0.0, 0.0, 1.0)
        self._commands = []

    def fill(self, color):
        """Set the background color and clear the current frame."""
        rgba = normalize_color(color)
        with self._lock:
            self._background = rgba
            self._commands.clear()
        return (0, 0, self.width, self.height)

    def get_size(self):
        return (self.width, self.height)

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def _add_rect(self, color, rect):
        x, y, width, height = [float(v) for v in rect]
        with self._lock:
            self._commands.append(
                DrawRect(normalize_color(color), (x, y, width, height))
            )

    def _snapshot(self):
        with self._lock:
            return self._background, list(self._commands)


# ---------------------------------------------------------------------------
# Kivy game display
# ---------------------------------------------------------------------------

_surface = None
_modal = None
_widget = None
_ui_ready = threading.Event()
_state_lock = threading.RLock()
_game_closed = False


class _KivyGameWidget:
    """Factory wrapper so importing pygame does not immediately import Kivy."""

    @staticmethod
    def create(surface):
        try:
            from kivy.clock import Clock
            from kivy.graphics import Color, Rectangle
            from kivy.uix.widget import Widget
        except Exception as exc:
            raise RuntimeError(
                "NovaGame needs Kivy. Run it inside the Android Python IDE app."
            ) from exc

        class GameWidget(Widget):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._surface = surface
                self._frame_event = Clock.schedule_interval(
                    self._draw_frame, 1 / 60
                )
                self.bind(size=self._draw_frame, pos=self._draw_frame)
                self._draw_frame(0)

            def _draw_frame(self, *_args):
                background, commands = self._surface._snapshot()
                virtual_w = float(self._surface.width)
                virtual_h = float(self._surface.height)
                if (
                    virtual_w <= 0
                    or virtual_h <= 0
                    or self.width <= 0
                    or self.height <= 0
                ):
                    return

                scale = min(self.width / virtual_w, self.height / virtual_h)
                drawn_w = virtual_w * scale
                drawn_h = virtual_h * scale
                offset_x = self.x + (self.width - drawn_w) / 2
                offset_y = self.y + (self.height - drawn_h) / 2

                self.canvas.clear()
                with self.canvas:
                    Color(0.035, 0.04, 0.055, 1)
                    Rectangle(pos=self.pos, size=self.size)
                    Color(*background)
                    Rectangle(
                        pos=(offset_x, offset_y),
                        size=(drawn_w, drawn_h),
                    )
                    for command in commands:
                        x, y, width, height = command.rect
                        Color(*command.color)
                        Rectangle(
                            pos=(
                                offset_x + x * scale,
                                offset_y + (virtual_h - y - height) * scale,
                            ),
                            size=(
                                max(0, width * scale),
                                max(0, height * scale),
                            ),
                        )

            def on_parent(self, _instance, parent):
                if parent is None and hasattr(self, "_frame_event"):
                    self._frame_event.cancel()

        return GameWidget(size_hint=(1, 1))


def _post_quit_event():
    with _event_lock:
        if not any(item.type == QUIT for item in _event_queue):
            _event_queue.append(Event(QUIT))


def _open_game_view(surface):
    """Create the Kivy modal on the UI thread and wait for it to be ready."""
    global _modal, _widget, _game_closed
    try:
        from kivy.clock import Clock
        from kivy.uix.modalview import ModalView
    except Exception as exc:
        raise RuntimeError(
            "NovaGame display requires a running Kivy Android app."
        ) from exc

    # A previous game session may have left a QUIT event in the queue
    # (for example, when Android Back dismissed the game view just as the
    # user's loop was finishing). Do not let that old event terminate the
    # next game session immediately.
    with _event_lock:
        _event_queue.clear()

    _ui_ready.clear()
    _game_closed = False
    creation_error = []

    def _on_modal_dismiss(*_args):
        global _game_closed
        _game_closed = True
        _post_quit_event()

    def _create(_dt):
        global _modal, _widget
        try:
            _widget = _KivyGameWidget.create(surface)
            _modal = ModalView(
                size_hint=(1, 1),
                auto_dismiss=True,
                background_color=(0.025, 0.03, 0.045, 1),
            )
            _modal.add_widget(_widget)
            _modal.bind(on_dismiss=_on_modal_dismiss)
            _modal.open()
        except BaseException as exc:
            creation_error.append(exc)
        finally:
            _ui_ready.set()

    Clock.schedule_once(_create, 0)
    if not _ui_ready.wait(timeout=10):
        raise RuntimeError("Timed out while opening the NovaGame display.")
    if creation_error:
        raise RuntimeError("Could not open the NovaGame display.") from creation_error[0]


def _close_game_view():
    global _modal, _widget
    try:
        from kivy.clock import Clock
    except Exception:
        return

    def _close(_dt):
        global _modal, _widget
        if _modal is not None:
            try:
                _modal.dismiss()
            except Exception:
                pass
        _modal = None
        _widget = None

    Clock.schedule_once(_close, 0)


# ---------------------------------------------------------------------------
# display API
# ---------------------------------------------------------------------------

_display_surface = None


def _display_set_mode(size, flags=0, depth=0, display=0, vsync=0):
    """Open the game view and return a drawing Surface."""
    del flags, depth, display, vsync
    global _display_surface, _surface
    if not isinstance(size, (tuple, list)) or len(size) != 2:
        raise TypeError("set_mode(size) expects a (width, height) pair")
    _display_surface = Surface((int(size[0]), int(size[1])))
    _surface = _display_surface
    _open_game_view(_display_surface)
    return _display_surface


def _display_get_surface():
    return _display_surface


def _display_flip():
    """Present the latest recorded frame. Rendering is driven by Kivy."""
    return None


def _display_update(*_args):
    return _display_flip()


def _display_set_caption(_title):
    return None


def _display_quit():
    global _display_surface, _surface
    _close_game_view()
    _display_surface = None
    _surface = None


# ---------------------------------------------------------------------------
# draw API
# ---------------------------------------------------------------------------

def _draw_rect(surface, color, rect, width=0, border_radius=0):
    """Draw a rectangle. width=0 fills it; positive width draws an outline."""
    del border_radius
    if surface is None:
        surface = _display_get_surface()
    if surface is None:
        raise RuntimeError("Call pygame.display.set_mode() before drawing")

    if hasattr(rect, "x"):
        values = (rect.x, rect.y, rect.width, rect.height)
    else:
        values = rect
    x, y, w, h = [float(v) for v in values]
    if w < 0 or h < 0:
        raise ValueError("Rectangle width and height must be non-negative")

    border = max(0, int(width))
    if border == 0:
        surface._add_rect(color, (x, y, w, h))
    else:
        border = min(border, int(max(w, h)))
        surface._add_rect(color, (x, y, w, min(border, h)))
        if h > border:
            surface._add_rect(color, (x, y + h - border, w, border))
        inner_h = max(0, h - 2 * border)
        if inner_h:
            surface._add_rect(
                color, (x, y + border, min(border, w), inner_h)
            )
            if w > border:
                surface._add_rect(
                    color,
                    (x + w - border, y + border, border, inner_h),
                )
    return (int(x), int(y), int(w), int(h))


# ---------------------------------------------------------------------------
# event API
# ---------------------------------------------------------------------------

@dataclass
class Event:
    type: int
    attributes: dict

    def __init__(self, event_type, attributes=None, **kwargs):
        self.type = int(event_type)
        self.attributes = dict(attributes or {})
        self.attributes.update(kwargs)
        for key, value in self.attributes.items():
            setattr(self, key, value)

    def __repr__(self):
        return f"<Event({self.type}, {self.attributes})>"


_event_queue = deque()
_event_lock = threading.Lock()


def _event_get():
    with _event_lock:
        items = list(_event_queue)
        _event_queue.clear()
    return items


def _event_poll():
    with _event_lock:
        return (
            _event_queue.popleft()
            if _event_queue
            else Event(NOEVENT)
        )


def _event_post(event):
    if not isinstance(event, Event):
        raise TypeError("event.post() expects an Event")
    with _event_lock:
        _event_queue.append(event)
    return True


def _event_clear():
    with _event_lock:
        _event_queue.clear()


# ---------------------------------------------------------------------------
# time API
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self._last = _time.perf_counter()
        self._last_tick = 0.0
        self._fps_samples = []

    def tick(self, framerate=0):
        now = _time.perf_counter()
        if framerate and framerate > 0:
            target = 1.0 / float(framerate)
            elapsed = now - self._last
            remaining = target - elapsed
            if remaining > 0:
                _time.sleep(remaining)
        current = _time.perf_counter()
        self._last_tick = current - self._last
        self._last = current
        self._fps_samples.append(self._last_tick)
        if len(self._fps_samples) > 20:
            self._fps_samples.pop(0)
        return int(self._last_tick * 1000)

    def get_time(self):
        return int(self._last_tick * 1000)

    def get_fps(self):
        if not self._fps_samples:
            return 0.0
        average = sum(self._fps_samples) / len(self._fps_samples)
        return 1.0 / average if average > 0 else 0.0


def _time_get_ticks():
    return int(_time.monotonic() * 1000)


def _time_delay(milliseconds):
    duration = max(0, int(milliseconds))
    _time.sleep(duration / 1000.0)
    return duration


# ---------------------------------------------------------------------------
# Public Pygame-like modules and top-level API
# ---------------------------------------------------------------------------

display = types.ModuleType(__name__ + ".display")
display.set_mode = _display_set_mode
display.get_surface = _display_get_surface
display.flip = _display_flip
display.update = _display_update
display.set_caption = _display_set_caption
display.quit = _display_quit

draw = types.ModuleType(__name__ + ".draw")
draw.rect = _draw_rect

event = types.ModuleType(__name__ + ".event")
event.Event = Event
event.get = _event_get
event.poll = _event_poll
event.post = _event_post
event.clear = _event_clear

time = types.ModuleType(__name__ + ".time")
time.Clock = Clock
time.get_ticks = _time_get_ticks
time.delay = _time_delay
time.wait = _time_delay

# Register submodule aliases so both `pygame.display` and
# `import pygame.display` resolve while keeping everything in this one file.
__path__ = []
sys.modules[__name__ + ".display"] = display
sys.modules[__name__ + ".draw"] = draw
sys.modules[__name__ + ".event"] = event
sys.modules[__name__ + ".time"] = time

_initialized = False


def init():
    """Initialize NovaGame. Returns (number_initialized, number_failed)."""
    global _initialized
    _initialized = True
    return (1, 0)


def get_init():
    return _initialized


def quit():
    """Close the game view and reset NovaGame."""
    global _initialized
    display.quit()
    _initialized = False


__all__ = [
    "Surface", "display", "draw", "event", "time", "Clock", "Event",
    "init", "get_init", "quit",
    "NOEVENT", "QUIT", "KEYDOWN", "KEYUP", "MOUSEMOTION",
    "MOUSEBUTTONDOWN", "MOUSEBUTTONUP",
    "K_UNKNOWN", "K_BACKSPACE", "K_TAB", "K_RETURN", "K_ESCAPE",
    "K_SPACE", "K_RIGHT", "K_LEFT", "K_DOWN", "K_UP",
    "SRCALPHA", "FULLSCREEN", "RESIZABLE",
]
