"""ADB recovery tests. No commands are sent to a real emulator."""
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from starlette.testclient import TestClient

from module.api.app import create_app
from module.device.adb_client import Adb
from module.runtime.runtime import Runtime


TARGET = '127.0.0.1:16416'


class AdbRestartTest(unittest.TestCase):
    def test_restart_sequence(self):
        adb = Adb('adb.exe')
        with patch.object(adb, 'run') as run:
            adb.restart_service()
        self.assertEqual(run.call_args_list, [call('kill-server', timeout=20), call('start-server', timeout=20)])

    def test_reconnect_only_touches_target_port(self):
        adb = Adb('adb.exe')
        with patch.object(adb, 'run', return_value=b'') as run:
            adb.reconnect(TARGET)
        self.assertEqual(run.call_args_list, [call('disconnect', TARGET), call('connect', TARGET)])

    def test_device_state_is_exact_and_does_not_query_other_devices(self):
        adb = Adb('adb.exe')
        output = f'List of devices attached\n127.0.0.1:5555 device\n{TARGET} offline\n'.encode()
        with patch.object(adb, 'run', return_value=output) as run:
            self.assertEqual(adb.device_state(TARGET), 'offline')
        run.assert_called_once_with('devices', '-l')


class RuntimeRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.runtime = r = Runtime.__new__(Runtime)
        r.adb = Mock(spec=Adb)
        r.lock, r.io_lock = threading.RLock(), threading.Lock()
        r.config = {'serial': TARGET, 'screenshot_method': 'ADB', 'control_method': 'ADB'}
        r.benchmark = {'running': False}
        r.automation = SimpleNamespace(busy=False, update_pending=False)
        r.auto_connect_enabled = True
        r.next_connect = r.next_adb_restart = 0
        r.status, r.serial, r.connect_error = 'idle', '', ''
        r.setup_error = r.emulator_error = ''
        r.store = Mock()
        r.recent_frames = {}
        r.wake = threading.Event()
        r.close_emulator = Mock()
        r.open_emulator = Mock()
        r.adb.profile.return_value = {'version': '5.6.0'}
        r.save_config = Mock()

    def test_automatic_restart_when_target_stays_offline(self):
        r = self.runtime
        r.adb.device_state.side_effect = ['offline', 'offline', 'device']
        r._auto_connect_if_due()
        self.assertEqual(r.adb.method_calls, [
            call.connect(TARGET), call.device_state(TARGET), call.reconnect(TARGET),
            call.device_state(TARGET), call.close(), call.restart_service(),
            call.connect(TARGET), call.device_state(TARGET), call.profile(TARGET),
        ])
        self.assertEqual((r.serial, r.status, r.connect_error), (TARGET, 'live', ''))
        r.save_config.assert_not_called()

    def test_offline_target_can_recover_without_server_restart(self):
        r = self.runtime
        r.adb.device_state.side_effect = ['offline', 'device']
        r._auto_connect_if_due()
        r.adb.reconnect.assert_called_once_with(TARGET)
        r.adb.restart_service.assert_not_called()
        self.assertEqual(r.status, 'live')

    def test_persistent_failure_respects_restart_cooldown(self):
        r = self.runtime
        r.adb.device_state.return_value = 'offline'
        r._auto_connect_if_due()
        r.next_connect = 0
        r._auto_connect_if_due()
        r.adb.restart_service.assert_called_once_with()
        self.assertIn('未在线', r.connect_error)

    def test_unavailable_server_is_restarted(self):
        r = self.runtime
        r.adb.device_state.side_effect = [RuntimeError('ADB unavailable'), 'device']
        r._auto_connect_if_due()
        r.adb.restart_service.assert_called_once_with()
        self.assertEqual(r.serial, TARGET)

    def test_closed_port_does_not_restart_shared_server(self):
        r = self.runtime
        r.adb.device_state.return_value = ''
        with patch.object(r, '_target_listening', return_value=False):
            r._auto_connect_if_due()
        r.adb.restart_service.assert_not_called()
        self.assertIn('未在线', r.connect_error)

    def test_listening_target_missing_from_adb_triggers_restart(self):
        r = self.runtime
        r.adb.device_state.side_effect = ['', 'device']
        with patch.object(r, '_target_listening', return_value=True):
            r._auto_connect_if_due()
        r.adb.restart_service.assert_called_once_with()
        self.assertEqual(r.serial, TARGET)

    def test_connecting_another_address_preserves_live_device(self):
        r = self.runtime
        r.serial, r.status = TARGET, 'live'
        r.adb.device_state.return_value = 'offline'
        with self.assertRaisesRegex(RuntimeError, '未在线'):
            r.connect_adb('127.0.0.1:16448')
        r.adb.restart_service.assert_not_called()
        self.assertEqual((r.serial, r.status), (TARGET, 'live'))

    def test_unauthorized_target_does_not_restart_shared_server(self):
        r = self.runtime
        r.adb.device_state.return_value = 'unauthorized'
        r._auto_connect_if_due()
        r.adb.restart_service.assert_not_called()
        self.assertIn('未授权', r.connect_error)

    def test_missing_game_does_not_restart_shared_server(self):
        r = self.runtime
        r.adb.device_state.return_value = 'device'
        r.adb.profile.side_effect = ValueError('没有安装战舰少女R')
        r._auto_connect_if_due()
        r.adb.restart_service.assert_not_called()
        self.assertIn('没有安装', r.connect_error)

    def test_manual_restart_refuses_busy_task(self):
        r = self.runtime
        r.automation.busy = True
        with self.assertRaises(ValueError):
            r.restart_adb()
        r.adb.restart_service.assert_not_called()

    def test_http_restart_uses_saved_target_and_requires_auth(self):
        r = self.runtime
        r.adb.device_state.return_value = 'device'
        r.resources = Path(__file__).resolve().parents[1]
        r.updater = None
        client = TestClient(create_app(r, 'secret', Mock()))
        self.assertEqual(client.post('/api/restart-adb', json={}).status_code, 401)
        r.adb.restart_service.assert_not_called()
        response = client.post('/api/restart-adb', json={'serial': '127.0.0.1:5555'},
                               headers={'Authorization': 'Bearer secret'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['serial'], TARGET)
        r.adb.restart_service.assert_called_once_with()
        r.adb.connect.assert_called_once_with(TARGET)
        self.assertEqual((r.serial, r.status), (TARGET, 'live'))

    def test_manual_restart_reports_failure_and_keeps_target_for_retry(self):
        r = self.runtime
        r.serial, r.status = TARGET, 'live'
        r.adb.device_state.return_value = 'offline'
        with self.assertRaisesRegex(RuntimeError, '未在线'):
            r.restart_adb()
        self.assertEqual((r.serial, r.status, r.config['serial']), ('', 'idle', TARGET))
        self.assertIn('未在线', r.connect_error)
