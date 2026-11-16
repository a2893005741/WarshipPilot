"""
MuMu 模拟器 IPC 通信方法。

通过进程间通信 (IPC) 直接与 MuMu 模拟器交互，实现高性能截图和触控操作。
使用 ctypes 加载 MuMu 的 nemu_ipc DLL，绕过 ADB 层直接调用模拟器内部接口，
截图延迟极低且无需网络传输。支持截图、点击、滑动和按键操作。
仅限 Windows 平台使用，需要 MuMu 模拟器支持 IPC 接口。
"""
import ctypes
import json
import os
import re
import sys
from functools import partial

import cv2
import numpy as np

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.device.base.timer import Timer
from module.base.utils import ensure_time
from module.device.compat import deep_get
from module.device.env import IS_WINDOWS
from module.device.method.retry import retry_backend, recover_unknown, retry_without_recovery
from module.device.method.minitouch import insert_swipe, random_rectangle_point
from module.device.method.pool import JobTimeout, WORKER_POOL
from module.device.method.utils import retry_sleep
from module.device.connection import Connection
from module.device.compat import EmulatorNotRunningError, RequestHumanTakeover
from module.device.compat import logger


class NemuIpcIncompatible(Exception):
    pass


class NemuIpcError(Exception):
    pass


class CaptureStd:
    """
    捕获 Python 和 C 库的 stdout 和 stderr。
    参考: https://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python/17954769

    ```
    with CaptureStd() as capture:
        # 不会实际打印
        print('whatever')
    # 但会捕获到 capture.stdout 中
    print(f'Got stdout: "{capture.stdout}"')
    print(f'Got stderr: "{capture.stderr}"')
    ```
    """

    def __init__(self):
        self.stdout = b''
        self.stderr = b''

    def _redirect_stdout(self, to):
        sys.stdout.close()
        os.dup2(to, self.fdout)
        sys.stdout = os.fdopen(self.fdout, 'w')

    def _redirect_stderr(self, to):
        sys.stderr.close()
        os.dup2(to, self.fderr)
        sys.stderr = os.fdopen(self.fderr, 'w')

    def __enter__(self):
        self.fdout = sys.stdout.fileno()
        self.fderr = sys.stderr.fileno()
        self.reader_out, self.writer_out = os.pipe()
        self.reader_err, self.writer_err = os.pipe()
        self.old_stdout = os.dup(self.fdout)
        self.old_stderr = os.dup(self.fderr)

        file_out = os.fdopen(self.writer_out, 'w')
        file_err = os.fdopen(self.writer_err, 'w')
        self._redirect_stdout(to=file_out.fileno())
        self._redirect_stderr(to=file_err.fileno())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._redirect_stdout(to=self.old_stdout)
        self._redirect_stderr(to=self.old_stderr)
        os.close(self.old_stdout)
        os.close(self.old_stderr)

        self.stdout = self.recvall(self.reader_out)
        self.stderr = self.recvall(self.reader_err)
        os.close(self.reader_out)
        os.close(self.reader_err)

    @staticmethod
    def recvall(reader, length=1024) -> bytes:
        fragments = []
        while 1:
            chunk = os.read(reader, length)
            if chunk:
                fragments.append(chunk)
            else:
                break
        output = b''.join(fragments)
        return output


