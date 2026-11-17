"""Exercise the real Rust launcher in a disposable installation, without Android input."""
import argparse
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT,
                                   encoding='utf-8').strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launcher', type=Path, default=ROOT.parent / 'WarshipLauncher/target/debug/warshippilot-launcher.exe')
    parser.add_argument('--tools', type=Path, default=ROOT / '.runtime-stage/portable/.venv')
    parser.add_argument('--base', type=Path)
    parser.add_argument('--reuse', action='store_true')
    args = parser.parse_args()
    base = (args.base or ROOT / '.deployment' / ('launcher-smoke-' + time.strftime('%Y%m%d-%H%M%S'))).resolve()
    source, live, http = (base / name for name in ('source', 'live', 'http'))
    remote = base / 'remote.git'
    if not args.reuse:
        base.mkdir(parents=True, exist_ok=True)
        source, live, http = (base / name for name in ('source', 'live', 'http'))
        for folder in (source, live, http):
            folder.mkdir()
        # Include the current implementation, without committing the user's working tree.
        files = git(ROOT, '-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')
        for name in set(files):
            path = ROOT / name
            if name and path.is_file():
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        git(source, 'init', '-b', 'main')
        git(source, 'config', 'user.email', 'launcher-test@example.invalid')
        git(source, 'config', 'user.name', 'Launcher smoke')
        git(source, 'add', '.')
        git(source, 'commit', '-m', 'Launcher integration fixture')
        previous = git(source, 'rev-parse', 'HEAD')
        remote = base / 'remote.git'
        subprocess.run(['git', 'clone', '--bare', str(source), str(remote)], check=True, capture_output=True)
        git(source, 'remote', 'add', 'origin', str(remote))
    previous = git(source, 'rev-parse', 'HEAD')

    class Server(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Server, directory=str(http)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_port}'
    components = []
    for name in ('git', 'adb'):
        package = http / (name + '.zip')
        if not package.exists():
            with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in (args.tools / name).rglob('*'):
                    if path.is_file():
                        archive.write(path, f'.warship/tools/{name}/' + path.relative_to(args.tools / name).as_posix())
        components.append({'id': name, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                           'size': package.stat().st_size, 'urls': [address + '/missing.zip', address + '/' + name + '.zip']})
    names = ['deploy/launcher.py', 'config/deploy.template.yaml']
    hashes = {}
    for name in names:
        target = http / 'raw' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        bad = http / 'badraw' / name
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text('corrupt primary response')
    manifest = {'runtime': {'schema': 2, 'revision': previous, 'platforms': {'windows-x86_64': components},
                            'deploy': {'bases': [address + '/badraw', address + '/raw'], 'files': names, 'hashes': hashes}}}
    manifest_path = base / 'stable.json'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    (live / 'config').mkdir(exist_ok=True)
    # yaml is valid JSON as well. No package imports are needed to configure the fixture.
    deployment = {'Git': {'Repository': str(remote)}, 'WebUI': {'Port': port, 'AccessCode': 'fixture-access'},
                  'Update': {'AutoCheck': False}, 'Fixture': {'preserved': True}}
    (live / 'config/deploy.yaml').write_text(json.dumps(deployment), encoding='utf-8')
    scheduler = {'schema_version': 2, 'Scheduler': {'Enable': False, 'NextRun': {}}, 'Tasks': {}}
    (live / 'config/warship.json').write_text(json.dumps(scheduler), encoding='utf-8')
    env = dict(os.environ, AZURPILOT_REPO_DIR=str(live), WARSHIP_TEST_MANIFEST=str(manifest_path),
               WARSHIP_TEST_REPOSITORY=str(remote))
    results = []

    def run(label, *options, expect_success=True):
        started = time.monotonic()
        log = base / (label + '.log')
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run([str(args.launcher.resolve()), '--verify-install', *options],
                                     env=env, stdout=stream, stderr=stream, timeout=900,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if (process.returncode == 0) != expect_success:
            raise RuntimeError(f'{label}: exit {process.returncode}; inspect {log}')
        results.append({'case': label, 'exit': process.returncode, 'seconds': round(time.monotonic() - started, 1)})
        print(json.dumps(results[-1]), flush=True)

    try:
        run('fresh')
        assert (live / 'gui.py').is_file()
        assert (live / '.warship/tools/git/cmd/git.exe').is_file()
        assert (live / '.warship/bootstrap/deploy/launcher.py').is_file()
        assert not (live / '.warship/transaction.json').exists()
        state_before = (live / 'config/warship.json').read_bytes()
        python_time = (live / '.venv/Scripts/python.exe').stat().st_mtime_ns
        run('restart', '--skip-update')
        assert (live / '.venv/Scripts/python.exe').stat().st_mtime_ns == python_time
        assert (live / 'config/warship.json').read_bytes() == state_before
        run('repair', '--repair')
        assert list((live / '.warship/backups').glob('environment-*/.venv'))
        assert (live / 'config/warship.json').read_bytes() == state_before
        # A foreign process's listening port must remain open and untouched.
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1', port))
            foreign.listen()
            run('foreign-port', expect_success=False)
            assert foreign.getsockname()[1] == port
        # A real pushed revision that cannot start must be rolled back and healthy.
        (source / 'gui.py').write_text("raise RuntimeError('intentional launcher rollback fixture')\n")
        git(source, 'add', 'gui.py')
        git(source, 'commit', '-m', 'Fixture that cannot start')
        git(source, 'push', 'origin', 'main')
        run('bad-update')
        assert git(live, 'rev-parse', 'HEAD') == previous
        report = json.loads((live / 'log/launcher-verification.json').read_text())
        assert report['recovered'] is True
        assert not report['transactionPending']
        assert (live / 'config/warship.json').read_bytes() == state_before
        import yaml
        saved = yaml.safe_load((live / 'config/deploy.yaml').read_text(encoding='utf-8'))
        assert saved['WebUI']['AccessCode'] == 'fixture-access'
        assert saved['Fixture']['preserved'] is True
        (base / 'acceptance.json').write_text(json.dumps({'ok': True, 'cases': results, 'root': str(live)}, indent=2), encoding='utf-8')
        print('Acceptance: ' + str(base / 'acceptance.json'), flush=True)
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
