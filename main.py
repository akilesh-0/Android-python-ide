
import io
import sys
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput


class PythonIDE(App):
    def build(self):
        Window.clearcolor = (0.07, 0.08, 0.11, 1)

        root = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
        )

        title = Label(
            text="Android Python IDE",
            font_size="23sp",
            bold=True,
            size_hint_y=None,
            height=dp(44),
        )
        root.add_widget(title)

        root.add_widget(Label(
            text="CODE EDITOR",
            size_hint_y=None,
            height=dp(24),
            halign="left",
            text_size=(Window.width - dp(24), None),
        ))

        self.editor = TextInput(
            text=(
                'print("Hello, Akilesh!")\n'
                'print("2 + 3 =", 2 + 3)\n'
            ),
            multiline=True,
            font_size="16sp",
            font_name="RobotoMono-Regular",
            background_color=(0.12, 0.14, 0.19, 1),
            foreground_color=(0.90, 0.94, 1, 1),
            cursor_color=(0.3, 0.8, 1, 1),
            padding=dp(10),
            size_hint_y=0.52,
        )
        root.add_widget(self.editor)

        buttons = BoxLayout(
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )

        run_button = Button(
            text="▶ RUN",
            background_normal="",
            background_color=(0.12, 0.55, 0.35, 1),
        )
        run_button.bind(on_press=self.run_code)

        clear_button = Button(
            text="CLEAR OUTPUT",
            background_normal="",
            background_color=(0.28, 0.32, 0.42, 1),
        )
        clear_button.bind(on_press=self.clear_output)

        buttons.add_widget(run_button)
        buttons.add_widget(clear_button)
        root.add_widget(buttons)

        root.add_widget(Label(
            text="OUTPUT CONSOLE",
            size_hint_y=None,
            height=dp(24),
            halign="left",
            text_size=(Window.width - dp(24), None),
        ))

        self.output = TextInput(
            text="Ready. Tap RUN to execute your Python code.",
            readonly=True,
            multiline=True,
            font_size="14sp",
            background_color=(0.04, 0.05, 0.07, 1),
            foreground_color=(0.55, 1, 0.70, 1),
            padding=dp(10),
            size_hint_y=0.35,
        )
        root.add_widget(self.output)

        return root

    def run_code(self, instance):
        code = self.editor.text

        if not code.strip():
            self.output.text = "Please enter some Python code first."
            return

        buffer = io.StringIO()
        error = None
        started = time.perf_counter()

        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                exec(
                    compile(code, "<editor>", "exec"),
                    {"__name__": "__main__"},
                )
        except Exception:
            error = traceback.format_exc()

        result = buffer.getvalue()

        if error:
            result += "\nERROR:\n" + error

        elapsed = time.perf_counter() - started
        result += f"\n\nFinished in {elapsed:.3f} seconds."

        self.output.text = result or "Program finished with no output."

    def clear_output(self, instance):
        self.output.text = ""


if __name__ == "__main__":
    PythonIDE().run()
        
