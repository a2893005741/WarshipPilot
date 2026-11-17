"""Read expedition countdowns on the 出征-远征 page (1280x720 RGB frames).

Each chapter lists up to four expeditions. The white panel on the right of a
row shows HH:MM:SS: black while a fleet is away (远征中, or 00:00:00 once
已完成), grey for the duration of an idle expedition (需耗时). Rows without
a panel (e.g. the single-expedition 第十章) have a dark background.

Rows are classified by text darkness here; the black countdowns are read with
the AzurPilot-style Duration OCR, whose template set (assets/ocr/duration.png,
cut from live frames) answers first and only leaves unknown glyphs to the
OCR model. The original 收远征 never read these timers, so there is no
original asset for this font.
"""
from functools import lru_cache

import cv2
import numpy as np

from module.ocr.ocr import Duration
from module.ocr.template import OcrTemplate

# Digits of row 1 span y 126-153; the row divider below sits near y 167.
ROW_TOPS = tuple(round(118 + 142.5 * i) for i in range(4))  # timer box top per row
BOX_X0, BOX_X1, BOX_H = 1062, 1242, 44
PANEL_MIN = 200      # median grey of the white panel (measured 242)
INK_GAP = 40         # text is at least this much darker than the panel
RUNNING_MAX = 120    # median grey of black text (measured 51); idle grey text 180
TEXT = (51, 51, 51)  # RGB of a running countdown


@lru_cache(maxsize=1)
def template():
    # Learned glyphs go to log/ocr/duration.npz under the installation root.
    return OcrTemplate('duration', '0123456789')


def row_area(row):
    top = ROW_TOPS[row]
    return BOX_X0, top, BOX_X1, top + BOX_H


def row_state(gray, row):
    """'none' (no panel / no text), 'idle' (grey duration) or 'running'."""
    x0, y0, x1, y1 = row_area(row)
    box = gray[y0:y1, x0:x1]
    bg = float(np.median(box))
    if bg < PANEL_MIN:
        return 'none'
    mask = box < bg - INK_GAP
    if not mask.any():
        return 'none'
    return 'running' if np.median(box[mask]) <= RUNNING_MAX else 'idle'


def running_rows(image):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return [row for row in range(len(ROW_TOPS)) if row_state(gray, row) == 'running']


def reader(rows, ocr_template=None):
    return Duration([row_area(r) for r in rows], letter=TEXT, threshold=128, name='EXPEDITION_TIMER',
                    template=ocr_template if ocr_template is not None else template())


def running(image, ocr_template=None):
    """(remaining seconds of every expedition away on this chapter,
    number of running rows whose countdown could not be read)."""
    rows = running_rows(image)
    if not rows:
        return [], 0
    ocr = reader(rows, ocr_template)
    values = ocr.ocr(image)
    values = values if isinstance(values, list) else [values]
    seconds = [int(v.total_seconds()) for v, ok in zip(values, ocr.last_valid) if ok]
    return seconds, ocr.last_valid.count(False)
