"""Kivy canvas renderer for the Elyx Turtle engine.

The renderer is deliberately the only part of the engine that imports Kivy.
Create it on the Kivy/UI thread. Its Clock callback drains TurtleCommandBridge
and is the only place where canvas instructions are created or modified.

This module can be imported on desktop systems without Kivy installed. In
that case the pure geometry/color helpers remain available, while constructing
TurtleRenderer raises a clear RuntimeError.
"""

from collections import deque
from dataclasses import dataclass
import math
import re
import threading
import traceback
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

from .turtle_commands import TurtleCommand, TurtleCommandBridge


try:  # Kivy is supplied by the Elyx Android build.
    from kivy.clock import Clock
    from kivy.graphics import (
        Color as _Color,
        InstructionGroup as _InstructionGroup,
        Line as _Line,
        PopMatrix as _PopMatrix,
        PushMatrix as _PushMatrix,
        Rectangle as _Rectangle,
        Scale as _Scale,
        Translate as _Translate,
        Triangle as _Triangle,
        Ellipse as _Ellipse,
        Mesh as _Mesh,
    )
    from kivy.core.text import Label as _CoreLabel
    from kivy.core.window import Window as _Window
    from kivy.metrics import dp as _dp
    from kivy.uix.widget import Widget as _Widget
    KIVY_AVAILABLE = True
except ImportError:  # Keep engine-level tests usable without the Kivy runtime.
    Clock = None
    _Color = _InstructionGroup = _Line = None
    _PopMatrix = _PushMatrix = _Rectangle = _Scale = None
    _Translate = _Triangle = None
    _Ellipse = _Mesh = _CoreLabel = _Window = None
    _dp = lambda value: float(value)  # noqa: E731 - tiny no-Kivy fallback
    _Widget = object
    KIVY_AVAILABLE = False


Point = Tuple[float, float]
RGBA = Tuple[float, float, float, float]


_NAMED_COLORS: Dict[str, str] = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000",
    "green": "#008000", "blue": "#0000ff", "cyan": "#00ffff",
    "aqua": "#00ffff", "magenta": "#ff00ff", "fuchsia": "#ff00ff",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080",
    "pink": "#ffc0cb", "brown": "#a52a2a", "gray": "#808080",
    "grey": "#808080", "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9",
    "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3", "navy": "#000080",
    "lime": "#00ff00", "gold": "#ffd700", "violet": "#ee82ee",
    "turquoise": "#40e0d0", "teal": "#008080", "coral": "#ff7f50",
    "indigo": "#4b0082", "maroon": "#800000", "olive": "#808000",
    "silver": "#c0c0c0", "skyblue": "#87ceeb", "lightblue": "#add8e6",
    "darkgreen": "#006400", "darkblue": "#00008b", "lightgreen": "#90ee90",
    "crimson": "#dc143c", "salmon": "#fa8072", "tomato": "#ff6347",
    "tan": "#d2b48c", "beige": "#f5f5dc", "khaki": "#f0e68c",
    "orchid": "#da70d6", "plum": "#dda0dd", "chocolate": "#d2691e",
    "darkred": "#8b0000", "hotpink": "#ff69b4", "forestgreen": "#228b22",
    "seagreen": "#2e8b57", "steelblue": "#4682b4", "royalblue": "#4169e1",
    "midnightblue": "#191970", "firebrick": "#b22222", "lavender": "#e6e6fa",
    "ivory": "#fffff0", "darkorange": "#ff8c00", "orangered": "#ff4500",
    "deeppink": "#ff1493", "lightyellow": "#ffffe0", "lightpink": "#ffb6c1",
    "darkviolet": "#9400d3", "blueviolet": "#8a2be2", "slateblue": "#6a5acd",
    "dodgerblue": "#1e90ff", "deepskyblue": "#00bfff",
    "cornflowerblue": "#6495ed", "lightseagreen": "#20b2aa",
    "mediumseagreen": "#3cb371", "springgreen": "#00ff7f",
    "limegreen": "#32cd32", "yellowgreen": "#9acd32", "chartreuse": "#7fff00",
    "greenyellow": "#adff2f", "darkcyan": "#008b8b", "lightcyan": "#e0ffff",
    "aquamarine": "#7fffd4", "sienna": "#a0522d", "saddlebrown": "#8b4513",
    "peru": "#cd853f", "wheat": "#f5deb3", "goldenrod": "#daa520",
    "darkgoldenrod": "#b8860b", "rosybrown": "#bc8f8f",
    "lightcoral": "#f08080", "indianred": "#cd5c5c",
    "darkmagenta": "#8b008b", "mediumpurple": "#9370db",
    "thistle": "#d8bfd8", "linen": "#faf0e6", "snow": "#fffafa",
    "mintcream": "#f5fffa", "aliceblue": "#f0f8ff",
    "whitesmoke": "#f5f5f5", "gainsboro": "#dcdcdc", "dimgray": "#696969",
    "dimgrey": "#696969", "darkslategray": "#2f4f4f",
    "slategray": "#708090", "lightsteelblue": "#b0c4de",
    "powderblue": "#b0e0e6", "cadetblue": "#5f9ea0",
    "darkturquoise": "#00ced1", "mediumturquoise": "#48d1cc",
    "paleturquoise": "#afeeee", "lightsalmon": "#ffa07a",
    "darkolivegreen": "#556b2f", "lightgoldenrod": "#eedd82",
}


