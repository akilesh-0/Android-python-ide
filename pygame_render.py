"""Replays pygame-layer draw commands with Kivy graphics (main thread only).

Commands are drawn in pygame coordinates (y down); the caller sets up a
Translate/Scale transform that maps them onto the screen.
"""

import math
import os
import threading
from collections import OrderedDict

from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.graphics import (Color, Ellipse, Line, Mesh, PopMatrix, PushMatrix,
                           Rectangle, RoundedRectangle, Rotate, Scale,
                           Translate, Triangle)
from kivy.resources import resource_find

try:
    from kivy.graphics.tesselator import TYPE_POLYGONS, WINDING_ODD, Tesselator
except Exception:  # pragma: no cover
    Tesselator = None

# SDL_ttf isn't thread-safe: the game thread (measuring) and the main thread
# (rendering text) take turns through this lock.
TTF_LOCK = threading.Lock()
MONO_FONT = resource_find("data/fonts/RobotoMono-Regular.ttf") or "Roboto"

_labels = {}
_widths = {}
_heights = {}


def font_name_for(name):
    if name is None:
        return "Roboto"
    if name == "mono":
        return MONO_FONT
    if os.path.isfile(str(name)):
        return str(name)
    return "Roboto"


def _label_for(fontkey):
    label = _labels.get(fontkey)
    if label is None:
        name, px, bold, italic = fontkey
        label = CoreLabel(font_size=px, font_name=font_name_for(name),
                          bold=bold, italic=italic)
        _labels[fontkey] = label
    return label


def measure_text(fontkey, text):
    """Size of text in pixels. Safe to call from the game thread.

    Glyph widths are measured once per font and then summed, so later calls
    don't touch SDL_ttf at all.
    """
    with TTF_LOCK:
        label = _label_for(fontkey)
        table = _widths.get(fontkey)
        if table is None:
            table = _widths[fontkey] = {}
            for code in range(32, 127):
                table[chr(code)] = label.get_extents(chr(code))[0]
        total = 0
        for char in text:
            width = table.get(char)
            if width is None:
                width = table[char] = label.get_extents(char)[0]
            total += width
        height = _heights.get(fontkey)
        if height is None:
            height = _heights[fontkey] = label.get_extents("Ag")[1]
    return (int(total), int(height))


