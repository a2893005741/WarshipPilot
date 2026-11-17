"""Stable launcher CLI. Bootstrap intentionally uses only the standard library.

The downloaded copy lives outside tracked source, in .warship/bootstrap.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run_git(executable, root, *args):
    trust = ['-c', 'http.sslBackend=schannel', '-c', 'http.schannelUseSSLCAInfo=false'] if os.name == 'nt' else []
    result = subprocess.run([str(executable), *trust, '-C', str(root), *args],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=180,
                            env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never'),
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Git ' + args[0] + ' 失败：' + re.sub(r'https?://\S+', '[repository]', result.stderr)[-700:])
    return result.stdout.strip()


def validate_checkout(root, executable):
    top = Path(run_git(executable, root, 'rev-parse', '--show-toplevel')).resolve()
    if top != root.resolve() or not (root / 'gui.py').is_file():
        raise ValueError('该目录不是独立的 WarshipPilot 安装')
    import tomllib
    if tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['name'] != 'warshippilot':
        raise ValueError('不能接管其他项目的仓库')


def exclude_runtime(root, executable):
    path = Path(run_git(executable, root, 'rev-parse', '--git-path', 'info/exclude'))
    if not path.is_absolute():
        path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    value = path.read_text(encoding='utf-8') if path.exists() else ''
    # Exact installation-owned paths only. Never ignore arbitrary source files.
    for rule in ('/.warship/', '/WarshipPilot.exe', '/.venv.old-*/'):
        if rule not in value.splitlines():
            value += '\n' + rule + '\n'
    path.write_text(value, encoding='utf-8')


def bootstrap(root, executable, repositories, branch='main'):
    root.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', branch) or '..' in branch:
        raise ValueError('分支格式错误')
    if (root / '.git').exists():
        validate_checkout(root, executable)
        exclude_runtime(root, executable)
        return
    if not repositories:
        raise ValueError('首次安装必须指定仓库地址')
    staging = root / '.warship' / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as temporary:
        source = Path(temporary)
        run_git(executable, source, 'init')
        last = None
        selected = None
        for repository in repositories:
            try:
                run_git(executable, source, 'fetch', '--depth', '1', '--no-tags', repository, 'refs/heads/' + branch)
                selected = repository
                break
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                last = exc
        if selected is None:
            raise RuntimeError('所有源码下载源均不可用') from last
        run_git(executable, source, 'checkout', '-B', branch, 'FETCH_HEAD')
        validate_checkout(source, executable)
        run_git(executable, source, 'remote', 'add', 'origin', selected)
        run_git(executable, source, 'config', 'remote.origin.fetch', f'+refs/heads/{branch}:refs/remotes/origin/{branch}')
        run_git(executable, source, 'update-ref', 'refs/remotes/origin/' + branch, 'HEAD')
        run_git(executable, source, 'branch', '--set-upstream-to', 'origin/' + branch, branch)
        files = run_git(executable, source, '-c', 'core.quotepath=false', 'ls-files', '-z').split('\0')
        paths = [Path(name) for name in files if name]
        for name in paths:
            target = root / name
            # Symlinks/junctions in an existing installation must not redirect writes.
            if any(p.is_symlink() or p.is_junction() for p in [target, *target.parents] if p != root.parent):
                raise ValueError('安装路径包含链接：' + str(name))
            if target.exists() and (not target.is_file() or target.read_bytes() != (source / name).read_bytes()):
                raise ValueError('已有文件与源码冲突，请先备份：' + str(name))
        installed = []
        try:
            for name in paths:
                target = root / name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / name, target)
                    installed.append(target)
            shutil.move(str(source / '.git'), str(root / '.git'))
            exclude_runtime(root, executable)
        except BaseException:
            for target in reversed(installed):
                target.unlink(missing_ok=True)
            if (root / '.git').is_dir():
                shutil.rmtree(root / '.git')
            raise


def configure(root, python, uv, git, adb):
    from module.config.config import Config
    from module.config.migration import migrate
    migrate(root)
    config = Config(root)
    value = config.deploy()
    value['Git']['Executable'] = str(git)
    value['Adb']['Executable'] = str(adb)
    value['Python'].update(Executable=str(python), Uv=str(uv))
    config.save_deploy(value)
    exclude_runtime(root, git)


def transaction_path(root):
    return root / '.warship' / 'transaction.json'


def read_transaction(root):
    path = transaction_path(root)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def recover(root):
    from deploy.git import Git
    from deploy import pip
    value = read_transaction(root)
    if not value:
        return
    git = Git(root)
    git.ensure_clean()
    current = git.run('rev-parse', 'HEAD')
    if current not in (value['previous'], value.get('target')):
        raise ValueError('源码已被其他操作改变，请保留事务记录并人工恢复')
    if current != value['previous']:
        git.run('reset', '--hard', value['previous'])
    pip.sync(root, force=True)
    transaction_path(root).unlink()


def update(root, target=None, skip_update=False):
    from deploy.git import Git
    from module.config.config import Config
    recover(root)
    git = Git(root)
    exclude_runtime(root, git.executable)
    git.ensure_clean()
    if skip_update or not Config(root).deploy()['Git']['AutoUpdate']:
        if target:
            raise ValueError('自动更新已关闭')
        return
    try:
        change = git.inspect()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        if target or (isinstance(exc, RuntimeError) and not str(exc).startswith('Git fetch ')):
            raise
        print('源码源暂时不可用，使用本地版本启动', file=sys.stderr)
        return
    if target and target != change['target']:
        raise ValueError('远端提交已改变，请重新检查更新')
    if change['current'] == change['target']:
        return
    write_json(transaction_path(root), {'previous': change['current'], 'target': change['target'], 'phase': 'updating'})
    try:
        git.run('reset', '--hard', change['target'])
    except BaseException:
        recover(root)
        raise


def sync(root):
    from deploy import adb, pip
    try:
        pip.sync(root)
        adb.check(root)
        value = read_transaction(root)
        if value:
            value['phase'] = 'awaiting-health'
            write_json(transaction_path(root), value)
    except BaseException:
        recover(root)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='舰R助手启动器入口')
    parser.add_argument('command', choices=('bootstrap', 'config', 'update', 'sync', 'commit', 'rollback'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--git', default=shutil.which('git'))
    parser.add_argument('--repository', action='append', default=[])
    parser.add_argument('--branch', default='main')
    parser.add_argument('--python')
    parser.add_argument('--uv')
    parser.add_argument('--adb')
    parser.add_argument('--target')
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.json:
        print(json.dumps({'phase': args.command, 'percent': 0}, ensure_ascii=False), flush=True)
    if args.command == 'bootstrap':
        if not args.git:
            raise ValueError('缺少 Git 可执行文件')
        bootstrap(root, args.git, args.repository, args.branch)
    else:
        sys.path.insert(0, str(root))
        from deploy.lock import instance_lock
        # The healthy GUI holds instance.lock during commit. Committing only
        # acknowledges metadata; all source/environment mutations require it.
        with (contextlib.nullcontext() if args.command == 'commit' else instance_lock(root)):
            if args.command == 'config':
                if not all((args.python, args.uv, args.git, args.adb)):
                    raise ValueError('配置必须指定 Python、uv、Git 和 ADB')
                configure(root, args.python, args.uv, args.git, args.adb)
            elif args.command == 'update':
                update(root, args.target, args.skip_update)
            elif args.command == 'sync':
                sync(root)
            elif args.command == 'rollback':
                recover(root)
            else:
                value = read_transaction(root)
                if value:
                    from deploy.git import Git
                    if value['phase'] != 'awaiting-health' or Git(root).run('rev-parse', 'HEAD') != value['target']:
                        raise ValueError('事务未同步完成，不能提交')
                    transaction_path(root).unlink()
    if args.json:
        print(json.dumps({'phase': args.command, 'percent': 100}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