class CaptureNemuIpc(CaptureStd):
    instance = None

    def is_capturing(self):
        """
        仅在最顶层包装器中捕获，避免嵌套捕获。
        如果已有捕获正在进行，当前实例不做任何操作。
        """
        cls = self.__class__
        return isinstance(cls.instance, cls) and cls.instance != self

    def __enter__(self):
        if self.is_capturing():
            return self

        super().__enter__()
        CaptureNemuIpc.instance = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_capturing():
            return

        CaptureNemuIpc.instance = None
        super().__exit__(exc_type, exc_val, exc_tb)

        self.check_stdout()
        self.check_stderr()

    def check_stdout(self):
        if not self.stdout:
            return
        logger.info(f'[设备-NemuIpc] NemuIpc标准输出: {self.stdout}')

    def check_stderr(self):
        if not self.stderr:
            return
        logger.error(f'[设备-NemuIpc] NemuIpc标准错误: {self.stderr}')

        # 调用了旧版本的 MuMu12
        # 在 3.4.0 上测试
        # b'nemu_capture_display rpc error: 1783\r\n'
        # 在 3.7.3 上测试
        # b'nemu_capture_display rpc error: 1745\r\n'
        if b'error: 1783' in self.stderr or b'error: 1745' in self.stderr:
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version')
        # contact_id 不正确
        # b'nemu_capture_display cannot find rpc connection\r\n'
        if b'cannot find rpc connection' in self.stderr:
            raise NemuIpcError(self.stderr)
        # 模拟器已停止运行
        # b'nemu_capture_display rpc error: 1722\r\n'
        # MuMuVMMSVC.exe 已停止运行
        # b'nemu_capture_display rpc error: 1726\r\n'
        # 暂无已知处理方式
        if b'error: 1722' in self.stderr or b'error: 1726' in self.stderr:
            raise NemuIpcError('Emulator instance is probably dead')


def _retry_recover(self, error, trial):
    if isinstance(error, NemuIpcIncompatible):
        logger.error(error)
        return None
    if isinstance(error, JobTimeout):
        logger.warning(f'[设备-NemuIpc] 调用超时，重试: {trial}')
        return retry_without_recovery
    if isinstance(error, NemuIpcError):
        logger.error(error)
        return self.reconnect
    return recover_unknown(error)


def _screenshot_retry_timeout(trial, args, kwargs):
    # 保留截图重试时 0.5 → 0.5 → 1 → 3 → 3 秒的超时阶梯。
    timeout = retry_sleep(trial)
    if timeout > 0:
        kwargs['timeout'] = timeout


retry = partial(retry_backend, recover=_retry_recover, label='设备-NemuIpc')


