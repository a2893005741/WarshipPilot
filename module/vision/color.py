"""Colour-point primitives with the original engine's semantics.

The recovered script addresses a 540x960 portrait canvas and writes colours
as BBGGRR. The game runs landscape at 1280x720, so every script point is
mapped through the same rotation + scale the original engine used.

Native contract (see 项目解析/深入分析/02-识别接口.md):

* a point matches when every channel is inside its explicit deviation
  (``BBGGRR-DDDDDD``), OR when |dR|+|dG|+|dB| <= T, with
  T = int((1 - float32(similarity)) * 765) for similarity < 0.999, else 0;
* coordinates scale with floor(v * scale + 0.5);
* FindMultiColor / FindColor scan directions 0-8 as tabulated below.
"""
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np

PORTRAIT_W, PORTRAIT_H = 540, 960
SCREEN_W, SCREEN_H = 1280, 720
SCALE = SCREEN_W / PORTRAIT_H  # 4/3: both axes scale identically.


def to_screen(x, y):
    """Script portrait (x, y) -> landscape screen (X, Y).

    Portrait x runs along the landscape vertical axis, reversed; portrait y
    runs along the landscape horizontal axis.
    """
    px = math.floor(float(x) * SCALE + 0.5)
    py = math.floor(float(y) * SCALE + 0.5)
    return min(py, SCREEN_W - 1), SCREEN_H - 1 - min(px, SCREEN_H - 1)


def to_portrait(X, Y):
    """Inverse of to_screen, for turning a screen hit back into script space."""
    return (SCREEN_H - 1 - Y) / SCALE, X / SCALE


def threshold(similarity):
    similarity = np.float32(similarity)
    if similarity >= np.float32(0.999):
        return 0
    return int((np.float32(1.0) - similarity) * np.float32(765.0))


@dataclass(frozen=True)
class Color:
    rgb: tuple      # expected (R, G, B)
    deviation: tuple  # explicit per-channel deviation (R, G, B); zeros = exact


def _bgr(hex6):
    value = int(hex6, 16)
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


@lru_cache(maxsize=4096)
def parse_colors(expression):
    """'BBGGRR[-DDDDDD][|BBGGRR[-DDDDDD]...]' -> tuple of Color alternatives."""
    result = []
    for alternative in expression.split('|'):
        color, _, deviation = alternative.partition('-')
        if len(color) != 6:
            raise ValueError(f'unsupported colour: {alternative!r}')
        result.append(Color(_bgr(color), _bgr(deviation) if deviation else (0, 0, 0)))
    return tuple(result)


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    colors: tuple

    @property
    def screen(self):
        return to_screen(self.x, self.y)


@lru_cache(maxsize=4096)
def parse_points(expression):
    """'x|y|color,x|y|color,...' (CmpColorEx / offset lists)."""
    points = []
    for item in expression.split(','):
        x, y, color = item.split('|', 2)
        points.append(Point(float(x), float(y), parse_colors(color)))
    return tuple(points)


def color_match(actual, colors, limit):
    """actual: RGB int array (..., 3). Returns bool array of shape actual[..., 0]."""
    actual = actual.astype(np.int16)
    hit = np.zeros(actual.shape[:-1], bool)
    for color in colors:
        diff = np.abs(actual - np.array(color.rgb, np.int16))
        explicit = np.all(diff <= np.array(color.deviation, np.int16), axis=-1)
        hit |= explicit | (diff.sum(axis=-1) <= limit)
    return hit


def pixel(image, x, y):
    X, Y = to_screen(x, y)
    return image[Y, X]


def cmp_color(image, x, y, colors, similarity=0.9):
    """CmpColor: index of first matching alternative, or -1."""
    actual = pixel(image, x, y)
    limit = threshold(similarity)
    for index, color in enumerate(parse_colors(colors)):
        if color_match(actual, (color,), limit):
            return index
    return -1


def cmp_points(image, expression, similarity=0.9):
    """CmpColorEx: every point must match."""
    limit = threshold(similarity)
    for point in parse_points(expression):
        X, Y = point.screen
        if not color_match(image[Y, X], point.colors, limit):
            return False
    return True


# Scan order of FindMultiColor/FindColor in portrait script coordinates.
def _scan_order(xs, ys, direction, cx, cy):
    if direction == 1:  # centre outwards (Chebyshev rings), then row-major
        return np.lexsort((xs, ys, np.maximum(np.abs(xs - cx), np.abs(ys - cy))))
    keys = {
        0: (xs, ys),    # rows top->bottom, left->right
        2: (-xs, -ys),  # rows bottom->top, right->left
        3: (xs, -ys),   # rows bottom->top, left->right
        4: (-xs, ys),   # rows top->bottom, right->left
        5: (ys, xs),    # columns left->right, top->bottom
        6: (ys, -xs),   # columns right->left, top->bottom
        7: (-ys, xs),   # columns left->right, bottom->top
        8: (-ys, -xs),  # columns right->left, bottom->top
    }[direction]
    return np.lexsort(keys)


def portrait_view(image):
    """Script-space view of a landscape frame, sampled with to_screen."""
    rows = np.array([to_screen(x, 0)[1] for x in range(PORTRAIT_W)])   # portrait x -> screen Y
    cols = np.array([to_screen(0, y)[0] for y in range(PORTRAIT_H)])   # portrait y -> screen X
    # view[y, x] == pixel(image, x, y): same sampling as single-point checks.
    return image[np.ix_(rows, cols)].transpose(1, 0, 2)


def find_multi_color(image, x1, y1, x2, y2, first, offsets='', direction=0, similarity=0.9, view=None):
    """FindMultiColor in script space; returns (x, y) or (-1, -1)."""
    x1, y1, x2, y2 = (int(v) for v in (x1, y1, x2, y2))
    if (x1, y1, x2, y2) == (0, 0, 0, 0):
        x1, y1, x2, y2 = 0, 0, PORTRAIT_W - 1, PORTRAIT_H - 1
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(PORTRAIT_W - 1, x2), min(PORTRAIT_H - 1, y2)
    if x2 < x1 or y2 < y1:
        return -1, -1
    view = portrait_view(image) if view is None else view
    limit = threshold(similarity)
    region = view[y1:y2 + 1, x1:x2 + 1]
    ys, xs = np.nonzero(color_match(region, parse_colors(first), limit))
    xs, ys = xs + x1, ys + y1
    if offsets:
        for point in parse_points(offsets):
            px, py = xs + int(point.x), ys + int(point.y)
            inside = (px >= 0) & (px < PORTRAIT_W) & (py >= 0) & (py < PORTRAIT_H)
            ok = np.zeros(len(xs), bool)
            if inside.any():
                ok[inside] = color_match(view[py[inside], px[inside]], point.colors, limit)
            xs, ys = xs[ok], ys[ok]
    if not len(xs):
        return -1, -1
    index = _scan_order(xs, ys, int(direction), (x1 + x2) / 2, (y1 + y2) / 2)[0]
    return int(xs[index]), int(ys[index])
