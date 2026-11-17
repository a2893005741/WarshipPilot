"""Web updates keep the launcher-owned root alive across worker replacement."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from module.api.update_service import Updater


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'log').mkdir()

    def request(self, target='a' * 40):
        (self.root / 'log' / 'update-request.json').write_text(json.dumps({'target': target}), encoding='utf-8')

    def test_web_update_stops_only_worker_without_launcher_rpc(self):
        from deploy.webui_supervisor import UPDATE_EXIT_CODE
        shutdown, launcher = Mock(), Mock()
        updater = Updater(self.root, {'argv': ['--no-browser', '--port', '23123']},
                          lambda: False, shutdown, Mock())
        updater.launcher = launcher
        updater.status['latest'] = {'version': 'a' * 40}
        with patch.dict(os.environ, {'AP_LAUNCHER_PID': '123', 'WARSHIP_WEBUI_SUPERVISED': '1'}), \
                patch('module.api.update_service.subprocess.Popen') as spawn:
            updater._handover()
        spawn.assert_not_called()
        launcher.request_update.assert_not_called()
        shutdown.assert_called_once()
        self.assertEqual(updater.exit_code, UPDATE_EXIT_CODE)
        self.assertEqual(json.loads((self.root / 'log' / 'update-request.json').read_text())['target'], 'a' * 40)
        self.assertEqual(json.loads((self.root / 'log' / 'update-arguments.json').read_text()),
                         ['--webui-worker', '--no-browser', '--port', '23123'])

    def test_repeated_updates_keep_supervisor_and_install_in_background(self):
        from deploy.webui_supervisor import UPDATE_EXIT_CODE, supervise
        calls = []

        def spawn(command, **options):
            calls.append((command, options))
            if len(calls) <= 2:
                self.request(str(len(calls)) * 40)
                return Mock(wait=Mock(return_value=UPDATE_EXIT_CODE))
            return Mock(wait=Mock(return_value=0))

        with patch('deploy.webui_supervisor.subprocess.Popen', side_effect=spawn), \
                patch.dict(os.environ, {'AP_LAUNCHER_PID': '123'}):
            self.assertEqual(supervise(self.root, ['--root', str(self.root), '--no-browser']), 0)
        self.assertEqual(len(calls), 3)
        self.assertIn('--webui-worker', calls[0][0])
        for command, options in calls[1:]:
            self.assertIn('deploy.installer', command)
            self.assertIn('--supervised', command)
            self.assertIn('--wait-gui', command)
            self.assertNotIn('--wait-pid', command)
            self.assertEqual(options['env']['AP_LAUNCHER_PID'], '123')
            self.assertEqual(options['env']['WARSHIP_WEBUI_SUPERVISED'], '1')
        self.assertFalse((self.root / 'log' / 'update-request.json').exists())

    def test_invalid_update_request_never_starts_installer(self):
        from deploy.webui_supervisor import UPDATE_EXIT_CODE, supervise
        self.request('main')
        with patch('deploy.webui_supervisor.subprocess.Popen', return_value=Mock(wait=Mock(return_value=UPDATE_EXIT_CODE))) as spawn:
            with self.assertRaisesRegex(ValueError, '更新请求'):
                supervise(self.root, [])
        spawn.assert_called_once()

    def test_console_interrupt_reaps_current_installer_and_worker_tree(self):
        from deploy.webui_supervisor import UPDATE_EXIT_CODE, supervise
        self.request()
        first = Mock(wait=Mock(return_value=UPDATE_EXIT_CODE))
        installer = Mock(pid=9876, poll=Mock(return_value=None), wait=Mock(side_effect=[KeyboardInterrupt, 0]))
        with patch('deploy.webui_supervisor.subprocess.Popen', side_effect=[first, installer]), \
                patch('deploy.webui_supervisor.subprocess.run') as stop:
            with self.assertRaises(KeyboardInterrupt):
                supervise(self.root, [])
        self.assertEqual(stop.call_args.args[0], ['taskkill', '/PID', '9876', '/T', '/F'])

    def test_real_gui_worker_serves_health_and_parent_exits_after_shutdown(self):
        import socket
        import urllib.request
        from module.config.config import Config
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        config = Config(self.root)
        config.ensure()
        deployment = config.deploy()
        deployment['WebUI'].update(Host='127.0.0.1', Port=port, AccessCode='supervisor-smoke')
        deployment['Update']['AutoCheck'] = False
        config.save_deploy(deployment)
        (self.root / 'log' / 'migration.json').write_text('{}')
        repo = Path(__file__).resolve().parents[1]
        with (self.root / 'log' / 'smoke.log').open('wb') as stream:
            process = subprocess.Popen([sys.executable, str(repo / 'gui.py'), '--root', str(self.root),
                                        '--host', '127.0.0.1', '--port', str(port), '--no-browser'],
                                       cwd=repo, stdout=stream, stderr=stream,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                health = None
                deadline = time.monotonic() + 20
                while process.poll() is None and time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=.5) as response:
                            health = json.load(response)
                        break
                    except OSError:
                        time.sleep(.05)
                self.assertIsNotNone(health)
                self.assertEqual(health['product'], 'WarshipPilot')
                self.assertNotEqual(health['pid'], process.pid)
                self.assertIsNone(process.poll())
                request = urllib.request.Request(f'http://127.0.0.1:{port}/api/shutdown', data=b'{}',
                                                 headers={'Authorization': 'Bearer supervisor-smoke',
                                                          'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                if process.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                    process.wait(timeout=5)

    def test_parent_process_stays_alive_during_real_worker_replacement(self):
        from deploy.webui_supervisor import UPDATE_EXIT_CODE
        # A real child exits for update; its replacement holds until released.
        worker = self.root / 'gui.py'
        worker.write_text(
            'import json, pathlib, sys\n'
            'root = pathlib.Path(__file__).parent\n'
            "(root / 'log' / 'update-request.json').write_text(json.dumps({'target': 'a' * 40}))\n"
            f'sys.exit({UPDATE_EXIT_CODE})\n', encoding='utf-8')
        script = self.root / 'probe.py'
        script.write_text(
            'import pathlib, subprocess, sys\n'
            f'sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n'
            'from deploy import webui_supervisor as supervisor\n'
            'root = pathlib.Path(__file__).parent\n'
            'original = subprocess.Popen\n'
            'def spawn(command, **options):\n'
            "    if 'deploy.installer' in command:\n"
            '        command = [sys.executable, "-c", '
            '"import pathlib, time; p=pathlib.Path(\'release\'); pathlib.Path(\'ready\').touch(); "'
            '"\\nwhile not p.exists(): time.sleep(.02)"]\n'
            '    return original(command, **options)\n'
            'supervisor.subprocess.Popen = spawn\n'
            'sys.exit(supervisor.supervise(root, [], entry=root / "gui.py"))\n', encoding='utf-8')
        process = subprocess.Popen([sys.executable, str(script)], cwd=self.root,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 5
            while not (self.root / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue((self.root / 'ready').exists())
            self.assertIsNone(process.poll())
        finally:
            (self.root / 'release').touch()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self.assertEqual(process.returncode, 0)


class SupervisedInstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'log').mkdir()
        self.args = ['installer', '--root', str(self.root), '--restart', '--wait-gui',
                     '--supervised', '--target', 'a' * 40, '--webui-worker', '--no-browser']

    def result(self):
        return json.loads((self.root / 'log' / 'update-result.json').read_text(encoding='utf-8'))

    def test_installer_health_tracks_serving_worker_in_both_modes(self):
        from deploy.installer import start_gui
        for argv in (['--no-browser'], ['--webui-worker', '--no-browser']):
            with self.subTest(argv=argv), patch('deploy.installer.subprocess.Popen') as spawn:
                start_gui(self.root, argv)
                command = spawn.call_args.args[0]
                self.assertEqual(command.count('--webui-worker'), 1)
                self.assertIn('--no-browser', command)

    def test_success_waits_for_worker_and_propagates_next_update(self):
        from deploy.installer import main
        from deploy.webui_supervisor import UPDATE_EXIT_CODE
        process = Mock(wait=Mock(return_value=UPDATE_EXIT_CODE))
        with patch.object(sys, 'argv', self.args), patch('deploy.installer.install', return_value='b' * 40), \
                patch('deploy.installer.start_gui', return_value=process) as start, \
                patch('deploy.installer.wait_healthy'):
            self.assertEqual(main(), UPDATE_EXIT_CODE)
        start.assert_called_once_with(self.root, ['--webui-worker', '--no-browser'])
        self.assertTrue(self.result()['ok'])

    def test_failed_install_keeps_old_service_running_and_records_error(self):
        from deploy.installer import main
        process = Mock(wait=Mock(return_value=0))
        with patch.object(sys, 'argv', self.args), patch('deploy.installer.install', side_effect=RuntimeError('network failed')), \
                patch('deploy.installer.start_gui', return_value=process) as start:
            self.assertEqual(main(), 0)
        start.assert_called_once()
        process.wait.assert_called_once()
        self.assertFalse(self.result()['ok'])
        self.assertEqual(self.result()['error'], 'network failed')

    def test_unhealthy_new_service_rolls_back_and_waits_for_old_service(self):
        from deploy.installer import main
        updated = Mock(poll=Mock(return_value=None))
        restored = Mock(wait=Mock(return_value=0))
        with patch.object(sys, 'argv', self.args), patch('deploy.installer.install', return_value='b' * 40), \
                patch('deploy.installer.start_gui', side_effect=[updated, restored]), \
                patch('deploy.installer.wait_healthy', side_effect=RuntimeError('unhealthy')), \
                patch('deploy.installer.rollback') as rollback:
            self.assertEqual(main(), 0)
        updated.terminate.assert_called_once()
        rollback.assert_called_once_with(self.root, 'b' * 40)
        restored.wait.assert_called_once()
        self.assertFalse(self.result()['ok'])

    def test_spawn_failure_also_restores_old_commit(self):
        from deploy.installer import main
        restored = Mock(wait=Mock(return_value=0))
        with patch.object(sys, 'argv', self.args), patch('deploy.installer.install', return_value='b' * 40), \
                patch('deploy.installer.start_gui', side_effect=[OSError('cannot start'), restored]), \
                patch('deploy.installer.rollback') as rollback:
            self.assertEqual(main(), 0)
        rollback.assert_called_once_with(self.root, 'b' * 40)
        restored.wait.assert_called_once()
        self.assertEqual(self.result()['error'], 'cannot start')


if __name__ == '__main__':
    unittest.main()
