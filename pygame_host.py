"""IDE side of the pygame layer: the game screen and the host the layer talks to.

The game runs in the IDE's worker thread. Frames travel to the main thread
through KivyHost.present(); touches, mouse and keys travel back through the
pygame event queue (pygame._core).
"""

import math
import threading
import time

from kivy.clock import Clock
from kivy.core.window import Keyboard, Window
from kivy.graphics import (Color, PopMatrix, PushMatrix, Rectangle,
                           RoundedRectangle, Scale, ScissorPop, ScissorPush,
                           Translate, Triangle)
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget

import pygame_render
from pygame import _core
from pygame import constants as C
from pygame.event import Event

_host = None


class _AudioPlayback:
    """State wrapper around the Kivy Sound instance (owned by the UI thread)."""

    def __init__(self, sound):
        self.sound = sound
        self.busy = False
        self.paused = False
        self.position = 0.0
        self.volume = 1.0
        self.remaining_loops = 0
        self.loop_forever = False
        self.manual_stop = False
        self.on_complete = None
        self._maxtime_event = None
        self._fade_event = None
        self._volume_event = None
        try:
            sound.bind(on_stop=self._on_stop)
        except Exception:
            pass

    def _on_stop(self, *args):
        if self.manual_stop or not self.busy:
            return
        if self.remaining_loops > 0:
            self.remaining_loops -= 1
            Clock.schedule_once(self._restart, 0)
        else:
            self.busy = False
            callback, self.on_complete = self.on_complete, None
            if callback is not None:
                try: callback()
                except Exception: pass

    def _restart(self, dt):
        if self.busy and not self.manual_stop:
            try:
                self.sound.play()
            except Exception:
                self.busy = False


# ----------------------------------------------------------------------
# Public API used by main.py
# ----------------------------------------------------------------------
def setup(app):
    """Create the host once and plug it into the pygame layer."""
    global _host
    if _host is None:
        _host = KivyHost(app)
        _core.host = _host
    return _host


def begin_run():
    if _host is not None:
        _host.close_main()
        _core.reset()


def end_run():
    if _host is not None:
        _host.close_main()


def is_open():
    return _host is not None and _host.screen is not None


def request_close():
    if _host is not None:
        _host.request_close()


# ----------------------------------------------------------------------
# Key mapping (Kivy key codes -> pygame key codes)
# ----------------------------------------------------------------------
def _build_key_map():
    names = {
        "up": C.K_UP, "down": C.K_DOWN, "left": C.K_LEFT, "right": C.K_RIGHT,
        "home": C.K_HOME, "end": C.K_END, "pgup": C.K_PAGEUP,
        "pgdown": C.K_PAGEDOWN, "insert": C.K_INSERT, "delete": C.K_DELETE,
        "capslock": C.K_CAPSLOCK, "lshift": C.K_LSHIFT, "rshift": C.K_RSHIFT,
        "lctrl": C.K_LCTRL, "rctrl": C.K_RCTRL, "alt": C.K_LALT,
        "lalt": C.K_LALT, "ralt": C.K_RALT,
    }
    for number in range(1, 13):
        names["f%d" % number] = getattr(C, "K_F%d" % number)
    mapping = {}
    for name, code in Keyboard.keycodes.items():
        if name in names:
            mapping[code] = names[name]
    return mapping


_KEY_MAP = None


def _convert_key(code):
    global _KEY_MAP
    if _KEY_MAP is None:
        _KEY_MAP = _build_key_map()
    if code in _KEY_MAP:
        return _KEY_MAP[code]
    if 0 < code < 256:
        return code
    return None


