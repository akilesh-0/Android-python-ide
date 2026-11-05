"""Kivy-independent foundations for the Elyx Turtle graphics engine."""

from .turtle_commands import TurtleCommand, TurtleCommandBridge
from .turtle_core import TurtleCore, TurtleSnapshot, TurtleState
from .turtle_api import (ElyxScreen, ElyxTurtle, TurtleRuntime, turtle_module_context)
from .turtle_renderer import (
    KIVY_AVAILABLE,
    TurtleRenderer,
    color_to_rgba,
    cursor_vertices,
    partial_path,
    path_length,
    triangulate_polygon,
    world_to_canvas,
)

__all__ = [
    "TurtleCommand",
    "TurtleCommandBridge",
    "TurtleCore",
    "TurtleSnapshot",
    "TurtleState",
    "ElyxScreen",
    "ElyxTurtle",
    "TurtleRuntime",
    "turtle_module_context",
    "KIVY_AVAILABLE",
    "TurtleRenderer",
    "color_to_rgba",
    "cursor_vertices",
    "partial_path",
    "path_length",
    "triangulate_polygon",
    "world_to_canvas",
]
