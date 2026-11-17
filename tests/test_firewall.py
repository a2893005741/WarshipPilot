"""LAN firewall rule check at startup (module/runtime/firewall.py)."""
import subprocess
import unittest

from module.runtime.firewall import RULE_DISPLAY_NAME, check_lan_access


class Store:
    def __init__(self):
        self.events = []

    def event(self, message, level='info'):
        self.events.append((level, message))


def netsh(returncode, calls):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode)
    return run


class FirewallCheckTest(unittest.TestCase):
    def test_missing_rule_on_lan_host_warns(self):
        store, calls = Store(), []
        check_lan_access(store, '0.0.0.0', 22680, run=netsh(1, calls), platform='nt')
        self.assertEqual(calls[0][-1], f'name={RULE_DISPLAY_NAME}')
        self.assertEqual(store.events[0][0], 'warning')
        self.assertIn('allow-lan-access.ps1', store.events[0][1])

    def test_present_rule_is_silent(self):
        store = Store()
        check_lan_access(store, '0.0.0.0', 22680, run=netsh(0, []), platform='nt')
        self.assertEqual(store.events, [])

    def test_loopback_or_other_platforms_are_not_checked(self):
        for host, platform in (('127.0.0.1', 'nt'), ('localhost', 'nt'), ('0.0.0.0', 'posix')):
            calls = []
            check_lan_access(Store(), host, 22680, run=netsh(1, calls), platform=platform)
            self.assertEqual(calls, [])

    def test_unavailable_netsh_is_not_reported_as_missing(self):
        def broken(*args, **kwargs):
            raise OSError('netsh missing')
        store = Store()
        check_lan_access(store, '0.0.0.0', 22680, run=broken, platform='nt')
        self.assertEqual(store.events, [])


if __name__ == '__main__':
    unittest.main()
