"""Kivy-independent Turtle state and geometry for Elyx.

World coordinates use the familiar Turtle convention: (0, 0) is the origin,
heading 0 points right/east, heading 90 points up/north, and positive Y points
up. The renderer will translate these world coordinates to its canvas space.
"""

from dataclasses import dataclass
import math
import threading
import itertools
from typing import Any, Optional, Tuple, Union

from .turtle_commands import TurtleCommandBridge


Number = Union[int, float]
Point = Tuple[float, float]


@dataclass
class TurtleState:
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    pen_down: bool = True
    pen_color: Any = "black"
    fill_color: Any = "black"
    pen_width: float = 1.0
    speed: int = 3
    visible: bool = True
    shape: str = "classic"
    shape_points: Any = None
    stretch_wid: float = 1.0
    stretch_len: float = 1.0
    shape_outline: float = 1.0


@dataclass(frozen=True)
class TurtleSnapshot:
    x: float
    y: float
    heading: float
    pen_down: bool
    pen_color: Any
    fill_color: Any
    pen_width: float
    speed: int
    visible: bool
    shape: str = "classic"
    shape_points: Any = None
    stretch_wid: float = 1.0
    stretch_len: float = 1.0
    shape_outline: float = 1.0


class TurtleCore:
    """Stateful Turtle whose drawing operations are emitted to a bridge."""

    SPEED_NAMES = {
        "slowest": 1,
        "slow": 3,
        "normal": 6,
        "fast": 10,
        "fastest": 0,
    }

    def __init__(
        self,
        bridge: TurtleCommandBridge,
        session_id: int,
        turtle_id: str = "turtle-1",
    ) -> None:
        if bridge is None:
            raise ValueError("bridge is required")
        if not turtle_id:
            raise ValueError("turtle_id must be a non-empty string")

        self.bridge = bridge
        self.session_id = session_id
        self.turtle_id = str(turtle_id)
        self._lock = threading.RLock()
        self._state = TurtleState()
        self._filling = False
        self._fill_points = []
        self._stamp_ids = itertools.count(1)
        self._emit_cursor()

    # ---- State inspection -------------------------------------------------

    def snapshot(self) -> TurtleSnapshot:
        with self._lock:
            state = self._state
            return TurtleSnapshot(
                x=state.x,
                y=state.y,
                heading=state.heading,
                pen_down=state.pen_down,
                pen_color=state.pen_color,
                fill_color=state.fill_color,
                pen_width=state.pen_width,
                speed=state.speed,
                visible=state.visible,
                shape=state.shape,
                shape_points=state.shape_points,
                stretch_wid=state.stretch_wid,
                stretch_len=state.stretch_len,
                shape_outline=state.shape_outline,
            )

    def position(self) -> Point:
        with self._lock:
            return (self._state.x, self._state.y)

    pos = position

    def xcor(self) -> float:
        with self._lock:
            return self._state.x

    def ycor(self) -> float:
        with self._lock:
            return self._state.y

    def heading(self) -> float:
        with self._lock:
            return self._state.heading

    def isdown(self) -> bool:
        with self._lock:
            return self._state.pen_down

    # ---- Movement --------------------------------------------------------

    def forward(self, distance: Number) -> "TurtleCore":
        distance_value = self._number(distance, "distance")
        with self._lock:
            radians = math.radians(self._state.heading)
            x = self._state.x + math.cos(radians) * distance_value
            y = self._state.y + math.sin(radians) * distance_value
            self._goto_locked(x, y)
        return self

    fd = forward

    def backward(self, distance: Number) -> "TurtleCore":
        return self.forward(-self._number(distance, "distance"))

    back = backward
    bk = backward

    def right(self, angle: Number) -> "TurtleCore":
        angle_value = self._number(angle, "angle")
        with self._lock:
            self._state.heading = self._normalize_heading(
                self._state.heading - angle_value
            )
            self._emit_cursor()
        return self

    rt = right

    def left(self, angle: Number) -> "TurtleCore":
        angle_value = self._number(angle, "angle")
        with self._lock:
            self._state.heading = self._normalize_heading(
                self._state.heading + angle_value
            )
            self._emit_cursor()
        return self

    lt = left

    def goto(self, x: Union[Number, Point], y: Optional[Number] = None) -> "TurtleCore":
        target_x, target_y = self._parse_point(x, y)
        with self._lock:
            self._goto_locked(target_x, target_y)
        return self

    setpos = goto
    setposition = goto

    def setx(self, x: Number) -> "TurtleCore":
        x_value = self._number(x, "x")
        with self._lock:
            self._goto_locked(x_value, self._state.y)
        return self

    def sety(self, y: Number) -> "TurtleCore":
        y_value = self._number(y, "y")
        with self._lock:
            self._goto_locked(self._state.x, y_value)
        return self

    def setheading(self, angle: Number) -> "TurtleCore":
        angle_value = self._number(angle, "angle")
        with self._lock:
            self._state.heading = self._normalize_heading(angle_value)
            self._emit_cursor()
        return self

    seth = setheading

    def home(self) -> "TurtleCore":
        with self._lock:
            self._goto_locked(0.0, 0.0)
            self._state.heading = 0.0
            self._emit_cursor()
        return self

    # ---- Pen state -------------------------------------------------------

    def penup(self) -> "TurtleCore":
        with self._lock:
            self._state.pen_down = False
            self._emit("pen", down=False)
        return self

    pu = penup
    up = penup

    def pendown(self) -> "TurtleCore":
        with self._lock:
            self._state.pen_down = True
            self._emit("pen", down=True)
        return self

    pd = pendown
    down = pendown

    def isvisible(self) -> bool:
        with self._lock:
            return self._state.visible

    def showturtle(self) -> "TurtleCore":
        with self._lock:
            self._state.visible = True
            self._emit_cursor()
        return self

    st = showturtle

    def hideturtle(self) -> "TurtleCore":
        with self._lock:
            self._state.visible = False
            self._emit_cursor()
        return self

    ht = hideturtle

    # ---- Turtle shape and stamping --------------------------------------

    def shape(self, name: Optional[str] = None, *, points: Any = None) -> Any:
        """Get or set the visible turtle shape. ``points`` supports custom polygons."""
        with self._lock:
            if name is None:
                return self._state.shape
            shape_name = str(name)
            if not shape_name:
                raise ValueError("shape name cannot be empty")
            self._state.shape = shape_name
            self._state.shape_points = (None if points is None else tuple(tuple(p) for p in points))
            self._emit_cursor()
        return self

    def shapesize(self, stretch_wid: Optional[Number] = None,
                  stretch_len: Optional[Number] = None,
                  outline: Optional[Number] = None) -> Any:
        """Get or set the turtle shape scale and outline thickness."""
        with self._lock:
            if stretch_wid is None and stretch_len is None and outline is None:
                return (self._state.stretch_wid, self._state.stretch_len,
                        self._state.shape_outline)
            wid = self._state.stretch_wid if stretch_wid is None else self._number(stretch_wid, "stretch_wid")
            length = self._state.stretch_len if stretch_len is None else self._number(stretch_len, "stretch_len")
            edge = self._state.shape_outline if outline is None else self._number(outline, "outline")
            if wid <= 0 or length <= 0 or edge < 0:
                raise ValueError("shape stretch values must be positive and outline cannot be negative")
            self._state.stretch_wid = wid
            self._state.stretch_len = length
            self._state.shape_outline = edge
            self._emit_cursor()
        return self

    turtlesize = shapesize

    def stamp(self) -> int:
        """Leave a permanent copy of the current turtle shape on the canvas."""
        with self._lock:
            stamp_id = next(self._stamp_ids)
            state = self._state
            self._emit(
                "stamp", stamp_id=stamp_id, x=state.x, y=state.y,
                heading=state.heading, shape=state.shape,
                shape_points=state.shape_points, fill_color=state.fill_color, outline_color=state.pen_color,
                outline_width=state.shape_outline,
                stretch_wid=state.stretch_wid, stretch_len=state.stretch_len,
            )
            return stamp_id

    def clearstamp(self, stamp_id: int) -> "TurtleCore":
        if isinstance(stamp_id, bool) or not isinstance(stamp_id, int):
            raise TypeError("stamp_id must be an integer")
        with self._lock:
            self._emit("clearstamp", stamp_id=stamp_id)
        return self

    def clearstamps(self, n: Optional[int] = None) -> "TurtleCore":
        if n is not None and (isinstance(n, bool) or not isinstance(n, int)):
            raise TypeError("n must be an integer or None")
        with self._lock:
            self._emit("clearstamps", count=n)
        return self

    # ---- Drawing style ---------------------------------------------------

    def pencolor(self, *color: Any) -> Any:
        if not color:
            with self._lock:
                return self._state.pen_color

        if len(color) == 1:
            color_value = color[0]
        elif len(color) == 3:
            color_value = tuple(color)
        else:
            raise TypeError("pencolor() accepts one color or three RGB values")

        with self._lock:
            self._state.pen_color = color_value
            self._emit("style", color=color_value, width=self._state.pen_width)
        return self

    def fillcolor(self, *color: Any) -> Any:
        """Get or set the fill color used by the next filled polygon."""
        if not color:
            with self._lock:
                return self._state.fill_color
        if len(color) == 1:
            color_value = color[0]
        elif len(color) == 3:
            color_value = tuple(color)
        else:
            raise TypeError("fillcolor() accepts one color or three RGB values")
        with self._lock:
            self._state.fill_color = color_value
            self._emit_cursor()
        return self

    def color(self, *colors: Any) -> Any:
        """Get/set pen and fill colors using familiar Turtle conventions."""
        if not colors:
            with self._lock:
                return (self._state.pen_color, self._state.fill_color)
        if len(colors) == 1:
            self.pencolor(colors[0])
            self.fillcolor(colors[0])
        elif len(colors) == 2:
            self.pencolor(colors[0])
            self.fillcolor(colors[1])
        elif len(colors) == 3:
            rgb = tuple(colors)
            self.pencolor(rgb)
            self.fillcolor(rgb)
        else:
            raise TypeError("color() accepts one, two, or three color values")
        return self

    def begin_fill(self) -> "TurtleCore":
        """Begin recording a polygon path for :meth:`end_fill`."""
        with self._lock:
            self._filling = True
            self._fill_points = [(self._state.x, self._state.y)]
        return self

    def end_fill(self) -> "TurtleCore":
        """Publish the recorded polygon to the renderer."""
        with self._lock:
            if not self._filling:
                return self
            points = tuple(self._fill_points)
            self._filling = False
            self._fill_points = []
            if len(points) >= 3:
                self._emit(
                    "polygon",
                    points=points,
                    color=self._state.fill_color,
                    outline_color=self._state.pen_color,
                    outline_width=self._state.pen_width,
                )
        return self

    def dot(self, size: Optional[Number] = None, color: Any = None) -> "TurtleCore":
        """Draw a filled circular dot centered at the current position."""
        with self._lock:
            if size is None:
                dot_size = max(self._state.pen_width + 4.0,
                               self._state.pen_width * 2.0)
            else:
                dot_size = self._number(size, "size")
            if dot_size <= 0:
                raise ValueError("dot size must be greater than zero")
            color_value = self._state.pen_color if color is None else color
            self._emit("dot", x=self._state.x, y=self._state.y,
                       size=dot_size, color=color_value)
        return self

    def write(self, arg: Any, move: bool = False, align: str = "left",
              font: Any = ("Arial", 8, "normal")) -> "TurtleCore":
        """Draw text at the current position using a compact Turtle font spec."""
        if align not in ("left", "center", "right"):
            raise ValueError("align must be 'left', 'center', or 'right'")
        try:
            if len(font) != 3:
                raise ValueError
            font_name, font_size, font_style = font
        except (TypeError, ValueError):
            raise TypeError("font must be a (name, size, style) tuple")
        font_size = self._number(font_size, "font size")
        if font_size <= 0:
            raise ValueError("font size must be greater than zero")
        style = str(font_style).lower()
        if style not in ("normal", "bold", "italic", "bold italic", "italic bold"):
            raise ValueError("font style must be normal, bold, italic, or bold italic")
        text = str(arg)
        with self._lock:
            self._emit(
                "text", x=self._state.x, y=self._state.y, text=text,
                color=self._state.pen_color, align=align,
                font_name=str(font_name), font_size=font_size,
                bold=("bold" in style), italic=("italic" in style),
            )
            if move and text:
                # CoreLabel measures the final glyph width on the UI thread;
                # this estimate keeps subsequent Turtle commands deterministic.
                advance = len(text) * font_size * 0.60
                if align == "center":
                    advance = len(text) * font_size * 0.60
                self._state.x += advance
                if self._filling:
                    self._fill_points.append((self._state.x, self._state.y))
                self._emit("move", x=self._state.x, y=self._state.y)
                self._emit_cursor()
        return self

    def pensize(self, width: Optional[Number] = None) -> Any:
        if width is None:
            with self._lock:
                return self._state.pen_width

        width_value = self._number(width, "width")
        if width_value <= 0:
            raise ValueError("pen width must be greater than zero")
        with self._lock:
            self._state.pen_width = width_value
            self._emit(
                "style",
                color=self._state.pen_color,
                width=self._state.pen_width,
            )
        return self

    width = pensize

    def speed(self, value: Optional[Union[int, str]] = None) -> Any:
        if value is None:
            with self._lock:
                return self._state.speed

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in self.SPEED_NAMES:
                raise ValueError(
                    "speed must be 0-10 or one of: "
                    + ", ".join(self.SPEED_NAMES.keys())
                )
            speed_value = self.SPEED_NAMES[normalized]
        elif isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("speed must be an integer from 0 to 10 or a speed name")
        else:
            speed_value = value

        if speed_value < 0 or speed_value > 10:
            raise ValueError("speed must be between 0 and 10")
        with self._lock:
            self._state.speed = speed_value
            self._emit("speed", value=speed_value)
        return self

    # ---- Curves and lifecycle -------------------------------------------

    def circle(
        self,
        radius: Number,
        extent: Optional[Number] = None,
        steps: Optional[int] = None,
    ) -> "TurtleCore":
        radius_value = self._number(radius, "radius")
        extent_value = 360.0 if extent is None else self._number(extent, "extent")
        if steps is not None:
            if isinstance(steps, bool) or not isinstance(steps, int):
                raise TypeError("steps must be an integer")
            if steps <= 0:
                raise ValueError("steps must be greater than zero")

        if radius_value == 0 or extent_value == 0:
            return self

        with self._lock:
            state = self._state
            direction = 1.0 if radius_value > 0 else -1.0
            radius_abs = abs(radius_value)
            heading_radians = math.radians(state.heading)
            center_x = state.x - radius_value * math.sin(heading_radians)
            center_y = state.y + radius_value * math.cos(heading_radians)
            start_angle = math.radians(state.heading - direction * 90.0)
            sweep_radians = math.radians(direction * extent_value)
            segment_count = steps or max(1, int(math.ceil(abs(extent_value) / 6.0)))

            points = [(state.x, state.y)]
            for index in range(1, segment_count + 1):
                angle = start_angle + sweep_radians * (index / float(segment_count))
                px = center_x + radius_abs * math.cos(angle)
                py = center_y + radius_abs * math.sin(angle)
                points.append((px, py))

            final_x, final_y = points[-1]
            if self._filling:
                self._fill_points.extend(points[1:])
            if state.pen_down:
                self._emit(
                    "polyline",
                    points=tuple(points),
                    color=state.pen_color,
                    width=state.pen_width,
                )
            else:
                self._emit("move", x=final_x, y=final_y)

            state.x = final_x
            state.y = final_y
            state.heading = self._normalize_heading(
                state.heading + direction * extent_value
            )
            self._emit_cursor()
        return self

    def clear(self) -> "TurtleCore":
        with self._lock:
            self._filling = False
            self._fill_points = []
            self._emit("clear")
            self._emit_cursor()
        return self

    def reset(self) -> "TurtleCore":
        with self._lock:
            self._state = TurtleState()
            self._filling = False
            self._fill_points = []
            self._emit("clear")
            self._emit(
                "style",
                color=self._state.pen_color,
                width=self._state.pen_width,
            )
            self._emit("pen", down=True)
            self._emit("speed", value=self._state.speed)
            self._emit_cursor()
        return self

    # ---- Internal helpers ------------------------------------------------

    def _goto_locked(self, x: float, y: float) -> None:
        state = self._state
        old_x, old_y = state.x, state.y
        if state.pen_down:
            self._emit(
                "line",
                start=(old_x, old_y),
                end=(x, y),
                color=state.pen_color,
                width=state.pen_width,
            )
        else:
            self._emit("move", x=x, y=y)
        state.x = x
        state.y = y
        if self._filling:
            self._fill_points.append((x, y))
        self._emit_cursor()

    def _emit_cursor(self) -> None:
        state = self._state
        self._emit(
            "cursor",
            x=state.x,
            y=state.y,
            heading=state.heading,
            visible=state.visible,
            shape=state.shape,
            shape_points=state.shape_points,
            fill_color=state.fill_color,
            stretch_wid=state.stretch_wid,
            stretch_len=state.stretch_len,
            outline_width=state.shape_outline,
        )

    def _emit(self, operation: str, **payload: Any) -> None:
        self.bridge.publish(
            self.session_id,
            self.turtle_id,
            operation,
            **payload
        )

    @staticmethod
    def _number(value: Number, name: str) -> float:
        if isinstance(value, bool):
            raise TypeError("%s must be a number" % name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise TypeError("%s must be a number" % name)
        if not math.isfinite(number):
            raise ValueError("%s must be finite" % name)
        return number

    @classmethod
    def _parse_point(
        cls,
        x: Union[Number, Point],
        y: Optional[Number],
    ) -> Point:
        if y is None:
            try:
                x, y = x
            except (TypeError, ValueError):
                raise TypeError("goto() expects x and y, or a two-item point")
        return (cls._number(x, "x"), cls._number(y, "y"))

    @staticmethod
    def _normalize_heading(angle: float) -> float:
        normalized = angle % 360.0
        if math.isclose(normalized, 360.0) or math.isclose(normalized, 0.0):
            return 0.0
        return normalized
