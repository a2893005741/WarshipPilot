"""Shared, lazily loaded OCR models (AzurPilot's OCR_MODEL).

    >>> from module.ocr.models import OCR_MODEL
    >>> OCR_MODEL.azur_lane.atomic_ocr_for_single_lines([image], '0123456789:')
"""
from functools import cached_property

from module.ocr.al_ocr import AlOcr


class OcrModel:
    @cached_property
    def azur_lane(self):
        """Digits, letters and times in the game UI."""
        return AlOcr(name='azur_lane')


OCR_MODEL = OcrModel()
