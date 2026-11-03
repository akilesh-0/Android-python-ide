"""Python IDE for Android, built with Kivy."""

import builtins
import ctypes
import json
import keyword
import linecache
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle, Triangle
from kivy.graphics.instructions import InstructionGroup
from kivy.metrics import dp, sp
from kivy.resources import resource_find
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.codeinput import CodeInput
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.splitter import Splitter
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup, get_color_from_hex, platform
from pygments.lexers import PythonLexer
from pygments.styles import get_style_by_name
from android_storage import AndroidStorageBridge, StorageBridgeError

# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
INDENT = "    "

# Output caps: keep only the tail so long-running prints can't freeze the UI
# or exceed Kivy's maximum label texture size.
MAX_CHARS = 12000
MAX_LINES = 300
FLUSH_INTERVAL = 0.1
TRUNCATED_NOTICE = "[... earlier output truncated ...]\n"

MAX_FILE_BYTES = 1024 * 1024  # refuse to open files larger than 1 MB
INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

MONO_FONT = resource_find("data/fonts/RobotoMono-Regular.ttf") or "Roboto"

# ----------------------------------------------------------------------
# Theme (Dracula-inspired)
# ----------------------------------------------------------------------
def _c(hex_color):
    return get_color_from_hex(hex_color)


C_BG = _c("#282a36")        # editor background
C_BAR = _c("#21222c")       # app bar, toolbars
C_PANEL = _c("#1b1c25")     # console background
C_GUTTER = _c("#242530")    # line-number gutter
C_BORDER = _c("#3a3d4d")
C_TEXT = _c("#f8f8f2")
C_MUTED = _c("#6c7293")
C_ACCENT = _c("#bd93f9")
C_OUTPUT = _c("#e6e6e6")
C_BTN = _c("#343746")
C_RUN = _c("#2e8b57")
C_STOP = _c("#c0392b")
C_PRIMARY = _c("#0e639c")
C_STATUS = _c("#0e639c")
DIRTY_DOT = "[color=ffb86c]\u2022[/color] "


def pick_style():
    for name in ("dracula", "monokai"):
        try:
            get_style_by_name(name)
            return name
        except Exception:
            continue
    return "default"


# Sentinel pushed into the input queue to wake a program blocked in input().
_STOP = object()


class StopRun(BaseException):
    """Raised inside the user's program to stop it.

    Derives from BaseException so a user's `except Exception:` won't swallow it.
    """


def raise_in_thread(thread, exc_type):
    """Ask Python to raise exc_type inside another thread.

    Delivered the next time that thread executes Python bytecode, so it can't
    interrupt a long blocking call such as time.sleep(60) until it returns.
    """
    if thread is None or thread.ident is None or not thread.is_alive():
        return
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident), ctypes.py_object(exc_type)
    )


_JNI = {}


def read_ime_height():
    """Soft-keyboard height in pixels, read from Android WindowInsets (API 30+).

    Returns 0 when the keyboard is hidden and None when it can't be measured
    (not Android, old Android, or the lookup failed).
    """
    if platform != "android" or _JNI.get("dead"):
        return None
    try:
        if "decor" not in _JNI:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            _JNI["decor"] = activity.getWindow().getDecorView()
            _JNI["type"] = autoclass("android.view.WindowInsets$Type")
        insets = _JNI["decor"].getRootWindowInsets()
        if insets is None:
            return 0
        return int(insets.getInsets(_JNI["type"].ime()).bottom)
    except Exception:
        _JNI["dead"] = True
        return None


# ----------------------------------------------------------------------
# File helpers
# ----------------------------------------------------------------------
def clean_filename(name):
    """Validate a user-typed file name and make sure it ends with .py."""
    name = name.strip()
    if not name or name in (".", ".."):
        raise ValueError("Please enter a file name.")
    if INVALID_NAME_CHARS.search(name):
        raise ValueError('A name cannot contain / \\ : * ? " < > |')
    if not name.lower().endswith(".py"):
        name += ".py"
    return name


def read_text_file(path):
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise ValueError("This file is larger than 1 MB.")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_text_file(path, text):
    """Write atomically so a crash can't leave a half-written file."""
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp_path, path)


def format_size(size):
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB"


def clean_explorer_name(name):
    """Validate a single project item name (file or directory component)."""
    name = str(name).strip()
    if not name or name in (".", ".."):
        raise ValueError("Enter a valid name.")
    if len(name) > 180:
        raise ValueError("Names must be 180 characters or fewer.")
    if INVALID_NAME_CHARS.search(name):
        raise ValueError('A name cannot contain / \\: * ? " < > | or control characters.')
    if name.endswith((".", " ")):
        raise ValueError("Names cannot end with a dot or space.")
    return name


def is_path_inside(root, path, allow_root=True):
    """Return whether path resolves inside root without following outside links."""
    root = os.path.realpath(os.path.abspath(root))
    path = os.path.realpath(os.path.abspath(path))
    try:
        common = os.path.commonpath((root, path))
    except (ValueError, OSError):
        return False
    if common != root:
        return False
    return allow_root or path != root


# ----------------------------------------------------------------------
# Reusable widgets
# ----------------------------------------------------------------------
def paint(widget, color):
    """Give a widget a solid background colour."""
    with widget.canvas.before:
        Color(*color)
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(
        pos=lambda w, v: setattr(rect, "pos", v),
        size=lambda w, v: setattr(rect, "size", v),
    )


def divider():
    line = Label(size_hint_y=None, height=dp(1))
    paint(line, C_BORDER)
    return line


def make_label(text="", size=12, color=C_TEXT, halign="left", valign="middle",
               bold=False, markup=False, **kwargs):
    label = Label(
        text=text,
        font_size=sp(size),
        color=color,
        halign=halign,
        valign=valign,
        bold=bold,
        markup=markup,
        **kwargs,
    )
    label.bind(size=lambda widget, value: setattr(widget, "text_size", value))
    return label


class FlatButton(Button):
    """Flat, solid-colour button with pressed and disabled states."""

    def __init__(self, bg=C_BTN, fg=C_TEXT, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_disabled_normal", "")
        kwargs.setdefault("background_disabled_down", "")
        kwargs.setdefault("font_size", sp(13))
        super().__init__(**kwargs)
        self.bg = bg
        self.color = fg
        self.disabled_color = (fg[0], fg[1], fg[2], 0.4)
        self.bind(state=self._refresh, disabled=self._refresh)
        self._refresh()

    def _refresh(self, *args):
        r, g, b, a = self.bg
        if self.disabled:
            self.background_color = (r, g, b, 0.5)
        elif self.state == "down":
            self.background_color = (
                min(1, r + 0.14), min(1, g + 0.14), min(1, b + 0.14), a
            )
        else:
            self.background_color = self.bg


class IconButton(FlatButton):
    """Button that draws a play or stop icon instead of text."""

    def __init__(self, icon, **kwargs):
        super().__init__(**kwargs)
        self.icon = icon
        self.bind(pos=self._draw_icon, size=self._draw_icon,
                  disabled=self._draw_icon)
        self._draw_icon()

    def _draw_icon(self, *args):
        self.canvas.after.clear()
        cx, cy = self.center
        s = min(self.width, self.height) * 0.30
        alpha = 0.35 if self.disabled else 1
        with self.canvas.after:
            Color(1, 1, 1, alpha)
            if self.icon == "play":
                Triangle(points=[cx - s * 0.7, cy - s, cx - s * 0.7, cy + s,
                                 cx + s * 1.0, cy])
            else:
                Rectangle(pos=(cx - s * 0.85, cy - s * 0.85),
                          size=(s * 1.7, s * 1.7))


class ConsoleStream:
    """File-like object that replaces sys.stdout / sys.stderr.

    Writes from the running program's thread go to the IDE console; writes from
    any other thread (Kivy itself, abandoned programs) go to the original stream.
    """

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, app, fallback):
        self.app = app
        self.fallback = fallback

    def write(self, text):
        if not text:
            return 0
        if threading.current_thread() is self.app.worker:
            self.app.append_output(text)
        elif self.fallback is not None:
            try:
                self.fallback.write(text)
            except Exception:
                pass
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        pass

    def isatty(self):
        return False

    def writable(self):
        return True


class FdCapture:
    """Capture C-level writes to stdout/stderr while a program runs.

    Python's print() and tracebacks are already routed by ConsoleStream; this
    also catches output written by native code (SDL, pygame internals).
    """

    def __init__(self, sink):
        self.sink = sink
        self.saved = {}
        self.read_fd = None
        self.thread = None

    def start(self):
        if self.thread is not None:
            return
        try:
            read_fd, write_fd = os.pipe()
        except OSError:
            return
        for fd in (1, 2):
            try:
                self.saved[fd] = os.dup(fd)
                os.dup2(write_fd, fd)
            except OSError:
                self.saved.pop(fd, None)
        os.close(write_fd)
        if not self.saved:
            os.close(read_fd)
            return
        self.read_fd = read_fd
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                data = os.read(self.read_fd, 4096)
            except OSError:
                break
            if not data:
                break
            text = decoder.decode(data)
            if text:
                self.sink(text)

    def stop(self):
        if self.thread is None:
            return
        try:
            ctypes.CDLL(None).fflush(None)  # flush C stdio buffers
        except Exception:
            pass
        for fd, saved in self.saved.items():
            try:
                os.dup2(saved, fd)
            except OSError:
                pass
            try:
                os.close(saved)
            except OSError:
                pass
        self.saved = {}
        self.thread.join(1.0)
        if not self.thread.is_alive():
            try:
                os.close(self.read_fd)
            except OSError:
                pass
        self.thread = None
        self.read_fd = None


HOLD_SECONDS = 0.5  # press-and-hold selects a word on touch screens


