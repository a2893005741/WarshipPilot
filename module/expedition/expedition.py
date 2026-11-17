"""Native expedition task: collect finished expeditions and redeploy.

Behaviour follows the original 收远征 (see dev_tools/legacy_extract/policies.json):

    港区, finished badge on 出征     -> tap 出征
    港区, no badge                   -> done
    出征-出征 / 战役 / 演习 / 决战   -> tap 远征 tab
    出征-远征                        -> wait 1 s, tap the first lit "收取奖励"
                                        (slot rows x=387/280/172/66, y=812),
                                        none lit -> 返回
    战斗结果 (= expedition result)   -> tap to continue
    继续远征 dialog (newer game)     -> 确认 (redeploy) or 取消
    anything else                    -> original default handling

After everything is collected the task (new, not in the original) walks every
chapter of 出征-远征 once and reads the countdown of each fleet still away, so
the scheduler can come back exactly when the next expedition finishes. A
finished expedition met on any chapter during that walk is collected too.

Every step is decided from a fresh screenshot; nothing is replayed blindly.
"""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from module.base.timer import Timer
from module.expedition import timer as countdown
from module.ui import assets
from module.ui.navigation import UI, GameStuckError, UnknownPageError
from module.vision import color

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

# Chapter list on 出征-远征: the selected chapter sits at screen y≈395; tapping
# the entry above (y 315) / below (y 484) moves exactly one chapter, and a tap
# past the first/last chapter changes nothing (measured on the live game).
CHAPTER_PREV = assets.Button('上一章', 303, 90, 'live 远征章节列表 (120,315)', jitter=0)
CHAPTER_NEXT = assets.Button('下一章', 176, 90, 'live 远征章节列表 (120,484)', jitter=0)
MAX_CHAPTERS = 30
CHAPTER_REACT = 3.0  # seconds to wait for the list to react to a chapter tap
CHAPTER_POLL = 0.25
CHAPTER_STILL = 3    # polls without change before the list counts as settled


def chapter_signature(image):
    """Downscaled chapter column; changes whenever another chapter is selected."""
    gray = cv2.cvtColor(image[100:650, 0:300], cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, (30, 55), interpolation=cv2.INTER_AREA).astype(np.int16)


def same_chapter(a, b):
    return float(np.abs(a - b).mean()) < 3


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
    remaining: list = None   # seconds left per fleet away; None = not surveyed
    unreadable: int = 0      # running countdowns that could not be read
    chapters: list = field(default_factory=list)  # per chapter walked: (seconds, unreadable)


class Expedition(UI):
    def __init__(self, device, redeploy=True, timeout=600, survey=True, survey_dir=None, **kwargs):
        super().__init__(device, **kwargs)
        self.redeploy = redeploy
        self.timeout = timeout
        self.survey = survey
        self.survey_dir = survey_dir

    def step_chapter(self, button, image):
        """Tap a neighbouring chapter; (new image, whether the chapter changed).

        The list reacts with a delay (live: well over 0.5 s), so first wait
        for the chapter column to differ from before the tap, then for it to
        stop moving. No change within CHAPTER_REACT means first/last chapter.
        """
        before = chapter_signature(image)
        # A tap that lands while the list is still easing out can be lost:
        # only a second unanswered tap means first/last chapter.
        for _ in range(2):
            self.click(button, '远征章节')
            self.result.inputs += 1
            for _ in range(int(CHAPTER_REACT / CHAPTER_POLL)):
                self.sleep(CHAPTER_POLL)
                image = self.screenshot().image
                signature = chapter_signature(image)
                if not same_chapter(signature, before):
                    return self.settle_chapters(image, signature), True
        return image, False

    def settle_chapters(self, image, signature):
        """Wait until the chapter column stays still for CHAPTER_STILL polls."""
        still = 0
        for _ in range(20):
            self.sleep(CHAPTER_POLL)
            image = self.screenshot().image
            current = chapter_signature(image)
            still = still + 1 if same_chapter(current, signature) else 0
            if still >= CHAPTER_STILL:
                break
            signature = current
        return image

    def keep_survey_frame(self, index, image):
        """log/expedition-survey/NN.jpg: what each chapter looked like when read."""
        if self.survey_dir is None:
            return
        try:
            if index == 1:
                self.survey_dir.mkdir(parents=True, exist_ok=True)
                for old in self.survey_dir.glob('*.jpg'):
                    old.unlink()
            ok, data = cv2.imencode('.jpg', cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                data.tofile(str(self.survey_dir / f'{index:02d}.jpg'))
        except OSError as exc:
            log.warning('survey frame not saved: %s', exc)

    def survey_chapters(self, image):
        """Read every chapter's countdowns, first to last.

        Returns (seconds, unreadable), or None when a finished expedition or
        another page turned up; the main loop then handles the screen first.
        """
        for _ in range(MAX_CHAPTERS):
            image, moved = self.step_chapter(CHAPTER_PREV, image)
            if self.get_current_page(self.frame) != '出征-远征':
                return None
            if not moved:
                break
        else:
            raise GameStuckError('远征章节列表无法回到第一章')
        seconds, unreadable = [], 0
        self.result.chapters = []
        for _ in range(MAX_CHAPTERS):
            if collectable_slot(image) is not None:
                return None
            found, missed = countdown.running(image)
            self.result.chapters.append((found, missed))
            self.keep_survey_frame(len(self.result.chapters), image)
            seconds += found
            unreadable += missed
            image, moved = self.step_chapter(CHAPTER_NEXT, image)
            if self.get_current_page(self.frame) != '出征-远征':
                return None
            if not moved:
                return sorted(seconds), unreadable
        raise GameStuckError('远征章节数量超出预期，停止翻页')

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
                finished = color.cmp_points(image, FINISHED_BADGE, 0.9)
                if not finished and (not self.survey or result.remaining is not None):
                    log.info('no finished expedition; collected %d, remaining %s', result.collected, result.remaining)
                    return result
                if finished and empty_visits >= 2:
                    raise GameStuckError('港区仍显示远征完成，但各章节都没有可收取的远征')
                self.click(assets.SORTIE, '有远征完成' if finished else '查看远征倒计时')
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
                elif self.survey and result.remaining is None:
                    surveyed = self.survey_chapters(image)
                    if surveyed is None:
                        action = ('出征-远征', '章节中断')
                    else:
                        result.remaining, result.unreadable = surveyed
                        log.info('expedition countdowns %s, unreadable %d', *surveyed)
                        action = ('出征-远征', '章节读取')
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
