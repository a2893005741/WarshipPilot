"""每个应用独立的启动器会话、命令状态与通知缓冲。"""
import asyncio
import sys
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from module.api.alas.protocol import ApiError
COMMAND_TIMEOUT, CONNECTION_EXPIRE = 10, 45
from module.runtime.launcher_trust import LauncherTrust
from module.api.alas.socket import is_local


def is_local_request(request):
    """直连回环与来源校验；经隧道或代理转发的请求不授予本机权限。"""
    return is_local(request) and not any(request.headers.get(key) for key in
        ('forwarded', 'x-forwarded-for', 'x-forwarded-host', 'x-ap-remote-access'))


@dataclass
class LauncherConnection:
    socket: object
    loop: object
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(128))
    ready: bool = False
    last_seen: float = field(default_factory=time.monotonic)


class LauncherService:
    """跨线程业务调用受锁保护，发送操作回到 WS 所属事件循环。"""

    def __init__(self, secret=None):
        self.trust = LauncherTrust(secret)
        self.lock = threading.RLock()
        self.connection = None
        self.commands = OrderedDict()
        self.notifications = OrderedDict()
        self.capabilities = []
        self.platform = sys.platform
        self.version = ''
        self.autostart = {'supported': False, 'enabled': None}

    async def attach(self, socket):
        connection = LauncherConnection(socket, asyncio.get_running_loop())
        with self.lock:
            previous = self.connection
            self._fail_pending('LAUNCHER_DISCONNECTED', '启动器连接已更换，请查询实际状态')
            self.connection = connection
        if previous:
            await previous.socket.close(code=1000)
        return connection

    def detach(self, connection):
        with self.lock:
            if self.connection is connection:
                self.connection = None
                self._fail_pending('LAUNCHER_DISCONNECTED', '启动器已断开，请查询实际状态')

    def hello(self, connection, params):
        with self.lock:
            if self.connection is not connection:
                raise ApiError('LAUNCHER_DISCONNECTED', '启动器会话已失效')
            if connection.ready:
                raise ApiError('INVALID_REQUEST', '启动器已完成握手')
            self.platform, self.version = params.platform, params.launcherVersion
            self.capabilities = params.capabilities
            self.autostart = params.autostart.model_dump()
            connection.ready = True
            return {'protocolVersion': 2, 'heartbeatSeconds': 15}

    def replay(self, connection):
        """握手响应先入队，客户端确认协议后才能收到缓冲通知。"""
        with self.lock:
            for message in self.notifications.values():
                self._enqueue(connection, message)

    def status(self):
        with self.lock:
            self._expire()
            connected = self.connection is not None and self.connection.ready
            return {'connected': connected, 'platform': self.platform, 'version': self.version,
                    'capabilities': list(self.capabilities) if connected else [],
                    'autostart': dict(self.autostart),
                    'commands': [dict(value) for value in self.commands.values()]}

    def set_autostart(self, enabled):
        with self.lock:
            self._expire()
            connection = self.connection
            if connection is None or not connection.ready:
                raise ApiError('LAUNCHER_DISCONNECTED', '启动器未连接')
            if 'autostart' not in self.capabilities or not self.autostart['supported']:
                raise ApiError('UNSUPPORTED', '当前启动器不支持开机自启')
            if sum(value['status'] == 'pending' for value in self.commands.values()) >= 32:
                raise ApiError('BUSY', '启动器命令队列已满')
            command_id = uuid.uuid4().hex
            self.commands[command_id] = {'id': command_id, 'method': 'autostart.set', 'status': 'pending',
                                         'deadline': time.time() + COMMAND_TIMEOUT}
            while len(self.commands) > 128:
                completed = next(key for key, value in self.commands.items() if value['status'] != 'pending')
                self.commands.pop(completed)
            message = {'type': 'request', 'id': command_id, 'method': 'autostart.set',
                       'params': {'enabled': enabled}, 'deadline': self.commands[command_id]['deadline']}
            connection.loop.call_soon_threadsafe(self._enqueue, connection, message)
            return {'commandId': command_id, 'status': 'pending'}

    def request_update(self, target):
        import re
        if not re.fullmatch(r'[0-9a-fA-F]{40}', target):
            raise ValueError('更新目标必须为完整提交 SHA')
        with self.lock:
            self._expire()
            connection = self.connection
            if connection is None or not connection.ready or 'backend.update' not in self.capabilities:
                raise ValueError('当前启动器不支持网页更新，请在启动器中停止后重新启动')
            if any(c['status'] == 'pending' and c.get('method') == 'backend.update' for c in self.commands.values()):
                raise ValueError('更新已经排队')
            command_id = uuid.uuid4().hex
            self.commands[command_id] = {'id': command_id, 'method': 'backend.update', 'status': 'pending',
                                         'deadline': time.time() + COMMAND_TIMEOUT}
            message = {'type': 'request', 'id': command_id, 'method': 'backend.update',
                       'params': {'target': target}, 'deadline': self.commands[command_id]['deadline']}
            connection.loop.call_soon_threadsafe(self._enqueue, connection, message)
            return command_id

    def command(self, command_id):
        with self.lock:
            self._expire()
            if command_id not in self.commands:
                raise ApiError('NOT_FOUND', '启动器命令不存在')
            return dict(self.commands[command_id])

    def should_send(self, message):
        with self.lock:
            self._expire()
            return message.get('type') != 'request' or self.commands.get(message['id'], {}).get('status') == 'pending'

    def complete(self, connection, reply):
        with self.lock:
            if self.connection is not connection:
                return
            self._expire()
            command = self.commands.get(reply.id)
            if not command or command['status'] != 'pending':
                return
            if reply.ok:
                if command.get('method') == 'backend.update':
                    if reply.result != {'accepted': True}:
                        raise ValueError('启动器未接受更新请求')
                    result = reply.result
                else:
                    from module.api.launcher_protocol import AutostartState
                    result = AutostartState.model_validate(reply.result).model_dump()
                    self.autostart = result
                command.update(status='succeeded', result=result)
            else:
                command.update(status='failed', error=reply.error.model_dump())

    def report_state(self, params):
        with self.lock:
            self.autostart = params.autostart.model_dump()
        return {'accepted': True}

    def publish(self, notification):
        message = {'type': 'event', 'id': uuid.uuid4().hex, 'topic': 'notification', 'data': notification}
        with self.lock:
            self.notifications[message['id']] = message
            while len(self.notifications) > 100:
                self.notifications.popitem(last=False)
            connection = self.connection
            if connection and connection.ready:
                connection.loop.call_soon_threadsafe(self._enqueue, connection, message)

    def acknowledge(self, ids):
        with self.lock:
            for event_id in ids:
                self.notifications.pop(event_id, None)
        return {'accepted': True}

    def _enqueue(self, connection, message):
        if self.connection is not connection:
            return
        try:
            connection.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.detach(connection)
            connection.loop.create_task(connection.socket.close(code=1013))

    def _expire(self):
        for command in self.commands.values():
            if command['status'] == 'pending' and command['deadline'] <= time.time():
                command.update(status='expired', error={'code': 'TIMEOUT', 'message': '启动器响应超时，请查询实际状态'})
        connection = self.connection
        if connection and time.monotonic() - connection.last_seen > CONNECTION_EXPIRE:
            self.detach(connection)
            connection.loop.call_soon_threadsafe(lambda: connection.loop.create_task(connection.socket.close(code=1001)))

    def _fail_pending(self, code, message):
        for command in self.commands.values():
            if command['status'] == 'pending':
                command.update(status='failed', error={'code': code, 'message': message})

    async def close(self):
        with self.lock:
            connection = self.connection
            if connection:
                self.detach(connection)
            self.notifications.clear()
            self.trust.clear()
        if connection:
            await connection.socket.close(code=1001)
