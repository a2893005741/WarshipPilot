"""Warn when the WebUI listens on the LAN but Windows Firewall has no rule for it.

The launcher and backend run as the desktop user and cannot add firewall rules;
an unanswered Windows prompt even leaves Block rules for the interpreter. The
port rule comes from scripts/allow-lan-access.ps1 (administrator) or the remote
migration/deploy scripts. Reading rules needs no elevation.
"""
import os
import subprocess

RULE_DISPLAY_NAME = 'WarshipPilot WebUI (LAN)'
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


def lan_rule_present(run=subprocess.run):
    """True / False, or None when the firewall could not be queried."""
    try:
        result = run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', f'name={RULE_DISPLAY_NAME}'],
                     capture_output=True, timeout=15,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def check_lan_access(store, host, port, run=subprocess.run, platform=os.name):
    if platform != 'nt' or str(host).strip() in LOOPBACK:
        return
    if lan_rule_present(run) is False:
        store.event(f'局域网可能无法访问控制台：Windows 防火墙没有放行端口 {port}。'
                    '请以管理员身份运行 scripts\\allow-lan-access.ps1（只允许本地子网）。', 'warning')