class Renderer:
    def __init__(self):
        self._images = {}
        self._bases = {}
        self._texts = OrderedDict()
        self._color = None
        self.last_error = None

    def draw_frame(self, commands, width, height):
        self._color = None
        self._draw(commands, width, height, 255, None)

    # ------------------------------------------------------------------
    def _set_color(self, color, alpha):
        r, g, b, a = color
        key = (r, g, b, a * alpha / 255.0)
        if key != self._color:
            Color(r / 255.0, g / 255.0, b / 255.0, key[3] / 255.0)
            self._color = key

    def _draw(self, commands, width, height, alpha, colorkey):
        for cmd in commands:
            try:
                self._draw_one(cmd, width, height, alpha, colorkey)
            except Exception as exc:  # a bad command must not kill the frame
                self.last_error = "%s: %s" % (type(exc).__name__, exc)

    def _draw_one(self, cmd, width, height, alpha, colorkey):
        kind = cmd[0]
        if kind == "group":
            self._group(cmd, alpha, colorkey)
            return
        if kind == "img":
            _, path, x, y, w, h, region = cmd
            texture = self._image_texture(path, region)
            if texture is not None:
                self._set_color((255, 255, 255, 255), alpha)
                Rectangle(texture=texture, pos=(x, y), size=(w, h))
            return

        color = cmd[1]
        if colorkey is not None and kind != "text" and color[:3] == colorkey:
            return
        self._set_color(color, alpha)

        if kind == "fill":
            Rectangle(pos=(0, 0), size=(width, height))
        elif kind == "rect":
            _, _, x, y, w, h, wd, radius = cmd
            if w <= 0 or h <= 0:
                return
            radius = min(radius, w / 2.0, h / 2.0)
            if wd <= 0:
                if radius > 0:
                    RoundedRectangle(pos=(x, y), size=(w, h), radius=[radius])
                else:
                    Rectangle(pos=(x, y), size=(w, h))
            else:
                wd = min(wd, w / 2.0, h / 2.0)
                half = wd / 2.0
                if radius > 0:
                    Line(rounded_rectangle=(x + half, y + half, w - wd, h - wd,
                                            radius), width=wd)
                else:
                    Line(rectangle=(x + half, y + half, w - wd, h - wd), width=wd)
        elif kind == "circle":
            _, _, cx, cy, r, wd = cmd
            segments = max(12, min(80, int(r * 1.5)))
            if wd <= 0 or wd >= r:
                Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r), segments=segments)
            else:
                Line(circle=(cx, cy, r - wd / 2.0), width=wd)
        elif kind == "ellipse":
            _, _, x, y, w, h, wd = cmd
            if w <= 0 or h <= 0:
                return
            if wd <= 0 or wd * 2 >= min(w, h):
                Ellipse(pos=(x, y), size=(w, h))
            else:
                half = wd / 2.0
                Line(ellipse=(x + half, y + half, w - wd, h - wd), width=wd)
        elif kind == "line":
            _, _, x1, y1, x2, y2, wd = cmd
            Line(points=[x1, y1, x2, y2], width=wd,
                 cap="none")
        elif kind == "lines":
            _, _, pts, closed, wd = cmd
            Line(points=[c for p in pts for c in p], width=wd,
                 close=bool(closed), cap="none")
        elif kind == "polygon":
            _, _, pts, wd = cmd
            if wd > 0:
                Line(points=[c for p in pts for c in p], width=wd,
                     close=True)
            else:
                self._fill_polygon(pts)
        elif kind == "arc":
            _, _, x, y, w, h, start, stop, wd = cmd
            cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
            if stop < start:
                stop += 2 * math.pi
            steps = max(8, min(90, int((stop - start) * max(rx, ry) / 3.0)))
            points = []
            for i in range(steps + 1):
                a = start + (stop - start) * i / steps
                points += [cx + rx * math.cos(a), cy - ry * math.sin(a)]
            Line(points=points, width=wd)
        elif kind == "text":
            _, _, fontkey, text, x, y = cmd
            texture = self._text_texture(fontkey, text)
            if texture is not None:
                Rectangle(texture=texture, pos=(x, y), size=texture.size)

    def _fill_polygon(self, pts):
        flat = [c for p in pts for c in p]
        if len(pts) == 3:
            Triangle(points=flat)
            return
        if Tesselator is not None:
            tess = Tesselator()
            tess.add_contour(flat)
            if tess.tesselate(WINDING_ODD, TYPE_POLYGONS):
                for vertices, indices in tess.meshes:
                    Mesh(vertices=vertices, indices=indices, mode="triangle_fan")
                return
        Line(points=flat, close=True)

    def _group(self, cmd, alpha, colorkey):
        _, sub, cx, cy, w, h, angle, sx, sy, galpha, gkey = cmd
        if galpha is not None:
            alpha = alpha * galpha / 255.0
        if gkey is not None:
            colorkey = gkey
        PushMatrix()
        try:
            if angle == 0 and sx == 1 and sy == 1:
                Translate(cx - w / 2.0, cy - h / 2.0)
            else:
                Translate(cx, cy)
                if angle:
                    Rotate(angle=-angle, axis=(0, 0, 1), origin=(0, 0))
                Scale(sx, sy, 1)
                Translate(-w / 2.0, -h / 2.0)
            self._draw(sub, w, h, alpha, colorkey)
        finally:
            PopMatrix()

    # -- textures (flipped once: the frame is drawn with a flipped y axis) -----
    def _image_texture(self, path, region):
        key = (path, region)
        texture = self._images.get(key)
        if texture is None:
            if region is None:
                texture = CoreImage(path, nocache=True).texture
            else:
                base = self._bases.get(path)
                if base is None:
                    base = CoreImage(path, nocache=True).texture
                    self._bases[path] = base
                rx = max(0, min(int(region[0]), base.width - 1))
                ry = max(0, min(int(region[1]), base.height - 1))
                rw = max(1, min(int(region[2]), base.width - rx))
                rh = max(1, min(int(region[3]), base.height - ry))
                texture = base.get_region(rx, base.height - ry - rh, rw, rh)
            texture.flip_vertical()
            texture.min_filter = "nearest"
            texture.mag_filter = "nearest"
            self._images[key] = texture
        return texture

    def _text_texture(self, fontkey, text):
        key = (fontkey, text)
        texture = self._texts.get(key)
        if texture is not None:
            self._texts.move_to_end(key)
            return texture
        name, px, bold, italic = fontkey
        with TTF_LOCK:
            label = CoreLabel(text=text, font_size=px, font_name=font_name_for(name),
                              bold=bold, italic=italic)
            label.refresh()
            texture = label.texture
        if texture is not None:
            texture.flip_vertical()
        self._texts[key] = texture
        if len(self._texts) > 400:
            self._texts.popitem(last=False)
        return texture
