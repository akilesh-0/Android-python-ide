"""Dedicated Kivy preview screen for Elyx Turtle graphics.

The screen owns the TurtleRenderer and exposes controls for running the
current editor buffer, stopping execution, resetting the drawing, changing
rendering mode/speed, and returning to the editor. It does not own or execute
Python code; callbacks are supplied by the host IDE.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Callable, Optional

try:
    from kivy.metrics import dp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.screenmanager import Screen
    from kivy.uix.slider import Slider
    from kivy.uix.spinner import Spinner
    KIVY_AVAILABLE = True
except ImportError:  # Engine tests can run on machines without Kivy.
    dp = lambda value: float(value)  # noqa: E731
    BoxLayout = Button = Label = Screen = Slider = Spinner = object
    KIVY_AVAILABLE = False

from .turtle_renderer import TurtleRenderer
from .turtle_commands import TurtleCommandBridge


def code_uses_turtle(code: str) -> bool:
    """Detect Turtle engine usage without matching comments or string literals.

    The detector recognises the upcoming standard ``import turtle`` API and
    the temporary Phase 3 low-level API (``TurtleCore`` plus the injected
    ``turtle_bridge``/``turtle_session_id`` names).
    """
    if not isinstance(code, str) or not code.strip():
        return False

    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, TypeError):
        # While the user is editing an incomplete program, retain a forgiving
        # fallback. It is only a preview-routing hint; compile() remains the
        # authoritative syntax check in the execution worker.
        return bool(re.search(
            r"(?m)^\s*(?:import\s+turtle\b|from\s+turtle\b|"
            r"import\s+turtle_engine\b|from\s+turtle_engine\b)", code
        ))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "turtle" or alias.name.startswith("turtle_engine")
                   for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "turtle" or module.startswith("turtle_engine"):
                return True
        elif isinstance(node, ast.Name):
            if node.id in {"TurtleCore", "turtle_bridge", "turtle_session_id"}:
                return True
    return False


def _make_button(text: str, color: tuple, *, width: Optional[float] = None) -> Any:
    kwargs = {
        "text": text,
        "size_hint_y": None,
        "height": dp(40),
        "background_normal": "",
        "background_down": "",
        "background_color": color,
        "color": (0.96, 0.96, 0.96, 1),
        "font_size": dp(13),
    }
    if width is not None:
        kwargs.update(size_hint_x=None, width=dp(width))
    return Button(**kwargs)


if KIVY_AVAILABLE:
    class TurtlePreviewScreen(Screen):
        """Full-screen Turtle workspace hosted by Elyx's ScreenManager."""

        def __init__(
            self,
            bridge: TurtleCommandBridge,
            session_id: int,
            *,
            on_back: Optional[Callable[[], None]] = None,
            on_run: Optional[Callable[[], None]] = None,
            on_stop: Optional[Callable[[], None]] = None,
            on_reset: Optional[Callable[[], None]] = None,
            **kwargs: Any,
        ) -> None:
            kwargs.setdefault("name", "turtle")
            super().__init__(**kwargs)
            if bridge is None:
                raise ValueError("bridge is required")

            self.bridge = bridge
            self.session_id = session_id
            self._on_back = on_back
            self._on_run = on_run
            self._on_stop = on_stop
            self._on_reset = on_reset
            self._running = False

            root = BoxLayout(orientation="vertical", spacing=0)

            # Header
            header = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(48),
                padding=[dp(8), dp(4)],
                spacing=dp(8),
            )
            back_button = _make_button(
                "‹ Back", (0.20, 0.21, 0.27, 1), width=72
            )
            back_button.bind(on_release=self._handle_back)
            header.add_widget(back_button)
            title_box = BoxLayout(orientation="vertical", spacing=0)
            title = Label(
                text="ELYX TURTLE",
                bold=True,
                font_size=dp(13),
                color=(0.97, 0.97, 0.97, 1),
                halign="left",
                valign="middle",
            )
            subtitle = Label(
                text="Graphics preview",
                font_size=dp(10),
                color=(0.62, 0.64, 0.72, 1),
                halign="left",
                valign="middle",
            )
            title.bind(size=lambda widget, value: setattr(widget, "text_size", value))
            subtitle.bind(size=lambda widget, value: setattr(widget, "text_size", value))
            title_box.add_widget(title)
            title_box.add_widget(subtitle)
            header.add_widget(title_box)
            self.status_label = Label(
                text="READY",
                size_hint_x=None,
                width=dp(58),
                color=(0.47, 0.86, 0.68, 1),
                font_size=dp(10),
                bold=True,
            )
            header.add_widget(self.status_label)
            root.add_widget(header)

            # Drawing options
            options = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(46),
                padding=[dp(9), dp(5)],
                spacing=dp(7),
            )
            options.add_widget(Label(
                text="Mode",
                size_hint_x=None,
                width=dp(38),
                color=(0.78, 0.79, 0.84, 1),
                font_size=dp(11),
            ))
            self.mode_spinner = Spinner(
                text="Animated",
                values=("Animated", "Instant"),
                size_hint=(None, None),
                size=(dp(105), dp(34)),
                background_normal="",
                background_color=(0.20, 0.21, 0.27, 1),
                color=(0.96, 0.96, 0.96, 1),
                font_size=dp(12),
            )
            self.mode_spinner.bind(text=self._on_mode_changed)
            options.add_widget(self.mode_spinner)
            options.add_widget(Label(
                text="Speed",
                size_hint_x=None,
                width=dp(42),
                color=(0.78, 0.79, 0.84, 1),
                font_size=dp(11),
            ))
            self.speed_slider = Slider(
                min=0.5,
                max=3.0,
                value=1.0,
                step=0.25,
                size_hint_x=1,
            )
            self.speed_slider.bind(value=self._on_speed_changed)
            options.add_widget(self.speed_slider)
            self.speed_value = Label(
                text="1.0×",
                size_hint_x=None,
                width=dp(38),
                color=(0.78, 0.79, 0.84, 1),
                font_size=dp(10),
            )
            options.add_widget(self.speed_value)
            root.add_widget(options)

            # Main drawing area. The renderer is created here, on the UI thread.
            self.renderer = TurtleRenderer(
                bridge,
                session_id,
                mode="animated",
                background_color="white",
                size_hint=(1, 1),
            )
            root.add_widget(self.renderer)

            # Action row
            actions = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(54),
                padding=[dp(8), dp(6)],
                spacing=dp(7),
            )
            self.run_button = _make_button("▶ Run", (0.16, 0.49, 0.34, 1))
            self.stop_button = _make_button("■ Stop", (0.68, 0.22, 0.20, 1))
            self.reset_button = _make_button("↻ Reset", (0.20, 0.21, 0.27, 1))
            self.run_button.bind(on_release=self._handle_run)
            self.stop_button.bind(on_release=self._handle_stop)
            self.reset_button.bind(on_release=self._handle_reset)
            self.stop_button.disabled = True
            actions.add_widget(self.run_button)
            actions.add_widget(self.stop_button)
            actions.add_widget(self.reset_button)
            root.add_widget(actions)

            self.add_widget(root)

        def on_pre_enter(self, *_args: Any) -> None:
            # Reacquire keyboard only while the Turtle workspace is visible.
            if getattr(self, "renderer", None) is not None:
                self.renderer.set_keyboard_active(True)

        def on_pre_leave(self, *_args: Any) -> None:
            # Do not steal keystrokes from the code editor when it is visible.
            if getattr(self, "renderer", None) is not None:
                self.renderer.set_keyboard_active(False)

        def _handle_back(self, *_args: Any) -> None:
            if self._on_back is not None:
                self._on_back()

        def _handle_run(self, *_args: Any) -> None:
            if self._on_run is not None:
                self._on_run()

        def _handle_stop(self, *_args: Any) -> None:
            if self._on_stop is not None:
                self._on_stop()

        def _handle_reset(self, *_args: Any) -> None:
            if self._on_reset is not None:
                self._on_reset()

        def _on_mode_changed(self, _spinner: Any, value: str) -> None:
            self.renderer.set_mode("instant" if value == "Instant" else "animated")

        def _on_speed_changed(self, _slider: Any, value: float) -> None:
            self.speed_value.text = "%.2f×" % value
            self.renderer.set_animation_scale(value)

        def set_session(self, session_id: int, *, clear: bool = True) -> None:
            self.session_id = session_id
            self.renderer.set_session(session_id, clear=clear)

        def set_running(self, running: bool) -> None:
            self._running = bool(running)
            self.run_button.disabled = self._running
            self.stop_button.disabled = not self._running

        def set_status(self, text: str) -> None:
            self.status_label.text = str(text).upper()[:12]

        def dispose(self) -> None:
            self.renderer.dispose(clear=False)
else:
    class TurtlePreviewScreen:  # pragma: no cover - requires Kivy runtime
        """Placeholder that explains why the Android preview cannot start."""

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "TurtlePreviewScreen requires Kivy and must run inside Elyx"
            )


__all__ = ["KIVY_AVAILABLE", "TurtlePreviewScreen", "code_uses_turtle"]
