"""Port of AzurPilot NemuIpcImpl (GPLv3); original DLL/capture implementation.

Removed application retry decorators; caller handles capture fallback. Worker pool,
DLL selection, connection, frame and coordinate handling retain upstream code.
"""
import ctypes
import os
import re
import sys
import logging as logger
import numpy as np
from .pool import WORKER_POOL

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
        if b'error: 1783' in self.stderr or b'error: 1745' in self.stderr:
            raise NemuIpcIncompatible(f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version')
        if b'cannot find rpc connection' in self.stderr:
            raise NemuIpcError(self.stderr)
        if b'error: 1722' in self.stderr or b'error: 1726' in self.stderr:
            raise NemuIpcError('Emulator instance is probably dead')

class NemuIpcImpl:

    def __init__(self, nemu_folder: str, instance_id: int, display_id: int=0, version: str=None):
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
        list_dll = []
        if version:
            list_dll.append(os.path.abspath(os.path.join(nemu_folder, f'./nx_device/{version}/shell/sdk/external_renderer_ipc.dll')))
        try:
            others = []
            for name in os.listdir(os.path.join(nemu_folder, 'nx_device')):
                if re.match('\\d+\\.\\d+$', name) and name != version:
                    others.append(name)
            others.sort(key=lambda s: float(s), reverse=True)
            list_dll += [os.path.abspath(os.path.join(nemu_folder, f'./nx_device/{name}/shell/sdk/external_renderer_ipc.dll')) for name in others]
        except OSError:
            pass
        list_dll += [os.path.abspath(os.path.join(nemu_folder, './shell/sdk/external_renderer_ipc.dll')), os.path.abspath(os.path.join(nemu_folder, './nx_device/12.0/shell/sdk/external_renderer_ipc.dll')), os.path.abspath(os.path.join(nemu_folder, './nx_main/sdk/external_renderer_ipc.dll'))]
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
            raise NemuIpcIncompatible(f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version. None of the following path exists: {list_dll}')
        logger.info(f'[设备-NemuIpc] NemuIpcImpl init, nemu_folder={nemu_folder}, ipc_dll={ipc_dll}, instance_id={instance_id}, version={version}, display_id={display_id}')
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
            res = re.match(f'.*-(\\d+\\.\\d+)-{instance_id}$', name)
            if res:
                return res.group(1)
        return None

    def connect(self, on_thread=True):
        if self.connect_id > 0:
            return
        if on_thread:
            connect_id = self.run_func(self.lib.nemu_connect, self.nemu_folder, self.instance_id)
        else:
            connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
        if connect_id == 0:
            raise NemuIpcError('连接失败，请检查 nemu_folder 是否正确以及模拟器是否正在运行')
        self.connect_id = connect_id

    def connect_with_retry(self, on_thread=True):
        self.connect(on_thread=on_thread)

    def disconnect(self):
        if self.connect_id == 0:
            return
        self.run_func(self.lib.nemu_disconnect, self.connect_id)
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
        elif result > 0:
            err = True
        if err:
            raise NemuIpcError(f'{func.__name__} failed: {result}')
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
        ret = self.run_func(self.lib.nemu_capture_display, self.connect_id, self.display_id, 0, width_ptr, height_ptr, nullptr, on_thread=on_thread)
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
        ret = self.lib.nemu_capture_display(self.connect_id, self.display_id, length, width_ptr, height_ptr, pixels_pointer)
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during screenshot()')
        return pixels_pointer

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
        image = np.ctypeslib.as_array(pixels_pointer.contents).reshape((self.height, self.width, 4))
        return image

    def down(self, x, y):
        """
        触摸按下，连续的触摸按下会被视为滑动。
        """
        if self.connect_id == 0:
            self.connect()
        x, y = (int(x), int(y))
        ret = self.run_func(self.lib.nemu_input_event_touch_down, self.connect_id, self.display_id, x, y)
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_down failed')

    def up(self):
        """
        触摸抬起。
        """
        if self.connect_id == 0:
            self.connect()
        ret = self.run_func(self.lib.nemu_input_event_touch_up, self.connect_id, self.display_id)
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
