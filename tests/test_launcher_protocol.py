"""Launcher v2 handshake, trust boundary, tickets and update delegation."""
import asyncio
import threading
import unittest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from module.api.launcher_api import routes
from module.runtime.launcher import LauncherService


class LauncherProtocolTest(unittest.TestCase):
    def setUp(self):
        self.service = LauncherService('test-secret')
        self.app = Starlette(routes=routes(self.service))
        self.client = TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))

    def hello(self, ws):
        ws.send_json({'type': 'request', 'id': 'hello', 'method': 'session.hello', 'params': {
            'protocolVersion': 2, 'launcherVersion': '3.0.7', 'platform': 'win32',
            'capabilities': ['autostart', 'notifications', 'login', 'backend.update'],
            'autostart': {'supported': True, 'enabled': False}}})
        self.assertTrue(ws.receive_json()['ok'])

    def connect(self, **headers):
        return self.client.websocket_connect('ws://127.0.0.1/api/v2/launcher/ws', headers={'Authorization': 'Bearer test-secret', **headers})

    def test_handshake_single_use_ticket_and_state(self):
        with self.connect() as ws:
            self.hello(ws)
            self.assertTrue(self.service.status()['connected'])
            ws.send_json({'type': 'request', 'id': 'ticket', 'method': 'login.issue', 'params': {}})
            ticket = ws.receive_json()['result']['ticket']
            self.assertTrue(self.service.trust.consume(ticket))
            self.assertFalse(self.service.trust.consume(ticket))
        self.assertFalse(self.service.status()['connected'])

    def test_forwarded_connections_and_wrong_secrets_are_rejected(self):
        from starlette.websockets import WebSocketDisconnect
        for headers in ({'x-forwarded-for': '127.0.0.1'}, {'Authorization': 'Bearer wrong'}):
            with self.assertRaises(WebSocketDisconnect):
                with self.connect(**headers):
                    pass

    def test_update_request_has_deadline_target_and_acceptance(self):
        with self.connect() as ws:
            self.hello(ws)
            command_id = self.service.request_update('a' * 40)
            request = ws.receive_json()
            self.assertEqual(request['method'], 'backend.update')
            self.assertEqual(request['params'], {'target': 'a' * 40})
            self.assertGreater(request['deadline'], 0)
            ws.send_json({'type': 'response', 'id': command_id, 'ok': True, 'result': {'accepted': True}})
            # A ping provides a deterministic boundary after response processing.
            ws.send_json({'type': 'request', 'id': 'ping', 'method': 'system.ping', 'params': {}})
            self.assertTrue(ws.receive_json()['result']['pong'])
            self.assertEqual(self.service.command(command_id)['status'], 'succeeded')

    def test_notification_is_pending_until_the_launcher_acknowledges_it(self):
        with self.connect() as ws:
            self.hello(ws)
            event_id = self.service.publish({'instance': '舰R', 'title': 't', 'content': 'c'})
            event = ws.receive_json()
            self.assertEqual((event['type'], event['topic'], event['id']), ('event', 'notification', event_id))
            self.assertFalse(self.service.acknowledged(event_id))
            ws.send_json({'type': 'request', 'id': 'ack', 'method': 'notifications.ack', 'params': {'ids': [event_id]}})
            self.assertTrue(ws.receive_json()['ok'])
            self.assertTrue(self.service.acknowledged(event_id))

    def test_update_requires_capability_and_valid_commit(self):
        with self.assertRaises(ValueError):
            self.service.request_update('not-a-commit')
        with self.assertRaises(ValueError):
            self.service.request_update('a' * 40)


if __name__ == '__main__':
    unittest.main()
