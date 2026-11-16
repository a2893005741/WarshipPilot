# Adapted from AzurPilot module/base/button.py, Button.match (GPL-3.0).
# Changes: fixed preloaded PNG resources; native-resolution matching only.
import cv2
import numpy as np

def crop(image, area, copy=False):
    x1,y1,x2,y2=map(int,area)
    return image[max(0,y1):y2,max(0,x1):x2]

def area_offset(area, offset):
    x,y=offset
    return np.array(area)+np.array((x,y,x,y))

class TemplateButton:
    is_gif = False
    def __init__(self, image, area, button=None):
        self.image = image
        self.area = np.array(area)
        self._button = np.array(button or area)
        self._button_offset = None

    def match(self, image, offset=30, similarity=0.85):
            """通过模板匹配检测按钮。部分按钮的位置可能不固定。

            Args:
                image: 截图。
                offset (int, tuple): 检测区域偏移量。
                similarity (float): 相似度阈值，范围 0-1。

            Returns:
                bool: 匹配成功返回 True。
            """
            similarity = float(similarity)
            pass  # Templates are loaded by the WarshipR resource catalog.

            if isinstance(offset, tuple):
                if len(offset) == 2:
                    offset = np.array((-offset[0], -offset[1], offset[0], offset[1]))
                else:
                    offset = np.array(offset)
            else:
                offset = np.array((-3, -offset, 3, offset))
            image = crop(image, offset + self.area, copy=False)

            if self.is_gif:
                for template in self.image:
                    res = cv2.matchTemplate(template, image, cv2.TM_CCOEFF_NORMED)
                    _, sim, _, point = cv2.minMaxLoc(res)
                    self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                    if sim > similarity:
                        return True
                return False
            else:
                res = cv2.matchTemplate(self.image, image, cv2.TM_CCOEFF_NORMED)
                _, sim, _, point = cv2.minMaxLoc(res)
                self._button_offset = area_offset(self._button, offset[:2] + np.array(point))
                return sim > similarity