def color_to_rgba(value: Any) -> RGBA:
    """Convert common Turtle color forms to normalized Kivy RGBA values.

    Supported forms: common named colors, #RGB/#RRGGBB/#RRGGBBAA strings,
    and three/four item RGB(A) sequences. Numeric sequences may use either
    normalized 0..1 values or byte-style 0..255 values.
    """
    if isinstance(value, str):
        text = value.strip().lower().replace(" ", "")
        shade = re.fullmatch(r"gr[ae]y(\d{1,3})", text)  # Tk's gray0..gray100
        if shade and int(shade.group(1)) <= 100:
            level = round(int(shade.group(1)) * 255 / 100)
            text = "#%02x%02x%02x" % (level, level, level)
        text = _NAMED_COLORS.get(text, text)
        if not text.startswith("#"):
            raise ValueError("unsupported color name: %s" % value)
        raw = text[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) not in (6, 8):
            raise ValueError("hex colors must use #RGB, #RRGGBB or #RRGGBBAA")
        try:
            channels = [int(raw[index:index + 2], 16) / 255.0
                        for index in range(0, len(raw), 2)]
        except ValueError:
            raise ValueError("invalid hexadecimal color: %s" % value)
        if len(channels) == 3:
            channels.append(1.0)
        return tuple(channels)  # type: ignore[return-value]

    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        try:
            channels = [float(channel) for channel in value]
        except (TypeError, ValueError):
            raise ValueError("RGB color channels must be numbers")
        if not all(math.isfinite(channel) for channel in channels):
            raise ValueError("RGB color channels must be finite")
        divisor = 255.0 if any(channel > 1.0 for channel in channels) else 1.0
        if any(channel < 0.0 or channel > divisor for channel in channels):
            raise ValueError("RGB color channels must be between 0 and 1 or 0 and 255")
        channels = [channel / divisor for channel in channels]
        if len(channels) == 3:
            channels.append(1.0)
        return tuple(channels)  # type: ignore[return-value]

    raise ValueError("color must be a name, hex string, or RGB(A) sequence")


def world_to_canvas(point: Point, origin: Point, scale: float = 1.0) -> Point:
    """Map Turtle world coordinates to Kivy canvas coordinates."""
    x, y = float(point[0]), float(point[1])
    ox, oy = float(origin[0]), float(origin[1])
    factor = float(scale)
    if not all(math.isfinite(item) for item in (x, y, ox, oy, factor)):
        raise ValueError("coordinates and scale must be finite")
    if factor <= 0:
        raise ValueError("scale must be greater than zero")
    return (ox + x * factor, oy + y * factor)


def cursor_vertices(position: Point, heading: float, size: float = 14.0) -> Tuple[Point, Point, Point]:
    """Return the three world-coordinate vertices for a right-facing arrow."""
    x, y = float(position[0]), float(position[1])
    angle = math.radians(float(heading))
    if not all(math.isfinite(item) for item in (x, y, angle, size)):
        raise ValueError("cursor geometry must be finite")
    if size <= 0:
        raise ValueError("cursor size must be greater than zero")

    cosine, sine = math.cos(angle), math.sin(angle)

    def rotate(local_x: float, local_y: float) -> Point:
        return (
            x + local_x * cosine - local_y * sine,
            y + local_x * sine + local_y * cosine,
        )

    return (
        rotate(size, 0.0),
        rotate(-size * 0.72, size * 0.58),
        rotate(-size * 0.72, -size * 0.58),
    )


def path_length(points: Sequence[Point]) -> float:
    """Calculate the length of a polyline."""
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += math.hypot(end[0] - start[0], end[1] - start[1])
    return total


def partial_path(points: Sequence[Point], distance: float) -> Tuple[Point, ...]:
    """Return the prefix of a polyline up to ``distance`` world units."""
    if not points:
        return ()
    if len(points) == 1:
        return (tuple(points[0]),)

    remaining = max(0.0, float(distance))
    result: List[Point] = [tuple(points[0])]
    if remaining <= 1e-12:
        return tuple(result)
    for start, end in zip(points, points[1:]):
        segment_length = math.hypot(end[0] - start[0], end[1] - start[1])
        if segment_length <= 1e-12:
            continue
        if remaining >= segment_length:
            result.append(tuple(end))
            remaining -= segment_length
            if remaining <= 1e-12:
                return tuple(result)
            continue
        fraction = remaining / segment_length
        result.append((
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        ))
        return tuple(result)
    return tuple(result)


