"""WebSocket sessions of the AzurPilot WebUI protocol (ported from AzurPilot
module/api/socket.py): control/data channels, fragmentation, authentication,
rate limits, duplicate-id protection and backpressure are kept.

AzurPilot wakes log/preview producers from in-process hubs; WarshipPilot's
events live in SQLite and frames on the runtime, so those producers poll the
newest event id / frame id instead.
"""
import asyncio
import contextlib
import json
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import anyio
from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from module.api.alas.protocol import ApiError, AuthParams, Request, SubscribeParams, failure, response
from module.api.alas.transport import DATA_TOPICS, FRAME_BYTES, REQUEST_BYTES, RESPONSE_BYTES, frames, receive

TOPIC_INTERVAL = {'overview': 1, 'instances': 2, 'launcher': 1, 'plugins': 2}
TICK = 0.5
LOG_POLL, PREVIEW_POLL = 0.5, 0.25
LOCAL_HOSTS = {'127.0.0.1', '::1', 'localhost'}


def host_name(value):
    if not value:
        return ''
    value = value.strip()
    if value.startswith('['):
        return value[1:value.find(']')] if ']' in value else value
    return value.rsplit(':', 1)[0] if value.count(':') == 1 else value


def is_local(ws: WebSocket) -> bool:
    """Loopback client talking to a loopback Host/Origin: the local console."""
    client = ws.client.host if ws.client else ''
    origin = ws.headers.get('origin')
    origin_host = urlsplit(origin).hostname if origin else 'localhost'
    return (client in LOCAL_HOSTS and host_name(ws.headers.get('host')) in LOCAL_HOSTS
            and origin_host in LOCAL_HOSTS)


class Gateway:
    @property
    def password(self):
        """Read on every login so a changed access code applies immediately;
        sessions that already logged in stay authorized."""
        value = getattr(getattr(self.router, 'runtime', None), 'access_code', None)
        return self._password if value is None else str(value)

    def __init__(self, router, password):
        self.router = router
        self._password = str(password or '')
        self.connections = 0
        self.data_connections = 0
        self.workers = asyncio.Semaphore(8)
        self.data_workers = asyncio.Semaphore(4)
        self.failures = OrderedDict()

    async def endpoint(self, ws: WebSocket):
        origin = ws.headers.get('origin')
        # WebSocket is not covered by CORS: check the origin before upgrading.
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != ws.headers.get('host'):
                await ws.close(code=1008)
                return
        channel = ws.query_params.get('channel')
        if channel not in (None, 'control', 'data'):
            await ws.close(code=1008)
            return
        is_data = channel == 'data'
        if self.connections >= 32 or is_data and self.data_connections >= 16:
            await ws.close(code=1013)
            return
        self.connections += 1
        self.data_connections += is_data
        try:
            await Session(self, ws, is_local(ws), channel).run()
        finally:
            self.connections -= 1
            self.data_connections -= is_data

    def authenticate(self, peer: str, password: str):
        current = time.monotonic()
        count, until = self.failures.get(peer, (0, 0))
        if until > current:
            raise ApiError('RATE_LIMITED', '登录尝试过于频繁，请稍后重试')
        if not secrets.compare_digest(password.encode(), self.password.encode()):
            count += 1
            self.failures[peer] = (count, current + min(60, count * 2))
            if len(self.failures) > 1024:
                self.failures.popitem(last=False)
            raise ApiError('UNAUTHORIZED', '访问密码不正确')
        self.failures.pop(peer, None)