# ----------------------------------------------------------------------
# Host
# ----------------------------------------------------------------------
class KivyHost:
    def __init__(self, app):
        self.app = app
        self.screen = None
        self._lock = threading.Lock()
        self._frame = None
        self._scheduled = False
        self._rendered = threading.Event()
        self._pad_sources = {}
        self._pad_down = set()
        self._frames = 0
        self._fps_start = time.perf_counter()
        self._main_thread_id = threading.get_ident()
        self._audio_handles = set()

    def _call_on_main(self, callback, timeout=10.0):
        """Run Kivy/audio-provider work on the UI thread and return its value."""
        if threading.get_ident() == self._main_thread_id:
            return callback()
        done = threading.Event()
        result = {}

        def invoke(dt):
            try:
                result["value"] = callback()
            except BaseException as exc:
                result["error"] = exc
            finally:
                done.set()

        Clock.schedule_once(invoke, 0)
        if not done.wait(timeout):
            raise RuntimeError("Kivy UI thread did not respond to an audio request")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _audio_stop_main(self, handle):
        if handle is None:
            return
        if handle._maxtime_event is not None:
            Clock.unschedule(handle._maxtime_event)
            handle._maxtime_event = None
        if handle._fade_event is not None:
            Clock.unschedule(handle._fade_event)
            handle._fade_event = None
        if handle._volume_event is not None:
            Clock.unschedule(handle._volume_event)
            handle._volume_event = None
        handle.manual_stop = True
        handle.busy = False
        handle.paused = False
        handle.position = 0.0
        try:
            handle.sound.stop()
        finally:
            handle.manual_stop = False

    # -- audio bridge: called by pygame.mixer from the game worker ------------
    def audio_load(self, path):
        def load_main():
            from kivy.core.audio import SoundLoader
            sound = SoundLoader.load(path)
            if sound is None:
                return None
            handle = _AudioPlayback(sound)
            self._audio_handles.add(handle)
            return handle
        return self._call_on_main(load_main)

    def audio_play(self, handle, loops=0, maxtime=0, fade_ms=0, start=0.0):
        def play_main():
            self._audio_stop_main(handle)
            handle.remaining_loops = max(0, int(loops))
            handle.loop_forever = int(loops) < 0
            try:
                handle.sound.loop = handle.loop_forever
            except Exception:
                pass
            target_volume = handle.volume
            handle.sound.volume = 0.0 if fade_ms and int(fade_ms) > 0 else target_volume
            handle.busy = True
            handle.paused = False
            handle.sound.play()
            if fade_ms and int(fade_ms) > 0:
                fade_duration = max(0.001, int(fade_ms) / 1000.0)
                fade_started = time.perf_counter()
                def fade_in(dt):
                    ratio = min(1.0, (time.perf_counter() - fade_started) / fade_duration)
                    handle.sound.volume = target_volume * ratio
                    if ratio >= 1.0:
                        handle.sound.volume = target_volume
                        handle._volume_event = None
                        return False
                    return True
                handle._volume_event = fade_in
                Clock.schedule_interval(fade_in, 0.04)
            if start:
                try: handle.sound.seek(float(start))
                except Exception: pass
            if maxtime and int(maxtime) > 0:
                def timed_stop(dt):
                    self._audio_stop_main(handle)
                handle._maxtime_event = timed_stop
                Clock.schedule_once(timed_stop, max(0.001, int(maxtime) / 1000.0))
        self._call_on_main(play_main)

    def audio_stop(self, handle):
        self._call_on_main(lambda: self._audio_stop_main(handle))

    def audio_pause(self, handle):
        def pause_main():
            if not handle.busy or handle.paused:
                return
            try: position = max(0.0, float(handle.sound.get_pos()))
            except Exception: position = 0.0
            self._audio_stop_main(handle)
            handle.position = position
            handle.busy = True
            handle.paused = True
        self._call_on_main(pause_main)

    def audio_unpause(self, handle):
        def unpause_main():
            if not handle.paused:
                return
            handle.sound.loop = handle.loop_forever
            handle.sound.volume = handle.volume
            handle.busy = True
            handle.paused = False
            handle.sound.play()
            if handle.position:
                try: handle.sound.seek(handle.position)
                except Exception: pass
        self._call_on_main(unpause_main)

    def audio_set_volume(self, handle, volume):
        def set_main():
            handle.volume = max(0.0, min(1.0, float(volume)))
            handle.sound.volume = handle.volume
        self._call_on_main(set_main)

    def audio_is_busy(self, handle):
        def busy_main():
            if not handle.busy or handle.paused:
                return False
            try:
                if getattr(handle.sound, "state", "play") == "stop":
                    handle.busy = False
            except Exception:
                pass
            return bool(handle.busy)
        return self._call_on_main(busy_main)

    def audio_length(self, handle):
        return self._call_on_main(lambda: float(getattr(handle.sound, "length", 0.0) or 0.0))

    def audio_set_on_complete(self, handle, callback):
        self._call_on_main(lambda: setattr(handle, "on_complete", callback))

    def audio_position(self, handle):
        def position_main():
            if handle.paused:
                return handle.position
            try: return max(0.0, float(handle.sound.get_pos()))
            except Exception: return 0.0
        return self._call_on_main(position_main)

    def audio_seek(self, handle, position):
        def seek_main():
            try: handle.sound.seek(max(0.0, float(position)))
            except Exception: pass
        self._call_on_main(seek_main)

    def audio_fadeout(self, handle, milliseconds):
        duration = max(0, int(milliseconds)) / 1000.0
        def begin_fade():
            if duration <= 0:
                self._audio_stop_main(handle)
                return
            started = time.perf_counter()
            initial = handle.volume
            if handle._fade_event is not None:
                Clock.unschedule(handle._fade_event)
            if handle._volume_event is not None:
                Clock.unschedule(handle._volume_event)
                handle._volume_event = None
            def step(dt):
                elapsed = time.perf_counter() - started
                ratio = min(1.0, elapsed / duration)
                handle.sound.volume = initial * (1.0 - ratio)
                if ratio >= 1.0:
                    handle._fade_event = None
                    self._audio_stop_main(handle)
                    handle.sound.volume = initial
                    return False
                return True
            handle._fade_event = step
            Clock.schedule_interval(step, 0.04)
        self._call_on_main(begin_fade)

    def audio_unload(self, handle):
        def unload_main():
            self._audio_stop_main(handle)
            try: handle.sound.unload()
            except Exception: pass
            self._audio_handles.discard(handle)
        self._call_on_main(unload_main)

    # -- called from the game thread ------------------------------------------
    def screen_size(self):
        return (int(Window.width), int(Window.height - dp(40)))

    def open(self, size, caption):
        done = threading.Event()

        def open_main(dt):
            try:
                if self.screen is None:
                    self.screen = GameScreen(self)
                    self.screen.open()
                self.screen.configure(size, caption)
            finally:
                done.set()

        Clock.schedule_once(open_main, 0)
        done.wait(5.0)

    def close(self):
        Clock.schedule_once(lambda dt: self.close_main(), 0)

    def set_caption(self, text):
        Clock.schedule_once(
            lambda dt: self.screen and self.screen.set_caption(text), 0)

    def present(self, commands, width, height):
        if self.screen is None:
            time.sleep(0.001)
            return
        with self._lock:
            self._frame = (commands, width, height)
            schedule = not self._scheduled
            self._scheduled = True
            self._rendered.clear()
        if schedule:
            Clock.schedule_once(self._render, 0)
        # Wait for the frame to be drawn: keeps the game from outrunning the
        # screen and gives the UI thread time to work.
        self._rendered.wait(0.05)

    def measure_text(self, fontkey, text):
        return pygame_render.measure_text(fontkey, text)

    # -- main thread ---------------------------------------------------------------
    def _render(self, dt):
        with self._lock:
            frame = self._frame
            self._scheduled = False
        screen = self.screen
        if screen is not None and frame is not None:
            screen.show_frame(*frame)
            self._frames += 1
            now = time.perf_counter()
            if now - self._fps_start >= 0.5:
                screen.set_fps(self._frames / (now - self._fps_start))
                self._frames = 0
                self._fps_start = now
        self._rendered.set()

    def close_main(self):
        for handle in list(self._audio_handles):
            try:
                self._audio_stop_main(handle)
                handle.sound.unload()
            except Exception:
                pass
        self._audio_handles.clear()
        screen, self.screen = self.screen, None
        if screen is not None:
            screen.shutdown()
        self._pad_sources.clear()
        self._pad_down.clear()
        _core.keys_down.clear()
        _core.mouse_buttons[:] = [False, False, False]
        self._rendered.set()

    def request_close(self):
        if self.screen is None:
            return
        _core.push_event(Event(C.QUIT))
        Clock.schedule_once(self._force_close, 2.0)

    def _force_close(self, dt):
        if self.screen is not None:  # the game ignored QUIT and kept its window
            try:
                self.app.stop_code(None)
            except Exception:
                pass
            self.close_main()

    # -- input -> pygame events -----------------------------------------------------
    def key_event(self, down, key):
        if down:
            if key in _core.keys_down:
                return
            _core.keys_down.add(key)
            if 32 <= key < 127:
                text = chr(key)
            else:
                text = "\r" if key == C.K_RETURN else ""
            _core.push_event(Event(C.KEYDOWN, key=key, unicode=text, mod=0,
                                   scancode=0))
        else:
            _core.keys_down.discard(key)
            _core.push_event(Event(C.KEYUP, key=key, mod=0, scancode=0))

    def pad_keys(self, source, keys):
        self._pad_sources[source] = set(keys)
        now = set()
        for group in self._pad_sources.values():
            now |= group
        for key in now - self._pad_down:
            self.key_event(True, key)
        for key in self._pad_down - now:
            self.key_event(False, key)
        self._pad_down = now

    def mouse_event(self, kind, pos, touch=True, touch_id=0):
        """Send the primary finger through Pygame's mouse compatibility API."""
        x, y = int(pos[0]), int(pos[1])
        old = _core.mouse_pos
        _core.mouse_pos = (x, y)
        if kind == "down":
            _core.mouse_buttons[0] = True
            _core.push_event(Event(C.MOUSEBUTTONDOWN, pos=(x, y), button=1,
                                   touch=touch, touch_id=touch_id))
        elif kind == "move":
            rel = (x - old[0], y - old[1])
            _core.mouse_rel[0] += rel[0]
            _core.mouse_rel[1] += rel[1]
            buttons = (1 if _core.mouse_buttons[0] else 0, 0, 0)
            _core.push_event(Event(C.MOUSEMOTION, pos=(x, y), rel=rel,
                                   buttons=buttons, touch=touch,
                                   touch_id=touch_id))
        else:
            _core.mouse_buttons[0] = False
            _core.push_event(Event(C.MOUSEBUTTONUP, pos=(x, y), button=1,
                                   touch=touch, touch_id=touch_id))

    def finger_event(self, kind, finger_id, pos, rel=(0.0, 0.0), pressure=1.0):
        """Queue normalized Pygame 2 finger events (origin at bottom-left)."""
        event_types = {
            "down": C.FINGERDOWN,
            "move": C.FINGERMOTION,
            "up": C.FINGERUP,
        }
        event_type = event_types.get(kind)
        if event_type is None:
            return
        data = {
            "touch_id": 0,
            "finger_id": int(finger_id),
            "x": float(pos[0]),
            "y": float(pos[1]),
            "pressure": float(pressure),
        }
        if kind == "move":
            data["dx"] = float(rel[0])
            data["dy"] = float(rel[1])
        _core.push_event(Event(event_type, data))


