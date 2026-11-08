"""Kivy-independent Python ``turtle`` compatibility layer for Elyx.

Screen input callbacks are serialized on a small daemon worker so user code is
never executed from Kivy's UI/touch/keyboard event handlers. Drawing still
travels exclusively through TurtleCommandBridge to the Kivy renderer.
"""
from __future__ import annotations

import itertools
import queue
import sys
import threading
import types
from contextlib import contextmanager
from typing import Any, Optional, Tuple

from .turtle_core import TurtleCore
from .turtle_renderer import color_to_rgba


_BUILTIN_SHAPES = ("classic", "arrow", "turtle", "circle", "square", "triangle", "blank")


class ElyxTurtle:
    """Python-facing Turtle object delegating geometry to :class:`TurtleCore`."""

    def __init__(self, runtime: "TurtleRuntime", shape: str = "classic",
                 visible: bool = True, turtle_id: Optional[str] = None, **_kwargs: Any):
        self._runtime = runtime
        self._core = runtime._new_core(turtle_id=turtle_id)
        self._shape_name = "classic"
        self._stretch = (1.0, 1.0, 1.0)
        self.shape(shape)
        if not visible:
            self._core.hideturtle()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)

    def pencolor(self, *color: Any) -> Any:
        if color:
            color_to_rgba(color[0] if len(color) == 1 else tuple(color))
        return self._core.pencolor(*color)

    def fillcolor(self, *color: Any) -> Any:
        if color:
            color_to_rgba(color[0] if len(color) == 1 else tuple(color))
        return self._core.fillcolor(*color)

    def color(self, *colors: Any) -> Any:
        # Check in the program's own thread so a bad color is an ordinary
        # exception with a traceback instead of a failure inside the renderer.
        if len(colors) == 3:
            color_to_rgba(tuple(colors))
        else:
            for value in colors[:2]:
                color_to_rgba(value)
        return self._core.color(*colors)

    def dot(self, size: Optional[float] = None, color: Any = None) -> Any:
        if color is not None:
            color_to_rgba(color)
        return self._core.dot(size, color)

    def getscreen(self) -> "ElyxScreen":
        return self._runtime.screen

    def getpen(self) -> "ElyxTurtle":
        return self

    def shape(self, name: Optional[str] = None) -> Any:
        if name is None:
            return self._shape_name
        shape_name = str(name)
        if shape_name not in self._runtime._shapes:
            raise ValueError("unknown turtle shape: %s" % shape_name)
        self._shape_name = shape_name
        self._core.shape(shape_name, points=self._runtime._shapes[shape_name])
        return self

    def shapesize(self, stretch_wid: Optional[float] = None,
                  stretch_len: Optional[float] = None,
                  outline: Optional[float] = None) -> Any:
        if stretch_wid is None and stretch_len is None and outline is None:
            return self._core.shapesize()
        result = self._core.shapesize(stretch_wid, stretch_len, outline)
        self._stretch = self._core.shapesize()
        return result

    turtlesize = shapesize

    def stamp(self) -> int:
        return self._core.stamp()

    def clearstamp(self, stampid: int) -> "ElyxTurtle":
        self._core.clearstamp(stampid)
        return self

    def clearstamps(self, n: Optional[int] = None) -> "ElyxTurtle":
        self._core.clearstamps(n)
        return self

    def clone(self) -> "ElyxTurtle":
        snapshot = self._core.snapshot()
        clone = self._runtime.new_turtle(shape=self._shape_name)
        clone._core.penup().goto(snapshot.x, snapshot.y)
        clone._core.setheading(snapshot.heading)
        clone._core.pencolor(snapshot.pen_color)
        clone._core.fillcolor(snapshot.fill_color)
        clone._core.pensize(snapshot.pen_width)
        clone._core.speed(snapshot.speed)
        clone._core.shapesize(snapshot.stretch_wid, snapshot.stretch_len,
                              snapshot.shape_outline)
        if snapshot.pen_down:
            clone._core.pendown()
        if not snapshot.visible:
            clone._core.hideturtle()
        return clone


