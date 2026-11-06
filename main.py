"""Crash-reporting launcher.

Runs the real app (ide_main.py). If anything fails during startup, the
traceback is shown on the phone screen (and saved to crash_log.txt) instead
of the app silently closing after the splash screen.
"""
import os
import sys
import traceback
import faulthandler


def _log_dir():
    for key in ("ANDROID_PRIVATE", "ANDROID_ARGUMENT"):
        path = os.environ.get(key)
        if path and os.path.isdir(path):
            return path
    return os.getcwd()


LOG_PATH = os.path.join(_log_dir(), "crash_log.txt")

try:
    _fault_file = open(LOG_PATH, "a")
    faulthandler.enable(file=_fault_file, all_threads=True)
except Exception:
    _fault_file = None


def _save(text):
    try:
        with open(LOG_PATH, "a") as handle:
            handle.write(text + "\n")
    except Exception:
        pass


def _error_widget(text):
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput

    root = BoxLayout(orientation="vertical", padding=12, spacing=8)
    root.add_widget(Label(
        text="Startup error (screenshot this and send it)",
        size_hint_y=None, height=48, color=(1, 0.4, 0.4, 1)))
    root.add_widget(TextInput(text=text, readonly=True, font_size="12sp"))
    return root


def _report(stage):
    text = "Stage: %s\nPython %s\n\n%s" % (
        stage, sys.version.split()[0], traceback.format_exc())
    _save(text)
    return text


def _run_error_app(text):
    from kivy.app import App

    class ErrorApp(App):
        def build(self):
            return _error_widget(text)

    ErrorApp().run()


def main():
    try:
        import ide_main
    except Exception:
        _run_error_app(_report("import ide_main"))
        return

    try:
        app = ide_main.PythonIDE()
    except Exception:
        _run_error_app(_report("create app"))
        return

    original_build = app.build

    def safe_build():
        try:
            return original_build()
        except Exception:
            return _error_widget(_report("build()"))

    app.build = safe_build
    app.run()


if __name__ == "__main__":
    main()
