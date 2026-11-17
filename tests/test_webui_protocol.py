"""AzurPilot WebUI protocol served by WarshipPilot (module/api/alas)."""
from pathlib import Path
import tempfile
import threading
import unittest

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient

from module.api.alas.config_adapter import alas_schema, convert_field
from module.api.alas.router import Router
from module.api.alas.service import INSTANCE
from module.api.alas.socket import Gateway
from module.config.task_settings import TaskDraft, save_task
from module.logger import Store


class Automation:
    def __init__(self):
        self.scheduler, self.busy, self.result, self.due = False, False, {'status': 'idle'}, {}
        self.started = []

    def control(self, action, task=''):
        self.scheduler = action == 'scheduler-start'

    def start(self, task):
        self.started.append(task)


class Runtime:
    def __init__(self, root):
        self.store = Store(root)
        self.automation = Automation()
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.updater = None
        self.serial, self.status, self.frame = '127.0.0.1:16416', 'live', None

    def device_state(self):
        return {'screenshot_method': 'nemu_ipc', 'control_method': 'ADB'}


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runtime = Runtime(self.root)
        self.addCleanup(self.runtime.store.close)
        save_task(self.root, 'expedition', TaskDraft(enabled=True))
        gateway = Gateway(Router(self.runtime), 'secret')
        self.client = TestClient(Starlette(routes=[WebSocketRoute('/api/v1/ws', gateway.endpoint)]))
        self.sequence = 0

    def call(self, ws, method, params=None):
        self.sequence += 1
        ws.send_json({'v': 1, 'type': 'request', 'id': f'r{self.sequence}', 'method': method, 'params': params or {}})
        while True:
            message = ws.receive_json()
            if message.get('type') == 'response' and message['id'] == f'r{self.sequence}':
                return message

    def login(self, ws):
        session = ws.receive_json()
        self.assertEqual((session['topic'], session['data']['authRequired']), ('session', True))
        self.assertTrue(self.call(ws, 'auth.login', {'password': 'secret'})['ok'])

    def test_login_schema_config_and_overview(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            schema = self.call(ws, 'schema.get', {'language': 'zh-CN'})['result']
            self.assertIn('expedition', schema['menu']['DailyMission']['tasks'])
            self.assertEqual(schema['translations']['Task']['expedition']['name'], '远征')
            self.assertEqual(schema['args']['campaign']['Campaign']['战役章节']['option'], [0, 1, 2, 3, 4])
            self.assertEqual(schema['translations']['Campaign']['战役章节']['2'], '战列')
            # one group, task-specific wording
            self.assertEqual(schema['translations']['TaskArgs']['reward']['Scheduler']['IntervalMinutes']['name'], '检查间隔（分钟）')

            self.assertEqual([i['name'] for i in self.call(ws, 'instances.list')['result']], [INSTANCE])
            config = self.call(ws, 'config.get', {'instance': INSTANCE})['result']
            self.assertTrue(config['values']['expedition']['Scheduler']['Enable'])
            patched = self.call(ws, 'config.patch', {'instance': INSTANCE, 'revision': config['revision'], 'changes': [
                {'path': 'campaign.Campaign.战役章节', 'value': 3},
                {'path': 'campaign.Scheduler.NextRun', 'value': '2030-01-02 03:04:05'}]})['result']
            self.assertEqual(patched['values']['campaign']['Campaign']['战役章节'], 3)
            self.assertEqual(patched['values']['campaign']['Scheduler']['NextRun'], '2030-01-02 03:04:05')
            self.assertNotEqual(patched['revision'], config['revision'])
            refused = self.call(ws, 'config.patch', {'instance': INSTANCE, 'changes': [
                {'path': 'campaign.Campaign.战役SL', 'value': True}]})
            self.assertEqual(refused['error']['code'], 'READ_ONLY')

            overview = self.call(ws, 'overview.get', {'instance': INSTANCE})['result']
            self.assertEqual((overview['status'], overview['tasks'][0]['name']), ('stopped', 'expedition'))
            started = self.call(ws, 'scheduler.start', {'instance': INSTANCE})['result']
            self.assertEqual(started['status'], 'running')
            self.call(ws, 'tasks.run', {'instance': INSTANCE, 'task': 'reward'})
            self.assertEqual(self.runtime.automation.started, ['reward'])

    def test_wrong_password_is_refused_and_rate_limited(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            self.assertEqual(self.call(ws, 'instances.list')['error']['code'], 'UNAUTHORIZED')
            self.assertEqual(self.call(ws, 'auth.login', {'password': 'nope'})['error']['code'], 'UNAUTHORIZED')
            self.assertEqual(self.call(ws, 'auth.login', {'password': 'secret'})['error']['code'], 'RATE_LIMITED')

    def test_changed_access_code_applies_without_restart(self):
        self.runtime.access_code = 'secret'
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            short = self.call(ws, 'settings.patch', {'values': {'WebUI.AccessCode': 'abc'}})
            self.assertEqual(short['error']['code'], 'INVALID_PARAMS')
            saved = self.call(ws, 'settings.patch', {'values': {'WebUI.AccessCode': 'new-secret'}})['result']
            self.assertEqual(saved['updated'], ['WebUI.AccessCode'])
            # The session that changed it stays logged in and gets the new HTTP key.
            self.assertEqual(self.call(ws, 'warship.httpKey')['result']['key'], 'new-secret')
        from module.config.config import Config
        self.assertEqual(Config(self.root).deploy()['WebUI']['AccessCode'], 'new-secret')
        with self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            self.assertEqual(self.call(ws, 'auth.login', {'password': 'new-secret'})['ok'], True)
        with self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            self.assertEqual(self.call(ws, 'auth.login', {'password': 'secret'})['error']['code'], 'UNAUTHORIZED')

    def test_azur_lane_only_methods_answer_not_found(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            self.login(ws)
            self.assertEqual(self.call(ws, 'dock.report', {'instance': INSTANCE})['error']['code'], 'NOT_FOUND')
            self.assertEqual(self.call(ws, 'instances.create', {'name': 'x'})['error']['code'], 'UNSUPPORTED')
            self.assertEqual(self.call(ws, 'plugins.list')['result'], [])

    def test_logs_subscription_on_data_channel(self):
        self.runtime.store.event('第一条')
        with self.client.websocket_connect('/api/v1/ws?channel=data') as ws:
            self.login(ws)
            reply = self.call(ws, 'events.subscribe', {'instance': INSTANCE, 'topics': ['logs']})
            self.assertTrue(reply['ok'])
            batch = ws.receive_json()
            self.assertEqual((batch['topic'], batch['data']['reset']), ('logs', True))
            self.assertRegex(batch['data']['entries'][-1]['text'], r'^INFO \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} │ 第一条$')
            self.runtime.store.event('第二条', 'warning')
            live = ws.receive_json()
            self.assertEqual((live['data']['reset'], live['data']['entries'][0]['level']), (False, 'WARNING'))
            wrong = self.call(ws, 'config.patch', {'instance': INSTANCE, 'changes': [
                {'path': 'campaign.Campaign.战役章节', 'value': 1}]})
            self.assertEqual(wrong['error']['code'], 'WRONG_CHANNEL')

    def test_overview_pushed_on_control_channel(self):
        with self.client.websocket_connect('/api/v1/ws?channel=control') as ws:
            self.login(ws)
            self.call(ws, 'events.subscribe', {'instance': INSTANCE, 'topics': ['instances', 'overview']})
            topics = {ws.receive_json()['topic'] for _ in range(2)}
            self.assertEqual(topics, {'instances', 'overview'})


class SchemaShapeTest(unittest.TestCase):
    def test_every_field_has_a_frontend_type_and_text(self):
        data = alas_schema()
        for task, groups in data['args'].items():
            for group, fields in groups.items():
                self.assertIn('_info', data['translations'][group])
                for arg, field in fields.items():
                    self.assertIn(field['type'], ('checkbox', 'select', 'input', 'datetime', 'textarea'))
                    self.assertIn(arg, data['translations'][group])

    def test_field_conversion(self):
        self.assertEqual(convert_field({'type': 'number', 'value': 60, 'min': 1, 'max': 10080}),
                         {'type': 'input', 'valuetype': 'int', 'value': 60, 'validate': [1, 10080]})
        self.assertEqual(convert_field({'type': 'checkbox', 'value': False, 'display': 'readonly'})['display'], 'disabled')


if __name__ == '__main__':
    unittest.main()