def triangulate_polygon(points: Sequence[Point]) -> Tuple[Tuple[int, int, int], ...]:
    """Triangulate a simple polygon with ear clipping (supports concave shapes)."""
    vertices = [(float(x), float(y)) for x, y in points]
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    # Remove adjacent duplicates, which otherwise create zero-area ears.
    compact = []
    for point in vertices:
        if not compact or point != compact[-1]:
            compact.append(point)
    vertices = compact
    if len(vertices) < 3:
        return ()

    area2 = sum(
        vertices[i][0] * vertices[(i + 1) % len(vertices)][1]
        - vertices[(i + 1) % len(vertices)][0] * vertices[i][1]
        for i in range(len(vertices))
    )
    if abs(area2) <= 1e-10:
        return ()
    orientation = 1.0 if area2 > 0 else -1.0
    remaining = list(range(len(vertices)))
    result = []

    def cross(a, b, c):
        return ((b[0] - a[0]) * (c[1] - a[1])
                - (b[1] - a[1]) * (c[0] - a[0]))

    def inside(point, a, b, c):
        c1 = cross(a, b, point) * orientation
        c2 = cross(b, c, point) * orientation
        c3 = cross(c, a, point) * orientation
        return c1 >= -1e-9 and c2 >= -1e-9 and c3 >= -1e-9

    guard = len(vertices) * len(vertices)
    while len(remaining) > 3 and guard > 0:
        guard -= 1
        ear_found = False
        for pos, current in enumerate(remaining):
            previous = remaining[pos - 1]
            following = remaining[(pos + 1) % len(remaining)]
            a, b, c = vertices[previous], vertices[current], vertices[following]
            if cross(a, b, c) * orientation <= 1e-10:
                continue
            if any(
                inside(vertices[index], a, b, c)
                for index in remaining
                if index not in (previous, current, following)
            ):
                continue
            result.append((previous, current, following))
            del remaining[pos]
            ear_found = True
            break
        if not ear_found:
            return ()
    if len(remaining) == 3:
        result.append(tuple(remaining))
    return tuple(result)


def _flatten_points(points: Iterable[Point]) -> List[float]:
    flattened: List[float] = []
    for x, y in points:
        flattened.extend((float(x), float(y)))
    return flattened


def _speed_rate(speed: int) -> float:
    """Approximate Turtle movement rate in world units per second."""
    rates = {
        1: 90.0, 2: 160.0, 3: 250.0, 4: 360.0, 5: 500.0,
        6: 700.0, 7: 900.0, 8: 1150.0, 9: 1450.0, 10: 1800.0,
    }
    return rates.get(int(speed), 250.0)


@dataclass
class _TurtleRenderState:
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    visible: bool = True
    pen_down: bool = True
    color: Any = "black"
    width: float = 1.0
    speed: int = 3
    fills: Any = None
    drawing: Any = None
    stamps: Any = None
    stamp_groups: Any = None
    cursor: Any = None
    shape: str = "classic"
    shape_points: Any = None
    fill_color: Any = "black"
    stretch_wid: float = 1.0
    stretch_len: float = 1.0
    outline_width: float = 1.0


@dataclass
class _AnimationJob:
    turtle_id: str
    points: Tuple[Point, ...]
    total_length: float
    elapsed: float
    duration: float
    line_instruction: Any
    final_point: Point