# ----------------------------------------------------------------------
# Widgets
# ----------------------------------------------------------------------
class GameView(Widget):
    """Draws the latest frame, scaled to fit, and turns touches into mouse events."""

    def __init__(self, host, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.renderer = pygame_render.Renderer()
        self.frame = None
        self.game_w = 1
        self.game_h = 1
        self._metrics = (1.0, 0.0, 0.0)
        self._touches = {}
        self._mouse_touch_uid = None
        self._next_finger_id = 1
        self.bind(pos=self.redraw, size=self.redraw)

    def set_game_size(self, width, height):
        self.game_w, self.game_h = max(1, width), max(1, height)
        self.redraw()

    def set_frame(self, commands, width, height):
        self.frame = (commands, width, height)
        self.game_w, self.game_h = max(1, width), max(1, height)
        self.redraw()

    def metrics(self):
        scale = min(self.width / float(self.game_w), self.height / float(self.game_h))
        ox = self.x + (self.width - self.game_w * scale) / 2.0
        oy = self.y + (self.height - self.game_h * scale) / 2.0
        return scale, ox, oy

    def redraw(self, *args):
        if self.width <= 0 or self.height <= 0:
            return
        scale, ox, oy = self._metrics = self.metrics()
        gw, gh = self.game_w, self.game_h
        self.canvas.clear()
        with self.canvas:
            Color(0, 0, 0, 1)
            Rectangle(pos=self.pos, size=self.size)
            if self.frame is None:
                return
            ScissorPush(x=int(ox), y=int(oy), width=max(1, int(gw * scale)),
                        height=max(1, int(gh * scale)))
            PushMatrix()
            Translate(ox, oy + gh * scale)
            Scale(scale, -scale, 1)
            Color(0, 0, 0, 1)
            Rectangle(pos=(0, 0), size=(gw, gh))
            commands, width, height = self.frame
            self.renderer.draw_frame(commands, width, height)
            PopMatrix()
            ScissorPop()

    def to_game(self, x, y):
        scale, ox, oy = self._metrics
        if scale <= 0:
            return (0, 0)
        return ((x - ox) / scale, self.game_h - (y - oy) / scale)

    def _inside_game(self, x, y):
        scale, ox, oy = self._metrics
        if scale <= 0:
            return False
        right = ox + self.game_w * scale
        top = oy + self.game_h * scale
        return ox <= x <= right and oy <= y <= top

    def _normalized(self, x, y):
        gx, gy = self.to_game(x, y)
        return (max(0.0, min(1.0, gx / float(self.game_w))),
                max(0.0, min(1.0, gy / float(self.game_h))))

    @staticmethod
    def _touch_key(touch):
        uid = getattr(touch, "uid", None)
        return uid if uid is not None else id(touch)

    @staticmethod
    def _pressure(touch):
        try:
            return max(0.0, min(1.0, float(touch.pressure)))
        except (AttributeError, TypeError, ValueError):
            return 1.0

    def on_touch_down(self, touch):
        if (not self.collide_point(*touch.pos)
                or not self._inside_game(*touch.pos)):
            return False
        uid = self._touch_key(touch)
        if uid in self._touches:
            return True

        finger_id = self._next_finger_id
        self._next_finger_id += 1
        normalized = self._normalized(*touch.pos)
        touch.grab(self)
        self._touches[uid] = {
            "finger_id": finger_id,
            "pos": normalized,
        }
        self.host.finger_event("down", finger_id, normalized,
                               pressure=self._pressure(touch))

        # Keep the familiar mouse API working with the first active finger.
        # Other fingers are available independently through FINGER* events.
        if self._mouse_touch_uid is None:
            self._mouse_touch_uid = uid
            self.host.mouse_event("down", self.to_game(*touch.pos), touch=True)
        return True

    def on_touch_move(self, touch):
        uid = self._touch_key(touch)
        state = self._touches.get(uid)
        if touch.grab_current is self and state is not None:
            normalized = self._normalized(*touch.pos)
            old = state["pos"]
            rel = (normalized[0] - old[0], normalized[1] - old[1])
            state["pos"] = normalized
            self.host.finger_event("move", state["finger_id"], normalized,
                                   rel=rel, pressure=self._pressure(touch))
            if uid == self._mouse_touch_uid:
                self.host.mouse_event("move", self.to_game(*touch.pos), touch=True)
            return True
        return False

    def on_touch_up(self, touch):
        uid = self._touch_key(touch)
        state = self._touches.get(uid)
        if touch.grab_current is self and state is not None:
            normalized = self._normalized(*touch.pos)
            self.host.finger_event("up", state["finger_id"], normalized,
                                   pressure=self._pressure(touch))
            touch.ungrab(self)
            self._touches.pop(uid, None)
            if uid == self._mouse_touch_uid:
                self.host.mouse_event("up", self.to_game(*touch.pos), touch=True)
                self._mouse_touch_uid = None
            return True
        return False


class DPad(Widget):
    """On-screen arrow keys."""

    def __init__(self, host, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.keys = set()
        self._touches = {}
        self.bind(pos=self.redraw, size=self.redraw)

    def _keys_at(self, x, y):
        cx, cy = self.center
        dx, dy = x - cx, y - cy
        radius = math.hypot(dx, dy)
        if radius < self.width * 0.10:
            return set()
        limit = 0.38 * radius
        keys = set()
        if dx > limit:
            keys.add(C.K_RIGHT)
        if dx < -limit:
            keys.add(C.K_LEFT)
        if dy > limit:
            keys.add(C.K_UP)
        if dy < -limit:
            keys.add(C.K_DOWN)
        return keys

    def _push(self):
        keys = set()
        for group in self._touches.values():
            keys |= group
        self.keys = keys
        self.host.pad_keys("dpad", keys)
        self.redraw()

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        self._touches[touch.uid] = self._keys_at(*touch.pos)
        self._push()
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._touches[touch.uid] = self._keys_at(*touch.pos)
            self._push()
            return True
        return False

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._touches.pop(touch.uid, None)
            self._push()
            return True
        return False

    def redraw(self, *args):
        self.canvas.clear()
        unit = self.width / 3.0
        x0, y0 = self.pos
        cells = ((C.K_UP, 1, 2), (C.K_DOWN, 1, 0), (C.K_LEFT, 0, 1),
                 (C.K_RIGHT, 2, 1))
        with self.canvas:
            for key, gx, gy in cells:
                on = key in self.keys
                Color(1, 1, 1, 0.45 if on else 0.2)
                RoundedRectangle(pos=(x0 + gx * unit + dp(2), y0 + gy * unit + dp(2)),
                                 size=(unit - dp(4), unit - dp(4)), radius=[dp(8)])
                Color(1, 1, 1, 0.9 if on else 0.55)
                cx, cy, s = x0 + gx * unit + unit / 2, y0 + gy * unit + unit / 2, unit * 0.22
                if key == C.K_UP:
                    pts = [cx - s, cy - s * 0.7, cx + s, cy - s * 0.7, cx, cy + s]
                elif key == C.K_DOWN:
                    pts = [cx - s, cy + s * 0.7, cx + s, cy + s * 0.7, cx, cy - s]
                elif key == C.K_LEFT:
                    pts = [cx + s * 0.7, cy - s, cx + s * 0.7, cy + s, cx - s, cy]
                else:
                    pts = [cx - s * 0.7, cy - s, cx - s * 0.7, cy + s, cx + s, cy]
                Triangle(points=pts)


def _action_button(host, text, key, **kwargs):
    button = Button(text=text, background_normal="", background_down="",
                    background_color=(1, 1, 1, 0.22), color=(1, 1, 1, 0.9),
                    font_size=sp(13), **kwargs)
    button.bind(state=lambda inst, state: host.pad_keys(
        ("button", key), {key} if state == "down" else set()))
    return button


class GameScreen(ModalView):
    """Full-screen game window with a thin top bar and on-screen controls."""

    def __init__(self, host, **kwargs):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background="",
                         background_color=(0, 0, 0, 1),
                         overlay_color=(0, 0, 0, 1), **kwargs)
        self.host = host

        root = BoxLayout(orientation="vertical")
        bar = BoxLayout(size_hint_y=None, height=dp(38),
                        padding=[dp(10), dp(3), dp(4), dp(3)], spacing=dp(4))
        with bar.canvas.before:
            Color(0.13, 0.13, 0.17, 1)
            self._bar_rect = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda w, v: setattr(self._bar_rect, "pos", v),
                 size=lambda w, v: setattr(self._bar_rect, "size", v))

        self.title_label = Label(text="pygame window", halign="left",
                                 valign="middle", font_size=sp(13), shorten=True)
        self.title_label.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.fps_label = Label(text="", size_hint_x=None, width=dp(64),
                               font_size=sp(12), color=(0.7, 0.7, 0.8, 1))
        self.pad_toggle = ToggleButton(
            text="PAD", state="down", size_hint_x=None, width=dp(54),
            font_size=sp(12), background_normal="", background_down="",
            background_color=(0.25, 0.27, 0.36, 1))
        self.pad_toggle.bind(state=self._update_pad)
        close = Button(text="CLOSE", size_hint_x=None, width=dp(70),
                       font_size=sp(12), background_normal="", background_down="",
                       background_color=(0.75, 0.25, 0.25, 1))
        close.bind(on_release=lambda *a: self.host.request_close())
        for widget in (self.title_label, self.fps_label, self.pad_toggle, close):
            bar.add_widget(widget)

        field = FloatLayout()
        self.view = GameView(host, size_hint=(1, 1))
        self.dpad = DPad(host, size_hint=(None, None), size=(dp(168), dp(168)),
                         pos_hint={"x": 0.02, "y": 0.03})
        self.space_button = _action_button(
            host, "SPACE", C.K_SPACE, size_hint=(None, None),
            size=(dp(96), dp(64)), pos_hint={"right": 0.98, "y": 0.03})
        self.enter_button = _action_button(
            host, "ENTER", C.K_RETURN, size_hint=(None, None),
            size=(dp(96), dp(52)), pos_hint={"right": 0.98, "y": 0.03 + 0.12})
        self.pad_widgets = [self.dpad, self.space_button, self.enter_button]
        field.add_widget(self.view)
        for widget in self.pad_widgets:
            field.add_widget(widget)

        root.add_widget(bar)
        root.add_widget(field)
        self.add_widget(root)
        Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)

    def configure(self, size, caption):
        self.view.set_game_size(*size)
        self.title_label.text = caption

    def set_caption(self, text):
        self.title_label.text = text

    def show_frame(self, commands, width, height):
        self.view.set_frame(commands, width, height)
        err = self.view.renderer.last_error
        if err and not getattr(self, "_reported", False):
            self._reported = True
            self.host.app.append_output(
                "[pygame layer] a draw command failed on screen: %s\n" % err)

    def set_fps(self, fps):
        self.fps_label.text = "%d fps" % round(fps)

    def _update_pad(self, instance, state):
        visible = state == "down"
        for widget in self.pad_widgets:
            widget.opacity = 1 if visible else 0
            widget.disabled = not visible
        if not visible:
            self.host.pad_keys("dpad", set())
            self.host.pad_keys(("button", C.K_SPACE), set())
            self.host.pad_keys(("button", C.K_RETURN), set())

    def _on_key_down(self, window, key, scancode=None, codepoint=None,
                     modifier=None):
        converted = _convert_key(key)
        if converted is not None and key != 27:  # Esc/Back closes via the IDE
            self.host.key_event(True, converted)
        return False

    def _on_key_up(self, window, key, scancode=None, *args):
        converted = _convert_key(key)
        if converted is not None:
            self.host.key_event(False, converted)
        return False

    def shutdown(self):
        Window.unbind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        try:
            self.dismiss(animation=False)
        except TypeError:
            self.dismiss()
