"""Real WebUI updater -> launcher WS -> stop/update/rollback/restart integration."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True, help='Fixture produced by check-warship-launcher.py')
    parser.add_argument('--launcher', type=Path, required=True)
    args = parser.parse_args()
    base = args.base.resolve()
    live = base / 'live'
    import yaml
    config = yaml.safe_load((live / 'config/deploy.yaml').read_text(encoding='utf-8'))
    port = config['WebUI']['Port']
    headers = {'Authorization': 'Bearer ' + config['WebUI']['AccessCode'], 'Content-Type': 'application/json'}

    def call(path, body=None):
        request = urllib.request.Request(f'http://127.0.0.1:{port}/' + path,
                                         data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def wait(check, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = check()
                if value:
                    return value
            except OSError:
                pass
            time.sleep(.25)
        raise RuntimeError('Timed out; inspect native-update.log and fixture log directory')

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(base / 'http')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    manifest = json.loads((base / 'stable.json').read_text())
    manifest.update(version='3.0.7', platforms={'windows-x86_64': {'url': 'https://example.invalid/unused.exe', 'sha256': 'a' * 64}})
    (base / 'http/stable.json').write_text(json.dumps(manifest), encoding='utf-8')
    env = dict(os.environ, AZURPILOT_REPO_DIR=str(live),
               AZURPILOT_STABLE_MANIFEST=f'http://127.0.0.1:{server.server_port}/stable.json')
    log = (base / 'native-update.log').open('w', encoding='utf-8')
    process = subprocess.Popen([str(args.launcher.resolve()), '--start-minimized', '--skip-update'],
                               env=env, stdout=log, stderr=log,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        before = wait(lambda: call('health'))
        change = call('api/update-check', {})
        assert change['state'] == 'available', change
        # The previous smoke pushed a GUI that intentionally fails on startup.
        requested = call('api/update-install', {})
        assert requested['state'] in ('waiting', 'restarting'), requested
        def restarted():
            health = call('health')
            if health['pid'] != before['pid']:
                return health
            state = call('api/state')['update']
            if state['state'] == 'error':
                raise RuntimeError(state['error'])
            return None
        after = wait(restarted)
        assert after['commit'] == before['commit'], after
        assert not (live / '.warship/transaction.json').exists()
        result = {'ok': True, 'beforePid': before['pid'], 'afterPid': after['pid'],
                  'restoredCommit': after['commit'], 'delegatedWebUpdate': True}
        (base / 'native-update-acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        server.shutdown()
        log.close()


if __name__ == '__main__':
    main()
