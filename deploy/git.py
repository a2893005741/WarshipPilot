"""Git operations shared by the installer and the WebUI."""
from pathlib import Path
import re
import shutil
import subprocess

from module.config.config import Config


class Git:
    def __init__(self, root):
        self.root = Path(root).resolve()
        settings = Config(self.root).deploy()['Git']
        configured = Path(settings['Executable'])
        configured = configured if configured.is_absolute() else self.root / configured
        self.executable = str(configured) if configured.is_file() else shutil.which('git')
        if not self.executable:
            raise RuntimeError('找不到 Git，请先准备 .venv/git')
        self.branch, self.remote = settings['Branch'], settings['Remote']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', self.branch) or '..' in self.branch:
            raise ValueError('更新分支格式错误')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', self.remote):
            raise ValueError('Git remote 格式错误')
        self.repository = settings.get('Repository', '')

    def run(self, *args, timeout=120):
        import os
        env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        trust = ['-c', 'http.sslBackend=schannel', '-c', 'http.schannelUseSSLCAInfo=false'] if os.name == 'nt' else []
        result = subprocess.run([self.executable, *trust, '-C', str(self.root), *args],
                                capture_output=True, encoding='utf-8', errors='replace',
                                timeout=timeout, env=env,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            # URL/user credentials must not make it into WebUI or logs.
            message = re.sub(r'https?://\S+', '[repository]', result.stderr.strip())
            raise RuntimeError('Git ' + args[0] + ' 失败：' + message[:700])
        return result.stdout.strip()

    def fetch(self):
        if self.repository:
            # A configured mirror can be used without rewriting the origin URL.
            self.run('fetch', '--no-tags', self.repository,
                     f'+refs/heads/{self.branch}:refs/remotes/{self.remote}/{self.branch}')
        else:
            self.run('fetch', '--no-tags', self.remote,
                     f'+refs/heads/{self.branch}:refs/remotes/{self.remote}/{self.branch}')
        return self.run('rev-parse', f'refs/remotes/{self.remote}/{self.branch}')

    def ensure_clean(self):
        # Untracked files in program paths could be destroyed by reset --hard too.
        if self.run('status', '--porcelain', '--untracked-files=all'):
            raise ValueError('仓库有未提交的修改或未跟踪文件，请先提交或移走再更新')

    def inspect(self):
        target = self.fetch()
        current = self.run('rev-parse', 'HEAD')
        branch = self.run('branch', '--show-current')
        if branch != self.branch:
            raise ValueError(f'当前分支 {branch} 与更新分支 {self.branch} 不一致')
        if self.run('merge-base', current, target) != current:
            raise ValueError('本地提交与更新源分叉，不能自动覆盖')
        commits = self.run('log', '--format=%H%x09%cs%x09%s', f'{current}..{target}', '--')
        entries = [dict(zip(('sha', 'date', 'subject'), line.split('\t', 2)))
                   for line in commits.splitlines() if line]
        return {'current': current, 'target': target, 'branch': self.branch, 'commits': entries}

    def apply(self, target=None):
        self.ensure_clean()
        change = self.inspect()
        if target and target != change['target']:
            raise ValueError('远端提交已改变，请重新检查更新')
        self.run('reset', '--hard', change['target'])
        return change
