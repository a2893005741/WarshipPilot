"""Updater: version logic, GitHub responses, install guards."""
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from backend import updater
from backend.updater import Updater, parse_version


class Response:
    def __init__(self, status, payload):
        self.status_code, self.payload = status, payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def make(busy=False):
    tmp = Path(tempfile.mkdtemp())
    events = []
    return Updater(tmp, {'port': 22680, 'argv': []}, busy=lambda: busy, shutdown=lambda: None,
                   event=lambda m, level='info': events.append(m)), events


def release(tag, asset=True):
    assets = [{'id': 7, 'name': f'WarshipPilot-{tag[1:]}-win-x64.zip', 'size': 10, 'digest': 'sha256:ab'}] if asset else []
    return {'tag_name': tag, 'name': tag, 'body': 'notes', 'published_at': '2026-11-17T00:00:00Z', 'assets': assets}


class VersionTest(unittest.TestCase):
    def test_numeric_comparison(self):
        self.assertGreater(parse_version('v0.10.0'), parse_version('0.9.9'))
        self.assertIsNone(parse_version('latest'))


class CheckTest(unittest.TestCase):
    def test_newer_release_is_available(self):
        u, _ = make()
        with mock.patch.object(updater.requests, 'get', return_value=Response(200, release('v9.0.0'))):
            state = u.check()
        self.assertEqual(state['state'], 'available')
        self.assertEqual(state['latest']['asset']['name'], 'WarshipPilot-9.0.0-win-x64.zip')

    def test_same_version_is_current(self):
        u, _ = make()
        with mock.patch.object(updater.requests, 'get', return_value=Response(200, release('v' + updater.VERSION))):
            self.assertEqual(u.check()['state'], 'current')

    def test_private_repo_without_token_explains(self):
        u, _ = make()
        with mock.patch.object(updater.requests, 'get', return_value=Response(404, {})):
            state = u.check()
        self.assertEqual(state['state'], 'error')
        self.assertIn('令牌', state['error'])

    def test_token_is_sent_but_never_exposed(self):
        u, _ = make()
        u.save_settings(token='github_pat_secret')
        with mock.patch.object(updater.requests, 'get', return_value=Response(200, release('v9.0.0'))) as get:
            state = u.check()
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer github_pat_secret')
        self.assertTrue(state['has_token'])
        self.assertNotIn('github_pat_secret', repr(state))

    def test_bad_repo_rejected(self):
        u, _ = make()
        with self.assertRaises(ValueError):
            u.save_settings(repo='not a repo')


class InstallGuardTest(unittest.TestCase):
    def test_source_mode_refuses(self):
        u, _ = make()
        with self.assertRaises(ValueError):
            u.install()

    def test_busy_refuses(self):
        u, _ = make(busy=True)
        u.status['state'] = 'available'
        with mock.patch.object(updater.sys, 'frozen', True, create=True):
            with self.assertRaises(ValueError) as ctx:
                u.install()
        self.assertIn('停止', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
