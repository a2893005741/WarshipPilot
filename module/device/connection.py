"""Slim port of AzurPilot module/device/connection.py + connection_attr.py (GPL-3.0).

Kept: serial normalisation, emulator family detection, adbutils client and
device, uiautomator2 device, the AzurPilot retry/reconnect policy, shell /
nc / push / forward / reverse helpers, orientation and MuMu properties - the
surface the ported screenshot and control methods rely on, with upstream
behaviour.

Dropped: Azur Lane package/server detection, BlueStacks Hyper-V registry
lookup, WSA, phone cloud, HTTP (u2-over-http) mode, adb auto-download. The
serial and game package are given explicitly by WarshipPilot.
"""
from dataclasses import dataclass
from functools import wraps
import ipaddress
import logging
import os
import re
import socket
import subprocess
import time

import adbutils
from adbutils import AdbClient, AdbDevice, AdbTimeout, ForwardItem, ReverseItem
from adbutils.errors import AdbError
import uiautomator2 as u2

from module.base.decorator import Config, cached_property, del_cached_property
from module.base.utils import ensure_time
from module.device.compat import EmulatorNotRunningError, RequestHumanTakeover, RETRY_TRIES, logger
from module.device.env import IS_LINUX
from module.device.method.remove_warning import remove_shell_warning
from module.device.method.utils import (PackageNotInstalled, get_serial_pair, handle_adb_error,
                                            handle_unknown_host_service, possible_reasons, random_port,
                                            recv_all, retry_sleep)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


@dataclass
class DeviceConfig:
    """The subset of AzurLaneConfig the device layer reads."""
    Emulator_Serial: str = '127.0.0.1:16384'
    Emulator_PackageName: str = 'com.huanmeng.zhanjian2'
    Emulator_ScreenshotMethod: str = 'nemu_ipc'
    Emulator_ControlMethod: str = 'nemu_ipc'
    Emulator_AdbRestart: bool = False
    EmulatorInfo_path: str = ''          # ...\MuMuPlayer-12.0\shell\MuMuPlayer.exe (or nx_main)
    AdbExecutable: str = ''
    DEVICE_OVER_HTTP: bool = False
    # module/config/config_manual.py
    FORWARD_PORT_RANGE: tuple = (20000, 21000)
    REVERSE_SERVER_PORT: int = 7903
    DROIDCAST_VERSION: str = 'DroidCast'
    DROIDCAST_FILEPATH_LOCAL: str = os.path.join(ROOT, 'bin/DroidCast/DroidCast_raw-release-1.1.apk')
    DROIDCAST_FILEPATH_REMOTE: str = '/data/local/tmp/DroidCast_raw.apk'
    MINITOUCH_FILEPATH_REMOTE: str = '/data/local/tmp/minitouch'
    SCRCPY_FILEPATH_LOCAL: str = os.path.join(ROOT, 'bin/scrcpy/scrcpy-server-v1.20.jar')
    SCRCPY_FILEPATH_REMOTE: str = '/data/local/tmp/scrcpy-server-v1.20.jar'
    MAATOUCH_FILEPATH_LOCAL: str = os.path.join(ROOT, 'bin/MaaTouch/maatouchsync')
    MAATOUCH_FILEPATH_REMOTE: str = '/data/local/tmp/maatouchsync'


def retry(func):
    """AzurPilot Connection retry: reconnect on transport faults, give up after RETRY_TRIES."""
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        init = None
        last_error = None
        for _ in range(RETRY_TRIES):
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            except (RequestHumanTakeover, EmulatorNotRunningError):
                raise
            except ConnectionResetError as e:
                last_error = e
                logger.error(e)

                def init():
                    self.adb_reconnect()
            except AdbError as e:
                last_error = e
                if handle_adb_error(e):
                    def init():
                        self.adb_reconnect()
                elif handle_unknown_host_service(e):
                    def init():
                        self.adb_start_server()
                        self.adb_reconnect()
                else:
                    raise RequestHumanTakeover(str(e)) from e
            except PackageNotInstalled as e:
                last_error = e
                logger.error(e)
                raise RequestHumanTakeover(str(e)) from e
            except Exception as e:
                last_error = e
                logger.exception(e)

                def init():
                    pass
        logger.critical(f'[设备-连接] 重试 {func.__name__}() 失败')
        raise EmulatorNotRunningError(f'{func.__name__}() 重试失败') from last_error

    return retry_wrapper


