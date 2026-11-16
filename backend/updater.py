"""Built-in update from GitHub Releases.

check()   -> latest release of the configured repository vs. VERSION
install() -> download the win-x64 zip asset, verify its SHA-256 (GitHub asset
             digest), extract next to the data, then hand over to a detached
             PowerShell script and shut the backend down. The script waits for
             this process to exit, swaps the program folder (keeping a backup),
             starts the new EXE with the same arguments and checks /health for
             the new version; on failure it restores the backup and restarts
             the old version. The data folder is never touched.

A private repository needs a read-only token (fine-grained, Contents: read on
that repository). It is stored only in <data>/update.json and never returned
by the API.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import zipfile

import requests

from .store import atomic_json, now
from .version import VERSION

DEFAULT_REPO = 'a2893005741/WarshipPilot'
ASSET_PATTERN = re.compile(r'^WarshipPilot-(\d+\.\d+\.\d+)-win-x64\.zip$')
API = os.getenv('WARSHIPPILOT_UPDATE_API', 'https://api.github.com')  # override only for local update tests


def parse_version(text):
    match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)$', str(text).strip())
    return tuple(int(x) for x in match.groups()) if match else None


APPLY_SCRIPT = r'''param([int]$OldPid, [string]$Live, [string]$Stage, [string]$Backup, [string]$Failed,
      [string]$Exe, [string]$ArgsB64, [string]$Health, [string]$Expected, [string]$Log)
$ErrorActionPreference = 'Stop'
function Note($text) { Add-Content -LiteralPath $Log -Value ("{0:s} {1}" -f (Get-Date), $text) -Encoding UTF8 }
Note "updater started (target $Expected)"
# Never sit inside the program folder: a process's current directory blocks renaming it.
Set-Location -LiteralPath (Split-Path -Parent $Log)
function Move-Retry($from, $to) {
    for ($i = 0; $i -lt 30; $i++) {
        try { Move-Item -LiteralPath $from -Destination $to; return } catch { Start-Sleep -Seconds 1 }
    }
    Move-Item -LiteralPath $from -Destination $to
}
$arguments = @()
function Start-App {
    if ($arguments.Count) { Start-Process -FilePath $Exe -ArgumentList $arguments -WorkingDirectory $Live }
    else { Start-Process -FilePath $Exe -WorkingDirectory $Live }
}
try {
    # Arguments travel as base64 JSON: no quoting through the Windows command line.
    $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgsB64))
    $arguments = @((ConvertFrom-Json $json) | ForEach-Object { [string]$_ })
    Note "waiting for pid $OldPid"
    $old = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
    if ($old -and !$old.WaitForExit(60000)) { throw 'old process did not exit' }
    Start-Sleep -Milliseconds 500
    Move-Retry $Live $Backup
    Move-Retry $Stage $Live
    Note "swapped; starting new version"
    Start-App
    $ok = $false
    for ($i = 0; $i -lt 120; $i++) {
        try { $h = Invoke-RestMethod -Uri $Health -TimeoutSec 1; if ($h.version -eq $Expected) { $ok = $true; break } } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (!$ok) { throw "new version did not report $Expected" }
    Note "update to $Expected healthy"
} catch {
    Note "update failed: $_"
    try {
        Get-Process | Where-Object { $_.Path -eq $Exe } | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $Backup) {
            if (Test-Path -LiteralPath $Live) { Move-Retry $Live $Failed }
            Move-Retry $Backup $Live
        }
        Start-App
        Note "rolled back and restarted previous version"
    } catch { Note "rollback failed: $_" }
}
'''


class Updater:
    def __init__(self, data: Path, launch: dict, busy, shutdown, event):
        self.data, self.launch = data, launch
        self.busy, self.shutdown, self.event = busy, shutdown, event
        self.file = data / 'update.json'
        self.status = {'state': 'idle', 'progress': '', 'error': '', 'latest': None, 'checked': ''}
        self.lock = threading.Lock()

    # --- settings ---------------------------------------------------------------
    def settings(self):
        try:
            saved = json.loads(self.file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        return {'repo': saved.get('repo') or DEFAULT_REPO, 'token': saved.get('token', ''),
                'auto_check': saved.get('auto_check', True)}

    def save_settings(self, repo=None, token=None, auto_check=None):
        current = self.settings()
        if repo is not None:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
                raise ValueError('仓库格式应为 用户名/仓库名')
            current['repo'] = repo
        if token is not None:  # empty string clears it
            current['token'] = token.strip()
        if auto_check is not None:
            current['auto_check'] = bool(auto_check)
        atomic_json(self.file, current)
        return self.state()

    def state(self):
        s = self.settings()
        return {'version': VERSION, 'repo': s['repo'], 'has_token': bool(s['token']), 'auto_check': s['auto_check'],
                'frozen': bool(getattr(sys, 'frozen', False)), **self.status}

    # --- GitHub -------------------------------------------------------------------
    def _headers(self, accept='application/vnd.github+json'):
        headers = {'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'WarshipPilot-updater'}
        token = self.settings()['token']
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def check(self):
        repo = self.settings()['repo']
        with self.lock:
            self.status.update(state='checking', error='')
        try:
            r = requests.get(f'{API}/repos/{repo}/releases/latest', headers=self._headers(), timeout=20)
            if r.status_code == 404:
                raise ValueError('找不到发布版本：仓库为私有时请填写只读访问令牌，或仓库还没有 Release')
            if r.status_code == 401:
                raise ValueError('访问令牌无效或已过期')
            r.raise_for_status()
            release = r.json()
            asset = next((a for a in release.get('assets', []) if ASSET_PATTERN.match(a['name'])), None)
            tag = release.get('tag_name', '')
            latest = {'tag': tag, 'version': tag.lstrip('v'), 'name': release.get('name') or tag,
                      'notes': (release.get('body') or '')[:4000], 'published': release.get('published_at', ''),
                      'asset': None if asset is None else {
                          'id': asset['id'], 'name': asset['name'], 'size': asset['size'],
                          'digest': asset.get('digest') or ''}}
            newer = parse_version(tag) is not None and parse_version(tag) > parse_version(VERSION)
            with self.lock:
                self.status.update(state='available' if newer and asset else 'current', latest=latest,
                                   checked=now(), error='' if asset or not newer else '该版本没有 win-x64 压缩包')
        except Exception as exc:
            with self.lock:
                self.status.update(state='error', error=str(exc)[:300], checked=now())
        return self.state()

    # --- install ------------------------------------------------------------------
    def install(self):
        if not getattr(sys, 'frozen', False):
            raise ValueError('开发模式（源码运行）不支持内置更新，请使用 git pull')
        if self.busy():
            raise ValueError('任务、调度器或测试运行中，请先停止再更新')
        if self.status['state'] != 'available':
            raise ValueError('没有可安装的新版本，请先检查更新')
        with self.lock:
            self.status.update(state='downloading', progress='0%', error='')
        threading.Thread(target=self._install, name='updater', daemon=True).start()
        return self.state()

    def _install(self):
        latest = self.status['latest']
        asset = latest['asset']
        folder = self.data / 'updates'
        folder.mkdir(exist_ok=True)
        archive = folder / asset['name']
        stage = folder / f'stage-{latest["version"]}'
        try:
            repo = self.settings()['repo']
            url = f'{API}/repos/{repo}/releases/assets/{asset["id"]}'
            digest = hashlib.sha256()
            with requests.get(url, headers=self._headers('application/octet-stream'), stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get('Content-Length') or asset['size'] or 0)
                done = 0
                with open(archive, 'wb') as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if total:
                            self.status['progress'] = f'{done * 100 // total}%'
            expected = asset['digest'].removeprefix('sha256:')
            if expected and digest.hexdigest() != expected:
                raise ValueError('下载文件校验失败（SHA-256 不一致）')
            self.status.update(state='extracting', progress='')
            if stage.exists():
                shutil.rmtree(stage)
            with zipfile.ZipFile(archive) as z:
                for member in z.namelist():
                    target = (stage / member).resolve()
                    if not str(target).startswith(str(stage.resolve())):
                        raise ValueError('压缩包包含非法路径')
                z.extractall(stage)
            if not (stage / 'WarshipPilot.exe').is_file():
                raise ValueError('压缩包里没有 WarshipPilot.exe')
            if self.busy():
                raise ValueError('下载期间有任务启动，已取消安装')
            self._handover(stage, latest['version'])
        except Exception as exc:
            with self.lock:
                self.status.update(state='error', error=str(exc)[:300], progress='')
            self.event(f'更新失败：{exc}', 'warning')

    def _handover(self, stage, version):
        live = Path(sys.executable).resolve().parent
        from datetime import datetime
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')  # local time, readable in Explorer
        backup = live.with_name(f'{live.name}-backup-{stamp}')
        failed = live.with_name(f'{live.name}-failed-{stamp}')
        # Stage must be on the same volume as the program folder for a rename.
        if os.path.splitdrive(str(stage.resolve()))[0].lower() != os.path.splitdrive(str(live))[0].lower():
            moved = live.with_name(f'{live.name}-stage-{stamp}')
            shutil.move(str(stage), str(moved))
            stage = moved
        script = self.data / 'updates' / 'apply-update.ps1'
        script.write_text(APPLY_SCRIPT, encoding='utf-8-sig')
        log = self.data / 'updates' / 'update.log'
        import base64
        args = base64.b64encode(json.dumps(self.launch.get('argv', [])).encode()).decode()
        health = f'http://127.0.0.1:{self.launch.get("port", 22680)}/health'
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                          '-OldPid', str(os.getpid()), '-Live', str(live), '-Stage', str(stage),
                          '-Backup', str(backup), '-Failed', str(failed), '-Exe', str(live / 'WarshipPilot.exe'),
                          '-ArgsB64', args, '-Health', health, '-Expected', version, '-Log', str(log)]
        # CREATE_NO_WINDOW | NEW_PROCESS_GROUP. Not DETACHED_PROCESS: powershell.exe
        # silently does nothing without a console.
        flags = 0x08000000 | 0x00000200
        try:
            # Leave the parent's job object (scheduled task / console) so the
            # updater survives this process exiting.
            subprocess.Popen(command, creationflags=flags | 0x01000000, close_fds=True, cwd=log.parent)
        except OSError:
            subprocess.Popen(command, creationflags=flags, close_fds=True, cwd=log.parent)
        self._prune_backups(live)
        with self.lock:
            self.status.update(state='restarting', progress='')
        self.event(f'更新 v{version} 已就绪，后台即将重启（旧版本备份为 {backup.name}）')
        self.shutdown()

    @staticmethod
    def _prune_backups(live, keep=2):
        backups = sorted(live.parent.glob(f'{live.name}-backup-*'))
        for old in backups[:-keep] if len(backups) > keep else []:
            shutil.rmtree(old, ignore_errors=True)

    def start_auto_check(self, stop_event, interval=6 * 3600):
        def loop():
            while not stop_event.wait(15 if not self.status['checked'] else interval):
                if self.settings()['auto_check'] and self.status['state'] in ('idle', 'current', 'error', 'available'):
                    self.check()
        threading.Thread(target=loop, name='update-check', daemon=True).start()
