"""Native expedition task: collect finished expeditions and redeploy.

Behaviour follows the original 收远征 (see tools/legacy_extract/policies.json):

    港区, finished badge on 出征     -> tap 出征
    港区, no badge                   -> done
    出征-出征 / 战役 / 演习 / 决战   -> tap 远征 tab
    出征-远征                        -> wait 1 s, tap the first lit "收取奖励"
                                        (slot rows x=387/280/172/66, y=812),
                                        none lit -> 返回
    战斗结果 (= expedition result)   -> tap to continue
    继续远征 dialog (newer game)     -> 确认 (redeploy) or 取消
    anything else                    -> original default handling

Every step is decided from a fresh screenshot; nothing is replayed blindly.
"""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from backend.alas.timer import Timer
from backend.ui import assets
from backend.ui.navigation import UI, GameStuckError, UnknownPageError
from backend.vision import color

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger('warship.expedition')

# --- assets (portrait script coordinates unless noted) -------------------------
FINISHED_BADGE = '83|934|2D59FF'          # 收远征: 港区 && CmpColorEx(...) == 1
SLOTS = (387, 280, 172, 66)               # 收远征: CmpColor(x, 812, "27DBFF", 0.9)
SLOT_Y, SLOT_COLOR = 812, '27DBFF'
OTHER_TABS = ('出征-出征', '出征-战役', '出征-演习', '出征-决战')
RESULT_PAGES = ('战斗结果', '远征完成')

# Newer game: "继续远征 / 是否使用该编队继续远征" after the result screen.
# Templates and the confirm-button colour come from the v0.4 live run
# (screen coordinates, 1280x720); buttons measured on the same frames.
CONTINUE_CONFIRM = assets.Button('继续远征-确认', 198, 368, 'v0.4 live: 固定延时点击(198,368)', jitter=0)
CONTINUE_CANCEL = assets.Button('继续远征-取消', 198, 592, 'evidence/expedition-list-after-collect.png', jitter=0)


def _template(name):
    image = cv2.imdecode(np.fromfile(ROOT / 'assets/game' / name, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


CONTINUE_TEMPLATES = ((390, 190, _template('expedition-continue-title.png')),
                      (515, 315, _template('expedition-continue-question.png')))
CONTINUE_BUTTON_PIXEL = ((450, 445), (231, 194, 32))  # (X, Y), RGB of the yellow 确认


def continue_dialog(image):
    for x, y, template in CONTINUE_TEMPLATES:
        h, w = template.shape[:2]
        score = cv2.matchTemplate(image[y:y + h, x:x + w], template, cv2.TM_CCOEFF_NORMED)[0, 0]
        if score < 0.96:
            return False
    (X, Y), rgb = CONTINUE_BUTTON_PIXEL
    return bool(np.all(np.abs(image[Y, X].astype(int) - rgb) < 35))


def collectable_slot(image):
    for x in SLOTS:
        if color.cmp_color(image, x, SLOT_Y, SLOT_COLOR, 0.9) >= 0:
            return x
    return None


@dataclass
class ExpeditionResult:
    collected: int = 0
    redeployed: int = 0
    inputs: int = 0
    pages: list = field(default_factory=list)


class Expedition(UI):
    def __init__(self, device, redeploy=True, timeout=600, **kwargs):
        super().__init__(device, **kwargs)
        self.redeploy = redeploy
        self.timeout = timeout

    def run(self):
        result = self.result = ExpeditionResult()  # live view for the runner
        deadline = Timer(self.timeout).start()
        unknown = 0
        last_action, repeats = None, 0
        empty_visits = 0     # 远征 page with nothing to collect while 港区 still shows the badge
        pending = False      # a slot was tapped, its result screen not seen yet
        settled = False      # waited once on the current 远征 list (original: delay 1000)
        while True:
            if deadline.reached():
                raise GameStuckError('远征任务超时')
            frame = self.screenshot()
            image = frame.image
            page = self.get_current_page(frame)
            if not result.pages or result.pages[-1] != page:
                result.pages.append(page)
                log.info('page %s', page)
            if page != '出征-远征':
                settled = False

            if continue_dialog(image):
                if self.redeploy:
                    self.click(CONTINUE_CONFIRM, '继续远征')
                    result.redeployed += 1
                else:
                    self.click(CONTINUE_CANCEL, '不继续远征')
                action = ('dialog', self.redeploy)
            elif page == '港区':
                if not color.cmp_points(image, FINISHED_BADGE, 0.9):
                    log.info('no finished expedition; collected %d', result.collected)
                    return result
                if empty_visits >= 2:
                    raise GameStuckError('港区仍显示远征完成，但远征页当前章节没有可收取的远征（可能在其他章节）')
                self.click(assets.SORTIE, '有远征完成')
                action = ('港区', '出征')
            elif page in OTHER_TABS:
                self.click(assets.TAB_EXPEDITION, page)
                action = (page, '远征标签')
            elif page == '出征-远征':
                if not settled:
                    # Original waits 1 s for the list to settle before reading slots.
                    self.sleep(1.0)
                    settled = True
                    continue
                slot = collectable_slot(image)
                if slot is not None:
                    self.click(assets.Button('收取奖励', slot, SLOT_Y, '收远征', jitter=3), f'槽位{SLOTS.index(slot) + 1}')
                    pending = True
                    action = ('出征-远征', slot)
                else:
                    empty_visits += 1
                    self.click(assets.BACK, '没有可收取的远征')
                    action = ('出征-远征', '返回')
                settled = False
            elif page in RESULT_PAGES:
                if pending:
                    result.collected += 1
                    pending = False
                    empty_visits = 0
                self.click(assets.CONTINUE, page)
                action = (page, '继续')
            elif page is not None and self.handle_default(page):
                action = (page, 'default')
            else:
                action = None
                unknown += 1
                if unknown >= 10:
                    raise UnknownPageError('连续10帧无法识别页面，停止输入')
            if action is not None:
                unknown = 0
                result.inputs += 1
            repeats = repeats + 1 if action is not None and action == last_action else 0
            last_action = action
            if repeats >= 6:
                raise GameStuckError(f'{action} 重复{repeats + 1}次画面无变化')
            self.sleep(self.interval)
