"""Thread-safe command bridge for the Elyx Turtle engine.

This module intentionally has no Kivy dependency. Python user code may publish
commands from its worker thread; a future Kivy renderer should drain commands
from the Kivy/UI thread.
"""

from dataclasses import dataclass
import queue
import threading
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class TurtleCommand:
    """One immutable envelope describing a renderer operation.

    The payload is copied when the command is created. Callers should use
    tuples and scalar values in payloads so a renderer cannot observe later
    mutations made by the producer.
    """

    session_id: int
    sequence: int
    turtle_id: str
    operation: str
    payload: Mapping[str, Any]


class TurtleCommandBridge:
    """A session-aware, thread-safe queue between Turtle and its renderer.

    A session is opened before a user program starts. ``publish`` accepts
    commands only while that session is accepting work. ``finish_session``
    stops new commands but leaves already-published commands available to the
    renderer. ``cancel_session`` invalidates the session and discards pending
    commands immediately.
    """

    def __init__(self, max_queue_size: int = 0) -> None:
        if max_queue_size < 0:
            raise ValueError("max_queue_size cannot be negative")

        self._queue = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.RLock()
        self._generation = 0
        self._active_session: Optional[int] = None
        self._accepting = False
        self._next_sequence = 0

    def start_session(self) -> int:
        """Start a fresh session and return its token.

        Any commands left over from a previous session are discarded. The
        token must be passed to every producer for that run.
        """
        with self._lock:
            self._discard_pending_locked()
            self._generation += 1
            self._active_session = self._generation
            self._accepting = True
            self._next_sequence = 0
            return self._active_session

    def publish(
        self,
        session_id: int,
        turtle_id: str,
        operation: str,
        **payload: Any
    ) -> Optional[TurtleCommand]:
        """Publish a command, or return ``None`` for a stale/closed session."""
        if not turtle_id:
            raise ValueError("turtle_id must be a non-empty string")
        if not operation:
            raise ValueError("operation must be a non-empty string")

        with self._lock:
            if (not self._accepting
                    or session_id != self._active_session):
                return None

            command = TurtleCommand(
                session_id=session_id,
                sequence=self._next_sequence,
                turtle_id=str(turtle_id),
                operation=str(operation),
                payload=MappingProxyType(dict(payload)),
            )
            self._next_sequence += 1
            try:
                self._queue.put_nowait(command)
            except queue.Full:
                raise RuntimeError("Turtle command queue is full")
            return command

    def drain(self, max_items: int = 256) -> Tuple[TurtleCommand, ...]:
        """Return up to ``max_items`` current-session commands.

        This method is intended to be called by the renderer on the Kivy main
        thread. Commands from invalidated sessions are never returned.
        """
        if max_items < 0:
            raise ValueError("max_items cannot be negative")
        if max_items == 0:
            return ()

        items = []
        with self._lock:
            active_session = self._active_session
            if active_session is None:
                return ()

            while len(items) < max_items:
                try:
                    command = self._queue.get_nowait()
                except queue.Empty:
                    break
                if command.session_id == active_session:
                    items.append(command)
        return tuple(items)

    def finish_session(self, session_id: int) -> bool:
        """Stop accepting commands while preserving queued drawing work."""
        with self._lock:
            if session_id != self._active_session:
                return False
            self._accepting = False
            return True

    def cancel_session(self, session_id: int) -> bool:
        """Invalidate a session and discard all of its queued commands."""
        with self._lock:
            if session_id != self._active_session:
                return False
            self._accepting = False
            self._active_session = None
            self._discard_pending_locked()
            return True

    def is_accepting(self, session_id: int) -> bool:
        """Return whether ``session_id`` may still publish commands."""
        with self._lock:
            return (self._accepting
                    and session_id == self._active_session)

    def pending_count(self) -> int:
        """Return the number of commands waiting to be drained."""
        return self._queue.qsize()

    def _discard_pending_locked(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
