"""Click targets taken from the original script (portrait 540x960 coordinates).

`source` records where each coordinate comes from, so a future game update
can be traced back. Coordinates marked "derived" were not clicked by the
original but follow its tab layout and were checked on a live screenshot.
"""
from dataclasses import dataclass
import random

from module.vision.color import to_screen


@dataclass(frozen=True)
class Button:
    name: str
    x: float
    y: float
    source: str
    jitter: int = 3  # original 随机点击 adds ShanHai.RndEx(-3, 3) on both axes

    def screen(self, rng=random):
        dx = rng.randint(-self.jitter, self.jitter) if self.jitter else 0
        dy = rng.randint(-self.jitter, self.jitter) if self.jitter else 0
        return to_screen(self.x + dx, self.y + dy)


# Main menu
SORTIE = Button('出征', 15, 900, '点击按钮("点击出征"); 打战役/打演习/出征战斗 on 港区', jitter=0)

# Shared top-left back button on every sub page
BACK = Button('返回', 510, 33, '点击按钮("点击返回") -> 固定延时点击(510,33)', jitter=0)

# 出征 tabs; selected-tab checks sit at x=502, y=125/250/375/500/625 (选项卡位置)
TAB_SORTIE = Button('出征标签', 510, 180, 'derived: tab label centre, verified on nav-sortie-after.png')
TAB_EXERCISE = Button('演习标签', 514, 306, '打演习 on 出征-出征/出征-远征')
TAB_EXPEDITION = Button('远征标签', 510, 427, '收远征 on 出征-出征/战役/演习')
TAB_CAMPAIGN = Button('战役标签', 513, 553, '打战役 on 出征-出征/出征-远征')
TAB_DECISIVE = Button('决战标签', 510, 680, 'derived: tab label centre, verified on nav-sortie-after.png')

# Result screens (战斗结果 also covers the expedition result screen)
CONTINUE = Button('点击继续', 270, 10, '现在画面 default handling of 战斗结果/远征完成')
