"""Compare generated page rules with the original function on real frames.

Oracle: the recovered 现在画面 bytecode, answering every recognition query
from the screenshot with backend.vision.color (original engine semantics).
Candidate: backend.ui.pages.PageDetector over assets/pages.json.

    uv run python tools/legacy_extract/validate_pages.py assets/pages.json evidence/**/*.png
"""
import glob
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.ui.pages import Frame, PageDetector, evaluate  # noqa: E402
from explore import DECISIONS, Explorer  # noqa: E402


class Oracle(Explorer):
    def real(self, command, args):
        check = {'kind': DECISIONS[command], 'args': args}
        if check['kind'] == 'points':
            return bool(evaluate(check, self.frame))
        if check['kind'] == 'color':
            from backend.vision import color
            hit = color.cmp_color(self.frame.image, args[0], args[1], args[2], float(args[3]))
            return None if hit < 0 else hit
        from backend.vision import color
        if check['kind'] == 'find_multi':
            x1, y1, x2, y2, first, offsets, direction, similarity = args[:8]
            found = color.find_multi_color(self.frame.image, x1, y1, x2, y2, first, offsets or '',
                                           int(float(direction)), float(similarity), self.frame.view)
        else:
            x1, y1, x2, y2, colors, direction, similarity = args[:7]
            found = color.find_multi_color(self.frame.image, x1, y1, x2, y2, colors, '',
                                           int(float(direction)), float(similarity), self.frame.view)
        return None if found[0] < 0 else found

    def decide(self, command, args, index, hit=None):
        return self.real(command, args)

    def page(self, frame):
        self.frame = frame
        return self.run(self.globals[b'id' + '现在画面'.encode().hex().encode()], [])


def load(path):
    bgr = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def main():
    rules = Path(sys.argv[1])
    files = sorted({f for pattern in sys.argv[2:] for f in glob.glob(pattern, recursive=True)})
    detector, oracle = PageDetector(rules), Oracle()
    agree, report, seeds = 0, [], []
    for file in files:
        image = load(file)
        if image.shape[:2] != (720, 1280):
            continue
        original = oracle.page(Frame(image))
        seeds.append(sorted(json.dumps([d['kind'], d['args']], ensure_ascii=False)
                            for d in original['decisions'] if d['hit']))
        expected = original['value'] if original['end'] == 'return' else f"<{original['end']}: {original['value']}>"
        got = detector.detect(Frame(image))
        agree += expected == got
        report.append({'file': file, 'original': expected, 'generated': got,
                       'taps': [t for t in original['trace'] if t[0] in ('tap', 'touch')]})
        mark = 'OK ' if expected == got else 'DIFF'
        print(f'{mark} {expected!s:14} {got!s:14} {file}')
    print(f'agree {agree}/{len(report)}')
    here = Path(__file__).resolve().parent
    (here / 'validation.json').write_text(json.dumps({'agree': agree, 'frames': len(report), 'results': report},
                                                     ensure_ascii=False, indent=1), encoding='utf-8')
    # Hit-sets seen on real frames: seeds for the next exploration. Merge with
    # existing seeds so frames that are no longer on disk keep contributing.
    seeds_file = here / 'seeds.json'
    old = json.loads(seeds_file.read_text(encoding='utf-8')) if seeds_file.exists() else []
    unique = sorted({tuple(s) for s in old + seeds})
    seeds_file.write_text(json.dumps([list(s) for s in unique], ensure_ascii=False, indent=0), encoding='utf-8')
    return agree == len(report)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
