"""ONNX text-line recogniser, following AzurPilot's AlOcr.

AzurPilot runs its AlOCR / PP-OCR recognition models through rapidocr. That
package pins opencv-python, which clashes with opencv-python-headless used
here, so the recognition step rapidocr performs (TextRecognizer: resize to
height 48, normalise to [-1, 1], CTC greedy decode) is done directly with
onnxruntime. Models and dictionaries are AzurPilot's (bin/ocr_models).
"""
import logging
import math
import os
from pathlib import Path
import threading

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'bin' / 'ocr_models'
log = logging.getLogger('warship.ocr')

# name -> (model, dictionary); AzurPilot's "auto" choice for English/digits.
ONNX_MODEL_PARAMS = {
    'azur_lane': (MODELS / 'azur_lane' / 'alocr-en-us-v2.6.nvc.onnx', MODELS / 'azur_lane' / 'en_dict.txt'),
}
REC_HEIGHT, REC_MIN_WIDTH = 48, 320


def _thread_options():
    """AZURPILOT_OCR_THREADS semantics: default 2 compute threads, 1-16."""
    try:
        requested = int(os.environ.get('AZURPILOT_OCR_THREADS', '2'))
    except ValueError:
        requested = 2
    return min(max(1, requested), os.cpu_count() or 1, 16)


class AlOcr:
    """Lazily loaded recogniser for one logical model name."""

    def __init__(self, name='azur_lane'):
        if name not in ONNX_MODEL_PARAMS:
            raise ValueError(f'Unsupported OCR model: {name}')
        self.name = name
        self._session = None
        self._characters = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        if self._session is not None:
            return
        import onnxruntime as ort
        model, keys = ONNX_MODEL_PARAMS[self.name]
        options = ort.SessionOptions()
        options.log_severity_level = 3  # the exported graph carries unused initialisers
        options.intra_op_num_threads = _thread_options()
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(model), sess_options=options,
                                             providers=['CPUExecutionProvider'])
        words = keys.read_text(encoding='utf-8').splitlines()
        # rapidocr: index 0 is the CTC blank, a space follows the dictionary.
        self._characters = ['blank', *words, ' ']
        log.info('OCR model %s loaded', self.name)

    @staticmethod
    def _normalise(image, width):
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        h, w = image.shape[:2]
        resized_w = min(width, int(math.ceil(REC_HEIGHT * w / max(h, 1))))
        resized = cv2.resize(image, (max(resized_w, 1), REC_HEIGHT)).astype(np.float32)
        resized = (resized.transpose(2, 0, 1) / 255 - 0.5) / 0.5
        padded = np.zeros((3, REC_HEIGHT, width), np.float32)
        padded[:, :, :resized.shape[2]] = resized
        return padded

    def _decode(self, probabilities):
        best = probabilities.argmax(axis=1)
        text, last = [], 0
        for index in best:
            if index != last and index != 0:
                text.append(self._characters[index])
            last = index
        return ''.join(text)

    def ocr_for_single_lines(self, img_list):
        if not img_list:
            return []
        with self._lock:
            self._ensure_loaded()
            ratio = max(REC_MIN_WIDTH / REC_HEIGHT, *(i.shape[1] / max(i.shape[0], 1) for i in img_list))
            width = int(REC_HEIGHT * ratio)
            batch = np.stack([self._normalise(i, width) for i in img_list])
            output = self._session.run(None, {self._session.get_inputs()[0].name: batch})[0]
        return [self._decode(p) for p in output]

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        results = self.ocr_for_single_lines(img_list)
        if cand_alphabet:
            results = [''.join(c for c in r if c in cand_alphabet) for r in results]
        return results
