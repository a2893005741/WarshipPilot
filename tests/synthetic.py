"""Synthetic frames and a scripted device for offline UI tests.

A frame for page P is painted from P's own generated rule: the expected
colour of every check point is written onto a black 1280x720 canvas. No real
screenshot (with account data) needs to live in the repository.
"""
import itertools
import json
from pathlib import Path

import numpy as np

from backend.ui.pages import PageDetector
from backend.vision import color

ROOT = Path(__file__).resolve().parents[1]
DETECTOR = PageDetector(ROOT / 'assets/pages.json')


def _paint_check(image, check):
    kind, args = check['kind'], check['args']
    if kind == 'points':
        for p in color.parse_points(args[0]):
            X, Y = p.screen
            image[Y, X] = p.colors[0].rgb
    elif kind == 'color':
        X, Y = color.to_screen(args[0], args[1])
        image[Y, X] = color.parse_colors(args[2])[0].rgb
    else:  # find_multi / find: draw the pattern at the region centre
        x1, y1, x2, y2 = (int(float(v)) for v in args[:4])
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        X, Y = color.to_screen(cx, cy)
        image[Y, X] = color.parse_colors(args[4])[0].rgb
        if kind == 'find_multi' and args[5]:
            for p in color.parse_points(args[5]):
                X, Y = color.to_screen(cx + int(p.x), cy + int(p.y))
                image[Y, X] = p.colors[0].rgb


def frame_for(page, extra=()):
    """A frame the detector recognises as `page`; `extra` check ids are painted too."""
    for rule in (r for r in DETECTOR.pages if r['name'] == page):
        for choice in itertools.product(*rule['all']):
            image = np.zeros((720, 1280, 3), np.uint8)
            for check_id in (*choice, *extra):
                _paint_check(image, DETECTOR.checks[check_id])
            if DETECTOR.detect(image) == page:
                return image
    raise ValueError(f'cannot synthesise a frame for {page}')


def paint_points(image, expression):
    """Paint a raw 'x|y|color,...' expression (task-level checks)."""
    _paint_check(image, {'kind': 'points', 'args': [expression]})
    return image


class ScriptedDevice:
    """Screens + click transitions. transitions[(screen, button_name)] = next screen."""

    def __init__(self, screens, transitions, start, buttons):
        self.screens, self.transitions, self.state = screens, transitions, start
        self.buttons = buttons  # name -> (X, Y) screen coordinates
        self.clicks = []

    def screenshot(self):
        return self.screens[self.state]

    def click(self, x, y):
        name = min(self.buttons, key=lambda n: (self.buttons[n][0] - x) ** 2 + (self.buttons[n][1] - y) ** 2)
        bx, by = self.buttons[name]
        if (bx - x) ** 2 + (by - y) ** 2 > 12 ** 2:
            name = f'({x},{y})'
        self.clicks.append((self.state, name))
        self.state = self.transitions.get((self.state, name), self.state)


def handlers():
    return json.loads((ROOT / 'assets/page_handlers.json').read_text(encoding='utf-8'))