class TurtleRenderer(_Widget):
    """Render bridge commands on a Kivy Widget's canvas.

    Construct this widget on the Kivy main thread. Python worker threads should
    publish only through ``TurtleCommandBridge``. The renderer's scheduled
    Clock callback drains and applies those commands on the UI thread.

    ``mode`` may be ``"animated"`` or ``"instant"``. In animated mode,
    ``TurtleCore.speed(0)`` still makes that turtle's individual moves instant.
    """

    VALID_MODES = ("animated", "instant")

    def __init__(
        self,
        bridge: TurtleCommandBridge,
        session_id: int,
        *,
        mode: str = "animated",
        background_color: Any = "white",
        animation_scale: float = 1.0,
        cursor_size: float = 14.0,
        max_commands_per_tick: int = 512,
        tick_interval: float = 1.0 / 60.0,
        auto_start: bool = True,
        **kwargs: Any
    ) -> None:
        if not KIVY_AVAILABLE:
            raise RuntimeError(
                "TurtleRenderer requires Kivy; install/run it inside the Elyx app"
            )
        if bridge is None:
            raise ValueError("bridge is required")
        if mode not in self.VALID_MODES:
            raise ValueError("mode must be 'animated' or 'instant'")
        if animation_scale <= 0 or not math.isfinite(float(animation_scale)):
            raise ValueError("animation_scale must be a finite positive number")
        if cursor_size <= 0 or not math.isfinite(float(cursor_size)):
            raise ValueError("cursor_size must be a finite positive number")
        if max_commands_per_tick <= 0:
            raise ValueError("max_commands_per_tick must be greater than zero")
        if tick_interval <= 0 or not math.isfinite(float(tick_interval)):
            raise ValueError("tick_interval must be a finite positive number")

        super().__init__(**kwargs)
        self.bridge = bridge
        self.session_id = session_id
        self.mode = mode
        self.animation_scale = float(animation_scale)
        self.cursor_size = float(cursor_size)
        self.max_commands_per_tick = int(max_commands_per_tick)
        self.tick_interval = float(tick_interval)
        self._ui_thread_id = threading.get_ident()
        self._pending: Deque[TurtleCommand] = deque()
        self._states: Dict[str, _TurtleRenderState] = {}
        self._active: Optional[_AnimationJob] = None
        self._clock_event = None
        self._disposed = False
        self._tracer_enabled = True
        self._background_color_value = color_to_rgba(background_color)
        self._click_dispatcher = None
        self._key_dispatcher = None
        self._listen_requested = False
        self._keyboard = None

        # A single matrix transform keeps Turtle's origin at the canvas center.
        self._matrix_push = _PushMatrix()
        self._translate = _Translate(x=self.center_x, y=self.center_y)
        self._scale_instruction = _Scale(x=1.0, y=1.0, z=1.0)
        self._root_group = _InstructionGroup()
        self._matrix_pop = _PopMatrix()

        self._background_color = _Color(*self._background_color_value)
        self._background_rect = _Rectangle(pos=self.pos, size=self.size)
        self.canvas.before.add(self._background_color)
        self.canvas.before.add(self._background_rect)
        self.canvas.add(self._matrix_push)
        self.canvas.add(self._translate)
        self.canvas.add(self._scale_instruction)
        self.canvas.add(self._root_group)
        self.canvas.add(self._matrix_pop)
        self.bind(pos=self._update_geometry, size=self._update_geometry)

        if auto_start:
            self.start()

    # ---- Public controls -------------------------------------------------

    @property
    def is_idle(self) -> bool:
        """True when the local queue, bridge queue and animation are empty."""
        return (
            not self._pending
            and self._active is None
            and self.bridge.pending_count() == 0
        )

    @property
    def is_running(self) -> bool:
        return self._clock_event is not None and not self._disposed

    def start(self) -> None:
        """Start the Kivy Clock consumer."""
        self._assert_ui_thread()
        if self._disposed:
            raise RuntimeError("renderer has been disposed")
        if self._clock_event is None:
            self._clock_event = Clock.schedule_interval(self._on_tick, self.tick_interval)

    def pause(self) -> None:
        """Pause consumption without discarding queued drawing commands."""
        self._assert_ui_thread()
        if self._clock_event is not None:
            self._clock_event.cancel()
            self._clock_event = None

    def set_mode(self, mode: str) -> None:
        """Switch between progressive and instant rendering."""
        self._assert_ui_thread()
        if mode not in self.VALID_MODES:
            raise ValueError("mode must be 'animated' or 'instant'")
        self.mode = mode
        if mode == "instant" and self._active is not None:
            self._complete_active_animation()

    def set_animation_scale(self, value: float) -> None:
        """Set global animation speed multiplier (larger values are faster)."""
        self._assert_ui_thread()
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("animation scale must be a finite positive number")
        self.animation_scale = value

    def set_background_color(self, color: Any) -> None:
        """Change the preview canvas background."""
        self._assert_ui_thread()
        rgba = color_to_rgba(color)
        self._background_color_value = rgba
        self._background_color.rgba = rgba

    def set_session(self, session_id: int, *, clear: bool = True) -> None:
        """Switch the renderer to a newly opened bridge session."""
        self._assert_ui_thread()
        self.cancel_pending()
        self.session_id = session_id
        if clear:
            self.clear_canvas()

    def cancel_pending(self) -> None:
        """Discard buffered commands and stop the current animated segment.

        Already rendered drawing remains visible, including the visible prefix
        of a segment that was in progress when cancellation occurred.
        """
        self._assert_ui_thread()
        self._pending.clear()
        self._active = None

    def clear_canvas(self) -> None:
        """Remove all turtle drawings and cursors from the preview."""
        self._assert_ui_thread()
        self._pending.clear()
        self._active = None
        self._states.clear()
        self._root_group.clear()

    def dispose(self, *, clear: bool = False) -> None:
        """Stop the Clock callback and release canvas instructions."""
        self._assert_ui_thread()
        if self._clock_event is not None:
            self._clock_event.cancel()
            self._clock_event = None
        self._pending.clear()
        self._active = None
        self._release_keyboard()
        if clear:
            self.clear_canvas()
        self._disposed = True

    # ---- Input bridge ----------------------------------------------------

    def set_event_dispatcher(self, click_handler=None, key_handler=None) -> None:
        """Set callbacks that enqueue events in the runtime's worker queue."""
        self._assert_ui_thread()
        self._click_dispatcher = click_handler
        self._key_dispatcher = key_handler

    def set_keyboard_listening(self, enabled: bool) -> None:
        """Enable or disable hardware-key capture while the preview is active."""
        self._assert_ui_thread()
        self._listen_requested = bool(enabled)
        if self._listen_requested:
            self.set_keyboard_active(True)
        else:
            self.set_keyboard_active(False)

    def set_keyboard_active(self, active: bool) -> None:
        """Temporarily attach/detach keyboard capture without forgetting listen()."""
        self._assert_ui_thread()
        if active and self._listen_requested and self._keyboard is None:
            try:
                keyboard = _Window.request_keyboard(self._keyboard_closed, self)
                if keyboard is not None:
                    keyboard.bind(on_key_down=self._on_key_down,
                                  on_key_up=self._on_key_up)
                    self._keyboard = keyboard
            except Exception:
                self._keyboard = None
        elif not active:
            self._release_keyboard()

    def _keyboard_closed(self) -> None:
        self._assert_ui_thread()
        self._release_keyboard()

    def _release_keyboard(self) -> None:
        keyboard = self._keyboard
        self._keyboard = None
        if keyboard is not None:
            try:
                keyboard.unbind(on_key_down=self._on_key_down,
                                on_key_up=self._on_key_up)
                keyboard.release()
            except Exception:
                pass

    @staticmethod
    def _key_name(keycode: Any, text: Any = "") -> str:
        if isinstance(keycode, (tuple, list)) and len(keycode) > 1:
            name = str(keycode[1])
        else:
            name = str(keycode)
        name = name.strip().lower()
        if name.startswith("keycode "):
            name = name.split()[-1]
        if text and len(str(text)) == 1 and name.isdigit():
            name = str(text).lower()
        return name

    def _on_key_down(self, _keyboard, keycode, text, _modifiers):
        if self._key_dispatcher is not None:
            return bool(self._key_dispatcher(self._key_name(keycode, text), "press"))
        return False

    def _on_key_up(self, _keyboard, keycode):
        if self._key_dispatcher is not None:
            return bool(self._key_dispatcher(self._key_name(keycode), "release"))
        return False

    def on_touch_down(self, touch):
        if self._click_dispatcher is not None and self.collide_point(*touch.pos):
            button_name = getattr(touch, "button", None) or "left"
            button = {"left": 1, "middle": 2, "right": 3}.get(button_name, 1)
            self._click_dispatcher(
                float(touch.x - self.center_x),
                float(touch.y - self.center_y),
                button,
            )
            return True
        return super().on_touch_down(touch)

    # ---- Kivy lifecycle --------------------------------------------------

    def _update_geometry(self, *_args: Any) -> None:
        self._assert_ui_thread()
        self._translate.x = self.center_x
        self._translate.y = self.center_y
        self._background_rect.pos = self.pos
        self._background_rect.size = self.size

    def _on_tick(self, dt: float) -> bool:
        try:
            return self._on_tick_inner(dt)
        except Exception:
            # An exception escaping a Kivy Clock callback closes the whole
            # app. Drop the offending command, log it, and keep drawing.
            traceback.print_exc()
            self._active = None
            return not self._disposed

    def _on_tick_inner(self, dt: float) -> bool:
        if self._disposed:
            self._clock_event = None
            return False
        self._assert_ui_thread()

        if self._active is not None:
            self._advance_animation(max(0.0, float(dt)))
            return True

        if not self._pending:
            self._pending.extend(self.bridge.drain(self.max_commands_per_tick))

        processed = 0
        while self._pending and processed < self.max_commands_per_tick:
            command = self._pending.popleft()
            processed += 1
            if command.session_id != self.session_id:
                continue

            if self._is_path_command(command) and self._should_animate(command):
                self._begin_animation(command)
                if self._active is not None:
                    self._advance_animation(max(0.0, float(dt)))
                    break
            else:
                self._apply_command(command)
        return True

    # ---- Command processing ---------------------------------------------

    @staticmethod
    def _is_path_command(command: TurtleCommand) -> bool:
        return command.operation in ("line", "polyline")

    def _should_animate(self, command: TurtleCommand) -> bool:
        if self.mode != "animated" or not self._tracer_enabled:
            return False
        state = self._state_for(command.turtle_id)
        return state.speed != 0

    def _state_for(self, turtle_id: str) -> _TurtleRenderState:
        state = self._states.get(turtle_id)
        if state is None:
            state = _TurtleRenderState()
            state.fills = _InstructionGroup()
            state.drawing = _InstructionGroup()
            state.stamps = _InstructionGroup()
            state.stamp_groups = {}
            state.cursor = _InstructionGroup()
            self._states[turtle_id] = state
            self._root_group.add(state.fills)
            self._root_group.add(state.drawing)
            self._root_group.add(state.stamps)
            self._root_group.add(state.cursor)
        return state

    def _apply_command(self, command: TurtleCommand) -> None:
        operation = command.operation
        payload = command.payload

        # Screen-level commands are handled before creating per-turtle state.
        if operation == "background":
            self.set_background_color(payload.get("color", "white"))
            return
        if operation == "tracer":
            self._tracer_enabled = bool(payload.get("enabled", True))
            if not self._tracer_enabled and self._active is not None:
                self._complete_active_animation()
            return
        if operation == "screen_clear":
            for turtle_state in self._states.values():
                turtle_state.fills.clear()
                turtle_state.drawing.clear()
                turtle_state.stamps.clear()
                turtle_state.stamp_groups.clear()
                turtle_state.cursor.clear()
            return
        if operation == "listen":
            self.set_keyboard_listening(bool(payload.get("enabled", True)))
            return
        if operation == "screen_reset":
            self.clear_canvas()
            self.set_background_color(payload.get("color", "white"))
            return

        state = self._state_for(command.turtle_id)

        if operation == "line":
            points = (tuple(payload["start"]), tuple(payload["end"]))
            self._draw_complete_path(state, points, payload.get("color", state.color),
                                     payload.get("width", state.width))
            state.x, state.y = points[-1]
            self._refresh_cursor(state)
        elif operation == "polyline":
            points = tuple(tuple(point) for point in payload.get("points", ()))
            self._draw_complete_path(state, points, payload.get("color", state.color),
                                     payload.get("width", state.width))
            if points:
                state.x, state.y = points[-1]
                self._refresh_cursor(state)
        elif operation == "move":
            state.x = float(payload["x"])
            state.y = float(payload["y"])
            self._refresh_cursor(state)
        elif operation == "cursor":
            state.x = float(payload["x"])
            state.y = float(payload["y"])
            state.heading = float(payload["heading"])
            state.visible = bool(payload.get("visible", True))
            state.shape = str(payload.get("shape", state.shape))
            state.shape_points = payload.get("shape_points", state.shape_points)
            state.fill_color = payload.get("fill_color", state.fill_color)
            state.stretch_wid = float(payload.get("stretch_wid", state.stretch_wid))
            state.stretch_len = float(payload.get("stretch_len", state.stretch_len))
            state.outline_width = float(payload.get("outline_width", state.outline_width))
            self._refresh_cursor(state)
        elif operation == "style":
            state.color = payload.get("color", state.color)
            state.width = float(payload.get("width", state.width))
            self._refresh_cursor(state)
        elif operation == "pen":
            state.pen_down = bool(payload.get("down", state.pen_down))
        elif operation == "speed":
            state.speed = int(payload.get("value", state.speed))
        elif operation == "clear":
            state.fills.clear()
            state.drawing.clear()
            state.stamps.clear()
            state.stamp_groups.clear()
        elif operation == "shape":
            state.shape = str(payload.get("shape", state.shape))
            state.shape_points = payload.get("shape_points", state.shape_points)
            self._refresh_cursor(state)
        elif operation == "stamp":
            self._add_stamp(state, payload)
        elif operation == "clearstamp":
            self._remove_stamp(state, payload.get("stamp_id"))
        elif operation == "clearstamps":
            self._remove_stamps(state, payload.get("count"))
        elif operation == "polygon":
            points = tuple(tuple(point) for point in payload.get("points", ()))
            self._draw_polygon(state, points, payload.get("color", "black"))
        elif operation == "dot":
            self._draw_dot(state, payload)
        elif operation == "text":
            self._draw_text(state, payload)
        # Unknown operations are intentionally ignored so new core commands
        # can be added without making the renderer crash.

    def _begin_animation(self, command: TurtleCommand) -> None:
        state = self._state_for(command.turtle_id)
        payload = command.payload
        if command.operation == "line":
            points = (tuple(payload["start"]), tuple(payload["end"]))
        else:
            points = tuple(tuple(point) for point in payload.get("points", ()))
        if len(points) < 2:
            self._apply_command(command)
            return

        total = path_length(points)
        if total <= 1e-9:
            self._apply_command(command)
            return

        color = payload.get("color", state.color)
        width = payload.get("width", state.width)
        try:
            rgba = color_to_rgba(color)
        except ValueError:
            # A bad user-supplied color should not kill the renderer's Clock
            # callback. Use a predictable fallback and keep drawing.
            color = "black"
            rgba = color_to_rgba(color)
        state.color = color
        state.width = float(width)
        line_instruction = _Line(
            points=[points[0][0], points[0][1], points[0][0], points[0][1]],
            width=_dp(state.width),
        )
        state.drawing.add(_Color(*rgba))
        state.drawing.add(line_instruction)

        duration = total / _speed_rate(state.speed) / self.animation_scale
        duration = min(3.0, max(0.045, duration))
        self._active = _AnimationJob(
            turtle_id=command.turtle_id,
            points=points,
            total_length=total,
            elapsed=0.0,
            duration=duration,
            line_instruction=line_instruction,
            final_point=points[-1],
        )

    def _advance_animation(self, dt: float) -> None:
        job = self._active
        if job is None:
            return
        job.elapsed = min(job.duration, job.elapsed + dt)
        fraction = job.elapsed / job.duration if job.duration else 1.0
        distance = job.total_length * fraction
        visible_points = partial_path(job.points, distance)
        if len(visible_points) == 1:
            visible_points = (visible_points[0], visible_points[0])
        job.line_instruction.points = _flatten_points(visible_points)

        state = self._state_for(job.turtle_id)
        if visible_points:
            state.x, state.y = visible_points[-1]
            self._refresh_cursor(state)

        if fraction >= 1.0:
            state.x, state.y = job.final_point
            self._refresh_cursor(state)
            self._active = None

    def _complete_active_animation(self) -> None:
        job = self._active
        if job is None:
            return
        job.line_instruction.points = _flatten_points(job.points)
        state = self._state_for(job.turtle_id)
        state.x, state.y = job.final_point
        self._refresh_cursor(state)
        self._active = None

    def _draw_complete_path(
        self,
        state: _TurtleRenderState,
        points: Sequence[Point],
        color: Any,
        width: Any,
    ) -> None:
        if len(points) < 2:
            return
        try:
            rgba = color_to_rgba(color)
        except ValueError:
            color = "black"
            rgba = color_to_rgba(color)
        line_width = float(width)
        if not math.isfinite(line_width) or line_width <= 0:
            line_width = 1.0
        state.drawing.add(_Color(*rgba))
        state.drawing.add(_Line(points=_flatten_points(points), width=_dp(line_width)))
        state.color = color
        state.width = line_width

    def _draw_polygon(
        self, state: _TurtleRenderState, points: Sequence[Point], color: Any
    ) -> None:
        polygon_points = [(float(x), float(y)) for x, y in points]
        if len(polygon_points) > 1 and polygon_points[0] == polygon_points[-1]:
            polygon_points.pop()
        compact = []
        for point in polygon_points:
            if not compact or point != compact[-1]:
                compact.append(point)
        polygon_points = compact
        triangles = triangulate_polygon(polygon_points)
        if not triangles:
            return
        try:
            rgba = color_to_rgba(color)
        except ValueError:
            rgba = color_to_rgba("black")
        vertices = []
        indices = []
        for triangle in triangles:
            for point_index in triangle:
                x, y = polygon_points[point_index]
                vertices.extend((float(x), float(y), 0.0, 0.0))
                indices.append(len(indices))
        state.fills.add(_Color(*rgba))
        state.fills.add(_Mesh(vertices=vertices, indices=indices, mode="triangles"))

    def _draw_dot(self, state: _TurtleRenderState, payload: Any) -> None:
        size = max(0.1, float(payload.get("size", 5.0)))
        x = float(payload.get("x", state.x))
        y = float(payload.get("y", state.y))
        try:
            rgba = color_to_rgba(payload.get("color", state.color))
        except ValueError:
            rgba = color_to_rgba("black")
        state.drawing.add(_Color(*rgba))
        state.drawing.add(_Ellipse(pos=(x - size / 2.0, y - size / 2.0),
                                   size=(size, size)))

    def _draw_text(self, state: _TurtleRenderState, payload: Any) -> None:
        text = str(payload.get("text", ""))
        if not text:
            return
        try:
            rgba = color_to_rgba(payload.get("color", state.color))
        except ValueError:
            rgba = color_to_rgba("black")
        label = _CoreLabel(
            text=text,
            font_name=str(payload.get("font_name", "Arial")),
            font_size=max(1.0, float(payload.get("font_size", 8.0))),
            bold=bool(payload.get("bold", False)),
            italic=bool(payload.get("italic", False)),
            color=rgba,
        )
        label.refresh()
        texture = label.texture
        if texture is None:
            return
        width, height = texture.size
        x = float(payload.get("x", state.x))
        y = float(payload.get("y", state.y))
        align = payload.get("align", "left")
        if align == "center":
            x -= width / 2.0
        elif align == "right":
            x -= width
        state.drawing.add(_Color(1.0, 1.0, 1.0, 1.0))
        state.drawing.add(_Rectangle(
            texture=texture,
            pos=(x, y),
            size=(width, height),
        ))

    def _shape_instruction_group(
        self, x: float, y: float, heading: float, shape: str,
        fill_color: Any, outline_color: Any, outline_width: float,
        stretch_wid: float = 1.0, stretch_len: float = 1.0,
        custom_points: Any = None,
    ):
        """Create canvas instructions for a built-in or custom turtle shape."""
        group = _InstructionGroup()
        name = str(shape or "classic").lower()
        if name == "blank":
            return group
        scale = self.cursor_size / 14.0
        sx = scale * max(0.05, float(stretch_len))
        sy = scale * max(0.05, float(stretch_wid))
        angle = math.radians(float(heading))
        cosine, sine = math.cos(angle), math.sin(angle)

        def transform(local_x, local_y):
            lx, ly = local_x * sx, local_y * sy
            return (x + lx * cosine - ly * sine,
                    y + lx * sine + ly * cosine)

        if name == "circle":
            radius = 7.0 * min(sx, sy)
            try:
                rgba = color_to_rgba(fill_color)
            except ValueError:
                rgba = color_to_rgba("black")
            group.add(_Color(*rgba))
            group.add(_Ellipse(pos=(x - radius, y - radius), size=(2 * radius, 2 * radius)))
            if outline_width > 0:
                try:
                    edge = color_to_rgba(outline_color)
                except ValueError:
                    edge = color_to_rgba("black")
                group.add(_Color(*edge))
                group.add(_Line(circle=(x, y, radius), width=_dp(max(0.5, outline_width))))
            return group

        if name == "turtle":
            # A compact top-down turtle: shell, head, four feet and tail.
            try:
                fill_rgba = color_to_rgba(fill_color)
                edge_rgba = color_to_rgba(outline_color)
            except ValueError:
                fill_rgba = edge_rgba = color_to_rgba("green")
            body_w, body_h = 8.5 * sx, 6.5 * sy
            group.add(_Color(*fill_rgba))
            group.add(_Ellipse(pos=(x - body_w, y - body_h), size=(2 * body_w, 2 * body_h)))
            for lx, ly, radius in ((5, 7, 2.1), (5, -7, 2.1), (-5, 7, 2.1), (-5, -7, 2.1)):
                px, py = transform(lx, ly)
                r = radius * min(sx, sy)
                group.add(_Ellipse(pos=(px-r, py-r), size=(2*r, 2*r)))
            hx, hy = transform(11, 0)
            hr = 3.0 * min(sx, sy)
            group.add(_Ellipse(pos=(hx-hr, hy-hr), size=(2*hr, 2*hr)))
            tx, ty = transform(-10, 0)
            tail = (transform(-8, 2), transform(-8, -2), (tx, ty))
            group.add(_Mesh(vertices=[v for px, py in tail for v in (px, py, 0.0, 0.0)],
                            indices=[0, 1, 2], mode="triangles"))
            if outline_width > 0:
                group.add(_Color(*edge_rgba))
                group.add(_Line(circle=(x, y, max(body_w, body_h)), width=_dp(max(0.5, outline_width))))
            return group

        if custom_points is not None:
            local_points = tuple((float(px), float(py)) for px, py in custom_points)
        elif name == "square":
            local_points = ((-9, -9), (9, -9), (9, 9), (-9, 9))
        elif name == "triangle":
            local_points = ((0, 12), (-10, -8), (10, -8))
        elif name == "arrow":
            local_points = ((14, 0), (-8, 8), (-4, 0), (-8, -8))
        else:  # classic
            local_points = ((14, 0), (-10, 7), (-7, 0), (-10, -7))
        world_points = tuple(transform(px, py) for px, py in local_points)
        triangles = triangulate_polygon(world_points)
        try:
            fill_rgba = color_to_rgba(fill_color)
        except ValueError:
            fill_rgba = color_to_rgba("black")
        if triangles:
            vertices, indices = [], []
            for tri in triangles:
                for point_index in tri:
                    px, py = world_points[point_index]
                    vertices.extend((px, py, 0.0, 0.0))
                    indices.append(len(indices))
            group.add(_Color(*fill_rgba))
            group.add(_Mesh(vertices=vertices, indices=indices, mode="triangles"))
        if outline_width > 0 and world_points:
            try:
                edge_rgba = color_to_rgba(outline_color)
            except ValueError:
                edge_rgba = color_to_rgba("black")
            outline = tuple(world_points) + (world_points[0],)
            group.add(_Color(*edge_rgba))
            group.add(_Line(points=_flatten_points(outline), close=False,
                            width=_dp(max(0.5, outline_width))))
        return group

    def _refresh_cursor(self, state: _TurtleRenderState) -> None:
        state.cursor.clear()
        if not state.visible:
            return
        group = self._shape_instruction_group(
            state.x, state.y, state.heading, state.shape,
            state.fill_color, state.color, state.outline_width,
            state.stretch_wid, state.stretch_len, state.shape_points,
        )
        state.cursor.add(group)

    def _add_stamp(self, state: _TurtleRenderState, payload: Any) -> None:
        stamp_id = payload.get("stamp_id")
        if stamp_id is None:
            return
        group = self._shape_instruction_group(
            float(payload.get("x", state.x)),
            float(payload.get("y", state.y)),
            float(payload.get("heading", state.heading)),
            str(payload.get("shape", state.shape)),
            payload.get("fill_color", state.fill_color),
            payload.get("outline_color", state.color),
            float(payload.get("outline_width", state.outline_width)),
            float(payload.get("stretch_wid", state.stretch_wid)),
            float(payload.get("stretch_len", state.stretch_len)),
            payload.get("shape_points", state.shape_points),
        )
        state.stamps.add(group)
        state.stamp_groups[stamp_id] = group

    def _remove_stamp(self, state: _TurtleRenderState, stamp_id: Any) -> None:
        group = state.stamp_groups.pop(stamp_id, None)
        if group is not None:
            state.stamps.remove(group)

    def _remove_stamps(self, state: _TurtleRenderState, count: Any) -> None:
        identifiers = list(state.stamp_groups)
        if count is None or count == 0:
            selected = identifiers
        elif count > 0:
            selected = identifiers[:int(count)]
        else:
            selected = identifiers[max(0, len(identifiers) + int(count)):]
        for stamp_id in selected:
            self._remove_stamp(state, stamp_id)

    def _assert_ui_thread(self) -> None:
        if threading.get_ident() != self._ui_thread_id:
            raise RuntimeError(
                "TurtleRenderer canvas methods must run on the Kivy UI thread"
            )


__all__ = [
    "KIVY_AVAILABLE",
    "TurtleRenderer",
    "color_to_rgba",
    "cursor_vertices",
    "partial_path",
    "path_length",
    "triangulate_polygon",
    "world_to_canvas",
]