class NemuIpcImpl:
    def __init__(self, nemu_folder: str, instance_id: int, display_id: int = 0, version: str = None):
        """
        Args:
            nemu_folder: MuMu12 安装路径，例如 E:/ProgramFiles/MuMuPlayer-12.0
            instance_id: 模拟器实例 ID，从 0 开始
            display_id: 如果未启用后台挂机保活，始终为 0
            version: 模拟器实例版本，如 '15.0'，来自实例名（MuMuPlayer-15.0-0）。
                未提供时从 vms 目录名自动推断，用于选择匹配版本的 IPC SDK。
                版本不匹配时（如用 12.0 的 DLL 连 15.0 实例）调用会失效。
        """
        self.nemu_folder: str = nemu_folder
        self.instance_id: int = instance_id
        self.display_id: int = display_id

        if version is None:
            version = self.detect_version(nemu_folder, instance_id)
        self.version: str = version

        # 尝试从多个路径加载 DLL，实例版本的 SDK 优先
        list_dll = []
        if version:
            # MuMu15 及后续版本：nx_device/<版本>/shell/sdk
            list_dll.append(os.path.abspath(os.path.join(
                nemu_folder, f'./nx_device/{version}/shell/sdk/external_renderer_ipc.dll')))
        # 兜底：探测 nx_device 下其余版本的 SDK（按版本号降序，优先新版本），
        # 覆盖单装 15.0 等未在下方硬编码的版本
        try:
            others = []
            for name in os.listdir(os.path.join(nemu_folder, 'nx_device')):
                if re.match(r'\d+\.\d+$', name) and name != version:
                    others.append(name)
            others.sort(key=lambda s: float(s), reverse=True)
            list_dll += [
                os.path.abspath(os.path.join(nemu_folder, f'./nx_device/{name}/shell/sdk/external_renderer_ipc.dll'))
                for name in others
            ]
        except OSError:
            pass
        list_dll += [
            # MuMuPlayer12
            os.path.abspath(os.path.join(nemu_folder, './shell/sdk/external_renderer_ipc.dll')),
            # MuMuPlayer12 5.0（未被上方探测覆盖时的兜底）
            os.path.abspath(os.path.join(nemu_folder, './nx_device/12.0/shell/sdk/external_renderer_ipc.dll')),
            # MuMuPlayer12 6.0
            os.path.abspath(os.path.join(nemu_folder, './nx_main/sdk/external_renderer_ipc.dll')),
        ]

        self.lib = None
        for ipc_dll in list_dll:
            if not os.path.exists(ipc_dll):
                continue
            try:
                self.lib = ctypes.CDLL(ipc_dll)
                break
            except OSError as e:
                logger.error(e)
                logger.error(f'ipc_dll={ipc_dll} 存在，但无法加载')
                continue
        if self.lib is None:
            # 未找到
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version. '
                f'None of the following path exists: {list_dll}')
        # 成功
        logger.info(
            f'[设备-NemuIpc] NemuIpcImpl init, '
            f'nemu_folder={nemu_folder}, '
            f'ipc_dll={ipc_dll}, '
            f'instance_id={instance_id}, '
            f'version={version}, '
            f'display_id={display_id}'
        )
        self.ipc_dll: str = ipc_dll
        self.connect_id: int = 0
        self.width = 0
        self.height = 0

    @staticmethod
    def detect_version(nemu_folder: str, instance_id: int):
        """
        从 vms 目录名推断实例版本。

        目录命名如 MuMuPlayer-15.0-0 / MuMuPlayer-12.0-1 / YXArkNights-12.0-1，
        尾部数字为实例 ID，与 instance_id 对应。

        Returns:
            str: 版本号如 '15.0'，推断失败返回 None
        """
        try:
            names = os.listdir(os.path.join(nemu_folder, 'vms'))
        except OSError:
            return None
        for name in names:
            res = re.match(rf'.*-(\d+\.\d+)-{instance_id}$', name)
            if res:
                return res.group(1)
        return None

    def connect(self, on_thread=True):
        if self.connect_id > 0:
            return

        if on_thread:
            connect_id = self.run_func(
                self.lib.nemu_connect,
                self.nemu_folder, self.instance_id
            )
        else:
            connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
        if connect_id == 0:
            raise NemuIpcError(
                '连接失败，请检查 nemu_folder 是否正确以及模拟器是否正在运行'
            )

        self.connect_id = connect_id
        # logger.info(f'NemuIpc connected: {self.connect_id}')

    @retry(on_exhausted=EmulatorNotRunningError)
    def connect_with_retry(self, on_thread=True):
        self.connect(on_thread=on_thread)

    def disconnect(self):
        if self.connect_id == 0:
            return

        self.run_func(
            self.lib.nemu_disconnect,
            self.connect_id
        )

        # logger.info(f'NemuIpc disconnected: {self.connect_id}')
        self.connect_id = 0

    def reconnect(self):
        self.disconnect()
        self.connect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @staticmethod
    def run_func(func, *args, on_thread=True, timeout=0.5):
        """
        Args:
            func: 要调用的同步函数
            *args:
            on_thread: 为 True 时在独立线程上运行 func
            timeout:

        Raises:
            JobTimeout: 函数调用超时时抛出
            NemuIpcIncompatible:
            NemuIpcError
        """
        if on_thread:
            # nemu_ipc 有时会超时，因此在独立线程上运行
            job = WORKER_POOL.start_thread_soon(func, *args)
            result = job.get_or_kill(timeout)
        else:
            result = func(*args)

        err = False
        if func.__name__ == '_screenshot':
            pass
        elif func.__name__ == 'nemu_connect':
            if result == 0:
                err = True
        else:
            if result > 0:
                err = True
        # 获取标准输出中实际的错误信息
        if err:
            logger.warning(f'调用失败 {func.__name__}, result={result}')
            with CaptureNemuIpc():
                func(*args)

        return result

    def get_resolution(self, on_thread=True):
        """
        获取模拟器分辨率，会设置 `self.width` 和 `self.height`。
        """
        if self.connect_id == 0:
            self.connect()

        width_ptr = ctypes.pointer(ctypes.c_int(0))
        height_ptr = ctypes.pointer(ctypes.c_int(0))
        nullptr = ctypes.POINTER(ctypes.c_int)()

        ret = self.run_func(
            self.lib.nemu_capture_display,
            self.connect_id, self.display_id, 0, width_ptr, height_ptr, nullptr,
            on_thread=on_thread
        )
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during get_resolution()')
        self.width = width_ptr.contents.value
        self.height = height_ptr.contents.value

    def _screenshot(self):
        if self.connect_id == 0:
            self.connect(on_thread=False)
        self.get_resolution(on_thread=False)

        width_ptr = ctypes.pointer(ctypes.c_int(self.width))
        height_ptr = ctypes.pointer(ctypes.c_int(self.height))
        length = self.width * self.height * 4
        pixels_pointer = ctypes.pointer((ctypes.c_ubyte * length)())

        ret = self.lib.nemu_capture_display(
            self.connect_id, self.display_id, length, width_ptr, height_ptr, pixels_pointer,
        )
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during screenshot()')

        # 返回 pixels_pointer 而非 image，避免通过 job 传递图像对象
        return pixels_pointer

    @retry(on_exhausted=EmulatorNotRunningError, before_attempt=_screenshot_retry_timeout)
    def screenshot(self, timeout=0.5):
        """
        Args:
            timeout: 调用 nemu_ipc 的超时时间（秒）。
                会被 `@retry` 动态延长。

        Returns:
            np.ndarray: RGBA 色彩空间的图像数组。
                注意图像是上下颠倒的。
        """
        if self.connect_id == 0:
            self.connect()

        pixels_pointer = self.run_func(self._screenshot, timeout=timeout)

        # image = np.ctypeslib.as_array(pixels_pointer, shape=(self.height, self.width, 4))
        image = np.ctypeslib.as_array(pixels_pointer.contents).reshape((self.height, self.width, 4))
        return image

    @retry(on_exhausted=EmulatorNotRunningError,
           passthrough=(ctypes.ArgumentError, TypeError, ValueError, OverflowError))
    def down(self, x, y):
        """
        触摸按下，连续的触摸按下会被视为滑动。
        """
        if self.connect_id == 0:
            self.connect()

        # click/drag/swipe 的坐标来自 numpy（np.int64），而 nemu 的函数没有声明
        # argtypes，ctypes 无法转换 numpy 标量，会抛
        # ArgumentError: Don't know how to convert parameter 3；被 retry 包装成
        # EmulatorNotRunningError 后 Alas 会误判为掉线并重启模拟器。
        # 这里统一转成 Python int；None / nan / inf 之类的无效坐标会抛
        # TypeError / ValueError / OverflowError，由 retry 包装按「调用方参数错误」
        # 直接抛出，同样不会触发模拟器重启。
        x, y = int(x), int(y)

        ret = self.run_func(
            self.lib.nemu_input_event_touch_down,
            self.connect_id, self.display_id, x, y
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_down failed')

    @retry(on_exhausted=EmulatorNotRunningError,
           passthrough=(ctypes.ArgumentError, TypeError, ValueError, OverflowError))
    def up(self):
        """
        触摸抬起。
        """
        if self.connect_id == 0:
            self.connect()

        ret = self.run_func(
            self.lib.nemu_input_event_touch_up,
            self.connect_id, self.display_id
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_up failed')

    @staticmethod
    def serial_to_id(serial: str):
        """
        从 serial 推断实例 ID。
        例如:
            "127.0.0.1:16384" -> 0
            "127.0.0.1:16416" -> 1
            端口 16414 到 16418 -> 1

        Returns:
            int: instance_id，推断失败时返回 None
        """
        try:
            port = int(serial.split(':')[1])
        except (IndexError, ValueError):
            return None
        index, offset = divmod(port - 16384 + 16, 32)
        offset -= 16
        if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
            return index
        else:
            return None


def find_mumu_folders(configured=''):
    """MuMu install roots (folder containing shell/ or nx_main/), best first.

    WarshipPilot replacement for AzurPilot Platform.emulator_instance: an
    explicit setting, the WARSHIPPILOT_MUMU variable, common locations, then
    uninstall entries in the registry.
    """
    seen, result = set(), []

    def add(path):
        if not path:
            return
        path = os.path.abspath(path)
        if os.path.isfile(path):
            path = os.path.dirname(path)
        # Walk up to the install root: the folder that contains shell/ or nx_main/.
        probe = path
        while probe and not any(os.path.isdir(os.path.join(probe, sub)) for sub in ('shell', 'nx_main')):
            parent = os.path.dirname(probe)
            probe = '' if parent == probe else parent
        path = probe
        if path and path.lower() not in seen and os.path.isdir(path):
            seen.add(path.lower())
            result.append(path)

    add(configured)
    add(os.getenv('WARSHIPPILOT_MUMU', ''))
    for path in (r'D:\MuMu\MuMuPlayer', r'C:\Program Files\Netease\MuMuPlayer',
                 r'C:\Program Files\Netease\MuMuPlayer-12.0', r'D:\Program Files\Netease\MuMuPlayer-12.0'):
        add(path)
    if IS_WINDOWS:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for base in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                         r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    key = winreg.OpenKey(root, base)
                except OSError:
                    continue
                for i in range(winreg.QueryInfoKey(key)[0]):
                    name = winreg.EnumKey(key, i)
                    if 'mumu' not in name.lower():
                        continue
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            for value in ('InstallLocation', 'DisplayIcon', 'UninstallString'):
                                try:
                                    raw = str(winreg.QueryValueEx(sub, value)[0])
                                except OSError:
                                    continue
                                add(raw.strip('"').split(',')[0].strip('"'))
                    except OSError:
                        pass
    return result


class NemuIpc(Connection):
    _screenshot_interval = Timer(0.1)

    @cached_property
    def nemu_ipc(self) -> NemuIpcImpl:
        """Initialise the MuMu IPC implementation for this serial (AzurPilot NemuIpc.nemu_ipc)."""
        index = NemuIpcImpl.serial_to_id(self.serial)
        if index is None:
            raise RequestHumanTakeover(f'{self.serial} 不是 MuMu12 实例地址，不能使用 nemu_ipc')
        errors = []
        for folder in find_mumu_folders(self.config.EmulatorInfo_path):
            try:
                version = NemuIpcImpl.detect_version(folder, index)
                impl = NemuIpcImpl(nemu_folder=folder, instance_id=index, display_id=0, version=version)
                impl.connect_with_retry()
                logger.attr('MuMu目录', folder)
                self.nemu_folder = folder
                return impl
            except (NemuIpcIncompatible, NemuIpcError, JobTimeout) as e:
                errors.append(f'{folder}: {e}')
        logger.error('[设备-NemuIpc] 无法初始化NemuIpc: ' + '; '.join(errors))
        raise RequestHumanTakeover('无法初始化 nemu_ipc：' + ('; '.join(errors) or '没有找到 MuMu 安装目录'))

    def nemu_ipc_available(self) -> bool:
        if not IS_WINDOWS or not self.is_mumu_family:
            return False
        if self.nemud_player_version != '' and self.nemud_app_keep_alive == '':
            return False  # MuMu6 or MuMu12 < 3.5.6
        try:
            _ = self.nemu_ipc
        except RequestHumanTakeover:
            return False
        return True

    @staticmethod
    def check_mumu_app_keep_alive_400(file):
        """MuMu >= 4.0 keeps app_keep_alive in the VM config instead of getprop."""
        try:
            with open(file, mode='r', encoding='utf-8') as f:
                data = json.loads(f.read())
        except FileNotFoundError:
            logger.warning(f'[设备-NemuIpc] 检查 check_mumu_app_keep_alive 失败，文件 {file} 不存在')
            return False
        value = deep_get(data, keys='customer.app_keptlive', default=None)
        logger.attr('customer.app_keptlive', value)
        if str(value).lower() == 'true':
            logger.critical('[设备-NemuIpc] 请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover('请在MuMu模拟器设置内关闭「后台挂机时保活运行」')
        return True

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_over_version_400:
            return super().check_mumu_app_keep_alive()
        index = NemuIpcImpl.serial_to_id(self.serial)
        if index is None:
            return False
        for folder in find_mumu_folders(self.config.EmulatorInfo_path):
            version = NemuIpcImpl.detect_version(folder, index) or '12.0'
            for configs in ('configs', 'config'):
                file = os.path.join(folder, 'vms', f'MuMuPlayer-{version}-{index}', configs, 'customer_config.json')
                if os.path.exists(file) and self.check_mumu_app_keep_alive_400(file):
                    return True
        logger.warning('[设备-NemuIpc] 没有找到 MuMu 实例配置，跳过保活检查')
        return False

    def nemu_ipc_release(self):
        if has_cached_property(self, 'nemu_ipc'):
            self.nemu_ipc.disconnect()
        del_cached_property(self, 'nemu_ipc')
        logger.info('[设备-NemuIpc] nemu_ipc已释放')

    def screenshot_nemu_ipc(self):
        """
        通过 NemuIpc 截取模拟器屏幕画面。

        Returns:
            np.ndarray: RGB 色彩空间的图像数组。
        """
        image = self.nemu_ipc.screenshot()

        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
        cv2.flip(image, 0, dst=image)
        return image

    def click_nemu_ipc(self, x, y):
        """
        通过 NemuIpc 模拟点击指定坐标。

        Args:
            x: 点击横坐标。
            y: 点击纵坐标。
        """
        down = ensure_time((0.010, 0.020))
        self.nemu_ipc.down(x, y)
        self.sleep(down)
        self.nemu_ipc.up()
        self.sleep(0.050 - down)

    def long_click_nemu_ipc(self, x, y, duration=1.0):
        """
        通过 NemuIpc 模拟长按指定坐标。

        Args:
            x: 长按横坐标。
            y: 长按纵坐标。
            duration: 长按持续时间（秒）。
        """
        self.nemu_ipc.down(x, y)
        self.sleep(duration)
        self.nemu_ipc.up()
        self.sleep(0.050)

    def swipe_nemu_ipc(self, p1, p2):
        """
        通过 NemuIpc 模拟平滑滑动操作。

        Args:
            p1: 滑动起点坐标 (x, y)。
            p2: 滑动终点坐标 (x, y)。
        """
        points = insert_swipe(p0=p1, p3=p2)

        for point in points:
            self.nemu_ipc.down(*point)
            self.sleep(0.010)

        self.nemu_ipc.up()
        self.sleep(0.050)

    def drag_nemu_ipc(self, p1, p2, point_random=(-10, -10, 10, 10), hold_duration=0.0):
        """
        通过 NemuIpc 模拟拖拽操作。

        Args:
            p1: 拖拽起始坐标 (x, y)。
            p2: 拖拽释放坐标 (x, y)。
            point_random: 起止坐标的随机偏移范围。
            hold_duration: 到达终点后的按住停顿时间（秒）。
        """
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        points = insert_swipe(p0=p1, p3=p2, speed=20)

        for point in points:
            self.nemu_ipc.down(*point)
            self.sleep(0.010)

        self.nemu_ipc.down(*p2)
        self.sleep(0.140)
        self.nemu_ipc.down(*p2)
        self.sleep(0.140)

        hold_duration = ensure_time(hold_duration) - 0.28
        if hold_duration > 0:
            self.nemu_ipc.down(*p2)
            self.sleep(hold_duration)

        self.nemu_ipc.up()
        self.sleep(0.050)
