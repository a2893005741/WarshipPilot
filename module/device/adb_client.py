"""ADB is always executed as an argument array; screenshot bytes never cross a shell."""
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import cv2
import numpy as np
from PIL import Image

from module.base.nemu_ipc import NemuIpcImpl

GAME_PACKAGE = "com.huanmeng.zhanjian2"
OLD_PACKAGE = "com.mcmpnknkmcmlmkno.shipwarrliverfree"


def find_adb(root: Path) -> str:
    candidates = [str(root / ".venv" / "adb" / "adb.exe"), str(root / "adb" / "adb.exe"), os.getenv("WARSHIPPILOT_ADB", ""),
                  r"D:\MuMu\MuMuPlayer\nx_main\adb.exe", r"C:\adb\adb.exe", shutil.which("adb")]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise RuntimeError("没有找到 ADB，请在设备页填写 MuMu 的 adb.exe 完整路径")


class Adb:
    def __init__(self, path: str):
        self.path = path
        self.input_checked = 0.
        self.ipc = None
        self.ipc_failed = ''

    def run(self, *args: str, timeout: float = 15) -> bytes:
        result = subprocess.run([self.path, *args], capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip()[:500] or "ADB 执行失败")
        return result.stdout

    def shell(self, serial: str, *args: str) -> str:
        return self.run("-s", serial, "shell", *args).decode("utf-8", errors="replace").strip()

    def ensure_input_ready(self, serial):
        # Any connected instance may receive input, but only while the game is
        # in front and no other automation (old script / probes) runs on it.
        if time.monotonic()-self.input_checked<2:
            return
        activity=self.shell(serial,'dumpsys','activity','activities')
        if not any(GAME_PACKAGE+'/' in line for line in activity.splitlines() if 'ResumedActivity' in line):
            raise RuntimeError('舰R不在前台，已停止输入')
        processes=self.shell(serial,'ps','-A','-o','ARGS')
        if OLD_PACKAGE in processes or 'frida-server' in processes:
            raise RuntimeError('旧脚本或提取工具仍在运行，不能同时接管输入')
        self.input_checked=time.monotonic()

    def click(self, serial, x, y):
        # Adapted from ALAS Adb.click_adb: input is not retried after an ambiguous failure.
        self.shell(serial,'input','tap',str(int(x)),str(int(y)))

    def swipe(self, serial, x1, y1, x2, y2, duration):
        # Adapted from ALAS Adb.swipe_adb, milliseconds retained from original SWIPEEX.
        self.shell(serial,'input','swipe',*[str(int(v)) for v in (x1,y1,x2,y2,duration)])

    def discover(self) -> list[dict]:
        devices = []
        for line in self.run("devices", "-l").decode("utf-8", errors="replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            item = {"serial": parts[0], "state": parts[1], "detail": " ".join(parts[2:]), "game_installed": False}
            if parts[1] == "device":
                try:
                    item["game_installed"] = ("package:" + GAME_PACKAGE) in self.shell(parts[0], "pm", "list", "packages", GAME_PACKAGE).splitlines()
                    item["size"] = self.shell(parts[0], "wm", "size")
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    item["error"] = str(exc)
            devices.append(item)
        return devices

    def connect(self, serial: str) -> str:
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", serial) or not 1 <= int(serial.split(":")[1]) <= 65535:
            raise ValueError("请填写本机 MuMu 地址，例如 127.0.0.1:16416")
        return self.run("connect", serial).decode("utf-8", errors="replace").strip()

    def profile(self, serial: str) -> dict:
        packages = self.shell(serial, "pm", "list", "packages", GAME_PACKAGE)
        if ("package:" + GAME_PACKAGE) not in packages.splitlines():
            raise ValueError("这个实例没有安装战舰少女R，请选择舰R实例")
        activity = self.shell(serial, "dumpsys", "activity", "activities")
        resumed = [line.strip() for line in activity.splitlines() if "ResumedActivity" in line]
        package = self.shell(serial, "dumpsys", "package", GAME_PACKAGE)
        version = re.search(r"versionName=(.*)", package)
        # pidof returns exit status 1 when the legacy app is stopped.
        try:
            legacy = self.shell(serial, "pidof", OLD_PACKAGE)
        except RuntimeError:
            legacy = ""
        return {"serial": serial, "package": GAME_PACKAGE, "version": version.group(1).strip() if version else "未读取",
                "android_size": self.shell(serial, "wm", "size"), "foreground": resumed,
                "game_foreground": any(GAME_PACKAGE + "/" in line for line in resumed),
                "legacy_running": bool(legacy), "model": self.shell(serial, "getprop", "ro.product.model")}

    def screenshot(self, serial: str) -> tuple[bytes, dict]:
        start = time.monotonic()
        if serial=='127.0.0.1:16416' and not self.ipc_failed:
            try:
                if self.ipc is None:
                    folder=os.getenv('WARSHIPPILOT_MUMU',r'D:\MuMu\MuMuPlayer')
                    self.ipc=NemuIpcImpl(folder,NemuIpcImpl.serial_to_id(serial),display_id=0)
                capture_started=time.monotonic()
                rgba=self.ipc.screenshot(timeout=2)
                capture_ms=round((time.monotonic()-capture_started)*1000,1)
                # Same color conversion and vertical flip as ALAS screenshot_nemu_ipc.
                bgr=cv2.flip(cv2.cvtColor(rgba,cv2.COLOR_RGBA2BGR),0)
                height,width=bgr.shape[:2]
                if (width,height)!=(1280,720):
                    raise RuntimeError(f'IPC画面尺寸不是1280×720：{width}×{height}')
                ok,png=cv2.imencode('.png',bgr,[cv2.IMWRITE_PNG_COMPRESSION,1])
                if not ok:raise RuntimeError('IPC图像编码失败')
                return png.tobytes(),{'width':width,'height':height,'backend':'nemu_ipc',
                                     'capture_ms':capture_ms,'latency_ms':round((time.monotonic()-start)*1000)}
            except Exception as exc:
                self.ipc_failed=str(exc)[:300]
        raw = self.run("-s", serial, "exec-out", "screencap", "-p", timeout=20)
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            width, height = im.size
        return raw, {"width": width, "height": height, "backend":"adb_png", "ipc_error":self.ipc_failed,
                     "latency_ms": round((time.monotonic() - start) * 1000)}

    def close(self):
        if self.ipc:
            try:self.ipc.disconnect()
            except Exception:pass
            self.ipc=None