class Session:
    def __init__(self, gateway: Gateway, ws: WebSocket, local: bool = False, channel=None):
        self.gateway, self.ws = gateway, ws
        self.channel = channel
        self.local = local
        self.authorized = local or not bool(gateway.password)
        self.queue = asyncio.Queue(maxsize=32)
        self.subscription = SubscribeParams(topics=[])
        self.sequence = 0
        self.cache = {}
        self.responses = OrderedDict()
        self.log_cursor = 0
        self.logs_initialized = False
        self.window = time.monotonic()
        self.requests = 0
        self.topic_seen = {}
        self.preview_pending = None
        self.reset = asyncio.Event()

    @property
    def workers(self):
        return self.gateway.data_workers if self.channel == 'data' else self.gateway.workers

    @property
    def router(self):
        return self.gateway.router

    async def enqueue(self, message: dict):
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            await self.ws.close(code=1013, reason='客户端读取过慢，请重新连接')
            raise WebSocketDisconnect(1013)

    async def event(self, topic: str, data):
        message = {'v': 1, 'type': 'event', 'topic': topic, 'data': data}
        if topic == 'preview':
            if self.preview_pending is None:
                await self.enqueue({'previewSlot': True})
            self.preview_pending = message
        else:
            await self.enqueue(message)

    async def writer(self):
        while True:
            message = await self.queue.get()
            if message.get('previewSlot'):
                message, self.preview_pending = self.preview_pending, None
                if (not message or 'preview' not in self.subscription.topics
                        or message['data']['instance'] != self.subscription.instance):
                    continue
            if message.get('type') == 'event':
                self.sequence += 1
                message['seq'] = self.sequence
            if self.channel is None:
                await asyncio.wait_for(self.ws.send_json(message), timeout=10)
                continue
            payload = await asyncio.to_thread(self.encode, message)
            if len(payload) > RESPONSE_BYTES:
                if message['type'] != 'response':
                    await self.ws.close(code=1009)
                    raise WebSocketDisconnect(1009)
                payload = self.encode(failure(message['id'], ApiError(
                    'MESSAGE_TOO_LARGE', '响应超过 64 MiB 限制，请缩小查询范围')))
            async with asyncio.timeout(10):
                if len(payload) <= FRAME_BYTES:
                    await self.ws.send_text(payload.decode())
                else:
                    for part in frames(payload):
                        await self.ws.send_bytes(part)
                        await asyncio.sleep(0)

    @staticmethod
    def encode(message):
        return json.dumps(message, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

    async def run(self):
        await self.ws.accept()
        tasks = [asyncio.create_task(self.writer()), asyncio.create_task(self.reader())]
        if self.channel != 'data':
            tasks.append(asyncio.create_task(self.producer()))
        if self.channel != 'control':
            tasks += [asyncio.create_task(self.log_producer()), asyncio.create_task(self.preview_producer())]
        session = {'authRequired': not self.authorized, 'protocolVersion': 1}
        if self.channel is not None:
            session['channel'] = self.channel
        await self.event('session', session)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            # The ASGI server may cancel the whole session scope when the client
            # leaves; shield the cleanup so the tasks really end before the slot
            # is returned (as in AzurPilot).
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                with contextlib.suppress(RuntimeError):
                    await self.ws.close()

    async def reader(self):
        while True:
            raw = await asyncio.wait_for(receive(self.ws, self.channel is not None),
                                         timeout=60 if self.authorized else 30)
            request_id = None
            try:
                if len(raw) > REQUEST_BYTES:
                    raise ApiError('INVALID_REQUEST', '请求超过 8 MiB 限制')
                current = time.monotonic()
                if current - self.window > 1:
                    self.window, self.requests = current, 0
                self.requests += 1
                decoded = json.loads(raw)
                if isinstance(decoded, dict) and isinstance(decoded.get('id'), str):
                    request_id = decoded['id'][:100]
                request = Request.model_validate(decoded)
                if len(raw) > 1024 * 1024:
                    raise ApiError('INVALID_REQUEST', '请求超过 1 MiB 限制')
                if self.requests > 30:
                    raise ApiError('RATE_LIMITED', '请求过于频繁')
                request_id = request.id
                if request_id in self.responses:
                    raise ApiError('DUPLICATE_REQUEST', '请求 ID 已使用，请检查状态后使用新 ID')
                if request.method == 'auth.launcher':
                    ticket = request.params.get('ticket', '')
                    if not self.local or not isinstance(ticket, str) or not self.router.runtime.launcher.trust.consume(ticket):
                        raise ApiError('UNAUTHORIZED', '启动器登录票据无效或已过期')
                    self.authorized = True
                    result = {'authenticated': True}
                elif request.method == 'auth.login':
                    params = AuthParams.model_validate(request.params)
                    peer = self.ws.client.host if self.ws.client else 'unknown'
                    if not self.authorized:
                        self.gateway.authenticate(peer, params.password)
                    self.authorized = True
                    result = {'authenticated': True}
                elif not self.authorized:
                    raise ApiError('UNAUTHORIZED', '请先登录')
                elif request.method == 'events.subscribe':
                    subscription = SubscribeParams.model_validate(request.params)
                    if self.channel is not None and any(
                        (topic in DATA_TOPICS) != (self.channel == 'data') for topic in subscription.topics
                    ):
                        raise ApiError('WRONG_CHANNEL', '请在对应的 WebSocket 通道订阅')
                    if 'launcher' in subscription.topics and not self.local:
                        raise ApiError('LOCAL_ONLY', '启动器状态只允许本机读取')
                    if subscription.instance is not None:
                        self.router.service.check(subscription.instance)
                    self.subscription = subscription
                    self.cache.clear()
                    self.log_cursor = 0
                    self.logs_initialized = False
                    self.topic_seen.clear()
                    self.reset.set()
                    result = {'topics': subscription.topics, 'instance': subscription.instance}
                else:
                    if self.channel is not None and request.method != 'system.ping':
                        method = self.router.methods.get(request.method)
                        if self.channel == 'data':
                            wrong = method is None or method.mutates or not method.data_channel
                        else:
                            wrong = method is not None and method.data_channel
                        if wrong:
                            raise ApiError('WRONG_CHANNEL', '请在对应的 WebSocket 通道调用此方法')
                    async with self.workers:
                        result = await asyncio.to_thread(self.router.dispatch, request.method, request.params,
                                                         local=self.local)
                reply = response(request_id, result)
            except ValidationError as exc:
                # Details never echo the input (passwords, private configuration).
                reply = failure(request_id, ApiError('INVALID_PARAMS', '请求格式或参数不正确',
                                [{'path': list(e['loc']), 'type': e['type']} for e in exc.errors()]))
            except ApiError as exc:
                reply = failure(request_id, exc)
            except (ValueError, PermissionError, RuntimeError) as exc:
                reply = failure(request_id, ApiError('INVALID_PARAMS', str(exc)[:700]))
            except Exception:
                import logging
                logging.getLogger('warship.webui').exception('WebSocket API 执行失败')
                reply = failure(request_id, ApiError('INTERNAL_ERROR', '服务暂时无法完成请求，请检查服务日志'))
            if request_id:
                self.responses[request_id] = True
                if len(self.responses) > 128:
                    self.responses.popitem(last=False)
            await self.enqueue(reply)

    async def producer(self):
        """Sample subscribed snapshot topics and push changes."""
        while True:
            await asyncio.sleep(TICK)
            if not self.authorized:
                continue
            subscription = self.subscription
            service = self.router.service
            for topic in subscription.topics:
                try:
                    if topic in ('logs', 'preview', 'stock', 'notifications'):
                        continue
                    if (moment := time.monotonic()) - self.topic_seen.get(topic, 0) < TOPIC_INTERVAL.get(topic, 2):
                        continue
                    self.topic_seen[topic] = moment
                    if topic == 'instances':
                        action = service.instances
                    elif topic == 'overview':
                        action = service.overview
                    elif topic == 'launcher':
                        from module.api.alas.service import launcher_status
                        action = self.router.runtime.launcher.status
                    else:  # plugins
                        action = list
                    async with self.workers:
                        data = await asyncio.to_thread(action)
                    if subscription is not self.subscription:
                        break
                    fingerprint = json.dumps(data, sort_keys=True, default=str)
                    if self.cache.get(topic) != fingerprint:
                        self.cache[topic] = fingerprint
                        await self.event(topic, data)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception as exc:
                    code, message = (exc.code, exc.message) if isinstance(exc, ApiError) else (
                        'INTERNAL_ERROR', '订阅暂时不可用，请检查服务日志')
                    if subscription is self.subscription and self.cache.get(topic) != code + message:
                        self.cache[topic] = code + message
                        await self.event('subscription.error', {'topic': topic, 'instance': subscription.instance,
                                                               'code': code, 'message': message})

    async def log_producer(self):
        """Initial/reset batches as one event, live additions one entry each."""
        store = self.router.runtime.store
        while True:
            if not self.reset.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.reset.wait(), LOG_POLL)
            subscription = self.subscription
            if not self.authorized or 'logs' not in subscription.topics:
                self.reset.clear()
                continue
            if self.logs_initialized and not self.reset.is_set():
                if await asyncio.to_thread(store.latest_event_id) == self.log_cursor:
                    continue
            self.reset.clear()
            initial = not self.logs_initialized
            try:
                async with self.workers:
                    data = await asyncio.to_thread(self.router.service.logs, subscription.instance, self.log_cursor)
                if subscription is not self.subscription:
                    continue
                if initial or data['reset'] and self.log_cursor:
                    self.log_cursor, self.logs_initialized = data['cursor'], True
                    await self.event('logs', {**data, 'reset': True})
                    continue
                for entry in data['entries']:
                    await self.event('logs', {'instance': data['instance'], 'cursor': entry['id'],
                                              'reset': False, 'entries': [entry]})
                self.log_cursor = data['cursor']
            except (WebSocketDisconnect, asyncio.CancelledError):
                raise
            except ApiError as exc:
                await self.event('subscription.error', {'topic': 'logs', 'instance': subscription.instance,
                                                       'code': exc.code, 'message': exc.message})

    async def preview_producer(self):
        """Push each new frame; a slow browser only gets the latest one."""
        service = self.router.service
        last = None
        while True:
            await asyncio.sleep(PREVIEW_POLL)
            subscription = self.subscription
            if not self.authorized or 'preview' not in subscription.topics:
                last = None
                continue
            current = service.frame_id()
            if current is None or current == last:
                continue
            last = current
            frame = await asyncio.to_thread(service.capture, subscription.instance)
            await self.event('preview', frame)
