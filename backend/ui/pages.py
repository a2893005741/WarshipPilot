"""Page detection from the rules generated out of the original 现在画面.

assets/pages.json is produced by tools/legacy_extract (do not edit by hand).
A page matches when every group has at least one matching check and none of
its `none` checks match; pages are tried in the generated order, which
reproduces the original function's priority.
"""
import json
from pathlib import Path

from backend.vision import color

KINDS = ('points', 'color', 'find_multi', 'find')


class Frame:
    """One screenshot plus a per-frame cache of check results."""

    def __init__(self, image):
        if image.shape[:2] != (color.SCREEN_H, color.SCREEN_W):
            raise ValueError(f'expected {color.SCREEN_W}x{color.SCREEN_H} RGB frame, got {image.shape[1]}x{image.shape[0]}')
        self.image = image
        self.cache = {}
        self._view = None

    @property
    def view(self):
        if self._view is None:
            self._view = color.portrait_view(self.image)
        return self._view


def evaluate(check, frame):
    kind, args = check['kind'], check['args']
    if kind == 'points':
        return color.cmp_points(frame.image, args[0], float(args[1]) if len(args) > 1 else 0.9)
    if kind == 'color':
        x, y, colors, similarity = args[:4]
        return color.cmp_color(frame.image, x, y, colors, float(similarity)) >= 0
    if kind == 'find_multi':
        x1, y1, x2, y2, first, offsets, direction, similarity = args[:8]
        return color.find_multi_color(frame.image, x1, y1, x2, y2, first, offsets or '',
                                      int(float(direction)), float(similarity), frame.view)[0] >= 0
    if kind == 'find':
        x1, y1, x2, y2, colors, direction, similarity = args[:7]
        return color.find_multi_color(frame.image, x1, y1, x2, y2, colors, '',
                                      int(float(direction)), float(similarity), frame.view)[0] >= 0
    raise ValueError(f'unknown check kind {kind}')


class PageDetector:
    def __init__(self, path: Path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.checks = data['checks']
        self.pages = data['pages']
        self.names = sorted({p['name'] for p in self.pages})

    def check(self, check_id, frame):
        if check_id not in frame.cache:
            frame.cache[check_id] = evaluate(self.checks[check_id], frame)
        return frame.cache[check_id]

    def matches(self, rule, frame):
        if any(self.check(c, frame) for c in rule.get('none', ())):
            return False
        return all(any(self.check(c, frame) for c in group) for group in rule['all'])

    def detect(self, frame):
        """Return the current page name, or None for an unknown screen."""
        if not isinstance(frame, Frame):
            frame = Frame(frame)
        for rule in self.pages:
            if self.matches(rule, frame):
                return rule['name']
        return None

    def is_page(self, name, frame):
        """True if any rule of `name` matches (ignores priority; for waits)."""
        if not isinstance(frame, Frame):
            frame = Frame(frame)
        return any(self.matches(r, frame) for r in self.pages if r['name'] == name)