class SmartCodeInput(CodeInput):
    """Python editor with smart indentation and its own touch scrolling.

    A quick tap places the cursor and opens the keyboard. Dragging scrolls in
    both directions (with a little momentum) without touching the keyboard.
    Press-and-hold selects the word under the finger, then lets Kivy's
    selection handles and drag-selection behaviour take over.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ide_rows = 1
        self.ide_cols = 0
        self.ide_vel = [0, 0]
        self.ide_fling = None
        label = CoreLabel(text="0", font_size=self.font_size,
                          font_name=self.font_name)
        label.refresh()
        self.ide_char_w = label.texture.width
        self.bind(text=self._ide_text_stats)
        self._ide_text_stats(self, self.text)

    # -- smart indentation ---------------------------------------------
    def paste(self):
        """Paste straight from the Android clipboard.

        Pasting through the keyboard's own clipboard panel goes via SDL's text
        input, which can mangle multi-line text; this path doesn't.
        """
        try:
            from kivy.core.clipboard import Clipboard
            data = Clipboard.paste()
        except Exception:
            data = ""
        if not data:
            return
        try:
            self._hide_cut_copy_paste()
        except Exception:
            pass
        self.delete_selection()
        # Pasted text must be inserted literally: don't create extra bracket
        # pairs when a clipboard block happens to contain a single delimiter.
        self._is_pasting = True
        try:
            self.insert_text(data)
        finally:
            self._is_pasting = False

    def insert_text(self, substring, from_undo=False):
        if substring:
            # Normalise line endings, tabs and stray NUL characters.
            substring = (substring.replace("\r\n", "\n").replace("\r", "\n")
                         .replace("\t", INDENT).replace("\x00", ""))
        if not substring:
            return

        # Smart indentation only for a single Enter keypress, not for paste.
        if substring == "\n":
            lines = self.text.split("\n")
            row = min(self.cursor_row, len(lines) - 1)
            col = self.cursor_col
            line_prefix = lines[row][:col]
            indent = line_prefix[:len(line_prefix) - len(line_prefix.lstrip(" \t"))]

            if line_prefix.rstrip().endswith(":"):
                indent += INDENT
            elif not line_prefix.strip() and indent:
                # Dedent one level when pressing Enter on a blank indented line.
                if indent.endswith(INDENT):
                    indent = indent[:-len(INDENT)]
                elif indent.endswith("\t"):
                    indent = indent[:-1]

            super().insert_text("\n" + indent, from_undo=from_undo)
            return

        # Complete pairs from the normal keyboard as well as the symbol bar.
        # Only handle a single typed character: multi-character IME input and
        # clipboard blocks must pass through unchanged.
        if (len(substring) == 1 and not from_undo
                and not getattr(self, "_is_pasting", False)):
            char = substring
            # TextInput.selection is an internal state object and can be truthy
            # even when no visible text is selected. Use the selected text itself.
            has_selection = bool(self.selection_text)
            try:
                cursor_index = self.cursor_index()
                previous_char = self.text[cursor_index - 1:cursor_index]
                next_char = self.text[cursor_index:cursor_index + 1]
            except Exception:
                previous_char = ""
                next_char = ""

            # Typing an existing closer moves over it instead of duplicating it.
            if not has_selection and char in PAIRS.values() and next_char == char:
                self.do_cursor_movement("cursor_right")
                return

            if char in PAIRS:
                # Apostrophes inside words (for example, don't) are ordinary
                # characters, not the start of a quoted string. A quote escaped
                # by a backslash should also be inserted literally.
                if (char in ("'", '"') and not has_selection
                        and (previous_char == "\\"
                             or previous_char == "_"
                             or previous_char.isalnum())):
                    super().insert_text(char, from_undo=from_undo)
                    return

                # Reuse a matching closer already at the cursor. Otherwise add
                # a new closer. Selected text is wrapped by the pair.
                closing = PAIRS[char]
                if not has_selection and next_char == closing:
                    super().insert_text(char, from_undo=from_undo)
                    return

                selected_text = self.selection_text if has_selection else ""
                super().insert_text(char + selected_text + closing,
                                    from_undo=from_undo)
                self.do_cursor_movement("cursor_left")
                return

        super().insert_text(substring, from_undo=from_undo)

    # -- scrolling -----------------------------------------------------
    def _ide_text_stats(self, instance, value):
        self.ide_rows = value.count("\n") + 1
        self.ide_cols = max(map(len, value.split("\n")))

    def _max_scroll_y(self):
        dy = self.line_height + self.line_spacing
        content = self.ide_rows * dy + self.padding[1] + self.padding[3]
        # Allow scrolling until only ~2 lines remain visible at the top.
        return max(0, content - dy * 2)

    def _max_scroll_x(self):
        content = (self.ide_cols * self.ide_char_w
                   + self.padding[0] + self.padding[2] + dp(24))
        return max(0, content - self.width)

    def _scroll_by(self, dx, dy):
        """Scroll by a finger movement; returns True if anything moved."""
        new_x = min(max(self.scroll_x - dx, 0), self._max_scroll_x())
        new_y = min(max(self.scroll_y + dy, 0), self._max_scroll_y())
        moved = new_x != self.scroll_x or new_y != self.scroll_y
        self.scroll_x = new_x
        self.scroll_y = new_y
        if moved:
            self._redraw_text()
        return moved

    def _redraw_text(self):
        # TextInput doesn't redraw its text when scroll_x/scroll_y are set from
        # outside, so the numbers moved but the text stayed. Ask it to redraw.
        try:
            self._trigger_update_graphics()
        except Exception:
            try:
                self._update_graphics()
            except Exception:
                pass

    def _start_fling(self):
        if abs(self.ide_vel[0]) + abs(self.ide_vel[1]) < dp(3):
            return
        self._stop_fling()
        self.ide_fling = Clock.schedule_interval(self._fling_step, 1 / 60.0)

    def _stop_fling(self):
        if self.ide_fling is not None:
            self.ide_fling.cancel()
            self.ide_fling = None

    def _fling_step(self, dt):
        vx, vy = self.ide_vel
        if (abs(vx) < 0.5 and abs(vy) < 0.5) or not self._scroll_by(vx, vy):
            self._stop_fling()
            return
        self.ide_vel = [vx * 0.94, vy * 0.94]

    # -- touch handling ------------------------------------------------
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if str(getattr(touch, "button", "left")).startswith("scroll"):
            return super().on_touch_down(touch)  # desktop mouse wheel

        self._stop_fling()
        touch.grab(self)
        touch.ud["ide_mode"] = "pending"
        touch.ud["ide_start"] = touch.pos
        touch.ud["ide_axis"] = None
        touch.ud["ide_hold"] = Clock.schedule_once(
            partial(self._hold_touch, touch), HOLD_SECONDS)
        return True

    def _hold_touch(self, touch, dt):
        # A stationary long press should select text, not start scrolling.
        # First let TextInput place the cursor at the finger position, then
        # select the word on the next frame (focus changes can clear selection).
        if touch.ud.get("ide_mode") == "pending":
            touch.ud["ide_mode"] = "forwarded"
            CodeInput.on_touch_down(self, touch)
            Clock.schedule_once(lambda _dt: self.select_word_at_cursor(), 0.05)

    def select_word_at_cursor(self):
        """Select the identifier/word under the current editor cursor."""
        text = self.text
        if not text:
            return False
        try:
            index = self.cursor_index()
        except Exception:
            return False
        index = max(0, min(index, len(text) - 1))

        def is_word_char(char):
            return char == "_" or char.isalnum()

        # A cursor just after a word should select that word, too.
        if not is_word_char(text[index]) and index > 0 and is_word_char(text[index - 1]):
            index -= 1

        if is_word_char(text[index]):
            start = index
            end = index + 1
            while start > 0 and is_word_char(text[start - 1]):
                start -= 1
            while end < len(text) and is_word_char(text[end]):
                end += 1
        else:
            # For punctuation, select the single character under the cursor.
            start, end = index, index + 1

        try:
            self.select_text(start, end)
            return True
        except Exception:
            return False

    def on_touch_move(self, touch):
        mode = touch.ud.get("ide_mode")
        if mode is None or touch.grab_current is not self:
            return super().on_touch_move(touch)

        if mode == "forwarded":
            return super().on_touch_move(touch)

        sx, sy = touch.ud["ide_start"]
        if mode == "pending":
            if abs(touch.x - sx) < dp(10) and abs(touch.y - sy) < dp(10):
                return True
            hold = touch.ud.get("ide_hold")
            if hold is not None:
                hold.cancel()
            ax, ay = abs(touch.x - sx), abs(touch.y - sy)
            touch.ud["ide_axis"] = "x" if ax > 1.6 * ay else (
                "y" if ay > 1.6 * ax else None)
            touch.ud["ide_mode"] = "scroll"
            dx, dy = touch.x - sx, touch.y - sy  # catch up on the slop distance
        else:
            dx, dy = touch.dx, touch.dy

        axis = touch.ud["ide_axis"]
        if axis == "x":
            dy = 0
        elif axis == "y":
            dx = 0
        self._scroll_by(dx, dy)
        self.ide_vel = [dx, dy]
        return True

    def on_touch_up(self, touch):
        mode = touch.ud.get("ide_mode")
        if mode is None or touch.grab_current is not self:
            return super().on_touch_up(touch)

        hold = touch.ud.get("ide_hold")
        if hold is not None:
            hold.cancel()

        if mode == "pending":
            # A quick tap: let TextInput place the cursor and open the keyboard.
            CodeInput.on_touch_down(self, touch)
            CodeInput.on_touch_up(self, touch)
        elif mode == "forwarded":
            CodeInput.on_touch_up(self, touch)
        elif mode == "scroll":
            self._start_fling()
        touch.ungrab(self)
        return True


class IndentationGuides:
    """Draw subtle vertical guides for active Python indentation blocks.

    Guides are attached to the editor area's background canvas, so they sit
    behind the text and never intercept touch input. Their positions follow
    the editor's horizontal and vertical scroll offsets.
    """

    def __init__(self, editor, backdrop):
        self.editor = editor
        self.group = InstructionGroup()
        backdrop.canvas.before.add(self.group)
        self._trigger = Clock.create_trigger(self.redraw, 0)
        editor.bind(
            text=self.schedule,
            scroll_x=self.schedule,
            scroll_y=self.schedule,
            pos=self.schedule,
            size=self.schedule,
            padding=self.schedule,
            font_size=self.schedule,
            font_name=self.schedule,
            tab_width=self.schedule,
        )
        self.schedule()

    def schedule(self, *args):
        self._trigger()

    @staticmethod
    def _indent_columns(line, tab_width):
        columns = 0
        for char in line:
            if char == " ":
                columns += 1
            elif char == "\t":
                columns += tab_width - (columns % tab_width)
            else:
                break
        return columns

    def redraw(self, *args):
        ed = self.editor
        self.group.clear()
        self.group.add(Color(C_MUTED[0], C_MUTED[1], C_MUTED[2], 0.30))

        dy = ed.line_height + ed.line_spacing
        if dy <= 0 or ed.width <= 0 or ed.height <= 0:
            return

        tab_width = max(1, int(getattr(ed, "tab_width", 4) or 4))
        source_lines = ed.text.split("\n")
        indents = [self._indent_columns(line, tab_width)
                   for line in source_lines]
        max_indent = max(indents, default=0)
        if max_indent < tab_width:
            return

        char_width = getattr(ed, "ide_char_w", 0)
        if not char_width:
            return

        pad_left, pad_top = ed.padding[0], ed.padding[1]
        top0 = ed.top - pad_top + ed.scroll_y
        visible_top, visible_bottom = ed.top, ed.y

        # Draw a guide only across runs belonging to an indented block.
        for level in range(tab_width, max_indent + 1, tab_width):
            active = [indent >= level for indent in indents]

            # Keep guides continuous across blank lines inside a block. Build
            # nearest nonblank neighbours in linear time for large source files.
            previous_active = [False] * len(source_lines)
            following_active = [False] * len(source_lines)
            nearest = False
            for index, line in enumerate(source_lines):
                previous_active[index] = nearest
                if line.strip():
                    nearest = indents[index] >= level
            nearest = False
            for index in range(len(source_lines) - 1, -1, -1):
                following_active[index] = nearest
                if source_lines[index].strip():
                    nearest = indents[index] >= level
            for index, line in enumerate(source_lines):
                if not line.strip():
                    active[index] = previous_active[index] and following_active[index]

            start = None
            for row, is_active in enumerate(active + [False]):
                if is_active and start is None:
                    start = row
                elif not is_active and start is not None:
                    x = ed.x + pad_left + level * char_width - ed.scroll_x
                    if ed.x <= x <= ed.right:
                        y_top = min(visible_top, top0 - start * dy)
                        y_bottom = max(visible_bottom, top0 - row * dy)
                        if y_top > y_bottom:
                            self.group.add(Line(
                                points=(x, y_bottom, x, y_top),
                                width=dp(1),
                            ))
                    start = None


class LineNumberGutter(StencilView):
    """Line numbers drawn next to a SmartCodeInput.

    Only the visible rows are drawn, using the editor's own scroll offset and
    line height so the numbers stay aligned while scrolling. It also paints a
    subtle highlight behind the current line in the editor.
    """

    def __init__(self, editor, backdrop, **kwargs):
        super().__init__(size_hint_x=None, width=dp(36), **kwargs)
        self.editor = editor
        self._textures = {}
        self._digits = 2
        self._total = editor.text.count("\n") + 1
        self._digit_width = self._render("0").width

        self.width = self._digit_width * self._digits + dp(12)

        # The highlight is drawn on the backdrop, behind the transparent
        # editor. (Drawing it inside the editor's own canvas would override
        # the colour TextInput uses for its text and make the text faint.)
        with backdrop.canvas.before:
            self._hl_color = Color(1, 1, 1, 0.05)
            self._hl_rect = Rectangle(pos=(0, 0), size=(0, 0))
            Color(1, 1, 1, 1)

        self._trigger = Clock.create_trigger(self.redraw, 0)
        editor.bind(
            scroll_y=self._schedule,
            cursor=self._schedule,
            size=self._schedule,
            pos=self._schedule,
            text=self._on_text,
        )
        self.bind(size=self._schedule, pos=self._schedule)
        self._schedule()

    def _render(self, text):
        label = CoreLabel(text=text, font_size=sp(12.5), font_name=MONO_FONT)
        label.refresh()
        return label.texture

    def _texture(self, number):
        texture = self._textures.get(number)
        if texture is None:
            if len(self._textures) > 5000:
                self._textures.clear()
            texture = self._render(str(number))
            self._textures[number] = texture
        return texture

    def _on_text(self, editor, value):
        self._total = value.count("\n") + 1
        self._schedule()

    def _schedule(self, *args):
        self._trigger()

    def redraw(self, *args):
        ed = self.editor
        dy = ed.line_height + ed.line_spacing
        if dy <= 0 or ed.height <= 0:
            return

        total = self._total
        digits = max(2, len(str(total)))
        if digits != self._digits:
            self._digits = digits
            self.width = self._digit_width * digits + dp(12)

        pad_top = ed.padding[1]
        top0 = ed.top - pad_top + ed.scroll_y  # top edge of the first line
        first = max(0, int((ed.scroll_y - pad_top) // dy) - 1)
        last = min(total - 1, int((ed.height - pad_top + ed.scroll_y) // dy) + 1)
        current = ed.cursor_row

        # Current-line highlight inside the editor (clamped to its bounds).
        cur_top = top0 - current * dy
        y0 = max(cur_top - dy, ed.y)
        y1 = min(cur_top, ed.top)
        if y1 > y0:
            self._hl_rect.pos = (ed.x, y0)
            self._hl_rect.size = (ed.width, y1 - y0)
        else:
            self._hl_rect.size = (0, 0)

        self.canvas.clear()
        with self.canvas:
            Color(*C_GUTTER)
            Rectangle(pos=self.pos, size=self.size)
            Color(*C_BORDER)
            Rectangle(pos=(self.right - 1, self.y), size=(1, self.height))
            for number in range(first, last + 1):
                row_bottom = top0 - (number + 1) * dy
                texture = self._texture(number + 1)
                Color(*(C_TEXT if number == current else C_MUTED))
                Rectangle(
                    texture=texture,
                    pos=(self.right - dp(6) - texture.width,
                         row_bottom + (dy - texture.height) / 2),
                    size=texture.size,
                )


# ----------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------
SAMPLE_CODE = (
    'name = input("What is your name? ")\n'
    'print("Hello,", name)\n'
    'print("Your Python IDE is working!")\n'
)

SYMBOLS = ["TAB", "PASTE", "(", ")", "[", "]", "{", "}", ":", '"', "'", "=", "#",
           "_", ".", ",", "+", "-", "*", "/", "<", ">"]
PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}


class PythonIDE(App):
    COMPLETIONS = sorted(set(
        keyword.kwlist
        + [name for name in dir(builtins) if not name.startswith("_")]
        + ["append", "self"]
    ))

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build(self):
        self.title = "Python IDE"
        Window.clearcolor = C_BG
        Window.softinput_mode = ""  # we lift the layout above the keyboard ourselves

        # Default app-private workspace is always available, even before a
        # project folder is selected. An imported project gets its own private
        # mirror and becomes the active editor/runtime workspace.
        self.default_workspace = os.path.join(self.user_data_dir, "workspace")
        os.makedirs(self.default_workspace, exist_ok=True)
        self.workspace = self.default_workspace
        self.active_project_root = None
        self._explorer_current_dir = self.workspace

        # Android Storage Access Framework: Stage 1/2 grants persistent access;
        # Stage 3 imports the selected tree into a private mirror. If that mirror
        # already exists, resume using it after an app restart.
        self.storage_bridge = AndroidStorageBridge(
            self.user_data_dir,
            platform_name=platform,
            on_folder_selected=self.on_project_folder_selected,
            on_error=self.on_project_folder_error,
        )
        self.project_folder = self.storage_bridge.get_saved_folder()
        if self.project_folder:
            try:
                cached_project = self.storage_bridge.project_cache_path(
                    record=self.project_folder
                )
                if os.path.isdir(cached_project):
                    self.active_project_root = cached_project
                    self.workspace = cached_project
            except Exception:
                pass

        self._explorer_current_dir = self.workspace

        # Keep the default workspace importable for the built-in file workflow.
        if self.default_workspace not in sys.path:
            sys.path.insert(0, self.default_workspace)
        self._project_import_thread = None
        self._project_sync_thread = None

        self.input_queue = queue.Queue()
        self.worker = None            # thread of the currently running program
        self.stop_requested = False
        self.output_text = ""
        self.output_truncated = False
        self.flush_pending = False
        self.output_lock = threading.Lock()

        self.current_path = None
        self.dirty = False
        self.popup = None
        self._loading = False
        self._autosave_event = None
        self._status_event = None
        self.state_text = "Ready"
        self._last_options = ()
        self._bar_current = None
        self.fd_capture = None
        self.kb_height = 0
        self._full_height = Window.height
        self._ime_works = False

        # Route print()/stderr from the running program to the console.
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = ConsoleStream(self, self._orig_stdout)
        sys.stderr = ConsoleStream(self, self._orig_stderr)

        root = BoxLayout(orientation="vertical")
        self.root_layout = root
        paint(root, C_BG)

        root.add_widget(self.build_app_bar())
        root.add_widget(divider())
        root.add_widget(self.build_symbol_bar())
        root.add_widget(self.build_editor_area())
        root.add_widget(self.build_console())
        root.add_widget(self.build_status_bar())

        Window.bind(on_keyboard=self.on_keyboard, on_key_down=self.on_key_down)
        Clock.schedule_interval(self.poll_keyboard, 0.2)

        self.editor.bind(text=self.on_editor_text, cursor=self.update_cursor)
        self.editor.bind(focus=self.on_editor_focus)
        self.editor.bind(text=self.update_suggestions,
                         cursor=self.update_suggestions)

        self.load_session()
        self.update_tab()
        self.update_cursor()
        Clock.schedule_once(self.update_suggestions, 0)
        return root

    def build_app_bar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(48),
                        padding=[dp(12), dp(6), dp(8), dp(6)], spacing=dp(8))
        paint(bar, C_BAR)

        self.tab_label = make_label(size=14, markup=True, bold=True)
        bar.add_widget(self.tab_label)

        self.file_button = FlatButton(
            text="FILE", bg=C_BTN, size_hint_x=None, width=dp(54),
            font_size=sp(12),
        )
        self.file_button.bind(on_release=self.show_file_menu)
        self.edit_button = FlatButton(
            text="EDIT", bg=C_BTN, size_hint_x=None, width=dp(54),
            font_size=sp(12),
        )
        self.edit_button.bind(on_release=self.show_edit_menu)
        self.run_button = IconButton("play", bg=C_RUN, size_hint_x=None,
                                     width=dp(56))
        self.run_button.bind(on_release=self.run_code)
        self.stop_button = IconButton("stop", bg=C_STOP, size_hint_x=None,
                                      width=dp(56), disabled=True)
        self.stop_button.bind(on_release=self.stop_code)
        bar.add_widget(self.file_button)
        bar.add_widget(self.edit_button)
        bar.add_widget(self.run_button)
        bar.add_widget(self.stop_button)
        return bar

    def build_symbol_bar(self):
        self.bar_scroll = ScrollView(
            size_hint_y=None,
            height=dp(38),
            do_scroll_x=True,
            do_scroll_y=False,
            bar_width=0,
            scroll_type=["content"],
        )
        paint(self.bar_scroll, C_BAR)

        def make_box():
            box = BoxLayout(size_hint=(None, 1), spacing=dp(4),
                            padding=[dp(6), dp(4)])
            box.bind(minimum_width=box.setter("width"))
            return box

        self.symbol_box = make_box()
        for symbol in SYMBOLS:
            button = FlatButton(
                text=symbol,
                size_hint=(None, 1),
                width=dp({"TAB": 52, "PASTE": 64}.get(symbol, 38)),
                font_size=sp(13),
            )
            button.bind(on_release=partial(self.insert_symbol, symbol))
            self.symbol_box.add_widget(button)

        self.suggest_box = make_box()
        self.show_bar(self.symbol_box)
        return self.bar_scroll

    def build_editor_area(self):
        area = BoxLayout(orientation="horizontal")
        paint(area, C_BG)

        extra = {}
        if hasattr(TextInput, "do_wrap"):
            extra["do_wrap"] = False  # keep one visual row per line number
        if hasattr(TextInput, "keyboard_suggestions"):
            extra["keyboard_suggestions"] = False  # no autocorrect in code
        if hasattr(TextInput, "use_handles"):
            extra["use_handles"] = True  # draggable selection handles on mobile

        self.editor = SmartCodeInput(
            text=SAMPLE_CODE,
            multiline=True,
            auto_indent=False,
            unfocus_on_touch=False,  # keep the keyboard up while using the symbol bar
            font_size=sp(15),
            font_name=MONO_FONT,
            foreground_color=C_TEXT,          # default colour for unstyled tokens
            background_color=(0, 0, 0, 0),    # transparent: the area paints C_BG
            background_normal="",
            background_active="",
            cursor_color=C_ACCENT,
            selection_color=(0.74, 0.58, 0.98, 0.35),
            padding=[dp(6), dp(8), dp(8), dp(8)],
            lexer=PythonLexer(),
            style_name=pick_style(),
            tab_width=4,
            **extra,
        )

        self.indent_guides = IndentationGuides(self.editor, area)
        self.gutter = LineNumberGutter(self.editor, area)
        area.add_widget(self.gutter)
        area.add_widget(self.editor)
        return area

    def build_console(self):
        self.console = Splitter(
            sizable_from="top",
            size_hint_y=None,
            height=dp(210),
            min_size=dp(90),
            max_size=dp(560),
            strip_size=dp(14),
            keep_within_parent=True,
        )
        content = BoxLayout(orientation="vertical")
        paint(content, C_PANEL)

        header = BoxLayout(size_hint_y=None, height=dp(30),
                           padding=[dp(12), 0, dp(4), 0])
        paint(header, C_BAR)
        header.add_widget(make_label("OUTPUT", size=11, color=C_MUTED, bold=True))
        clear_button = FlatButton(text="CLEAR", bg=C_BAR, fg=C_MUTED,
                                  size_hint_x=None, width=dp(64),
                                  font_size=sp(11))
        clear_button.bind(on_release=self.clear_output)
        header.add_widget(clear_button)
        content.add_widget(header)

        self.scroll = ScrollView(do_scroll_x=False, do_scroll_y=True,
                                 bar_width=dp(4), scroll_type=["bars", "content"])
        self.output_label = Label(
            text="Ready. Tap the green button to run your code.",
            size_hint_y=None,
            halign="left",
            valign="top",
            font_size=sp(13),
            font_name=MONO_FONT,
            color=C_OUTPUT,
            padding=(dp(12), dp(10)),
        )
        self.output_label.bind(width=self.update_output_width,
                               texture_size=self.update_output_height)
        self.scroll.add_widget(self.output_label)
        content.add_widget(self.scroll)

        # Shown only while the program is waiting for input().
        self.input_panel = BoxLayout(size_hint_y=None, height=0, opacity=0,
                                     disabled=True,
                                     padding=[dp(6), dp(4)], spacing=dp(6))
        paint(self.input_panel, C_BAR)
        self.input_field = TextInput(
            hint_text="Type input and press Enter",
            multiline=False,
            font_size=sp(14),
            write_tab=False,
        )
        self.style_input(self.input_field)
        self.input_field.bind(on_text_validate=self.submit_input)
        send_button = FlatButton(text="SEND", bg=C_PRIMARY, size_hint_x=None,
                                 width=dp(72))
        send_button.bind(on_release=self.submit_input)
        self.input_panel.add_widget(self.input_field)
        self.input_panel.add_widget(send_button)
        content.add_widget(self.input_panel)

        self.console.add_widget(content)
        return self.console

    def build_status_bar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(24),
                        padding=[dp(10), 0], spacing=dp(10))
        paint(bar, C_STATUS)

        self.pos_label = make_label("Ln 1, Col 1", size=11, size_hint_x=None,
                                    width=dp(100))
        self.state_label = make_label("Ready", size=11)
        info = f"Python {sys.version_info.major}.{sys.version_info.minor} \u00b7 UTF-8"
        info_label = make_label(info, size=11, halign="right", size_hint_x=None,
                                width=dp(120))
        bar.add_widget(self.pos_label)
        bar.add_widget(self.state_label)
        bar.add_widget(info_label)
        return bar

    @staticmethod
    def style_input(field):
        field.background_normal = ""
        field.background_active = ""
        field.background_color = C_BG
        field.foreground_color = C_TEXT
        field.hint_text_color = C_MUTED
        field.cursor_color = C_ACCENT
        field.padding = [dp(10), dp(12), dp(10), dp(8)]

    # ------------------------------------------------------------------
    # App lifecycle and keys
    # ------------------------------------------------------------------
    def on_pause(self):
        self.save_session()
        return True

    def on_resume(self):
        Clock.schedule_once(self.refresh_display, 0.2)

    def on_stop(self):
        self.close_game_screen()
        self.save_session()
        self.stop_capture()
        if getattr(self, "storage_bridge", None) is not None:
            self.storage_bridge.unbind()
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        raise_in_thread(self.worker, StopRun)

    def on_keyboard(self, window, key, scancode=None, codepoint=None,
                    modifier=None):
        if key != 27:  # Android back button / Esc
            return False
        game = sys.modules.get("pygame_host")
        if game is not None and game.is_open():
            game.request_close()
            return True
        if self.popup is not None:
            self.close_popup()
            return True
        if self.editor.focus:
            self.editor.focus = False
            return True
        if self.dirty:
            self.guard_unsaved(self.exit_app)
            return True
        return False

    def on_key_down(self, window, key, scancode, codepoint, modifier):
        if "ctrl" not in modifier or not codepoint:
            return False
        letter = codepoint.lower()
        if letter == "s":
            self.save_file()
        elif letter == "o":
            self.guard_unsaved(self.show_open_dialog)
        elif letter == "n":
            self.guard_unsaved(self.new_file)
        elif letter == "r":
            self.run_code(None)
        elif letter == "a":
            self.select_all_text()
        elif letter == "c":
            self.copy_selection()
        elif letter == "x":
            self.cut_selection()
        elif letter == "v":
            self.paste_clipboard()
        else:
            return False
        return True

    def on_editor_focus(self, editor, focused):
        self.refresh_console_visibility()

    def refresh_console_visibility(self):
        # While the keyboard is up for the editor, give it all the room.
        typing = self.editor.focus and self.kb_height > 0
        self.set_console_visible(not typing)

    def measure_keyboard(self):
        self._full_height = max(self._full_height, Window.height)
        shrunk = self._full_height - Window.height  # if Android resized the window
        raw = read_ime_height()
        height = Window.keyboard_height or 0
        if raw is not None:
            height = max(height, raw)
            if raw > 0:
                self._ime_works = True
        if not height and not self._ime_works:
            # Couldn't measure: assume a typical keyboard while a field has focus.
            if self.editor.focus or self.input_field.focus:
                height = int(Window.height * 0.36)
        return max(0, int(height - shrunk))

    def poll_keyboard(self, dt):
        height = self.measure_keyboard()
        if abs(height - self.kb_height) > 2:
            self.kb_height = height
            # Lift the whole layout so nothing sits behind the keyboard.
            self.root_layout.padding = [0, 0, 0, height]
            self.refresh_console_visibility()

    def set_console_visible(self, visible):
        parent = self.console.parent
        if visible and parent is None:
            self.root_layout.add_widget(self.console, index=1)  # above status bar
        elif not visible and parent is not None:
            parent.remove_widget(self.console)

    def exit_app(self):
        self.dirty = False
        self.stop()

    # ------------------------------------------------------------------
    # Status bar and tab title
    # ------------------------------------------------------------------
    def set_state(self, text):
        self.state_text = text
        if self._status_event is None:
            self.state_label.text = text

    def flash(self, message, seconds=2.5):
        if self._status_event is not None:
            self._status_event.cancel()
        self.state_label.text = message
        self._status_event = Clock.schedule_once(self._end_flash, seconds)

    def _end_flash(self, dt):
        self._status_event = None
        self.state_label.text = self.state_text

    def current_name(self):
        if self.current_path:
            return os.path.basename(self.current_path)
        return "untitled.py"

    def update_tab(self):
        dot = DIRTY_DOT if self.dirty else ""
        self.tab_label.text = dot + escape_markup(self.current_name())
        self.file_button.color = C_ACCENT if self.dirty else C_TEXT

    def update_cursor(self, *args):
        col, row = self.editor.cursor
        self.pos_label.text = f"Ln {row + 1}, Col {col + 1}"

    def set_dirty(self, flag):
        self.dirty = flag
        self.update_tab()

    # ------------------------------------------------------------------
    # Editor content, files and session
    # ------------------------------------------------------------------
    def on_editor_text(self, editor, value):
        if self._loading:
            return
        if not self.dirty:
            self.set_dirty(True)
        # Debounced draft save so an Android kill doesn't lose work.
        if self._autosave_event is not None:
            self._autosave_event.cancel()
        self._autosave_event = Clock.schedule_once(self.save_session, 2.0)

    def set_editor_text(self, text):
        self._loading = True
        try:
            self.editor.text = text
        finally:
            self._loading = False
        self.editor.cursor = (0, 0)
        self.editor.scroll_x = 0
        self.editor.scroll_y = 0
        try:
            self.editor.reset_undo()
        except Exception:
            pass

    def new_file(self):
        self.set_editor_text("")
        self.current_path = None
        self.set_dirty(False)
        self.editor.focus = True
        self.flash("New file")

    def open_file(self, path):
        try:
            text = read_text_file(path)
        except Exception as exc:
            self.show_message("Could not open file", str(exc))
            return
        self.set_editor_text(text)
        self.current_path = path
        self.set_dirty(False)
        self.save_session()
        self.flash(f"Opened {os.path.basename(path)}")

    def save_file(self, then=None):
        if not self.current_path:
            self.show_save_as(then)
            return
        self.write_current(self.current_path, then)

    def write_current(self, path, then=None):
        try:
            write_text_file(path, self.editor.text)
        except Exception as exc:
            self.show_message("Could not save file", str(exc))
            return
        self.current_path = path
        self.set_dirty(False)
        self.save_session()
        self.flash(f"Saved {os.path.basename(path)}")
        if then is not None:
            then()

    def list_files(self):
        entries = []
        try:
            names = os.listdir(self.workspace)
        except OSError:
            return entries
        for name in names:
            path = os.path.join(self.workspace, name)
            if name.lower().endswith(".py") and os.path.isfile(path):
                stat = os.stat(path)
                entries.append((name, path, stat.st_size, stat.st_mtime))
        entries.sort(key=lambda item: item[3], reverse=True)
        return entries

    def session_path(self):
        return os.path.join(self.user_data_dir, "session.json")

    def save_session(self, *args):
        data = {
            "path": self.current_path,
            "workspace": self.workspace,
            "dirty": self.dirty,
            "text": self.editor.text if self.dirty else None,
        }
        try:
            write_text_file(self.session_path(), json.dumps(data))
        except Exception:
            pass

    def load_session(self):
        try:
            with open(self.session_path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return
        path = data.get("path")
        if path:
            try:
                path_abs = os.path.abspath(path)
                root_abs = os.path.abspath(self.workspace)
                inside_workspace = os.path.commonpath((path_abs, root_abs)) == root_abs
            except (TypeError, ValueError, OSError):
                inside_workspace = False
            if not inside_workspace or not os.path.isfile(path_abs):
                path = None
            else:
                path = path_abs
        if data.get("dirty") and isinstance(data.get("text"), str):
            self.set_editor_text(data["text"])
            self.current_path = path
            self.set_dirty(True)
        elif path:
            try:
                self.set_editor_text(read_text_file(path))
                self.current_path = path
                self.set_dirty(False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Popups and dialogs
    # ------------------------------------------------------------------
    def open_popup(self, title, content, size_hint=(0.92, None),
                   height=dp(220), pos_hint=None):
        self.close_popup()
        popup = Popup(
            title=title,
            content=content,
            size_hint=size_hint,
            height=height,
            pos_hint=pos_hint or {"center_x": 0.5, "center_y": 0.5},
            background="",
            background_color=C_PANEL,
            overlay_color=(0, 0, 0, 0.65),
            separator_color=C_ACCENT,
            separator_height=dp(2),
            title_color=C_TEXT,
            title_size=sp(15),
        )
        popup.bind(on_dismiss=lambda *a: self._popup_closed(popup))
        self.popup = popup
        return popup

    def _popup_closed(self, popup):
        if self.popup is popup:
            self.popup = None

    def close_popup(self):
        popup, self.popup = self.popup, None
        if popup is not None:
            popup.dismiss()

    def show_dialog(self, title, message, actions, height=dp(210)):
        """actions: list of (label, callback or None, kind) with kind in
        'primary', 'danger' or 'neutral'."""
        self.editor.focus = False
        content = BoxLayout(orientation="vertical", padding=dp(14),
                            spacing=dp(12))
        content.add_widget(make_label(message[:400], size=14, valign="top"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = self.open_popup(title, content, height=height)
        colors = {"primary": C_PRIMARY, "danger": C_STOP}
        for label, callback, kind in actions:
            button = FlatButton(text=label, bg=colors.get(kind, C_BTN))
            button.bind(on_release=partial(self._dialog_action, popup, callback))
            row.add_widget(button)
        content.add_widget(row)
        popup.open()

    def _dialog_action(self, popup, callback, instance):
        popup.dismiss()
        if callback is not None:
            Clock.schedule_once(lambda dt: callback(), 0)

    def show_message(self, title, message):
        self.show_dialog(title, message, [("OK", None, "primary")])

    def guard_unsaved(self, then):
        """Run `then`, asking first if there are unsaved changes."""
        if not self.dirty:
            then()
            return
        self.show_dialog(
            "Unsaved changes",
            f"Save changes to {self.current_name()} before continuing?",
            [
                ("Cancel", None, "neutral"),
                ("Discard", then, "danger"),
                ("Save", lambda: self.save_file(then=then), "primary"),
            ],
        )

    def choose_project_folder(self):
        """Launch the Android system picker for a persistent project folder."""
        if platform != "android":
            self.show_message(
                "Android storage",
                "Choose Project Folder is available when this IDE runs on Android."
            )
            return
        if self.worker is not None:
            self.show_message(
                "Program is running",
                "Stop the running program before changing the project folder."
            )
            return
        if (self._project_import_thread is not None
                and self._project_import_thread.is_alive()):
            self.show_message(
                "Project import running",
                "Wait for the current project import to finish before choosing another folder."
            )
            return
        if (self._project_sync_thread is not None
                and self._project_sync_thread.is_alive()):
            self.show_message(
                "Project sync running",
                "Wait for synchronization to finish before changing the selected folder."
            )
            return
        try:
            self.storage_bridge.select_project_folder()
            self.flash("Choose a project folder in the Android picker")
        except StorageBridgeError as exc:
            self.show_message("Could not select project folder", str(exc))

    def on_project_folder_selected(self, folder):
        """Receive a folder selection after Android has persisted its grant."""
        def apply_selection(_dt):
            self.project_folder = dict(folder)
            self.flash("Project folder selected: %s" % folder.get("name", "Folder"))
        Clock.schedule_once(apply_selection, 0)

    def on_project_folder_error(self, message):
        Clock.schedule_once(
            lambda _dt: self.show_message("Project folder access", message), 0
        )

    def import_project_folder(self):
        """Import the selected SAF tree into the IDE's private project mirror."""
        if platform != "android":
            self.show_message(
                "Android storage",
                "Project import is available when the IDE runs on Android."
            )
            return
        if self.worker is not None:
            self.show_message(
                "Program is running",
                "Stop the running program before importing a project."
            )
            return
        if (self._project_import_thread is not None
                and self._project_import_thread.is_alive()):
            self.flash("A project import is already running.")
            return
        if (self._project_sync_thread is not None
                and self._project_sync_thread.is_alive()):
            self.flash("Wait for project synchronization to finish.")
            return

        folder = self.storage_bridge.get_saved_folder()
        if not folder:
            self.show_message("No project folder", "Choose a project folder first.")
            return
        if not self.storage_bridge.has_persisted_permission(folder):
            self.show_message(
                "Project access expired",
                "Choose the project folder again to restore Android storage access."
            )
            return

        self.guard_unsaved(partial(self._confirm_project_import, folder))

    def _confirm_project_import(self, folder):
        try:
            target = self.storage_bridge.project_cache_path(record=folder)
        except Exception as exc:
            self.show_message("Project import", str(exc))
            return

        if os.path.isdir(target) and os.listdir(target):
            self.show_dialog(
                "Replace local project copy?",
                "Importing again replaces the private copy with the selected "
                "storage folder. Local edits not yet synchronized back may be lost.",
                [
                    ("Cancel", None, "neutral"),
                    ("Re-import", lambda: self._start_project_import(folder, target), "danger"),
                ],
                height=dp(240),
            )
        else:
            self._start_project_import(folder, target)

    def _start_project_import(self, folder, target):
        self.set_state("Importing project...")
        self.file_button.disabled = True
        self.edit_button.disabled = True
        self.run_button.disabled = True
        self.editor.disabled = True

        def report_progress(files, byte_count):
            # Avoid flooding Kivy's event queue on projects with many small files.
            if files == 1 or files % 10 == 0:
                Clock.schedule_once(
                    partial(self._update_project_import_progress, files, byte_count), 0
                )

        def worker_main():
            try:
                stats = self.storage_bridge.import_project(
                    destination=target,
                    record=folder,
                    progress_callback=report_progress,
                )
                Clock.schedule_once(
                    partial(self._finish_project_import, folder, target, stats, None), 0
                )
            except Exception as exc:
                Clock.schedule_once(
                    partial(self._finish_project_import, folder, target, None, str(exc)), 0
                )

        self._project_import_thread = threading.Thread(
            target=worker_main, name="NovaProjectImport", daemon=True
        )
        self._project_import_thread.start()

    def _update_project_import_progress(self, files, byte_count, dt):
        size_mb = byte_count / (1024.0 * 1024.0)
        self.set_state("Importing project... %d files · %.1f MB" % (files, size_mb))

    def _finish_project_import(self, folder, target, stats, error, dt):
        self._project_import_thread = None
        self.file_button.disabled = False
        self.edit_button.disabled = False
        self.run_button.disabled = False
        self.editor.disabled = False
        if error:
            self.set_state("Ready")
            self.show_message("Project import failed", error)
            return

        # Remove stale modules from the previous project before switching roots.
        self.purge_workspace_modules()

        # Switch the editor/file browser to the imported private project copy.
        self.project_folder = dict(folder)
        self.active_project_root = target
        self.workspace = target
        self._explorer_current_dir = target
        self.current_path = None
        self.set_editor_text("")
        self.set_dirty(False)

        # Open a conventional root entry point when present; otherwise leave a
        # clean buffer so the user can choose any file from the File menu.
        entrypoint = os.path.join(target, "main.py")
        if not os.path.isfile(entrypoint):
            files = self.list_files()
            entrypoint = files[0][1] if files else None
        if entrypoint:
            self.open_file(entrypoint)
        else:
            self.save_session()

        self.set_state("Project ready")
        self.flash(
            "Imported %d files (%0.1f MB)" %
            (stats.get("files", 0), stats.get("bytes", 0) / (1024.0 * 1024.0))
        )

    def sync_project_folder(self, delete_missing=False):
        """Synchronize the active private project copy back to Android storage."""
        if platform != "android":
            self.show_message(
                "Android storage",
                "Project synchronization is available when the IDE runs on Android."
            )
            return
        if self.worker is not None:
            self.show_message(
                "Program is running",
                "Stop the running program before synchronizing the project."
            )
            return
        if (self._project_import_thread is not None
                and self._project_import_thread.is_alive()):
            self.flash("Wait for the project import to finish.")
            return
        if (self._project_sync_thread is not None
                and self._project_sync_thread.is_alive()):
            self.flash("Project synchronization is already running.")
            return

        folder = self.storage_bridge.get_saved_folder()
        if not folder:
            self.show_message("No project folder", "Choose a project folder first.")
            return
        if not self.active_project_root or not os.path.isdir(self.active_project_root):
            self.show_message(
                "No active project",
                "Import the selected project before synchronizing it."
            )
            return
        try:
            expected_root = self.storage_bridge.project_cache_path(record=folder)
            if os.path.abspath(self.active_project_root) != os.path.abspath(expected_root):
                self.show_message(
                    "Different project selected",
                    "The selected Android folder does not match the active local project. "
                    "Import the selected folder before syncing."
                )
                return
        except Exception as exc:
            self.show_message("Project synchronization", str(exc))
            return
        if not self.storage_bridge.has_persisted_permission(folder):
            self.show_message(
                "Project access expired",
                "Choose the project folder again to restore Android storage access."
            )
            return

        if self.dirty:
            if delete_missing:
                message = (
                    "The editor has unsaved changes. Save them before syncing and "
                    "deleting removed files?"
                )
            else:
                message = (
                    "The editor has unsaved changes. Save them before syncing? "
                    "You can also sync the files already saved in the project copy."
                )
            actions = [
                ("Cancel", None, "neutral"),
                ("Sync saved files", lambda: self._start_project_sync(
                    folder, self.active_project_root, delete_missing), "neutral"),
                ("Save & sync", lambda: self.save_file(then=partial(
                    self._start_project_sync, folder, self.active_project_root,
                    delete_missing)), "primary"),
            ]
            self.show_dialog("Unsaved changes", message, actions, height=dp(250))
            return

        self._start_project_sync(folder, self.active_project_root, delete_missing)

    def confirm_project_sync_with_deletions(self):
        """Ask before deleting source items that no longer exist in the local copy."""
        self.show_dialog(
            "Sync and delete removed items?",
            "This also permanently deletes files and folders in the selected Android "
            "folder when they are missing from the local project copy. Files added "
            "outside Nova IDE since the last import may also be removed. This cannot "
            "be undone.",
            [
                ("Cancel", None, "neutral"),
                ("Continue", lambda: self.sync_project_folder(delete_missing=True), "danger"),
            ],
            height=dp(270),
        )

    def _start_project_sync(self, folder, source_root, delete_missing=False):
        """Run SAF synchronization off the Kivy UI thread."""
        if (self._project_sync_thread is not None
                and self._project_sync_thread.is_alive()):
            self.flash("Project synchronization is already running.")
            return
        self.set_state("Preparing project sync...")
        self.file_button.disabled = True
        self.edit_button.disabled = True
        self.run_button.disabled = True
        self.editor.disabled = True

        def report_progress(processed, total, relative_path, action, byte_count):
            if processed == 1 or processed % 5 == 0 or processed == total:
                Clock.schedule_once(partial(
                    self._update_project_sync_progress, processed, total,
                    relative_path, action, byte_count), 0
                )

        def worker_main():
            try:
                stats = self.storage_bridge.sync_project(
                    source_root=source_root,
                    record=folder,
                    delete_missing=delete_missing,
                    progress_callback=report_progress,
                )
                Clock.schedule_once(
                    partial(self._finish_project_sync, stats, None), 0
                )
            except Exception as exc:
                Clock.schedule_once(
                    partial(self._finish_project_sync, None, str(exc)), 0
                )

        self._project_sync_thread = threading.Thread(
            target=worker_main, name="NovaProjectSync", daemon=True
        )
        self._project_sync_thread.start()

    def _update_project_sync_progress(self, processed, total, relative_path,
                                      action, byte_count, dt):
        size_mb = byte_count / (1024.0 * 1024.0)
        self.set_state(
            "Syncing %d/%d · %s · %.1f MB" %
            (processed, total, os.path.basename(relative_path), size_mb)
        )

    def _finish_project_sync(self, stats, error, dt):
        self._project_sync_thread = None
        self.file_button.disabled = False
        self.edit_button.disabled = False
        self.run_button.disabled = False
        self.editor.disabled = False
        if error:
            self.set_state("Sync incomplete")
            self.show_message(
                "Project synchronization failed",
                error + "\n\nSome earlier files may already have synchronized. "
                "Run sync again after resolving the problem."
            )
            return

        self.set_state("Project synchronized")
        summary = (
            "Created: %d\nUpdated: %d\nUnchanged: %d\n" 
            "Folders created: %d\nDeleted files: %d\nDeleted folders: %d\n" 
            "Bytes written: %.1f KB"
        ) % (
            stats.get("created", 0), stats.get("updated", 0),
            stats.get("unchanged", 0), stats.get("folders_created", 0),
            stats.get("deleted_files", 0), stats.get("deleted_folders", 0),
            stats.get("bytes", 0) / 1024.0,
        )
        if stats.get("preserved_remote_only"):
            summary += (
                "\n\n%d source-only file(s) were preserved. "
                "Use the delete-removed-items option only when you intend to remove them."
                % stats["preserved_remote_only"]
            )
        self.show_message("Project synchronized", summary)

    def show_file_menu(self, instance=None):
        """Show file and project-folder actions without shrinking the editor."""
        self.editor.focus = False
        content = BoxLayout(orientation="vertical", padding=dp(12),
                            spacing=dp(7))

        popup = self.open_popup(
            "File", content, size_hint=(0.90, None), height=dp(650)
        )

        folder = self.storage_bridge.get_saved_folder()
        if folder:
            has_access = self.storage_bridge.has_persisted_permission(folder)
            if platform == "android":
                access_text = "persistent access granted" if has_access else "access needs renewal"
            else:
                access_text = "available in Android app"
            try:
                selected_cache = self.storage_bridge.project_cache_path(record=folder)
                is_active = (self.active_project_root is not None
                             and os.path.abspath(self.active_project_root)
                             == os.path.abspath(selected_cache))
            except Exception:
                is_active = False
            active_text = ("\nlocal project copy active"
                           if is_active else "\nnot imported yet")
            folder_text = "Project folder: %s\n%s%s" % (
                folder.get("name", "Selected"), access_text, active_text
            )
        else:
            folder_text = "Project folder: not selected"
        folder_status = make_label(
            text=folder_text, size=11, color=C_MUTED,
            size_hint_y=None, height=dp(38),
        )
        content.add_widget(folder_status)

        actions = (
            ("Project explorer", self.open_project_explorer),
            ("New file", lambda: self.guard_unsaved(self.new_file)),
            ("Open file", lambda: self.guard_unsaved(self.show_open_dialog)),
            ("Save", self.save_file),
            ("Save as", self.show_save_as),
            ("Choose project folder", self.choose_project_folder),
            ("Import selected project", self.import_project_folder),
            ("Sync project to selected folder", self.sync_project_folder),
            ("Sync + delete removed items", self.confirm_project_sync_with_deletions),
        )
        for label, callback in actions:
            button = FlatButton(
                text=label, bg=C_BTN, size_hint_y=None, height=dp(48),
                halign="left", padding=[dp(16), 0],
            )
            button.bind(on_release=partial(self._dialog_action, popup, callback))
            content.add_widget(button)

        close = FlatButton(
            text="Close", bg=C_BAR, size_hint_y=None, height=dp(42)
        )
        close.bind(on_release=lambda *args: popup.dismiss())
        content.add_widget(close)
        popup.open()

    def show_edit_menu(self, instance=None):
        """Open clipboard and selection actions without shrinking the editor."""
        content = BoxLayout(orientation="vertical", padding=dp(12),
                            spacing=dp(7))
        popup = self.open_popup(
            "Edit", content, size_hint=(0.82, None), height=dp(340)
        )
        actions = (
            ("Select all", self.select_all_text),
            ("Select word", self.select_word_at_cursor),
            ("Cut", self.cut_selection),
            ("Copy", self.copy_selection),
            ("Paste", self.paste_clipboard),
        )
        for label, callback in actions:
            button = FlatButton(
                text=label, bg=C_BTN, size_hint_y=None, height=dp(48),
                halign="left", padding=[dp(16), 0],
            )
            button.bind(on_release=partial(self._dialog_action, popup, callback))
            content.add_widget(button)

        close = FlatButton(
            text="Close", bg=C_BAR, size_hint_y=None, height=dp(40)
        )
        close.bind(on_release=lambda *args: popup.dismiss())
        content.add_widget(close)
        popup.open()

    def select_all_text(self):
        # Kivy can clear selection during a focus update; schedule after the
        # popup closes so the selection remains visible.
        Clock.schedule_once(lambda _dt: self.editor.select_all(), 0.05)

    def select_word_at_cursor(self):
        self.editor.select_word_at_cursor()

    def cut_selection(self):
        selected = self.editor.selection_text
        if not selected:
            self.flash("Select code first, then tap Cut")
            return
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(selected)
            self.editor.delete_selection()
        except Exception as exc:
            self.flash("Cut failed: %s" % exc)

    def copy_selection(self):
        selected = self.editor.selection_text
        if not selected:
            self.flash("Long-press a word or select code first")
            return
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(selected)
        except Exception as exc:
            self.flash("Copy failed: %s" % exc)

    def paste_clipboard(self):
        self.editor.paste()

    def show_save_as(self, then=None):
        self.editor.focus = False
        content = BoxLayout(orientation="vertical", padding=dp(14),
                            spacing=dp(8))
        content.add_widget(make_label(
            f"Folder: {self.workspace}", size=11, color=C_MUTED, valign="top",
            size_hint_y=None, height=dp(34)))
        field = TextInput(text=self.current_name(), multiline=False,
                          font_size=sp(15), size_hint_y=None, height=dp(44),
                          write_tab=False)
        self.style_input(field)
        error = make_label("", size=12, color=C_STOP, size_hint_y=None,
                           height=dp(20))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel = FlatButton(text="Cancel")
        save = FlatButton(text="Save", bg=C_PRIMARY)
        row.add_widget(cancel)
        row.add_widget(save)
        content.add_widget(field)
        content.add_widget(error)
        content.add_widget(row)

        popup = self.open_popup("Save as", content, height=dp(280),
                                pos_hint={"center_x": 0.5, "top": 0.93})

        def do_save(*args):
            try:
                name = clean_filename(field.text)
            except ValueError as exc:
                error.text = str(exc)
                return
            path = os.path.join(self.workspace, name)
            popup.dismiss()
            if os.path.exists(path) and path != self.current_path:
                self.show_dialog(
                    "Overwrite file?",
                    f"{name} already exists. Replace it?",
                    [
                        ("Cancel", lambda: self.show_save_as(then), "neutral"),
                        ("Overwrite", lambda: self.write_current(path, then),
                         "danger"),
                    ],
                )
            else:
                Clock.schedule_once(lambda dt: self.write_current(path, then), 0)

        cancel.bind(on_release=lambda *a: popup.dismiss())
        save.bind(on_release=do_save)
        field.bind(on_text_validate=do_save)
        popup.bind(on_open=lambda *a: Clock.schedule_once(
            lambda dt: (setattr(field, "focus", True), field.select_all()), 0.1))
        popup.open()

    # ------------------------------------------------------------------
    # Project explorer (Stage 6)
    # ------------------------------------------------------------------
    def open_project_explorer(self, instance=None):
        """Open a navigable view of the active private project workspace."""
        if self.worker is not None:
            self.flash("Stop the running program before managing project files.")
            return
        if ((self._project_import_thread is not None
             and self._project_import_thread.is_alive())
                or (self._project_sync_thread is not None
                    and self._project_sync_thread.is_alive())):
            self.flash("Wait for project import or synchronization to finish.")
            return
        self.show_project_explorer(self._explorer_current_dir or self.workspace)

    def _explorer_root(self):
        return os.path.realpath(os.path.abspath(self.workspace))

    def _explorer_checked_path(self, path, allow_root=True):
        path = os.path.realpath(os.path.abspath(path))
        root = self._explorer_root()
        if not is_path_inside(root, path, allow_root=allow_root):
            raise ValueError("That item is outside the active project folder.")
        return path

    def show_project_explorer(self, directory=None):
        """Render the current folder; directory navigation stays within workspace."""
        root = self._explorer_root()
        try:
            os.makedirs(root, exist_ok=True)
            current = self._explorer_checked_path(
                directory or self._explorer_current_dir or root
            )
            if not os.path.isdir(current):
                current = root
        except Exception as exc:
            self.show_message("Project explorer", str(exc))
            return

        self._explorer_current_dir = current
        relative = os.path.relpath(current, root)
        if relative == ".":
            relative_label = "/"
        else:
            relative_label = "/" + relative.replace(os.sep, "/")

        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(7))
        path_label = make_label(
            "PROJECT  " + escape_markup(relative_label), size=12,
            color=C_ACCENT, size_hint_y=None, height=dp(30),
            markup=True,
        )
        content.add_widget(path_label)

        toolbar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
        parent = os.path.dirname(current)
        up_button = FlatButton(
            text="UP", bg=C_BTN, size_hint_x=None, width=dp(58),
            disabled=(current == root),
        )
        up_button.bind(on_release=lambda *_: self.show_project_explorer(parent))
        folder_button = FlatButton(text="+ FOLDER", bg=C_BTN)
        folder_button.bind(
            on_release=lambda *_: self._prompt_explorer_name(
                "New folder", "", partial(self._create_explorer_folder, current),
                "Folder name", return_directory=current,
            )
        )
        file_button = FlatButton(text="+ PY FILE", bg=C_BTN)
        file_button.bind(on_release=lambda *_: self._begin_explorer_new_file(current))
        refresh_button = FlatButton(
            text="↻", bg=C_BTN, size_hint_x=None, width=dp(48)
        )
        refresh_button.bind(on_release=lambda *_: self.show_project_explorer(current))
        for button in (up_button, folder_button, file_button, refresh_button):
            toolbar.add_widget(button)
        content.add_widget(toolbar)

        note = make_label(
            "Local copy · normal Sync adds/updates; Sync + delete mirrors renames/deletions",
            size=10, color=C_MUTED, size_hint_y=None, height=dp(30),
        )
        content.add_widget(note)

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True,
                            bar_width=dp(4), scroll_type=["bars", "content"])
        entries_box = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(3),
            padding=[0, dp(2), 0, dp(4)],
        )
        entries_box.bind(minimum_height=entries_box.setter("height"))

        entries = []
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    # Do not follow symlinks: they may point outside the project
                    # or create directory cycles in the explorer.
                    if entry.is_symlink():
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            entries.append((0, entry.name, entry.path, 0, 0))
                        elif entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            entries.append((1, entry.name, entry.path,
                                            stat.st_size, stat.st_mtime))
                    except OSError:
                        continue
        except OSError as exc:
            self.show_message("Could not read folder", str(exc))
            return

        entries.sort(key=lambda item: (item[0], item[1].casefold()))
        if not entries:
            entries_box.add_widget(make_label(
                "This folder is empty.\nCreate a folder or Python file to get started.",
                size=13, color=C_MUTED, halign="center", size_hint_y=None,
                height=dp(100),
            ))
        else:
            for kind, name, path, size, mtime in entries:
                entries_box.add_widget(self.make_explorer_row(
                    kind, name, path, size, mtime, current
                ))
        scroll.add_widget(entries_box)
        content.add_widget(scroll)

        close = FlatButton(
            text="Close", bg=C_BAR, size_hint_y=None, height=dp(42)
        )
        content.add_widget(close)
        title = "Project Explorer"
        if self.active_project_root:
            title += " · " + os.path.basename(root)
        popup = self.open_popup(title, content, size_hint=(0.97, 0.88))
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        return popup

    def make_explorer_row(self, kind, name, path, size, mtime, current_dir):
        row = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(4))
        if kind == 0:
            title = "▸  " + escape_markup(name)
            detail = "Folder"
        else:
            title = "    " + escape_markup(name)
            extension = os.path.splitext(name)[1].lower() or "File"
            detail = "%s · %s" % (format_size(size), extension)
        label = "%s\n[size=%d][color=8b93b5]%s[/color][/size]" % (
            title, int(sp(10)), escape_markup(detail)
        )
        open_button = FlatButton(
            text=label, bg=C_BTN, markup=True, halign="left",
            valign="middle", font_size=sp(13),
        )
        open_button.bind(
            size=lambda widget, value: setattr(
                widget, "text_size", (max(0, value[0] - dp(16)), value[1])
            )
        )
        if kind == 0:
            open_button.bind(
                on_release=partial(self._explorer_open_directory, path)
            )
        else:
            open_button.bind(on_release=partial(self._explorer_open_file, path))

        rename_button = FlatButton(
            text="REN", bg=C_BTN, size_hint_x=None, width=dp(48),
            font_size=sp(10),
        )
        rename_button.bind(on_release=partial(self._explorer_rename_item, path))
        delete_button = FlatButton(
            text="DEL", bg=C_BTN, fg=_c("#ff7b72"),
            size_hint_x=None, width=dp(48), font_size=sp(10),
        )
        delete_button.bind(on_release=partial(self._explorer_confirm_delete, path))
        row.add_widget(open_button)
        row.add_widget(rename_button)
        row.add_widget(delete_button)
        return row

    def _explorer_open_directory(self, path, instance=None):
        try:
            path = self._explorer_checked_path(path)
            if not os.path.isdir(path):
                raise ValueError("This folder no longer exists.")
        except Exception as exc:
            self.show_message("Project explorer", str(exc))
            return
        self.show_project_explorer(path)

    def _explorer_open_file(self, path, instance=None):
        try:
            path = self._explorer_checked_path(path, allow_root=False)
            if not os.path.isfile(path):
                raise ValueError("This file no longer exists.")
        except Exception as exc:
            self.show_message("Project explorer", str(exc))
            return
        if os.path.splitext(path)[1].lower() != ".py":
            relative = os.path.relpath(path, self._explorer_root()).replace(os.sep, "/")
            self.flash("Asset file: use the relative path %s" % relative, seconds=4)
            return
        self.close_popup()
        if path == self.current_path and not self.dirty:
            return
        self.guard_unsaved(lambda: self.open_file(path))

    def _prompt_explorer_name(self, title, initial, callback, hint,
                              return_directory=None):
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        field = TextInput(
            text=initial, hint_text=hint, multiline=False, font_size=sp(15),
            size_hint_y=None, height=dp(46), write_tab=False,
        )
        self.style_input(field)
        error = make_label(
            "", size=11, color=C_STOP, size_hint_y=None, height=dp(28),
        )
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        cancel = FlatButton(text="Cancel", bg=C_BTN)
        save = FlatButton(
            text=("Apply" if title.lower().startswith("rename") else "Create"),
            bg=C_PRIMARY,
        )
        actions.add_widget(cancel)
        actions.add_widget(save)
        content.add_widget(field)
        content.add_widget(error)
        content.add_widget(actions)
        popup = self.open_popup(title, content, size_hint=(0.90, None), height=dp(205))

        def submit(*_args):
            try:
                name = clean_explorer_name(field.text)
            except ValueError as exc:
                error.text = str(exc)
                return
            popup.dismiss()
            Clock.schedule_once(lambda _dt: callback(name), 0)

        def cancel_prompt(*_args):
            popup.dismiss()
            if return_directory is not None:
                Clock.schedule_once(
                    lambda _dt: self.show_project_explorer(return_directory), 0
                )

        cancel.bind(on_release=cancel_prompt)
        save.bind(on_release=submit)
        field.bind(on_text_validate=submit)
        popup.bind(on_open=lambda *_: Clock.schedule_once(
            lambda _dt: setattr(field, "focus", True), 0.1
        ))
        popup.open()

    def _create_explorer_folder(self, name, parent):
        try:
            parent = self._explorer_checked_path(parent)
            target = os.path.join(parent, name)
            if not is_path_inside(self._explorer_root(), target, allow_root=False):
                raise ValueError("Invalid folder location.")
            if os.path.lexists(target):
                raise FileExistsError("An item with that name already exists.")
            os.mkdir(target)
        except Exception as exc:
            self.show_message("Could not create folder", str(exc))
            return
        self.flash("Created folder %s" % name)
        self.show_project_explorer(parent)

    def _begin_explorer_new_file(self, parent):
        if self.dirty:
            self.guard_unsaved(lambda: self._prompt_explorer_new_file(parent))
        else:
            self._prompt_explorer_new_file(parent)

    def _prompt_explorer_new_file(self, parent):
        self._prompt_explorer_name(
            "New Python file", "", partial(self._create_explorer_file, parent),
            "example.py", return_directory=parent,
        )

    def _create_explorer_file(self, name, parent):
        try:
            filename = clean_filename(name)
            parent = self._explorer_checked_path(parent)
            target = os.path.join(parent, filename)
            if not is_path_inside(self._explorer_root(), target, allow_root=False):
                raise ValueError("Invalid file location.")
            with open(target, "x", encoding="utf-8", newline="\n"):
                pass
        except FileExistsError:
            self.show_message("File already exists", "Choose a different filename.")
            return
        except Exception as exc:
            self.show_message("Could not create file", str(exc))
            return
        self.close_popup()
        self.current_path = target
        self.set_editor_text("")
        self.set_dirty(False)
        self.save_session()
        self.flash("Created %s" % filename)

    def _explorer_rename_item(self, path, instance=None):
        try:
            path = self._explorer_checked_path(path, allow_root=False)
            if not os.path.lexists(path):
                raise FileNotFoundError("This item no longer exists.")
        except Exception as exc:
            self.show_message("Could not rename item", str(exc))
            return
        parent = os.path.dirname(path)
        old_name = os.path.basename(path)
        self._prompt_explorer_name(
            "Rename item", old_name,
            partial(self._rename_explorer_item, path, parent),
            "New name", return_directory=self._explorer_current_dir,
        )

    def _rename_explorer_item(self, old_path, parent, new_name):
        try:
            old_path = self._explorer_checked_path(old_path, allow_root=False)
            parent = self._explorer_checked_path(parent)
            new_name = clean_explorer_name(new_name)
            new_path = os.path.join(parent, new_name)
            if not is_path_inside(self._explorer_root(), new_path, allow_root=False):
                raise ValueError("Invalid destination.")
            if not os.path.lexists(old_path):
                raise FileNotFoundError("The original item no longer exists.")
            if os.path.abspath(old_path) == os.path.abspath(new_path):
                self.show_project_explorer(parent)
                return
            if os.path.lexists(new_path):
                raise FileExistsError("An item with that name already exists.")
            os.rename(old_path, new_path)

            # Keep an open editor buffer attached to its renamed file or folder.
            if self.current_path and is_path_inside(old_path, self.current_path):
                relative_file = os.path.relpath(self.current_path, old_path)
                self.current_path = (new_path if relative_file == "."
                                     else os.path.join(new_path, relative_file))
                self.update_tab()
                self.save_session()

            # Preserve the explorer location when a containing folder is renamed.
            old_dir = self._explorer_current_dir
            if is_path_inside(old_path, old_dir):
                relative_dir = os.path.relpath(old_dir, old_path)
                self._explorer_current_dir = (
                    new_path if relative_dir == "."
                    else os.path.join(new_path, relative_dir)
                )
            else:
                self._explorer_current_dir = parent
        except Exception as exc:
            self.show_message("Could not rename item", str(exc))
            return
        self.flash("Renamed to %s" % new_name)
        self.show_project_explorer(self._explorer_current_dir)

    def _explorer_confirm_delete(self, path, instance=None):
        try:
            path = self._explorer_checked_path(path, allow_root=False)
            if not os.path.lexists(path):
                raise FileNotFoundError("This item no longer exists.")
        except Exception as exc:
            self.show_message("Could not delete item", str(exc))
            return
        name = os.path.basename(path)
        is_folder = os.path.isdir(path) and not os.path.islink(path)
        item_kind = "folder and all its contents" if is_folder else "file"
        self.show_dialog(
            "Delete project item?",
            "Delete %s '%s' from the local project copy? This cannot be undone. "
            "The original Android folder is changed only after using Sync + delete removed items." %
            (item_kind, name),
            [
                ("Cancel", lambda: self.show_project_explorer(
                    self._explorer_current_dir), "neutral"),
                ("Delete", lambda: self._delete_explorer_item(path), "danger"),
            ],
            height=dp(255),
        )

    def _delete_explorer_item(self, path):
        try:
            path = self._explorer_checked_path(path, allow_root=False)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

            # Preserve unsaved text in memory, but detach it from the removed file.
            if self.current_path and is_path_inside(path, self.current_path):
                self.current_path = None
                self.set_dirty(True)
                self.save_session()

            current_dir = self._explorer_current_dir
            if is_path_inside(path, current_dir):
                current_dir = os.path.dirname(path)
            self._explorer_current_dir = current_dir
        except Exception as exc:
            self.show_message("Could not delete item", str(exc))
            return
        self.flash("Deleted %s" % os.path.basename(path))
        self.show_project_explorer(self._explorer_current_dir)

    def show_open_dialog(self):
        self.editor.focus = False
        files = self.list_files()
        content = BoxLayout(orientation="vertical", padding=dp(10),
                            spacing=dp(8))
        content.add_widget(make_label(
            f"Folder: {self.workspace}", size=11, color=C_MUTED, valign="top",
            size_hint_y=None, height=dp(34)))

        if not files:
            content.add_widget(make_label(
                "No saved files yet.\nWrite some code and choose File → Save.",
                size=14, color=C_MUTED, halign="center"))
        else:
            scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
            box = BoxLayout(orientation="vertical", size_hint_y=None,
                            spacing=dp(4))
            box.bind(minimum_height=box.setter("height"))
            for name, path, size, mtime in files:
                box.add_widget(self.make_file_row(name, path, size, mtime))
            scroll.add_widget(box)
            content.add_widget(scroll)

        close = FlatButton(text="Close", size_hint_y=None, height=dp(44))
        content.add_widget(close)
        popup = self.open_popup("Open file", content, size_hint=(0.94, 0.72))
        close.bind(on_release=lambda *a: popup.dismiss())
        popup.open()

    def make_file_row(self, name, path, size, mtime):
        row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(4))
        stamp = time.strftime("%d %b %H:%M", time.localtime(mtime))
        marker = DIRTY_DOT if path == self.current_path else ""
        label = (f"{marker}{escape_markup(name)}\n"
                 f"[size={int(sp(11))}][color=8b93b5]{format_size(size)}"
                 f"  \u00b7  {stamp}[/color][/size]")
        open_button = FlatButton(text=label, markup=True, halign="left",
                                 valign="middle", font_size=sp(14))
        open_button.bind(
            size=lambda w, s: setattr(w, "text_size", (s[0] - dp(20), s[1])))
        open_button.bind(on_release=partial(self.pick_file, path))
        delete_button = FlatButton(text="DEL", bg=C_BTN, fg=_c("#ff7b72"),
                                   size_hint_x=None, width=dp(56),
                                   font_size=sp(12))
        delete_button.bind(on_release=partial(self.confirm_delete, name, path))
        row.add_widget(open_button)
        row.add_widget(delete_button)
        return row

    def pick_file(self, path, instance):
        self.close_popup()
        if path == self.current_path and not self.dirty:
            return
        self.guard_unsaved(lambda: self.open_file(path))

    def confirm_delete(self, name, path, instance):
        self.show_dialog(
            "Delete file?",
            f"Delete {name}? This cannot be undone.",
            [
                ("Cancel", self.show_open_dialog, "neutral"),
                ("Delete", lambda: self.delete_file(path), "danger"),
            ],
        )

    def delete_file(self, path):
        try:
            os.remove(path)
        except Exception as exc:
            self.show_message("Could not delete file", str(exc))
            return
        if path == self.current_path:
            # Keep the text in the editor, but it is no longer backed by a file.
            self.current_path = None
            self.set_dirty(True)
        self.flash(f"Deleted {os.path.basename(path)}")
        self.show_open_dialog()

    # ------------------------------------------------------------------
    # Output console
    # ------------------------------------------------------------------
    def update_output_width(self, label, width):
        label.text_size = (max(0, width - dp(24)), None)

    def update_output_height(self, label, size):
        label.height = max(size[1] + dp(20), dp(40))
        Clock.schedule_once(self.scroll_to_bottom, 0.05)

    def scroll_to_bottom(self, dt):
        self.scroll.scroll_y = 0

    def append_output(self, text):
        """Thread-safe. Buffers text and schedules one batched UI refresh."""
        schedule = False
        with self.output_lock:
            self.output_text += str(text)
            # Trim the buffer itself so memory stays bounded.
            if len(self.output_text) > MAX_CHARS * 2:
                self.output_text = self.output_text[-MAX_CHARS:]
                self.output_truncated = True
            if not self.flush_pending:
                self.flush_pending = True
                schedule = True
        if schedule:
            Clock.schedule_once(self.flush_output, FLUSH_INTERVAL)

    def flush_output(self, dt):
        with self.output_lock:
            text = self.output_text
            truncated = self.output_truncated
            self.flush_pending = False

        lines = text.split("\n")
        if len(lines) > MAX_LINES:
            lines = lines[-MAX_LINES:]
            truncated = True
        text = "\n".join(lines)
        if len(text) > MAX_CHARS:
            text = text[-MAX_CHARS:]
            truncated = True
        if truncated:
            text = TRUNCATED_NOTICE + text

        self.output_label.text = text

    def clear_output(self, instance=None):
        with self.output_lock:
            self.output_text = ""
            self.output_truncated = False
        self.output_label.text = ""
        self.scroll.scroll_y = 0

    # ------------------------------------------------------------------
    # input() support
    # ------------------------------------------------------------------
    def request_input(self, prompt=""):
        if prompt:
            self.append_output(str(prompt))
        Clock.schedule_once(self.show_input_panel, 0)
        answer = self.input_queue.get()
        if answer is _STOP:
            raise StopRun()
        return answer

    def show_input_panel(self, dt):
        if self.worker is None:
            return
        self.set_console_visible(True)
        self.input_panel.height = dp(46)
        self.input_panel.opacity = 1
        self.input_panel.disabled = False
        self.input_field.text = ""
        self.input_field.focus = True
        self.set_state("Waiting for input...")

    def hide_input_panel(self):
        self.input_panel.height = 0
        self.input_panel.opacity = 0
        self.input_panel.disabled = True
        self.input_field.focus = False

    def submit_input(self, instance):
        if self.worker is None:
            return
        answer = self.input_field.text
        self.hide_input_panel()
        self.set_state("Running...")
        self.append_output(answer + "\n")
        self.input_queue.put(answer)

    # ------------------------------------------------------------------
    # Symbol bar and autocomplete
    # ------------------------------------------------------------------
    def show_bar(self, box):
        if self._bar_current is box:
            return
        self.bar_scroll.clear_widgets()
        self.bar_scroll.add_widget(box)
        self.bar_scroll.scroll_x = 0
        self._bar_current = box

    def insert_symbol(self, symbol, instance):
        editor = self.editor
        if symbol == "TAB":
            editor.insert_text(INDENT)
        elif symbol == "PASTE":
            editor.paste()
        elif symbol in PAIRS:
            editor.insert_text(symbol + PAIRS[symbol])
            editor.do_cursor_movement("cursor_left")
        else:
            editor.insert_text(symbol)
        editor.focus = True

    def update_suggestions(self, *args):
        prefix = ""
        try:
            index = self.editor.cursor_index()
            before = self.editor.text[max(0, index - 64):index]
            match = re.search(r"[A-Za-z_]\w*$", before)
            prefix = match.group(0) if match else ""
        except Exception:
            pass

        options = ()
        if prefix:
            options = tuple(
                item for item in self.COMPLETIONS
                if item.startswith(prefix) and item != prefix
            )[:8]

        if not options:
            self._last_options = ()
            self.show_bar(self.symbol_box)
            return

        if options != self._last_options:
            self.suggest_box.clear_widgets()
            for option in options:
                button = FlatButton(
                    text=option,
                    bg=_c("#3d4157"),
                    fg=C_ACCENT,
                    size_hint=(None, 1),
                    width=dp(max(64, min(130, len(option) * 9 + 24))),
                    font_size=sp(13),
                )
                button.bind(on_release=partial(self.apply_completion, option))
                self.suggest_box.add_widget(button)
            self._last_options = options
        self.show_bar(self.suggest_box)

    def apply_completion(self, completion, instance):
        editor = self.editor
        # A completion should only replace the identifier immediately before
        # the cursor; don't disturb a user's active selection.
        if editor.selection_text:
            return

        index = editor.cursor_index()
        before = editor.text[:index]
        match = re.search(r"[A-Za-z_]\w*$", before)
        if not match:
            return

        # Use normal backspace/insert operations so TextInput's undo stack,
        # syntax highlighting and change bindings remain in sync.
        for _ in match.group(0):
            editor.do_backspace()
        editor.insert_text(completion)
        editor.focus = True

    # ------------------------------------------------------------------
    # Running and stopping code
    # ------------------------------------------------------------------
    def run_code(self, instance):
        if self.worker is not None:
            self.flash("A program is already running.")
            return
        if (self._project_import_thread is not None
                and self._project_import_thread.is_alive()):
            self.flash("Wait for the project import to finish.")
            return
        if (self._project_sync_thread is not None
                and self._project_sync_thread.is_alive()):
            self.flash("Wait for project synchronization to finish.")
            return

        code = self.editor.text
        if not code.strip():
            self.flash("Nothing to run.")
            return

        self.editor.focus = False  # hide the keyboard so the console is visible
        self.clear_output()
        self.purge_workspace_modules()
        if "pygame" in code:
            self.setup_pygame()

        # Remove stale answers / stop signals from an earlier run.
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break

        name = self.current_name()
        run_root = os.path.abspath(self.workspace)
        file_path = os.path.abspath(
            self.current_path or os.path.join(run_root, name)
        )

        self.stop_requested = False
        self.run_button.disabled = True
        self.stop_button.disabled = False
        self.set_state("Running...")

        self.fd_capture = FdCapture(self.append_output)
        self.fd_capture.start()

        thread = threading.Thread(
            target=self.execute_code,
            args=(code, name, file_path, run_root),
            daemon=True,
        )
        self.worker = thread
        thread.start()

    def setup_pygame(self):
        """Plug in the pygame-compatible layer (pygame/ + pygame_host.py)."""
        try:
            import pygame_host
            pygame_host.setup(self)
            pygame_host.begin_run()
        except Exception as exc:
            self.append_output(
                "[pygame layer] could not start: %s: %s\n"
                "Make sure the pygame/ folder, pygame_host.py and "
                "pygame_render.py are next to main.py.\n\n"
                % (type(exc).__name__, exc))

    def purge_workspace_modules(self):
        """Forget workspace modules so edited helper files are re-imported."""
        prefix = self.workspace + os.sep
        for name, module in list(sys.modules.items()):
            path = getattr(module, "__file__", None)
            if isinstance(path, str) and path.startswith(prefix):
                sys.modules.pop(name, None)

    def stop_code(self, instance):
        thread = self.worker
        if thread is None:
            return

        if self.stop_requested:
            # Second tap: the program ignored the first request (for example it
            # is stuck in a long blocking call). Release the UI and abandon the
            # thread; its output now goes to the original stdout, not the console.
            self.worker = None
            self.append_output(
                "\n[Stopped. The program did not respond and was abandoned; "
                "it may keep using CPU until the app is closed.]\n"
            )
            self.reset_ui()
            return

        self.stop_requested = True
        self.set_state("Stopping... tap stop again to force")
        self.input_queue.put(_STOP)       # wakes a blocked input()
        raise_in_thread(thread, StopRun)  # interrupts running Python code

    def make_builtins(self):
        run_builtins = dict(vars(builtins))
        run_builtins["input"] = self.request_input
        return run_builtins

    def execute_code(self, code, name, file_path, run_root=None):
        me = threading.current_thread()
        started = time.perf_counter()
        previous_cwd = os.getcwd()
        previous_sys_path = list(sys.path)
        run_root = os.path.abspath(run_root or os.path.dirname(file_path) or self.workspace)
        script_dir = os.path.abspath(os.path.dirname(file_path) or run_root)

        # Give user code normal project-relative file access and imports. This
        # makes open("data.json"), pygame.image.load("assets/a.png"), and
        # sibling module imports resolve from the imported project mirror.
        try:
            os.chdir(run_root)
            if script_dir != run_root:
                sys.path.insert(0, script_dir)
            sys.path.insert(0, run_root)

            # Lets tracebacks show the real source lines of the editor's code.
            linecache.cache[name] = (len(code), None, code.splitlines(True), name)

            compiled = compile(code, name, "exec")
            exec(compiled, {
                "__name__": "__main__",
                "__file__": file_path,
                "__builtins__": self.make_builtins(),
            })
        except StopRun:
            self.append_output("\n[Stopped]\n")
        except SystemExit:
            pass
        except SyntaxError as exc:
            self.append_output(
                "\n" + "".join(traceback.format_exception_only(type(exc), exc))
            )
        except BaseException as exc:
            # Skip this method's own frame so only the user's code is shown.
            tb = exc.__traceback__.tb_next if exc.__traceback__ else None
            self.append_output(
                "\n" + "".join(traceback.format_exception(type(exc), exc, tb))
            )
        finally:
            # cwd is process-global, so always restore it before the next IDE
            # action/run. Restore sys.path too, even if user code changed it.
            try:
                os.chdir(previous_cwd)
            except OSError:
                pass
            sys.path[:] = previous_sys_path
            try:
                elapsed = time.perf_counter() - started
                self.append_output(f"\nFinished in {elapsed:.3f} seconds.\n")
            except StopRun:
                pass  # a late stop request landed while finishing; ignore it
            finally:
                Clock.schedule_once(partial(self.finish_run, me), 0)

    def finish_run(self, thread, dt):
        # Ignore if this thread was abandoned or a newer run has replaced it.
        if thread is not self.worker:
            return
        self.worker = None
        self.reset_ui()

    def stop_capture(self):
        if self.fd_capture is not None:
            self.fd_capture.stop()
            self.fd_capture = None

    def refresh_display(self, dt=None):
        # After a full-screen pygame window closes, make Kivy repaint itself.
        try:
            Window.update_viewport()
            Window.canvas.ask_update()
        except Exception:
            pass

    def close_game_screen(self):
        game = sys.modules.get("pygame_host")
        if game is not None:
            game.end_run()

    def reset_ui(self):
        self.close_game_screen()
        self.stop_capture()
        Clock.schedule_once(self.refresh_display, 0.1)
        Clock.schedule_once(self.refresh_display, 0.6)
        self.run_button.disabled = False
        self.stop_button.disabled = True
        self.hide_input_panel()
        self.set_state("Ready")


if __name__ == "__main__":
    PythonIDE().run()
