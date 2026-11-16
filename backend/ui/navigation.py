"""ALAS-style page graph and navigation for 战舰少女R.

Pages are recognised by the rules generated from the original 现在画面
(backend.ui.pages). Links carry the original click targets
(backend.ui.assets). Pages outside the graph (result screens, popups,
dialogs) are handled with the original script's default action for that
page (assets/page_handlers.json), the same fallback 收远征 uses.

The device only needs `screenshot() -> RGB ndarray` and `click(x, y)` in
1280x720 screen coordinates.
"""
import json
import logging
from pathlib import Path
import time

from backend.alas.page import Page
from backend.alas.timer import Timer
from backend.ui import assets
from backend.ui.pages import Frame, PageDetector

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger('warship.ui')

# --- page graph --------------------------------------------------------------
page_main = Page(None, name='港区')
page_sortie = Page(None, name='出征-出征')
page_exercise = Page(None, name='出征-演习')
page_expedition = Page(None, name='出征-远征')
page_campaign = Page(None, name='出征-战役')
page_decisive = Page(None, name='出征-决战')

SORTIE_TABS = {
    page_sortie: assets.TAB_SORTIE,
    page_exercise: assets.TAB_EXERCISE,
    page_expedition: assets.TAB_EXPEDITION,
    page_campaign: assets.TAB_CAMPAIGN,
    page_decisive: assets.TAB_DECISIVE,
}
# 港区 -> 出征 opens the last used tab; ui_goto re-plans from whichever tab appears.
page_main.link(assets.SORTIE, page_sortie)
for tab_page in SORTIE_TABS:
    tab_page.link(assets.BACK, page_main)
    for other, button in SORTIE_TABS.items():
        if other is not tab_page:
            tab_page.link(button, other)

PAGES = {p.name: p for p in (page_main, *SORTIE_TABS)}


class GameStuckError(RuntimeError):
    pass


class UnknownPageError(RuntimeError):
    pass


class UI:
    """Navigation primitives shared by every task."""

    def __init__(self, device, detector=None, handlers=None, interval=0.3, sleep=time.sleep, rng=None):
        self.device = device
        self.detector = detector or PageDetector(ROOT / 'assets/pages.json')
        if handlers is None:
            handlers = json.loads((ROOT / 'assets/page_handlers.json').read_text(encoding='utf-8'))
        self.handlers = handlers
        self.interval = interval
        self.sleep = sleep
        self.rng = rng
        self.frame = None
        self.history = []  # (page, action) for diagnostics and loop detection

    # --- frames and input ---------------------------------------------------
    def screenshot(self):
        self.frame = Frame(self.device.screenshot())
        return self.frame

    def get_current_page(self, frame=None):
        return self.detector.detect(frame or self.frame or self.screenshot())

    def appear(self, page_name, frame=None):
        return self.detector.is_page(page_name, frame or self.frame)

    def click(self, button, reason=''):
        x, y = button.screen(self.rng) if self.rng else button.screen()
        log.info('click %s (%d,%d) %s', button.name, x, y, reason)
        self.history.append((reason, button.name))
        self.device.click(x, y)

    def tap_portrait(self, x, y, name, reason=''):
        self.click(assets.Button(name, x, y, 'page_handlers.json', jitter=0), reason)

    # --- generic handling ---------------------------------------------------
    def handle_default(self, page):
        """Run the original script's default action for a page; False if none."""
        handler = self.handlers.get(page) if page else None
        if not handler or not handler.get('first_tap'):
            return False
        x, y = handler['first_tap']
        self.tap_portrait(x, y, f'{page}默认处理', reason=page)
        return True

    # --- navigation -----------------------------------------------------------
    def ui_goto(self, destination, timeout=60, unknown_limit=10, repeat_limit=6):
        """Navigate to `destination` (Page or page name), re-planning every frame."""
        destination = PAGES[destination] if isinstance(destination, str) else destination
        Page.init_connection(destination)
        deadline = Timer(timeout).start()
        unknown = 0
        last_action, repeats = None, 0
        while True:
            self.screenshot()
            current = self.get_current_page()
            if current == destination.name:
                log.info('arrived at %s', current)
                return current
            if deadline.reached():
                raise GameStuckError(f'无法到达{destination.name}：当前页面 {current}')
            page = PAGES.get(current)
            if page is not None and page.parent is not None:
                button = page.links[page.parent]
                action = (current, button.name)
                self.click(button, reason=f'{current} -> {page.parent.name}')
                unknown = 0
            elif current is not None and self.handle_default(current):
                action = (current, 'default')
                unknown = 0
            else:
                unknown += 1
                action = None
                if unknown >= unknown_limit:
                    raise UnknownPageError(f'连续{unknown}帧无法识别页面，停止输入')
            # The same click on the same page over and over means the click
            # does not work (wrong coordinates, changed UI): stop, don't spam.
            repeats = repeats + 1 if action is not None and action == last_action else 0
            last_action = action
            if repeats >= repeat_limit:
                raise GameStuckError(f'在{current}重复点击{action[1]} {repeats + 1}次无变化')
            self.sleep(self.interval)

    def ui_ensure(self, destination, **kwargs):
        """ui_goto, but return immediately if already there."""
        name = destination if isinstance(destination, str) else destination.name
        if self.get_current_page(self.screenshot()) == name:
            return name
        return self.ui_goto(destination, **kwargs)
