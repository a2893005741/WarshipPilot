"""Selectable screenshot and control methods, as in AzurPilot (GPL-3.0 port).

    device = Device(DeviceConfig(Emulator_Serial='127.0.0.1:16416',
                                 Emulator_ScreenshotMethod='nemu_ipc',
                                 Emulator_ControlMethod='MaaTouch'))
    image = device.screenshot()      # RGB, 1280x720, landscape
    device.click(640, 360)           # screen coordinates

Differences from AzurPilot Screenshot/Control on purpose:
* frames are never resized: the colour rules need exact pixels, so a
  non-1280x720 frame is an error instead of being scaled with blur;
* methods that do not exist for MuMu 12 / Android 10+ are left out
  (aScreenCap <= Android 9, ldopengl = LDPlayer, WSA, Hermit,
  AzurPilot's own APK).
"""
import time

import cv2
import numpy as np

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.device.base.timer import Timer
from module.base.utils import ensure_time
from module.device.compat import RequestHumanTakeover, ScriptError, logger
from module.device.connection import DeviceConfig
from module.device.method.adb import Adb
from module.device.method.droidcast import DroidCast
from module.device.method.maatouch import MaaTouch
from module.device.method.minitouch import Minitouch
from module.device.method.nemu_ipc import NemuIpc
from module.device.method.scrcpy import Scrcpy
from module.device.method.uiautomator_2 import Uiautomator2

SCREENSHOT_METHODS = ('nemu_ipc', 'ADB', 'ADB_nc', 'DroidCast', 'DroidCast_raw', 'uiautomator2', 'scrcpy')
CONTROL_METHODS = ('nemu_ipc', 'MaaTouch', 'minitouch', 'ADB', 'uiautomator2', 'scrcpy')
SCREEN_SIZE = (1280, 720)


class ScreenSizeError(RequestHumanTakeover):
    pass


class Device(NemuIpc, Adb, DroidCast, Scrcpy, Minitouch, MaaTouch, Uiautomator2):
    def __init__(self, config: DeviceConfig, connect=True):
        super().__init__(config, connect=connect)
        self.image = None
        self._screenshot_interval = Timer(0.1)

    # --- method tables (AzurPilot Screenshot.screenshot_methods / Control.click_methods) ---
    @cached_property
    def screenshot_methods(self):
        return {
            'nemu_ipc': self.screenshot_nemu_ipc,
            'ADB': self.screenshot_adb,
            'ADB_nc': self.screenshot_adb_nc,
            'DroidCast': self.screenshot_droidcast,
            'DroidCast_raw': self.screenshot_droidcast_raw,
            'uiautomator2': self.screenshot_uiautomator2,
            'scrcpy': self.screenshot_scrcpy,
        }

    @cached_property
    def click_methods(self):
        return {
            'nemu_ipc': self.click_nemu_ipc,
            'MaaTouch': self.click_maatouch,
            'minitouch': self.click_minitouch,
            'ADB': self.click_adb,
            'uiautomator2': self.click_uiautomator2,
            'scrcpy': self.click_scrcpy,
        }

    @cached_property
    def swipe_methods(self):
        return {
            'nemu_ipc': lambda p1, p2, duration: self.swipe_nemu_ipc(p1, p2),
            'MaaTouch': lambda p1, p2, duration: self.swipe_maatouch(p1, p2),
            'minitouch': lambda p1, p2, duration: self.swipe_minitouch(p1, p2),
            'ADB': lambda p1, p2, duration: self.swipe_adb(p1, p2, duration=duration),
            'uiautomator2': lambda p1, p2, duration: self.swipe_uiautomator2(p1, p2, duration=duration),
            'scrcpy': lambda p1, p2, duration: self.swipe_scrcpy(p1, p2),
        }

    # --- screenshot -----------------------------------------------------------------------
    def screenshot(self, method=None):
        """RGB landscape 1280x720 frame from the configured (or given) method."""
        method = method or self.config.Emulator_ScreenshotMethod
        if method not in self.screenshot_methods:
            raise ScriptError(f'未知截图方式：{method}')
        self._screenshot_interval.wait()
        self._screenshot_interval.reset()
        image = self.screenshot_methods[method]()
        height, width = image.shape[:2]
        if width < height:
            self.get_orientation()
            image = self._handle_orientated_image(image)
            height, width = image.shape[:2]
        if (width, height) != SCREEN_SIZE:
            raise ScreenSizeError(f'{method} 截图尺寸为 {width}×{height}，请把模拟器分辨率设为 1280×720')
        self.image = image
        return image

    def _handle_orientated_image(self, image):
        if self.orientation in (0, 2):
            return image
        if self.orientation == 1:
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self.orientation == 3:
            return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        raise ScriptError(f'Invalid device orientation: {self.orientation}')

    # --- control ----------------------------------------------------------------------------
    def click(self, x, y, method=None):
        method = method or self.config.Emulator_ControlMethod
        if method not in self.click_methods:
            raise ScriptError(f'未知控制方式：{method}')
        x, y = int(x), int(y)
        if not (0 <= x < SCREEN_SIZE[0] and 0 <= y < SCREEN_SIZE[1]):
            raise ScriptError(f'点击坐标越界：{x},{y}')
        self.click_methods[method](x, y)

    def swipe(self, p1, p2, duration=0.3, method=None):
        method = method or self.config.Emulator_ControlMethod
        self.swipe_methods[method](tuple(map(int, p1)), tuple(map(int, p2)), ensure_time(duration))

    # --- lifecycle --------------------------------------------------------------------------
    def release(self):
        """Close method sessions (servers on the device keep no inputs pending)."""
        for name in ('nemu_ipc',):
            if has_cached_property(self, name):
                try:
                    self.nemu_ipc.disconnect()
                except Exception as e:
                    logger.warning(f'[设备] 释放 nemu_ipc 失败: {e}')
                del_cached_property(self, name)
        if self._scrcpy_alive:
            try:
                self._scrcpy_server_stop()
            except Exception as e:
                logger.warning(f'[设备] 停止 scrcpy 失败: {e}')
        if has_cached_property(self, 'droidcast_session'):
            try:
                self.droidcast_stop()
            except Exception as e:
                logger.warning(f'[设备] 停止 DroidCast 失败: {e}')
        self.release_resource()
