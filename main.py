
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button


class PythonIDE(App):
    def build(self):
        layout = BoxLayout(
            orientation="vertical",
            padding=20,
            spacing=15
        )

        title = Label(
            text="My Android Python IDE",
            font_size="24sp",
            size_hint_y=None,
            height=60
        )

        message = Label(
            text="Cloud build test ready!",
            font_size="18sp"
        )

        run_button = Button(
            text="Test App",
            size_hint_y=None,
            height=55
        )

        def test_app(instance):
            message.text = "Our IDE is running!"

        run_button.bind(on_press=test_app)

        layout.add_widget(title)
        layout.add_widget(message)
        layout.add_widget(run_button)

        return layout


if __name__ == "__main__":
    PythonIDE().run()
