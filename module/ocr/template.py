"""OCR templates: a fast glyph-matching path in front of the OCR model.

Game numbers use a few fixed fonts, so once a glyph is known, matching it is
far cheaper than running the recognition model. A template set reads the
same pre-processed image the model would get (``extract_letters`` +
``crop_to_text``: dark letters on white). When every glyph matches, the model
is skipped; otherwise the model reads the line and, if its answer is valid,
the glyphs are cut out and learned so the next frame takes the fast path.

Shipped glyphs live in ``assets/ocr/<name>.png`` (a strip, one GLYPH_W wide
column per character of ``alphabet``). Learned glyphs are cached in
``log/ocr/<name>.npz``, outside the Git work tree used by the updater.
"""
import logging
from pathlib import Path
import threading

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger('warship.ocr')

GLYPH_W, GLYPH_H = 16, 24
INK = 0.5            # ink > INK is part of a glyph (pre-processed pixel < 128)
SEPARATOR_HEIGHT = 0.85
LEARN_LIMIT = 6      # variants kept per character


def ink_of(image):
    return 1 - image.astype(np.float32) / 255


def split_glyphs(ink):
    """Column runs of ink, left to right, each cropped to its own rows."""
    cols = (ink > INK).any(axis=0)
    runs, start = [], None
    for x, value in enumerate(np.append(cols, False)):
        if value and start is None:
            start = x
        elif not value and start is not None:
            runs.append((start, x))
            start = None
    out = []
    for a, b in runs:
        ys = np.where((ink[:, a:b] > INK).any(axis=1))[0]
        glyph = ink[ys[0]:ys[-1] + 1, a:b]
        if glyph.shape[0] >= 6 and glyph.shape[1] >= 2:
            out.append(glyph)
    return out


def normalise(glyph):
    return cv2.resize(glyph.astype(np.float32), (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA)


class OcrTemplate:
    """Glyph templates for one font, e.g. OcrTemplate('duration', '0123456789')."""

    def __init__(self, name, alphabet, separator=':', max_diff=0.16, root=ROOT):
        self.name, self.alphabet, self.separator = name, alphabet, separator
        self.max_diff = max_diff
        self.shipped = Path(root) / 'assets' / 'ocr' / f'{name}.png'
        self.learned = Path(root) / 'log' / 'ocr' / f'{name}.npz'
        self._lock = threading.Lock()
        self._chars, self._glyphs = self._load()

    def _load(self):
        chars, glyphs = [], []
        if self.shipped.exists():
            strip = cv2.imdecode(np.fromfile(self.shipped, np.uint8), cv2.IMREAD_GRAYSCALE)
            strip = strip.astype(np.float32) / 255
            for i, char in enumerate(self.alphabet):
                chars.append(char)
                glyphs.append(strip[:, i * GLYPH_W:(i + 1) * GLYPH_W])
        try:
            data = np.load(self.learned)
            chars += [str(c) for c in data['chars']]
            glyphs += list(data['glyphs'].astype(np.float32))
        except (OSError, KeyError, ValueError):
            pass
        return chars, glyphs

    def _split(self, image):
        """[(kind, glyph)] with kind 'sep' for separators, else 'char'."""
        parts = split_glyphs(ink_of(image))
        if not parts:
            return []
        height = max(g.shape[0] for g in parts)
        return [('sep' if self.separator and g.shape[0] < height * SEPARATOR_HEIGHT and
                 g.shape[1] <= height * 0.4 else 'char', g) for g in parts]

    def _match(self, glyph):
        if not self._glyphs:
            return None, 1.0
        sample = normalise(glyph)
        scores = [float(np.abs(sample - t).mean()) for t in self._glyphs]
        best = int(np.argmin(scores))
        return self._chars[best], scores[best]

    def read(self, image):
        """Text of a pre-processed line, or None when any glyph is unknown."""
        parts = self._split(image)
        if not parts:
            return None
        text = []
        with self._lock:
            for kind, glyph in parts:
                if kind == 'sep':
                    text.append(self.separator)
                    continue
                char, score = self._match(glyph)
                if char is None or score > self.max_diff:
                    return None
                text.append(char)
        return ''.join(text)

    def learn(self, image, text):
        """Remember the glyphs of a line the model read as `text`."""
        parts = self._split(image)
        if len(parts) != len(text):
            return 0
        added = 0
        with self._lock:
            for (kind, glyph), char in zip(parts, text):
                if (kind == 'sep') != (char == self.separator):
                    return added
                if kind == 'sep' or char not in self.alphabet:
                    continue
                known, score = self._match(glyph)
                if known == char and score <= self.max_diff:
                    continue
                if self._chars.count(char) >= LEARN_LIMIT:
                    continue
                self._chars.append(char)
                self._glyphs.append(normalise(glyph))
                added += 1
            if added:
                self._save()
        if added:
            log.info('OCR template %s learned %d glyph(s) from "%s"', self.name, added, text)
        return added

    def _save(self):
        count = len(self.alphabet) if self.shipped.exists() else 0
        chars, glyphs = self._chars[count:], self._glyphs[count:]
        try:
            self.learned.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.learned.with_suffix('.tmp.npz')
            np.savez(temporary, chars=np.array(chars), glyphs=np.stack(glyphs).astype(np.float16))
            temporary.replace(self.learned)
        except OSError as exc:
            log.warning('OCR template %s not saved: %s', self.name, exc)
