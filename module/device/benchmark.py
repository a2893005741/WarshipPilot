"""Screenshot / control method benchmark (after AzurPilot module/daemon/benchmark.py).

Speed is measured like AzurPilot: TEST_TOTAL calls, mean of the fastest 80%,
same rating bands. WarshipPilot adds two checks AzurPilot does not need:

* screenshot accuracy - page rules compare exact pixels, so every method's
  frame is checked against a lossless ADB frame taken right after it: the
  detected page and the result of every rule check must agree (lossy
  streams such as scrcpy/H.264 can be fast but useless here);
* control effect - a click is only counted as working when the game reacts.
  The test switches between two 出征 tabs and back, which changes nothing in
  the game, and requires the expected page after each click.

Screenshot benchmarks send no input. Control benchmarks tap the game and must
only be started by the user.
"""
from dataclasses import asdict, dataclass, field
import time

import numpy as np

from module.device.compat import RequestHumanTakeover, logger
from module.ui import assets
from module.ui.pages import Frame, PageDetector

TEST_TOTAL = 15
TEST_BEST = int(TEST_TOTAL * 0.8)
REFERENCE = 'ADB'


def rate_screenshot(cost):
    for limit, name in ((0.025, '极快'), (0.100, '超快'), (0.200, '很快'), (0.300, '快'),
                        (0.500, '中等'), (0.750, '慢'), (1.000, '很慢')):
        if cost < limit:
            return name
    return '极慢'


def rate_click(cost):
    for limit, name in ((0.100, '快'), (0.200, '中等'), (0.400, '慢')):
        if cost < limit:
            return name
    return '很慢'


@dataclass
class Result:
    method: str
    ok: bool = False
    cost: float = None          # seconds, mean of the fastest TEST_BEST runs
    rating: str = ''
    error: str = ''
    detail: dict = field(default_factory=dict)


def _timed(func, total=TEST_TOTAL):
    record = []
    for _ in range(total):
        start = time.perf_counter()
        func()
        record.append(time.perf_counter() - start)
    return float(np.mean(np.sort(record)[:max(1, int(total * 0.8))])), record


def compare_frames(detector, frame, reference):
    """Agreement of page + every rule check between two frames."""
    a, b = Frame(frame), Frame(reference)
    differing = [cid for cid in detector.checks if detector.check(cid, a) != detector.check(cid, b)]
    return {'page': detector.detect(a), 'reference_page': detector.detect(b),
            'checks': len(detector.checks), 'differing_checks': len(differing),
            'mean_abs_diff': round(float(np.mean(np.abs(frame.astype(np.int16) - reference.astype(np.int16)))), 3)}


def benchmark_screenshot(device, methods, detector: PageDetector, total=TEST_TOTAL, progress=None):
    results = []
    for method in methods:
        result = Result(method)
        if progress:
            progress(f'截图测速：{method}')
        try:
            device.screenshot(method)  # initialise the module (server push, IPC connect, ...)
            result.cost, record = _timed(lambda: device.screenshot(method), total)
            frame = device.screenshot(method)
            reference = device.screenshot(REFERENCE)
            result.detail = compare_frames(detector, frame, reference)
            result.detail['runs'] = [round(r * 1000, 1) for r in record]
            same = (result.detail['page'] == result.detail['reference_page']
                    and result.detail['differing_checks'] == 0)
            result.ok = same
            result.rating = rate_screenshot(result.cost)
            if not same:
                result.error = (f'画面与无损截图不一致：页面 {result.detail["page"]} / {result.detail["reference_page"]}，'
                                f'{result.detail["differing_checks"]} 项颜色检查不同')
        except RequestHumanTakeover as e:
            result.error = f'不可用：{e}'
        except Exception as e:
            logger.exception(e)
            result.error = f'{type(e).__name__}: {e}'[:300]
        results.append(result)
        logger.info(f'[测速] {method}: {result}')
    return results


# Two tabs on the 出征 page; switching between them has no side effect in game.
TAB_PAIR = (('出征-远征', assets.TAB_EXPEDITION), ('出征-演习', assets.TAB_EXERCISE))


def _wait_page(device, detector, name, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if detector.detect(Frame(device.screenshot())) == name:
            return True
        time.sleep(0.1)
    return False


def benchmark_click(device, methods, detector: PageDetector, rounds=2, progress=None):
    """Tab round trips per method. Requires the game on 出征-远征 or 出征-演习."""
    start_page = detector.detect(Frame(device.screenshot()))
    names = [p for p, _ in TAB_PAIR]
    if start_page not in names:
        raise RequestHumanTakeover(f'请先停在出征页的远征或演习标签再测试点击（当前：{start_page}）')
    results = []
    for method in methods:
        result = Result(method)
        if progress:
            progress(f'点击测试：{method}')
        costs, transitions = [], []
        try:
            current = detector.detect(Frame(device.screenshot()))
            for _ in range(rounds * 2):
                target, button = TAB_PAIR[0] if current == names[1] else TAB_PAIR[1]
                x, y = button.screen()
                started = time.perf_counter()
                device.click(x, y, method)
                costs.append(time.perf_counter() - started)
                reached = _wait_page(device, detector, target)
                transitions.append(reached)
                if not reached:
                    break
                current = target
            result.cost = float(np.mean(costs)) if costs else None
            result.ok = bool(transitions) and all(transitions)
            result.rating = rate_click(result.cost) if result.cost is not None else ''
            result.detail = {'clicks': len(costs), 'reacted': sum(transitions),
                             'runs': [round(c * 1000, 1) for c in costs]}
            if not result.ok:
                result.error = '点击后游戏没有切换标签'
        except RequestHumanTakeover as e:
            result.error = f'不可用：{e}'
        except Exception as e:
            logger.exception(e)
            result.error = f'{type(e).__name__}: {e}'[:300]
        results.append(result)
        logger.info(f'[测速] {method}: {result}')
    # Leave the game on the tab it started on.
    try:
        if detector.detect(Frame(device.screenshot())) != start_page:
            button = dict(TAB_PAIR)[start_page]
            device.click(*button.screen(), 'ADB')
    except Exception as e:
        logger.warning(f'[测速] 恢复标签失败: {e}')
    return results


def recommend(results):
    working = [r for r in results if r.ok and r.cost is not None]
    return min(working, key=lambda r: r.cost).method if working else None


def to_json(results):
    return [asdict(r) for r in results]