class ElyxScreen:
    """Screen-level commands and input callback registration."""

    def __init__(self, runtime: "TurtleRuntime"):
        self._runtime = runtime
        self._background = "white"
        self._width = 800
        self._height = 600
        self._tracer = 1
        self._title = "Elyx Turtle"

    def bgcolor(self, *color: Any) -> Any:
        if not color:
            return self._background
        if len(color) == 1:
            value = color[0]
        elif len(color) in (3, 4):
            value = tuple(color)
        else:
            raise TypeError("bgcolor() accepts a color or RGB(A) values")
        color_to_rgba(value)
        self._background = value
        self._runtime._publish_screen("background", color=value)
        return value

    def clear(self) -> None:
        self._runtime._publish_screen("screen_clear")

    def reset(self) -> None:
        self._runtime._publish_screen("screen_reset", color="white")
        self._background = "white"
        for turtle in self._runtime._turtles:
            turtle._core.reset()

    def screensize(self, canvwidth: Optional[int] = None,
                   canvheight: Optional[int] = None, bg: Any = None) -> Tuple[int, int]:
        if canvwidth is not None:
            self._width = max(1, int(canvwidth))
        if canvheight is not None:
            self._height = max(1, int(canvheight))
        if bg is not None:
            self.bgcolor(bg)
        return self._width, self._height

    def tracer(self, n: Optional[int] = None, delay: Optional[int] = None) -> int:
        if n is None:
            return self._tracer
        self._tracer = max(0, int(n))
        self._runtime._publish_screen("tracer", enabled=(self._tracer != 0))
        return self._tracer

    def update(self) -> None:
        # Non-blocking: renderer commands are drained by Kivy Clock.
        return None

    def title(self, title: Optional[str] = None) -> str:
        if title is not None:
            self._title = str(title)
        return self._title

    def mode(self, mode: Optional[str] = None) -> str:
        if mode is not None and mode != "standard":
            raise NotImplementedError("Elyx currently supports standard Turtle mode only")
        return "standard"

    def window_width(self) -> int:
        return self._width

    def window_height(self) -> int:
        return self._height

    def bye(self) -> None:
        self._runtime._publish_screen("screen_clear")

    def exitonclick(self) -> None:
        # Android preview remains under Elyx navigation control.
        return None

    def onscreenclick(self, fun: Any, btn: int = 1, add: Any = None) -> None:
        self._runtime._register_click(fun, btn, add)

    onclick = onscreenclick

    def onkey(self, fun: Any, key: str) -> None:
        self._runtime._register_key(fun, key, "press")

    onkeypress = onkey

    def onkeyrelease(self, fun: Any, key: str) -> None:
        self._runtime._register_key(fun, key, "release")

    def listen(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        self._runtime._manual_listen = True
        self._runtime._publish_screen("listen", enabled=True)

    def ontimer(self, fun: Any, t: int = 0) -> None:
        self._runtime._schedule_timer(fun, t)

    def register_shape(self, name: str, shape: Any) -> None:
        self._runtime.register_shape(name, shape)

    addshape = register_shape

    def getshapes(self) -> list:
        return list(self._runtime._shapes)

    mainloop = update


class TurtleRuntime:
    """Per-execution Turtle module and serialized event callback runtime."""

    def __init__(self, bridge: Any, session_id: int):
        if bridge is None:
            raise ValueError("bridge is required")
        self.bridge = bridge
        self.session_id = session_id
        self._ids = itertools.count(2)
        self._turtles = []
        self.screen = ElyxScreen(self)
        self._default_turtle: Optional[ElyxTurtle] = None
        self._shapes = {name: None for name in _BUILTIN_SHAPES}
        self._click_callbacks = {}
        self._key_callbacks = {}
        self._timers = set()
        self._manual_listen = False
        self._event_queue = queue.Queue()
        self._event_thread = None
        self._callbacks_pending = 0
        self._event_lock = threading.RLock()
        self._closed = False

    @property
    def has_interactions(self) -> bool:
        with self._event_lock:
            return bool(self._click_callbacks or self._key_callbacks or self._timers
                        or self._callbacks_pending)

    @property
    def wants_keyboard(self) -> bool:
        with self._event_lock:
            return self._manual_listen or bool(self._key_callbacks)

    def _new_core(self, turtle_id: Optional[str] = None) -> TurtleCore:
        identifier = turtle_id or "turtle-%d" % next(self._ids)
        return TurtleCore(self.bridge, self.session_id, turtle_id=identifier)

    def new_turtle(self, *args: Any, **kwargs: Any) -> ElyxTurtle:
        turtle = ElyxTurtle(self, *args, **kwargs)
        self._turtles.append(turtle)
        return turtle

    def default_turtle(self) -> ElyxTurtle:
        if self._default_turtle is None:
            self._default_turtle = self.new_turtle(turtle_id="turtle-1")
        return self._default_turtle

    def register_shape(self, name: str, shape: Any) -> None:
        name = str(name)
        if not name:
            raise ValueError("shape name cannot be empty")
        if isinstance(shape, str):
            if shape not in self._shapes:
                raise NotImplementedError("image-file turtle shapes are not supported yet")
            self._shapes[name] = self._shapes[shape]
            return
        try:
            points = tuple((float(point[0]), float(point[1])) for point in shape)
        except (TypeError, ValueError, IndexError):
            raise TypeError("custom shapes must be a sequence of (x, y) points")
        if len(points) < 3:
            raise ValueError("custom polygon shapes need at least three points")
        for x, y in points:
            if not (x == x and y == y) or abs(x) == float("inf") or abs(y) == float("inf"):
                raise ValueError("custom shape coordinates must be finite")
        self._shapes[name] = points

    def _publish_screen(self, operation: str, **payload: Any) -> None:
        self.bridge.publish(self.session_id, "__screen__", operation, **payload)

    @staticmethod
    def _normalize_key(key: Any) -> str:
        return str(key).strip().lower()

    def _ensure_event_worker(self) -> None:
        with self._event_lock:
            if self._closed:
                return
            if self._event_thread is None or not self._event_thread.is_alive():
                self._event_thread = threading.Thread(
                    target=self._event_loop,
                    name="ElyxTurtleEvents-%s" % self.session_id,
                    daemon=True,
                )
                self._event_thread.start()

    def _enqueue_callback(self, callback: Any, args: tuple = ()) -> None:
        if callback is None:
            return
        self._ensure_event_worker()
        with self._event_lock:
            if not self._closed:
                self._callbacks_pending += 1
                self._event_queue.put((callback, args))

    def _event_loop(self) -> None:
        while True:
            item = self._event_queue.get()
            if item is None:
                return
            callback, args = item
            try:
                # The callback retains the globals of its original program.
                # Avoid mutating process-global sys.modules from this worker.
                callback(*args)
            except BaseException as exc:
                try:
                    sys.stderr.write("\nElyx Turtle callback error: %s\n" % exc)
                    sys.stderr.flush()
                except Exception:
                    pass
            finally:
                with self._event_lock:
                    self._callbacks_pending = max(0, self._callbacks_pending - 1)
                # One-shot ontimer-only programs should not leave an idle
                # event thread or an accepting command session behind. The
                # idle check and close mark are atomic against new handlers.
                self._shutdown_if_idle()

    def _register_click(self, callback: Any, button: int, add: Any) -> None:
        if isinstance(button, bool) or button not in (1, 2, 3):
            raise ValueError("onscreenclick button must be 1, 2 or 3")
        with self._event_lock:
            if self._closed:
                return
            if callback is None:
                self._click_callbacks.pop(button, None)
            elif add:
                self._click_callbacks.setdefault(button, []).append(callback)
            else:
                self._click_callbacks[button] = [callback]

    def _register_key(self, callback: Any, key: str, action: str) -> None:
        normalized = self._normalize_key(key)
        if not normalized:
            raise ValueError("key cannot be empty")
        pair = (normalized, action)
        with self._event_lock:
            if self._closed:
                return
            if callback is None:
                self._key_callbacks.pop(pair, None)
            else:
                self._key_callbacks[pair] = [callback]
            keyboard_enabled = self.wants_keyboard
        self._publish_screen("listen", enabled=keyboard_enabled)

    def dispatch_click(self, x: float, y: float, button: int = 1) -> None:
        with self._event_lock:
            callbacks = tuple(self._click_callbacks.get(button, ()))
        for callback in callbacks:
            self._enqueue_callback(callback, (float(x), float(y)))

    def dispatch_key(self, key: str, action: str = "press") -> bool:
        normalized = self._normalize_key(key)
        with self._event_lock:
            callbacks = tuple(self._key_callbacks.get((normalized, action), ()))
        for callback in callbacks:
            self._enqueue_callback(callback)
        return bool(callbacks)

    def _schedule_timer(self, callback: Any, milliseconds: int) -> None:
        if not callable(callback):
            raise TypeError("ontimer callback must be callable")
        delay = max(0, int(milliseconds)) / 1000.0
        with self._event_lock:
            if self._closed:
                return
            timer = threading.Timer(delay, self._timer_fired, args=(callback,))
            timer.daemon = True
            self._timers.add(timer)
            timer.start()

    def _timer_fired(self, callback: Any) -> None:
        current = threading.current_thread()
        # Keep timer removal and callback enqueue atomic so finish_run cannot
        # observe a false idle gap and close the runtime before this callback.
        with self._event_lock:
            self._timers.discard(current)
            self._enqueue_callback(callback)

    def _shutdown_if_idle(self) -> None:
        with self._event_lock:
            idle = not (self._click_callbacks or self._key_callbacks
                        or self._timers or self._callbacks_pending)
            if self._closed or not idle:
                return
            self._closed = True
            worker = self._event_thread
        self.bridge.finish_session(self.session_id)
        if worker is not None:
            self._event_queue.put(None)

    def close(self) -> None:
        with self._event_lock:
            if self._closed:
                return
            self._closed = True
            timers = tuple(self._timers)
            self._timers.clear()
            worker = self._event_thread
            self._click_callbacks.clear()
            self._key_callbacks.clear()
            # Drop callbacks that have not started. An already-running Python
            # callback cannot be forcibly stopped safely.
            while True:
                try:
                    self._event_queue.get_nowait()
                except queue.Empty:
                    break
            self._callbacks_pending = 0
            if worker is not None:
                self._event_queue.put(None)
        for timer in timers:
            timer.cancel()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=0.25)

    def create_module(self) -> types.ModuleType:
        module = types.ModuleType("turtle")
        module.__doc__ = (
            "Elyx Turtle graphics compatibility module. "
            "Graphics are rendered in the Elyx preview."
        )
        module.__package__ = ""
        module.__all__ = []

        def default_call(method: str):
            def call(*args: Any, **kwargs: Any) -> Any:
                return getattr(self.default_turtle(), method)(*args, **kwargs)
            call.__name__ = method
            return call

        def screen_call(method: str):
            def call(*args: Any, **kwargs: Any) -> Any:
                return getattr(self.screen, method)(*args, **kwargs)
            call.__name__ = method
            return call

        exports = {
            "Turtle": self.new_turtle,
            "Pen": self.new_turtle,
            "RawTurtle": self.new_turtle,
            "Screen": lambda: self.screen,
            "TurtleScreen": lambda *_args, **_kwargs: self.screen,
            "ElyxTurtle": ElyxTurtle,
            "ElyxScreen": ElyxScreen,
        }
        turtle_methods = (
            "forward fd backward back bk right rt left lt goto setpos setposition "
            "setx sety setheading seth home penup pu up pendown pd down isdown "
            "pencolor fillcolor color pensize width speed circle position pos xcor ycor "
            "heading isvisible showturtle st hideturtle ht clear reset "
            "begin_fill end_fill dot write shape shapesize turtlesize stamp "
            "clearstamp clearstamps"
        ).split()
        for method in turtle_methods:
            exports[method] = default_call(method)

        screen_methods = (
            "bgcolor screensize clear tracer update title mode window_width "
            "window_height bye exitonclick mainloop onscreenclick onclick onkey "
            "onkeypress onkeyrelease listen ontimer register_shape addshape getshapes"
        ).split()
        for method in screen_methods:
            exports[method] = screen_call(method)
        exports["done"] = screen_call("update")
        for name, value in exports.items():
            setattr(module, name, value)
        module.__all__ = list(exports)
        module.__dict__["_elyx_runtime"] = self
        return module


@contextmanager
def turtle_module_context(runtime: TurtleRuntime):
    """Temporarily expose this run's API as ``import turtle``."""
    missing = object()
    previous = sys.modules.get("turtle", missing)
    module = runtime.create_module()
    sys.modules["turtle"] = module
    try:
        yield module
    finally:
        if previous is missing:
            sys.modules.pop("turtle", None)
        else:
            sys.modules["turtle"] = previous


__all__ = ["ElyxTurtle", "ElyxScreen", "TurtleRuntime", "turtle_module_context"]
