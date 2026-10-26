"""Python IDE for Android, built with Kivy."""

import builtins
import ctypes
import json
import keyword
import linecache
import os
import queue
import re
import sys
import threading
import time
import traceback
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, Triangle
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
from kivy.utils import escape_markup, get_color_from_hex
from pygments.lexers import PythonLexer
from pygments.styles import get_style_by_name

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


HOLD_SECONDS = 0.4  # press-and-hold time that starts normal text selection


class SmartCodeInput(CodeInput):
    """Python editor with smart indentation and its own touch scrolling.

    A quick tap places the cursor and opens the keyboard. Dragging scrolls in
    both directions (with a little momentum) without touching the keyboard.
    Press-and-hold falls back to normal TextInput selection.
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
    def insert_text(self, substring, from_undo=False):
        if substring == "\t":
            substring = INDENT

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

        super().insert_text(substring, from_undo=from_undo)

    # -- scrolling -----------------------------------------------------
    def _ide_text_stats(self, instance, value):
        self.ide_rows = value.count("\n") + 1
        self.ide_cols = max(map(len, value.split("\n")))

    def _max_scroll_y(self):
        dy = self.line_height + self.line_spacing
        content = self.ide_rows * dy + self.padding[1] + self.padding[3]
        return max(0, content - self.height + self.height * 0.25)

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
        return moved

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
        # Finger stayed down without moving: hand over to normal TextInput
        # behaviour (selection handles, copy/paste bubble).
        if touch.ud.get("ide_mode") == "pending":
            touch.ud["ide_mode"] = "forwarded"
            CodeInput.on_touch_down(self, touch)

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

SYMBOLS = ["TAB", "(", ")", "[", "]", "{", "}", ":", '"', "'", "=", "#",
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
        Window.softinput_mode = "below_target"

        # Workspace: app-private folder, so no storage permissions are needed.
        self.workspace = os.path.join(self.user_data_dir, "workspace")
        os.makedirs(self.workspace, exist_ok=True)
        try:
            os.chdir(self.workspace)  # relative paths in user code land here
        except OSError:
            pass
        if self.workspace not in sys.path:
            sys.path.insert(0, self.workspace)  # saved files can import each other

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

        # Route print()/stderr from the running program to the console.
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = ConsoleStream(self, self._orig_stdout)
        sys.stderr = ConsoleStream(self, self._orig_stderr)

        root = BoxLayout(orientation="vertical")
        paint(root, C_BG)

        root.add_widget(self.build_app_bar())
        root.add_widget(divider())
        root.add_widget(self.build_file_toolbar())
        root.add_widget(divider())
        root.add_widget(self.build_symbol_bar())
        root.add_widget(self.build_editor_area())
        root.add_widget(self.build_console())
        root.add_widget(self.build_status_bar())

        Window.bind(on_keyboard=self.on_keyboard, on_key_down=self.on_key_down)

        self.editor.bind(text=self.on_editor_text, cursor=self.update_cursor)
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

        self.run_button = IconButton("play", bg=C_RUN, size_hint_x=None,
                                     width=dp(60))
        self.run_button.bind(on_release=self.run_code)
        self.stop_button = IconButton("stop", bg=C_STOP, size_hint_x=None,
                                      width=dp(60), disabled=True)
        self.stop_button.bind(on_release=self.stop_code)
        bar.add_widget(self.run_button)
        bar.add_widget(self.stop_button)
        return bar

    def build_file_toolbar(self):
        bar = BoxLayout(size_hint_y=None, height=dp(38),
                        padding=[dp(6), dp(3)], spacing=dp(4))
        paint(bar, C_BAR)

        def add(text, callback):
            button = FlatButton(text=text, bg=C_BAR, font_size=sp(12))
            button.bind(on_release=callback)
            bar.add_widget(button)
            return button

        add("NEW", lambda *a: self.guard_unsaved(self.new_file))
        add("OPEN", lambda *a: self.guard_unsaved(self.show_open_dialog))
        self.save_button = add("SAVE", lambda *a: self.save_file())
        add("SAVE AS", lambda *a: self.show_save_as())
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
                width=dp(52 if symbol == "TAB" else 38),
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
        pass

    def on_stop(self):
        self.save_session()
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        raise_in_thread(self.worker, StopRun)

    def on_keyboard(self, window, key, scancode=None, codepoint=None,
                    modifier=None):
        if key != 27:  # Android back button / Esc
            return False
        if self.popup is not None:
            self.close_popup()
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
        else:
            return False
        return True

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
        self.save_button.color = C_ACCENT if self.dirty else C_TEXT

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
        if path and not os.path.isfile(path):
            path = None
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
                   height=dp(220)):
        self.close_popup()
        popup = Popup(
            title=title,
            content=content,
            size_hint=size_hint,
            height=height,
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

        popup = self.open_popup("Save as", content, height=dp(280))

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
                "No saved files yet.\nWrite some code and tap SAVE.",
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
        text = self.editor.text
        index = self.editor.cursor_index()
        before = text[:index]
        match = re.search(r"[A-Za-z_]\w*$", before)
        if not match:
            return

        new_text = text[:match.start()] + completion + text[index:]
        new_index = match.start() + len(completion)
        self.editor.text = new_text
        self.editor.cursor = self.editor.get_cursor_from_index(new_index)
        self.editor.focus = True

    # ------------------------------------------------------------------
    # Running and stopping code
    # ------------------------------------------------------------------
    def run_code(self, instance):
        if self.worker is not None:
            self.flash("A program is already running.")
            return

        code = self.editor.text
        if not code.strip():
            self.flash("Nothing to run.")
            return

        self.editor.focus = False  # hide the keyboard so the console is visible
        self.clear_output()
        self.purge_workspace_modules()

        # Remove stale answers / stop signals from an earlier run.
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break

        name = self.current_name()
        file_path = self.current_path or os.path.join(self.workspace, name)

        self.stop_requested = False
        self.run_button.disabled = True
        self.stop_button.disabled = False
        self.set_state("Running...")

        thread = threading.Thread(
            target=self.execute_code, args=(code, name, file_path), daemon=True
        )
        self.worker = thread
        thread.start()

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

    def execute_code(self, code, name, file_path):
        me = threading.current_thread()
        started = time.perf_counter()

        # Lets tracebacks show the real source lines of the editor's code.
        linecache.cache[name] = (len(code), None, code.splitlines(True), name)

        try:
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

    def reset_ui(self):
        self.run_button.disabled = False
        self.stop_button.disabled = True
        self.hide_input_panel()
        self.set_state("Ready")


if __name__ == "__main__":
    PythonIDE().run()
