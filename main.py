import builtins
import io
import keyword
import queue
import re
import threading
import time
import traceback

from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.codeinput import CodeInput
from pygments.lexers import PythonLexer
from kivy.uix.textinput import TextInput


class SmartCodeInput(CodeInput):
    """Python editor with syntax highlighting and smart newline indentation."""

    def insert_text(self, substring, from_undo=False):
        # Do smart indentation only for a single Enter keypress, not for paste.
        if substring == "\n":
            lines = self.text.split("\n")
            row = min(self.cursor_row, len(lines) - 1)
            col = self.cursor_col
            line_prefix = lines[row][:col]
            indent = line_prefix[:len(line_prefix) - len(line_prefix.lstrip(" \t"))]

            if line_prefix.rstrip().endswith(":"):
                indent += "    "
            elif not line_prefix.strip() and indent:
                # Dedent one level when pressing Enter on a blank indented line.
                if indent.endswith("    "):
                    indent = indent[:-4]
                elif indent.endswith("\t"):
                    indent = indent[:-1]

            super().insert_text("\n" + indent, from_undo=from_undo)
            return

        super().insert_text(substring, from_undo=from_undo)


class PythonIDE(App):
    COMPLETIONS = sorted(set(
        keyword.kwlist
        + [name for name in dir(builtins) if not name.startswith("_")]
        + ["append", "pygame", "self", "main"]
    ))

    def build(self):
        Window.clearcolor = (0.07, 0.08, 0.11, 1)

        self.input_queue = queue.Queue()
        self.running = False
        self.output_text = ""
        self.output_lock = threading.Lock()

        root = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(7),
        )

        root.add_widget(Label(
            text="Android Python IDE",
            font_size="23sp",
            bold=True,
            size_hint_y=None,
            height=dp(42),
        ))

        root.add_widget(Label(
            text="PYTHON CODE EDITOR",
            size_hint_y=None,
            height=dp(22),
            halign="left",
            text_size=(Window.width - dp(24), None),
        ))

        # Small autocomplete row; it only suggests Python keywords and built-ins.
        suggestion_scroll = ScrollView(
            size_hint_y=None,
            height=dp(38),
            do_scroll_x=True,
            do_scroll_y=False,
            bar_width=dp(3),
            scroll_type=["bars", "content"],
        )
        self.suggestion_bar = BoxLayout(
            orientation="horizontal",
            size_hint=(None, 1),
            spacing=dp(5),
        )
        self.suggestion_bar.bind(minimum_width=self.suggestion_bar.setter("width"))
        suggestion_scroll.add_widget(self.suggestion_bar)
        root.add_widget(suggestion_scroll)

        self.editor = SmartCodeInput(
            text=(
                'name = input("What is your name? ")\n'
                'print("Hello,", name)\n'
                'print("Your Python IDE is working!")\n'
            ),
            multiline=True,
            auto_indent=False,
            font_size="15sp",
            font_name="RobotoMono-Regular",
            background_color=(0.12, 0.14, 0.19, 1),
            cursor_color=(0.3, 0.8, 1, 1),
            padding=dp(10),
            size_hint_y=0.42,
            lexer=PythonLexer(),
            style_name="monokai",
            tab_width=4,
        )
        root.add_widget(self.editor)
        self.editor.bind(text=self.update_suggestions, cursor=self.update_suggestions)

        buttons = BoxLayout(
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )

        self.run_button = Button(
            text="▶ RUN",
            background_normal="",
            background_color=(0.12, 0.55, 0.35, 1),
        )
        self.run_button.bind(on_press=self.run_code)

        clear_button = Button(
            text="CLEAR OUTPUT",
            background_normal="",
            background_color=(0.28, 0.32, 0.42, 1),
        )
        clear_button.bind(on_press=self.clear_output)

        buttons.add_widget(self.run_button)
        buttons.add_widget(clear_button)
        root.add_widget(buttons)

        root.add_widget(Label(
            text="OUTPUT CONSOLE",
            size_hint_y=None,
            height=dp(22),
            halign="left",
            text_size=(Window.width - dp(24), None),
        ))

        self.scroll = ScrollView(
            size_hint_y=0.35,
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(5),
            scroll_type=["bars", "content"],
        )

        self.output_label = Label(
            text="Ready. Tap RUN to execute your code.",
            size_hint_y=None,
            halign="left",
            valign="top",
            font_size="14sp",
            color=(0.65, 1, 0.75, 1),
            padding=(dp(10), dp(10)),
        )
        self.output_label.bind(
            width=self.update_output_width,
            texture_size=self.update_output_height,
        )
        self.scroll.add_widget(self.output_label)
        root.add_widget(self.scroll)

        self.input_panel = BoxLayout(
            size_hint_y=None,
            height=dp(48),
            spacing=dp(6),
            opacity=0,
            disabled=True,
        )

        self.input_field = TextInput(
            hint_text="Enter input here...",
            multiline=False,
            font_size="15sp",
            size_hint_x=0.72,
        )
        self.input_field.bind(on_text_validate=self.submit_input)

        self.submit_button = Button(
            text="SEND",
            size_hint_x=0.28,
            background_normal="",
            background_color=(0.15, 0.40, 0.70, 1),
        )
        self.submit_button.bind(on_press=self.submit_input)
        self.input_panel.add_widget(self.input_field)
        self.input_panel.add_widget(self.submit_button)
        root.add_widget(self.input_panel)

        self.status = Label(
            text="Ready",
            size_hint_y=None,
            height=dp(20),
            font_size="12sp",
        )
        root.add_widget(self.status)

        Clock.schedule_once(self.update_suggestions, 0)
        return root

    def update_output_width(self, label, width):
        label.text_size = (max(0, width - dp(20)), None)

    def update_output_height(self, label, size):
        label.height = max(size[1] + dp(20), dp(40))
        Clock.schedule_once(self.scroll_to_bottom, 0.05)

    def scroll_to_bottom(self, dt):
        self.scroll.scroll_y = 0

    def append_output(self, text):
        with self.output_lock:
            self.output_text += str(text)
            current = self.output_text
        Clock.schedule_once(lambda dt, value=current: self.show_output(value), 0)

    def show_output(self, text):
        self.output_label.text = text

    def clear_output(self, instance):
        with self.output_lock:
            self.output_text = ""
        self.output_label.text = ""
        self.scroll.scroll_y = 0

    def request_input(self, prompt=""):
        if prompt:
            self.append_output(prompt)
        Clock.schedule_once(self.show_input_panel, 0)
        return self.input_queue.get()

    def show_input_panel(self, dt):
        self.input_panel.opacity = 1
        self.input_panel.disabled = False
        self.input_field.text = ""
        self.input_field.focus = True
        self.status.text = "Waiting for your input..."

    def submit_input(self, instance):
        if not self.running:
            return
        answer = self.input_field.text
        self.input_panel.opacity = 0
        self.input_panel.disabled = True
        self.input_field.focus = False
        self.append_output(answer + "\n")
        self.input_queue.put(answer)

    def update_suggestions(self, *args):
        # cursor_index() gives the caret position in the complete source text.
        try:
            index = self.editor.cursor_index()
            before_cursor = self.editor.text[:index]
            match = re.search(r"[A-Za-z_]\w*$", before_cursor)
            prefix = match.group(0) if match else ""
        except Exception:
            prefix = ""
            match = None

        self.suggestion_bar.clear_widgets()
        if not prefix or len(prefix) < 1:
            return

        options = [
            item for item in self.COMPLETIONS
            if item.startswith(prefix) and item != prefix
        ][:6]

        for option in options:
            button = Button(
                text=option,
                size_hint=(None, 1),
                width=dp(max(68, min(110, len(option) * 8 + 24))),
                font_size="12sp",
                background_normal="",
                background_color=(0.20, 0.25, 0.34, 1),
            )
            button.bind(on_press=partial(self.apply_completion, option))
            self.suggestion_bar.add_widget(button)

    def apply_completion(self, completion, instance):
        text = self.editor.text
        index = self.editor.cursor_index()
        before_cursor = text[:index]
        match = re.search(r"[A-Za-z_]\w*$", before_cursor)
        if not match:
            return

        new_text = text[:match.start()] + completion + text[index:]
        new_index = match.start() + len(completion)
        self.editor.text = new_text
        self.editor.cursor = self.editor.get_cursor_from_index(new_index)
        self.editor.focus = True
        self.update_suggestions()

    def run_code(self, instance):
        if self.running:
            self.status.text = "A program is already running."
            return

        code = self.editor.text
        if not code.strip():
            self.append_output("Please enter some Python code first.\n")
            return

        self.clear_output(None)
        # Remove stale answers from an earlier run.
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break

        self.running = True
        self.run_button.disabled = True
        self.run_button.text = "RUNNING..."
        self.status.text = "Running Python..."

        threading.Thread(
            target=self.execute_code,
            args=(code,),
            daemon=True,
        ).start()

    def execute_code(self, code):
        started = time.perf_counter()

        class OutputStream(io.StringIO):
            def write(inner_self, text):
                if text:
                    self.append_output(text)
                return len(text)

            def flush(inner_self):
                pass

        stream = OutputStream()
        safe_builtins = dict(vars(builtins))
        safe_builtins["input"] = self.request_input
        safe_builtins["print"] = partial(print, file=stream)

        try:
            compiled = compile(code, "<editor>", "exec")
            exec(compiled, {
                "__name__": "__main__",
                "__builtins__": safe_builtins,
            })
        except Exception:
            self.append_output("\nERROR:\n" + traceback.format_exc())
        finally:
            elapsed = time.perf_counter() - started
            self.append_output(f"\n\nFinished in {elapsed:.3f} seconds.\n")
            Clock.schedule_once(self.finish_run, 0)

    def finish_run(self, dt):
        self.running = False
        self.run_button.disabled = False
        self.run_button.text = "▶ RUN"
        self.input_panel.opacity = 0
        self.input_panel.disabled = True
        self.status.text = "Finished"


if __name__ == "__main__":
    PythonIDE().run()
