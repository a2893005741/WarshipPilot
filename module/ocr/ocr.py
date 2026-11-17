"""OCR recognisers ported from AzurPilot (module/ocr/ocr.py): Ocr, Digit,
DigitCounter and Duration keep its interface, pre-processing
(extract_letters -> crop_to_text) and after-processing.

Addition: an optional OcrTemplate is tried first for every area; only areas
it cannot read go to the model, in one batch, and what the model reads is
learned by the template (see module/ocr/template.py).

Areas are (x1, y1, x2, y2) on the 1280x720 RGB screenshot.
"""
from datetime import timedelta
import logging
import re
import time

import numpy as np

from module.base.utils import crop, crop_to_text, extract_letters
from module.ocr.models import OCR_MODEL

log = logging.getLogger('warship.ocr')


class Ocr:
    SHOW_LOG = True

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet=None,
                 name=None, template=None):
        self.name = name or 'OCR'
        self._buttons = buttons
        self.letter = letter
        self.threshold = threshold
        self.alphabet = alphabet
        self.lang = lang
        self.template = template
        self.sources = []

    @property
    def cnocr(self):
        return getattr(OCR_MODEL, self.lang)

    @property
    def buttons(self):
        return self._buttons if isinstance(self._buttons, list) else [self._buttons]

    @buttons.setter
    def buttons(self, value):
        self._buttons = value

    def pre_process(self, image):
        return extract_letters(image, letter=self.letter, threshold=self.threshold).astype(np.uint8)

    def after_process(self, result):
        return result

    def valid(self, result):
        """Whether a raw model result may be learned by the template."""
        return bool(result)

    def ocr(self, image, direct_ocr=False):
        start = time.perf_counter()
        if direct_ocr:
            images = [self.pre_process(i) for i in image]
        else:
            images = [self.pre_process(crop(image, area)) for area in self.buttons]
        images = [crop_to_text(i) for i in images]

        raw = [self.template.read(i) if self.template else None for i in images]
        self.sources = ['template' if r is not None else 'model' for r in raw]
        pending = [i for i, r in enumerate(raw) if r is None]
        if pending:
            try:
                texts = self.cnocr.atomic_ocr_for_single_lines([images[i] for i in pending], self.alphabet)
            except Exception as exc:  # model missing/broken: those areas stay unreadable
                log.warning('%s OCR model unavailable: %s', self.name, exc)
                texts = [''] * len(pending)
            for i, text in zip(pending, texts):
                raw[i] = text
                if self.template and self.valid(text):
                    self.template.learn(images[i], text)

        results = [self.after_process(r) for r in raw]
        if self.SHOW_LOG:
            log.info('%s %.3fs %s %s', self.name, time.perf_counter() - start, results, self.sources)
        return results[0] if len(self.buttons) == 1 and not direct_ocr else results


class Digit(Ocr):
    """Plain numbers such as `45`; ocr() returns int (0 when empty)."""

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128,
                 alphabet='0123456789IDSB', name=None, template=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet,
                         name=name, template=template)

    def valid(self, result):
        return result.isdigit()

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')
        self.last_valid = bool(result and result.isdigit())
        return int(result) if self.last_valid else 0


class DigitCounter(Ocr):
    """Counters such as `14/15`; ocr() returns (current, remain, total)."""

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128,
                 alphabet='0123456789/IDSB', name=None, template=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet,
                         name=name, template=template)

    def valid(self, result):
        return bool(re.fullmatch(r'\d+/\d+', result))

    def after_process(self, result):
        result = super().after_process(result)
        return result.replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')

    def ocr(self, image, direct_ocr=False):
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list
        match = re.search(r'(\d+)/(\d+)', result)
        if match:
            current, total = (int(s) for s in match.groups())
            current = min(current, total)
            return current, total - current, total
        log.warning('[OCR] 意外的OCR结果: %s', result_list)
        return 0, 0, 0


class Duration(Ocr):
    """Times such as `01:30:00`; ocr() returns timedelta (list for several areas).

    `last_valid` tells a real 00:00:00 from an unreadable area, which
    AzurPilot's parse_time also reports as zero.
    """

    def __init__(self, buttons, lang='azur_lane', letter=(255, 255, 255), threshold=128,
                 alphabet='0123456789:IDSB', name=None, template=None):
        super().__init__(buttons, lang=lang, letter=letter, threshold=threshold, alphabet=alphabet,
                         name=name, template=template)
        self.last_valid = []

    def valid(self, result):
        return bool(re.fullmatch(r'\d{2}:\d{2}:\d{2}', result))

    def after_process(self, result):
        result = super().after_process(result)
        return result.replace('I', '1').replace('D', '0').replace('S', '5').replace('B', '8')

    def ocr(self, image, direct_ocr=False):
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if not isinstance(result_list, list):
            result_list = [result_list]
        parsed = [self.parse_time(r) for r in result_list]
        self.last_valid = [p is not None for p in parsed]
        parsed = [p or timedelta(0) for p in parsed]
        return parsed[0] if len(self.buttons) == 1 and not direct_ocr else parsed

    @staticmethod
    def parse_time(string):
        match = re.search(r'(\d{1,2}):?(\d{2}):?(\d{2})', string)
        if match:
            h, m, s = (int(v) for v in match.groups())
            if m < 60 and s < 60:
                return timedelta(hours=h, minutes=m, seconds=s)
        log.warning('[OCR] 无效的时长: %s', string)
        return None
