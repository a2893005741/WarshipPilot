"""Source WebUI entry point; all user state stays outside tracked files."""
import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import traceback
import webbrowser

import uvicorn

from alas import Runtime
from deploy.lock import instance_lock
from module.config.config import Config
from module.config.migration import migrate
from module.webui.api import create_app
from module.webui.updater import Updater

APP_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="舰R助手")
    parser.add_argument('--root', type=Path, default=APP_DIR)
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    with instance_lock(root):
        migrated = migrate(root)
        config = Config(root)
        deployment = config.deploy()['WebUI']
        host, port = args.host or deployment['Host'], args.port or deployment['Port']
        key = deployment['AccessCode']
        url = f'http://127.0.0.1:{port}/#key={key}'
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'端口 {port} 已被占用，请先退出旧后台')
        runtime = Runtime(root, APP_DIR)
        from deploy.git import Git
        runtime.commit = Git(APP_DIR).run('rev-parse', 'HEAD')
        if migrated:
            runtime.store.event(f'已复制旧数据 {migrated}；旧目录保留')
        server = None

        def shutdown():
            if server:
                server.should_exit = True

        def quiesce(value):
            with runtime.io_lock, runtime.lock:
                runtime.automation.update_pending = value
                runtime.automation.save_due()
            runtime.wake.set()

        argv = ['--no-browser']
        if args.host:
            argv += ['--host', args.host]
        if args.port:
            argv += ['--port', str(args.port)]
        runtime.updater = Updater(root, {'port': port, 'argv': argv},
            busy=lambda: runtime.automation.busy or runtime.benchmark['running'],
            shutdown=shutdown, event=runtime.store.event, quiesce=quiesce,
            stop_event=runtime.stop_event)
        runtime.updater.start_auto_check(runtime.stop_event)
        app = create_app(runtime, key, shutdown)
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port,
            access_log=False, log_config=None, ws='wsproto'))
        (root / 'log' / 'console-url.txt').write_text(url, encoding='utf-8')

        def open_when_ready():
            while not runtime.stop_event.wait(0.1):
                if server.started:
                    webbrowser.open(url)
                    return
                if server.should_exit:
                    return

        if not args.no_browser:
            threading.Thread(target=open_when_ready, daemon=True).start()
        try:
            server.run()
        finally:
            runtime.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        folder = APP_DIR / 'log'
        folder.mkdir(exist_ok=True)
        (folder / 'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
