"""Real Git fixtures for launcher bootstrap and transaction recovery."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deploy import launcher
from module.config.config import Config
from tests.test_updater import UpdateTest, git


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        git(self.source, 'init', '-b', 'main')
        git(self.source, 'config', 'user.email', 'test@example.invalid')
        git(self.source, 'config', 'user.name', 'Test')
        (self.source / 'gui.py').write_text('# GUI\n')
        (self.source / 'pyproject.toml').write_text('[project]\nname="warshippilot"\nversion="0.0.0"\n')
        (self.source / '.gitignore').write_text('config/deploy.yaml\nlog/\n')
        git(self.source, 'add', '.')
        git(self.source, 'commit', '-m', 'initial')
        self.root = self.base / 'live'
        self.executable = shutil.which('git')

    def test_isolated_empty_install_with_fallback_and_existing_state(self):
        (self.root / 'config').mkdir(parents=True)
        state = self.root / 'config' / 'deploy.yaml'
        state.write_text('preserved')
        # Run the downloaded file alone, with no project imports available.
        script = self.base / 'launcher.py'
        shutil.copy2(Path(launcher.__file__), script)
        result = subprocess.run([sys.executable, '-I', str(script), 'bootstrap', '--json',
                                 '--root', str(self.root), '--git', self.executable,
                                 '--repository', str(self.base / 'missing'),
                                 '--repository', str(self.source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(state.read_text(), 'preserved')
        self.assertEqual(git(self.root, 'branch', '--show-current'), 'main')
        self.assertEqual(git(self.root, 'rev-parse', '@{upstream}'), git(self.root, 'rev-parse', 'HEAD'))
        (self.root / 'WarshipPilot.exe').write_bytes(b'launcher')
        self.assertEqual(git(self.root, 'status', '--porcelain'), '')

    def test_conflict_preserves_files_and_leaves_no_git_metadata(self):
        self.root.mkdir()
        (self.root / 'gui.py').write_text('user source')
        with self.assertRaisesRegex(ValueError, '冲突'):
            launcher.bootstrap(self.root, self.executable, [str(self.source)])
        self.assertFalse((self.root / '.git').exists())
        self.assertEqual((self.root / 'gui.py').read_text(), 'user source')
        self.assertFalse((self.root / 'pyproject.toml').exists())

    def test_wrong_project_is_not_adopted(self):
        subprocess.run(['git', 'clone', str(self.source), str(self.root)], check=True, capture_output=True)
        (self.root / 'pyproject.toml').write_text('[project]\nname="other"\n')
        with self.assertRaisesRegex(ValueError, '其他项目'):
            launcher.bootstrap(self.root, self.executable, [])

    def test_configuration_preserves_user_settings_and_sets_tools(self):
        config = Config(self.root)
        config.ensure()
        value = config.deploy()
        value['WebUI'].update(AccessCode='saved-key', Port=23123)
        value['Custom'] = {'enabled': True}
        config.save_deploy(value)
        subprocess.run(['git', 'init', str(self.root)], check=True, capture_output=True)
        launcher.configure(self.root, 'python-new', 'uv-new', self.executable, 'adb-new')
        after = config.deploy()
        self.assertEqual(after['WebUI'], value['WebUI'])
        self.assertEqual(after['Custom'], value['Custom'])
        self.assertEqual(after['Python']['Uv'], 'uv-new')


class LauncherTransactionTest(UpdateTest):
    def test_sync_failure_restores_old_code_and_records_recovery(self):
        previous = git(self.live, 'rev-parse', 'HEAD')
        self.push('new dependency')
        launcher.update(self.live)
        self.assertNotEqual(git(self.live, 'rev-parse', 'HEAD'), previous)
        with patch('deploy.pip.sync', side_effect=[RuntimeError('sync failed'), True]):
            with self.assertRaisesRegex(RuntimeError, 'sync failed'):
                launcher.sync(self.live)
        self.assertEqual(git(self.live, 'rev-parse', 'HEAD'), previous)
        self.assertIsNone(launcher.read_transaction(self.live))

    def test_unconfirmed_update_is_recovered_before_next_update(self):
        previous = git(self.live, 'rev-parse', 'HEAD')
        self.push('new')
        launcher.update(self.live)
        with patch('deploy.pip.sync', return_value=True):
            launcher.update(self.live, skip_update=True)
        self.assertEqual(git(self.live, 'rev-parse', 'HEAD'), previous)

    def test_offline_start_uses_existing_code_but_explicit_target_fails(self):
        before = git(self.live, 'rev-parse', 'HEAD')
        git(self.live, 'remote', 'set-url', 'origin', str(self.base / 'offline.git'))
        launcher.update(self.live)
        self.assertEqual(git(self.live, 'rev-parse', 'HEAD'), before)
        with self.assertRaises(RuntimeError):
            launcher.update(self.live, target='a' * 40)

    def test_commit_requires_successful_sync(self):
        self.push('new')
        launcher.update(self.live)
        with self.assertRaisesRegex(ValueError, '未同步'):
            launcher.main(['commit', '--root', str(self.live)])
        with patch('deploy.pip.sync', return_value=True), patch('deploy.adb.check'):
            launcher.sync(self.live)
        launcher.main(['commit', '--root', str(self.live)])
        self.assertIsNone(launcher.read_transaction(self.live))

    def test_managed_mode_blocks_legacy_handover(self):
        self.push('new')
        self.u.check()
        with patch.dict(os.environ, {'AP_LAUNCHER_PID': '123'}), patch.object(self.u, '_handover') as handover:
            with self.assertRaisesRegex(ValueError, '启动器'):
                self.u.install()
            handover.assert_not_called()
        self.assertEqual(self.quiesced, [])


if __name__ == '__main__':
    unittest.main()
