"""Versioned WebSocket requests and live state, backed by the same API handlers."""
import asyncio
import json
import secrets
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect
from module.api.protocol import RequestEnvelope

METHODS = {'config.schema': ('schema', 'GET'), 'config.get': ('config', 'GET'),
           'config.set': ('config-field', 'POST'), 'runtime.get': ('state', 'GET')}
GET_ACTIONS = {'state', 'events', 'samples', 'task-configs', 'legacy-catalog', 'legacy-rule', 'schema', 'config'}
POST_ACTIONS = {'task-control', 'task-config', 'config-field', 'legacy-settings', 'legacy-check',
                'devices', 'update-check', 'update-install', 'update-settings', 'serial',
                'device-config', 'benchmark', 'connect-adb', 'select', 'control', 'session-start',
                'session-stop', 'sample', 'sample-delete', 'fault', 'legacy-report', 'shutdown'}


def endpoint(runtime, key, handler):
    async def websocket(ws):
        await ws.accept()
        send_lock = asyncio.Lock()
        async def send(value):
            async with send_lock:
                await ws.send_json(value)
        async def push():
            while True:
                state = await asyncio.to_thread(runtime.state)
                events = await asyncio.to_thread(runtime.store.events)
                await send({'v': 1, 'type': 'event', 'state': state, 'events': events})
                await asyncio.sleep(2)
        sender = None
        try:
            login = await asyncio.wait_for(ws.receive_json(), timeout=10)
            if not isinstance(login, dict) or not secrets.compare_digest(str(login.get('key', '')), key):
                await ws.close(code=1008)
                return
            sender = asyncio.create_task(push())
            while True:
                message = await ws.receive_json()
                identifier = message.get('id') if isinstance(message, dict) else None
                try:
                    request = RequestEnvelope.model_validate(message)
                    method, params = request.method, request.params
                    action, verb = METHODS.get(method, (method, 'GET' if method in GET_ACTIONS else 'POST'))
                    if action not in GET_ACTIONS | POST_ACTIONS:
                        raise ValueError('接口不存在')
                    payload = json.dumps(params).encode()
                    async def receive():
                        return {'type': 'http.request', 'body': payload, 'more_body': False}
                    scope = {'type': 'http', 'method': verb, 'path': '/api/' + action,
                             'path_params': {'action': action}, 'query_string': urlencode(params).encode() if verb == 'GET' else b'',
                             'headers': [(b'authorization', ('Bearer ' + key).encode()),
                                         (b'content-type', b'application/json')]}
                    response = await handler(Request(scope, receive=receive))
                    result = json.loads(response.body)
                    if response.status_code >= 400:
                        raise ValueError(result.get('error', '请求失败'))
                    await send({'v': 1, 'type': 'response', 'id': identifier, 'result': result})
                except (ValueError, RuntimeError, OSError) as exc:
                    await send({'v': 1, 'type': 'response', 'id': identifier,
                                'error': {'code': 'INVALID_REQUEST', 'message': str(exc)[:700]}})
        except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError, OSError):
            pass
        finally:
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
    return websocket