class AdbDeviceWithStatus(AdbDevice):
    def __init__(self, client: AdbClient, serial: str, status: str):
        self.status = status
        super().__init__(client, serial)


class Connection:
    _orientation_description = {0: '正常', 1: 'HOME 键在右侧', 2: 'HOME 键在顶部', 3: 'HOME 键在左侧'}
    orientation = 0

    def __init__(self, config: DeviceConfig, connect=True):
        self.config = config
        adbutils.adb_path = lambda: self.adb_binary
        self.serial = self.revise_serial(str(config.Emulator_Serial))
        self.package = config.Emulator_PackageName
        if connect:
            self.adb_connect(wait_device=False)
            logger.attr('ADB设备', self.adb)
            self.check_mumu_app_keep_alive()

    # --- ConnectionAttr ---------------------------------------------------------
    @staticmethod
    def revise_serial(serial: str):
        serial = serial.strip().replace(' ', '')
        serial = serial.replace('。', '.').replace('，', '.').replace(',', '.').replace('：', ':')
        serial = serial.replace('127.0.0.1.', '127.0.0.1:')
        if serial.isdigit() and 1000 < int(serial) < 65536:
            serial = f'127.0.0.1:{serial}'
        return serial

    @cached_property
    def port(self) -> int:
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is None:
            port_serial = self.serial
        try:
            return int(port_serial.split(':')[1])
        except (IndexError, ValueError):
            return 0

    @cached_property
    def is_mumu12_family(self):
        return 16384 <= self.port <= 17408

    @cached_property
    def is_mumu_family(self):
        return self.serial == '127.0.0.1:7555' or self.is_mumu12_family

    @cached_property
    def is_ldplayer_bluestacks_family(self):
        return self.serial.startswith('emulator-') or 5555 <= self.port <= 5619

    @cached_property
    def is_nox_family(self):
        return 62001 <= self.port <= 63025

    @cached_property
    def is_emulator(self):
        return self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:')

    @cached_property
    def is_network_device(self):
        return bool(re.match(r'\d+\.\d+\.\d+\.\d+:\d+', self.serial))

    is_over_http = False
    is_bluestacks_hyperv = False
    is_bluestacks_air = False
    is_mumu_pro = False
    is_wsa = False
    is_avd = False

    @cached_property
    def adb_binary(self):
        candidates = [self.config.AdbExecutable, os.path.join(ROOT, 'adb', 'adb.exe'),
                      os.getenv('WARSHIPPILOT_ADB', ''), r'D:\MuMu\MuMuPlayer\nx_main\adb.exe', r'C:\adb\adb.exe']
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)
        import shutil
        return shutil.which('adb') or 'adb'

    @cached_property
    def adb_client(self) -> AdbClient:
        port = int(os.environ.get('ANDROID_ADB_SERVER_PORT', 5037))
        return AdbClient('127.0.0.1', port)

    @cached_property
    def adb(self) -> AdbDevice:
        return AdbDevice(self.adb_client, self.serial)

    @cached_property
    def u2(self) -> u2.Device:
        if self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:'):
            device = u2.connect_usb(self.serial)
        else:
            device = u2.connect(self.serial)
        try:
            device.set_new_command_timeout(604800)
        except Exception as e:
            logger.warning(f'[设备-u2] 设置命令超时失败，忽略（keepalive 非必需）: {e}')
        return device

    # --- commands -------------------------------------------------------------------
    def adb_command(self, cmd, timeout=10):
        cmd = [self.adb_binary, '-s', self.serial] + list(map(str, cmd))
        return self.subprocess_run(cmd, timeout=timeout)

    @staticmethod
    def subprocess_run(cmd, timeout=10):
        logger.info(f'[设备-连接] 执行: {cmd}')
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            logger.warning(f'[设备-连接] 命令超时: {cmd}')
        return stdout

    def adb_start_server(self):
        logger.info(self.subprocess_run([self.adb_binary, 'devices']))

    def adb_shell(self, cmd, stream=False, recvall=True, timeout=10, rstrip=True):
        if not isinstance(cmd, str):
            cmd = list(map(str, cmd))
        if stream:
            result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
            if recvall:
                try:
                    return recv_all(result)
                finally:
                    try:
                        if hasattr(result, 'close'):
                            result.close()
                        elif hasattr(result, 'conn') and hasattr(result.conn, 'close'):
                            result.conn.close()
                    except Exception:
                        pass
            return result
        result = self.adb.shell(cmd, stream=stream, timeout=timeout, rstrip=rstrip)
        return remove_shell_warning(result)

    def adb_getprop(self, name):
        return self.adb_shell(['getprop', name]).strip()

    @cached_property
    @retry
    def cpu_abi(self) -> str:
        abi = self.adb_getprop('ro.product.cpu.abi')
        if not len(abi):
            logger.error(f'[设备-连接] CPU ABI无效: "{abi}"')
        return abi

    @cached_property
    @retry
    def sdk_ver(self) -> int:
        sdk = self.adb_getprop('ro.build.version.sdk')
        try:
            return int(sdk)
        except ValueError:
            logger.error(f'[设备-连接] SDK版本无效: {sdk}')
        return 0

    @cached_property
    @retry
    def nemud_app_keep_alive(self) -> str:
        return self.adb_getprop('nemud.app_keep_alive')

    @cached_property
    @retry
    def nemud_player_version(self) -> str:
        return self.adb_getprop('nemud.player_version')

    @cached_property
    @retry
    def nemud_player_engine(self) -> str:
        return self.adb_getprop('nemud.emulator_engine')

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_family:
            return False
        res = self.nemud_app_keep_alive
        if res in ('', 'false'):
            return True
        if res == 'true':
            logger.critical('[设备-连接] 请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover('请在MuMu模拟器设置内关闭「后台挂机时保活运行」')
        logger.warning(f'[设备-连接] 无效的MuMu保持活跃值: {res}')
        return False

    @cached_property
    def is_mumu_over_version_400(self) -> bool:
        return self.is_mumu_family and self.nemud_player_version == ''

    @cached_property
    def is_mumu_over_version_356(self) -> bool:
        if not self.is_mumu_family:
            return False
        return self.is_mumu_over_version_400 or self.nemud_app_keep_alive != ''

    # --- netcat reverse server (ADB_nc) ------------------------------------------
    @cached_property
    def _nc_server_host_port(self):
        if self.is_emulator:
            try:
                host = socket.gethostbyname(socket.gethostname())
            except socket.gaierror as e:
                logger.error(e)
                host = '127.0.0.1'
            if IS_LINUX and host == '127.0.1.1':
                host = '127.0.0.1'
            port = random_port(self.config.FORWARD_PORT_RANGE)
            return host, port, host, port
        if self.is_network_device:
            hosts = socket.gethostbyname_ex(socket.gethostname())[2]
            ip = ipaddress.ip_address(self.serial.split(':')[0])
            for host in hosts:
                if ip in ipaddress.ip_interface(f'{host}/24').network:
                    port = random_port(self.config.FORWARD_PORT_RANGE)
                    return host, port, host, port
        host = '127.0.0.1'
        port = self.adb_reverse(f'tcp:{self.config.REVERSE_SERVER_PORT}')
        return host, port, host, self.config.REVERSE_SERVER_PORT

    @cached_property
    def reverse_server(self):
        del_cached_property(self, '_nc_server_host_port')
        host_port = self._nc_server_host_port
        logger.info(f'[设备-连接] 反向服务器监听 {host_port[0]}:{host_port[1]}, '
                    f'客户端可发送数据到 {host_port[2]}:{host_port[3]}')
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(host_port[:2])
        server.settimeout(5)
        server.listen(5)
        return server

    @cached_property
    def nc_command(self):
        trial = [['busybox', 'nc'], ['nc']] if self.is_emulator and self.sdk_ver >= 28 else [['nc'], ['busybox', 'nc']]
        for command in trial:
            result = self.adb_shell(command)
            if 'not found' in result or 'inaccessible' in result:
                continue
            logger.attr('nc命令', command)
            return command
        logger.error('[设备-连接] 没有可用的 `netcat` 命令，请使用不带 `_nc` 后缀的截图方法')
        raise RequestHumanTakeover('设备没有可用的 netcat 命令')

    def adb_shell_nc(self, cmd, timeout=5, chunk_size=262144):
        server = self.reverse_server
        server.settimeout(timeout)
        cmd += ['|', *self.nc_command, *self._nc_server_host_port[2:]]
        stream = self.adb_shell(cmd, stream=True, recvall=False)

        def _safe_close(s):
            try:
                if hasattr(s, 'close'):
                    s.close()
                elif hasattr(s, 'conn') and hasattr(s.conn, 'close'):
                    s.conn.close()
            except Exception:
                pass

        try:
            conn, _ = server.accept()
        except socket.timeout:
            try:
                logger.warning(f'[设备-连接] {recv_all(stream, chunk_size=chunk_size)}')
            finally:
                _safe_close(stream)
            raise AdbTimeout('reverse server accept timeout')
        try:
            return recv_all(conn, chunk_size=chunk_size, recv_interval=0.001)
        finally:
            try:
                conn.close()
            except Exception:
                pass
            _safe_close(stream)

    # --- forward / reverse / push --------------------------------------------------
    def adb_forward(self, remote):
        port = 0
        for forward in self.adb.forward_list():
            if forward.serial == self.serial and forward.remote == remote and forward.local.startswith('tcp:'):
                if not port:
                    port = int(forward.local[4:])
                else:
                    self.adb_forward_remove(forward.local)
        if port:
            return port
        port = random_port(self.config.FORWARD_PORT_RANGE)
        forward = ForwardItem(self.serial, f'tcp:{port}', remote)
        logger.info(f'[设备-连接] 创建端口转发: {forward}')
        self.adb.forward(forward.local, forward.remote)
        return port

    def _adb_reverse_transport(self, remote: str, local: str, norebind: bool = False):
        args = ['reverse:forward'] + (['norebind'] if norebind else []) + [remote + ';' + local]
        with self.adb_client._connect() as c:
            c.send_command(f'host:transport:{self.serial}')
            c.check_okay()
            c.send_command(':'.join(args))
            c.check_okay()

    def adb_reverse(self, remote):
        port = 0
        for reverse in self.adb.reverse_list():
            if reverse.remote == remote and reverse.local.startswith('tcp:'):
                if not port:
                    port = int(reverse.local[4:])
                else:
                    self.adb_reverse_remove(reverse.remote)
        if port:
            return port
        port = random_port(self.config.FORWARD_PORT_RANGE)
        reverse = ReverseItem(remote, f'tcp:{port}')
        self._adb_reverse_transport(reverse.remote, reverse.local)
        return port

    def adb_forward_remove(self, local):
        try:
            with self.adb_client._connect() as c:
                c.send_command(f'host-serial:{self.serial}:killforward:{local}')
                c.check_okay()
        except AdbError as e:
            if not re.search(r'listener .*? not found', str(e)):
                raise

    def adb_reverse_remove(self, local):
        try:
            with self.adb_client._connect() as c:
                c.send_command(f'host:transport:{self.serial}')
                c.check_okay()
                c.send_command(f'reverse:killforward:{local}')
                c.check_okay()
        except AdbError as e:
            if not re.search(r'listener .*? not found', str(e)):
                raise

    def adb_push(self, local, remote):
        return self.adb_command(['push', local, remote])

    # --- connect / reconnect ---------------------------------------------------------
    def list_device(self):
        devices = []
        try:
            with self.adb_client._connect() as c:
                c.send_command('host:devices')
                c.check_okay()
                for line in c.read_string_block().splitlines():
                    parts = line.strip().split('\t')
                    if len(parts) == 2:
                        devices.append(AdbDeviceWithStatus(self.adb_client, parts[0], parts[1]))
        except ConnectionResetError as e:
            logger.error(e)
        return devices

    def adb_connect(self, wait_device=True):
        for device in self.list_device():
            if device.status == 'offline':
                logger.warning(f'[设备-连接] 设备 {device.serial} 离线，连接前先断开')
                self.adb_client.disconnect(device.serial)
            elif device.status == 'unauthorized':
                logger.error(f'[设备-连接] 设备 {device.serial} 未授权，请在设备上接受ADB调试')
        if 'emulator-' in self.serial or re.match(r'^[a-zA-Z0-9]+$', self.serial):
            return True
        for _ in range(3):
            msg = self.adb_client.connect(self.serial)
            logger.info(msg)
            if 'connected' in msg:
                return True
            if 'bad port' in msg:
                possible_reasons('Serial incorrect, might be a typo')
                raise RequestHumanTakeover(msg)
            if '(10061)' in msg:
                logger.warning('[设备-连接] ADB 无法连接至该模拟器，或是模拟器未启动。')
                raise EmulatorNotRunningError(msg)
        logger.warning(f'[设备-连接] 尝试3次后仍无法连接 {self.serial}，假设已连接')
        return False

    def detect_package(self):
        """Recovery hook used by the method retry policies (AzurPilot re-detects the
        Azur Lane server here). The package is fixed; just confirm it is installed."""
        packages = self.adb_shell(['pm', 'list', 'packages', self.package])
        if f'package:{self.package}' not in packages.splitlines():
            raise RequestHumanTakeover(f'设备上没有安装 {self.package}')

    def release_resource(self):
        for name in ('droidcast_session', '_minitouch_builder', '_maatouch_builder', 'reverse_server'):
            del_cached_property(self, name)

    def adb_disconnect(self):
        msg = self.adb_client.disconnect(self.serial)
        if msg:
            logger.info(msg)
        self.release_resource()

    def adb_restart(self):
        logger.info('[设备-连接] 重启ADB')
        self.adb_client.server_kill()
        del_cached_property(self, 'adb_client')
        self.release_resource()
        _ = self.adb_client

    def adb_reconnect(self):
        if self.config.Emulator_AdbRestart and len(self.list_device()) == 0:
            self.adb_restart()
            self.adb_connect()
        else:
            self.adb_disconnect()
            self.adb_connect()

    def install_uiautomator2(self):
        logger.info('[设备-连接] 安装uiautomator2')
        init = u2.init.Initer(self.adb, loglevel=logging.DEBUG)
        if init.abi not in ['x86_64', 'x86', 'arm64-v8a', 'armeabi-v7a', 'armeabi']:
            init.abi = init.abis[0]
        init.set_atx_agent_addr('127.0.0.1:7912')
        init.install()
        self.uninstall_minicap()

    def uninstall_minicap(self):
        self.adb_shell(['rm', '/data/local/tmp/minicap'])
        self.adb_shell(['rm', '/data/local/tmp/minicap.so'])

    def restart_atx(self):
        logger.info('[设备-连接] 重启ATX')
        atx_agent_path = '/data/local/tmp/atx-agent'
        self.adb_shell([atx_agent_path, 'server', '--stop'])
        self.adb_shell([atx_agent_path, 'server', '--nouia', '-d', '--addr', '127.0.0.1:7912'])

    @staticmethod
    def sleep(second):
        time.sleep(ensure_time(second))

    @retry
    def get_orientation(self):
        pattern = re.compile(r'.*DisplayViewport{.*valid=true, .*orientation=(?P<orientation>\d+), '
                             r'.*deviceWidth=(?P<width>\d+), deviceHeight=(?P<height>\d+).*')
        res = pattern.search(self.adb_shell(['dumpsys', 'display']), 0)
        o = int(res.group('orientation')) if res else 0
        if o not in self._orientation_description:
            o = 0
        self.orientation = o
        logger.attr('设备方向', f'{o} ({self._orientation_description.get(o, "Unknown")})')
        return o
