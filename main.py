"""Windows directory-release entry point; works from Chinese paths."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import webbrowser

import uvicorn

from backend.api import create_app
from backend.runtime import Runtime
from backend.store import atomic_json


def main():
    parser = argparse.ArgumentParser(description="舰R助手 · 原生远征与原脚本出征")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=22680)
    default_data = (Path(sys.executable).resolve().parent.parent / "WarshipPilot-data") if getattr(sys, "frozen", False) else Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "WarshipPilot"
    parser.add_argument("--data-dir", type=Path, default=default_data)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    auth_file = args.data_dir / "access.json"
    lock_file = (args.data_dir / "instance.lock").open("a+b")
    # Windows byte-range locks also prohibit reads by the second process.
    if os.fstat(lock_file.fileno()).st_size == 0:
        lock_file.write(b"0")
        lock_file.flush()
    lock_file.seek(0)
    import msvcrt
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        for _ in range(30):
            if auth_file.exists():
                break
            threading.Event().wait(0.1)
        key = json.loads(auth_file.read_text(encoding="utf-8"))["key"]
        url = f"http://127.0.0.1:{args.port}/#key={key}"
        if not args.no_browser:
            webbrowser.open(url)
        return
    if not auth_file.exists():
        atomic_json(auth_file, {"key": secrets.token_urlsafe(24)})
    key = json.loads(auth_file.read_text(encoding="utf-8"))["key"]
    url = f"http://127.0.0.1:{args.port}/#key={key}"
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    runtime = Runtime(args.data_dir, resources)
    server = None

    def shutdown():
        if server:
            server.should_exit = True

    from backend.updater import Updater
    runtime.updater = Updater(args.data_dir, {"port": args.port, "argv": sys.argv[1:]},
                              busy=lambda: runtime.automation.busy or runtime.automation.scheduler
                              or runtime.benchmark["running"],
                              shutdown=shutdown, event=runtime.store.event)
    runtime.updater.start_auto_check(runtime.stop_event)
    app = create_app(runtime, key, shutdown)
    # websockets-sansio is not required; use uvicorn's wsproto backend.
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, access_log=False, log_config=None, ws="wsproto"))
    (args.data_dir / "console-url.txt").write_text(url, encoding="utf-8")

    def open_when_ready():
        for _ in range(100):
            if server.started:
                webbrowser.open(url)
                return
            if server.should_exit:
                return
            threading.Event().wait(0.1)

    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        server.run()
    finally:
        runtime.close()
        lock_file.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        log = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "WarshipPilot" / "startup-error.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if getattr(sys, "frozen", False) and "--no-browser" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"启动失败，详情已保存到：\n{log}", "舰R助手", 0x10)
        else:
            raise
