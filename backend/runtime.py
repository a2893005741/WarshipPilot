"""Device frames and original-script execution share a single device I/O owner."""
from copy import deepcopy
import hashlib
import io
import json
import re
from pathlib import Path
import threading
import time
import uuid
import zipfile

import cv2
import numpy as np
from PIL import Image

from .device import Adb, find_adb
from .version import VERSION
from .store import Store, atomic_json, now
from .legacy import ColorProfile, LegacyVision
from .automation import TaskController

SCREENSHOT_DEFAULT, CONTROL_DEFAULT = 'nemu_ipc', 'ADB'  # the pair verified live in v0.4


class FrameRecord(dict):
    """Frame metadata; the PNG is encoded from the RGB frame only when someone reads it."""

    def __init__(self, rgb=None, png=None, **meta):
        super().__init__(meta)
        self.rgb, self._png = rgb, png

    def __getitem__(self, key):
        if key == 'png':
            if self._png is None:
                ok, data = cv2.imencode('.png', cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR),
                                        [cv2.IMWRITE_PNG_COMPRESSION, 1])
                if not ok:
                    raise RuntimeError('截图编码失败')
                self._png = data.tobytes()
            return self._png
        return super().__getitem__(key)


LABELS = ("母港", "出征选择", "关卡选择", "舰队准备", "地图节点", "索敌", "阵型", "战斗", "夜战", "结算", "远征", "战役", "演习", "修理", "补给", "弹窗", "未分类")


class Runtime:
    def __init__(self, data: Path, resources: Path):
        self.store = Store(data)
        self.resources = resources
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        config = data / "config.json"
        self.config = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {"schema_version": 1, "serial": "", "interval": 3, "adb_path": ""}
        self.config.setdefault('screenshot_method', SCREENSHOT_DEFAULT)
        self.config.setdefault('control_method', CONTROL_DEFAULT)
        self.config.setdefault('mumu_path', '')
        self.emulator = None
        self.emulator_error = ''
        self.updater = None  # set by main.py (needs the server's shutdown hook)
        # AzurPilot connects to the configured emulator on start; so do we.
        self.auto_connect_enabled = True
        self.next_connect = 0.0
        self.connect_error = ''
        self.benchmark = {'running': False, 'kind': '', 'progress': '', 'results': {}, 'error': ''}
        self.legacy = LegacyVision(resources / "assets" / "legacy")
        self.color_profile = ColorProfile.model_validate(self.config.get("color_profile", {}))
        self.color_observing = bool(self.config.get("color_observing", False))
        self.legacy_result = None
        try:
            self.adb = Adb(self.config.get("adb_path") or find_adb(resources))
            self.setup_error = ""
        except RuntimeError as exc:
            self.adb = None
            self.setup_error = str(exc)
        self.frame = None
        self.recent_frames = {}
        self.profile = None
        self.serial = ""  # Re-select and recheck the device after every process restart.
        self.status = "idle"
        self.error = self.setup_error
        self.recognition = {"label": "未分类", "score": None}
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.sequence = 0
        self.failures = 0
        self.session = None
        self.session_last_hash = ""
        self.session_last_time = 0.0
        self.session_count = 0
        self.automation = TaskController(self)
        self.thread = threading.Thread(target=self._loop, name="frame-acquisition", daemon=True)
        self.store.event(f"舰R助手 v{VERSION} 已启动 · 原生远征 · 原脚本出征")
        self.thread.start()

    def state(self):
        with self.lock:
            return {"version": VERSION, "status": self.status, "error": self.error, "serial": self.serial,
                    "legacy": {"profile": self.color_profile.model_dump(), "observing": self.color_observing,
                               "result": deepcopy(self.legacy_result), "stats": self.legacy.catalog["stats"]},
                    "last_serial": self.config.get("serial", ""), "adb_path": self.adb.path if self.adb else "",
                    "frame": {k: v for k, v in self.frame.items() if k != "png"} if self.frame else None,
                    "profile": deepcopy(self.profile), "recognition": self.recognition, "session": deepcopy(self.session),
                    "automation": self.automation.state(),
                    "session_count": self.session_count, "labels": LABELS, "read_only": False,
                    "device": self.device_state(), "connect_error": self.connect_error,
                    "update": self.updater.state() if self.updater else None,
                    "samples_count": len(self.store.samples())}

    def discover(self, path=""):
        with self.io_lock:
            if path:
                if self.serial:
                    raise ValueError("先断开当前设备，再切换 ADB")
                if not Path(path).is_file() or Path(path).name.lower() != "adb.exe":
                    raise ValueError("请填写已存在的 adb.exe 完整路径")
                self.adb = Adb(path)
                self.config["adb_path"] = path
                atomic_json(self.store.root / "config.json", self.config)
            if not self.adb:
                raise ValueError(self.setup_error)
            devices = self.adb.discover()
        self.store.event(f"设备发现完成：{len(devices)} 个安卓实例")
        return devices

    def select(self, serial: str):
        self.auto_connect_enabled = True
        with self.io_lock:
            if self.automation.busy:
                raise ValueError('请先停止当前任务，再切换设备')
            if not self.adb:
                raise ValueError(self.setup_error)
            devices = self.adb.discover()
            if not any(d["serial"] == serial and d["game_installed"] and d["state"] == "device" for d in devices):
                raise ValueError(f"{serial} 不在线或没有安装战舰少女R（请确认模拟器已启动、Serial 正确）")
            profile = self.adb.profile(serial)
            self.open_emulator(serial)
            with self.lock:
                self.serial = serial
                self.profile = profile
                self.frame = None
                self.legacy_result = None
                self.recent_frames.clear()
                self.recognition = {"label": "未分类", "score": None}
                self.session = None
                self.error = ""
                self.failures = 0
                self.status = "live"
                self.config["serial"] = serial
                atomic_json(self.store.root / "config.json", self.config)
        self.store.event(f"已连接舰R实例 {serial} · 游戏版本 {profile['version']} · "
                         f"截图 {self.config['screenshot_method']} · 控制 {self.config['control_method']}"
                         + (f" · 设备方式初始化失败：{self.emulator_error}" if self.emulator_error else ""))
        self.wake.set()
        return profile

    def auto_connect(self):
        """Connect the configured emulator serial, as AzurPilot does with
        Emulator_Serial. Never falls back to another instance."""
        if not self.adb:
            raise ValueError(self.setup_error or '没有找到 ADB')
        serial = self.config.get('serial', '').strip()
        if not serial:
            raise ValueError('请在「设备设置」填写模拟器 Serial，例如 127.0.0.1:16416')
        if serial.startswith('127.0.0.1:'):
            try:
                self.adb.connect(serial)
            except Exception:
                pass
        return self.select(serial)

    def set_serial(self, serial):
        """Save the emulator serial (AzurPilot Emulator_Serial) and reconnect to it."""
        serial = serial.strip().replace('：', ':').replace(' ', '')
        if serial.isdigit():
            serial = f'127.0.0.1:{serial}'
        if not re.fullmatch(r'(127\.0\.0\.1:\d{1,5}|emulator-\d+)', serial):
            raise ValueError('Serial 格式应为 127.0.0.1:端口（例如 127.0.0.1:16416）')
        with self.io_lock:
            if self.automation.busy:
                raise ValueError('请先停止当前任务')
            with self.lock:
                self.config['serial'] = serial
                atomic_json(self.store.root / "config.json", self.config)
                if self.serial and self.serial != serial:
                    self.close_emulator()
                    self.serial, self.status, self.profile, self.frame = '', 'idle', None, None
        self.auto_connect_enabled = True
        self.next_connect = 0
        self.connect_error = ''
        self.store.event(f'模拟器 Serial 已设为 {serial}，正在连接')
        self.wake.set()
        return {'serial': serial}

    def control(self, action: str):
        with self.io_lock, self.lock:
            if action == "pause":
                if not self.serial:
                    raise ValueError("请先连接舰R实例")
                self.status = "paused"
                if self.automation.native:
                    self.automation.native.paused.set()
                if self.automation.busy:
                    self.automation.result['status'] = 'paused'
            elif action == "resume":
                if not self.serial:
                    raise ValueError("请先连接舰R实例")
                self.status = "live"
                self.failures = 0
                self.error = ""
            elif action == "disconnect":
                self.auto_connect_enabled = False
                self.automation.scheduler = False
                self.automation.stop('已断开设备并停止任务')
                self.close_emulator()
                self.status = "idle"
                self.serial = ""
                self.profile = None
                self.frame = None
                self.legacy_result = None
                self.recent_frames.clear()
                self.recognition = {"label": "未分类", "score": None}
                self.session = None
            elif action == "refresh":
                if self.status != "live":
                    raise ValueError("请先恢复采集")
            else:
                raise ValueError("未知操作")
        self.store.event({"pause": "已暂停画面采集", "resume": "已恢复画面采集", "disconnect": "已断开设备", "refresh": "请求新截图"}[action])
        self.wake.set()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            if (self.auto_connect_enabled and not self.automation.busy and time.monotonic() >= self.next_connect
                    and (not self.serial or self.status == 'fault')):
                self.next_connect = time.monotonic() + 15
                try:
                    if self.status == 'fault':
                        with self.lock:
                            self.serial, self.status = '', 'idle'
                    self.auto_connect()
                    self.connect_error = ''
                except Exception as exc:
                    message = str(exc)[:200]
                    if message != self.connect_error:
                        self.store.event('自动连接模拟器失败，15 秒后重试：' + message, 'warning')
                    self.connect_error = message
            if self.automation.native:
                # The native task takes its own screenshots and publishes them.
                with self.lock:
                    self.automation.tick(None)
                self.wake.wait(.2)
                continue
            active = self.automation.vm and self.automation.result['status']=='running'
            if self.status=='live' and active and not self.automation.needs_frame:
                # KeepCapture holds the original frame until the script requests
                # another one. A delay or tap must not force a new ADB screenshot.
                with self.io_lock, self.lock:
                    self.automation.tick(None)
                self.wake.wait(.02)
                continue
            if self.status == "live":
                try:
                    with self.io_lock:
                        if self.status != "live":
                            continue
                        raw, meta = self.capture()
                        with self.lock:
                            if not self.frame or self.frame.get('backend')!=meta.get('backend'):
                                self.store.event('截图方式：'+meta.get('backend','adb_png')+
                                                 (' · '+meta['ipc_error'] if meta.get('ipc_error') else ''))
                            self.sequence += 1
                            self.frame = FrameRecord(png=raw, id=self.sequence, time=now(), serial=self.serial, **meta)
                            self.recent_frames[self.sequence] = self.frame
                            if len(self.recent_frames) > 8:
                                del self.recent_frames[next(iter(self.recent_frames))]
                            self.error = ""
                            self.failures = 0
                            self.recognition = self.recognize(raw)
                            if self.color_observing:
                                self.legacy_result = self.scan_colors(raw)
                                self.legacy_result.update(frame_id=self.sequence, time=self.frame["time"])
                            self.automation.tick(raw)
                            if self.session and time.monotonic() - self.session_last_time >= 5:
                                digest = hashlib.sha256(raw).hexdigest()
                                if digest != self.session_last_hash:
                                    if self.session_count >= 600:
                                        self.store.event("本批已达 600 张，已停止连续留档", "warning")
                                        self.session = None
                                    else:
                                        folder = self.store.root / "sessions" / self.session["id"]
                                        stem = f"{self.sequence:07}"
                                        (folder / f"{stem}.png").write_bytes(raw)
                                        atomic_json(folder / f"{stem}.json", {k: v for k, v in self.frame.items() if k != "png"})
                                        self.session_last_hash = digest
                                        self.session_count += 1
                                self.session_last_time = time.monotonic()
                except Exception as exc:
                    with self.lock:
                        self.failures += 1
                        self.error = str(exc)[:500]
                        self.store.event(f"截图失败 ({self.failures}/3)：{self.error}", "warning")
                        if self.failures >= 3:
                            self.status = "fault"
                            self.session = None
                            self.save_fault("连续三次截图失败，请检查实例后恢复采集")
            active = self.automation.vm and self.automation.result['status']=='running'
            self.wake.wait(.02 if active else self.config.get("interval", 3))

    def start_session(self):
        with self.lock:
            if self.status != "live":
                raise ValueError("请先恢复实时采集")
            self.current_frame()
            if self.session:
                raise ValueError("已有采集批次正在留档")
            self.session = {"id": uuid.uuid4().hex, "time": now(), "serial": self.serial}
            self.session_count = 0
            self.session_last_hash = ""
            self.session_last_time = 0
            folder = self.store.root / "sessions" / self.session["id"]
            folder.mkdir()
            atomic_json(folder / "session.json", self.session)
        self.store.event("已开始连续留档：每 5 秒最多保存一帧，最多 600 帧")
        self.wake.set()

    def stop_session(self):
        with self.lock:
            self.session = None
        self.store.event("已结束连续留档")

    def current_frame(self, frame_id=None):
        with self.lock:
            if not self.frame:
                raise ValueError("尚未取得截图")
            selected = self.recent_frames.get(frame_id) if frame_id is not None else self.frame
            if not selected:
                raise ValueError("这张画面已过期，请锁定新画面后重新框选")
            return selected

    def save_sample(self, label: str, roi: list[int] | None, frame_id: int, note: str):
        if label not in LABELS:
            raise ValueError("未知页面标签")
        frame = self.current_frame(frame_id)
        if len(self.store.samples()) >= 1000:
            raise ValueError("已达 1000 个页面样本，请先归档数据目录")
        sid = uuid.uuid4().hex
        image = Image.open(io.BytesIO(frame["png"]))
        if roi:
            x, y, width, height = roi
            if min(x, y) < 0 or min(width, height) < 12 or x + width > image.width or y + height > image.height:
                raise ValueError("特征区域必须在截图内，且至少 12×12 像素")
        metadata = {"id": sid, "label": label, "note": note, "time": now(), "roi": roi,
                    "frame": {k: v for k, v in frame.items() if k != "png"}, "profile": deepcopy(self.profile)}
        folder = self.store.root / "samples" / sid
        folder.mkdir()
        (folder / "screen.png").write_bytes(frame["png"])
        if roi:
            x, y, w, h = roi
            image.crop((x, y, x + w, y + h)).save(folder / "feature.png")
        atomic_json(folder / "metadata.json", metadata)
        with self.store.lock:
            self.store.db.execute("INSERT INTO samples VALUES(?,?,?,?)", (sid, metadata["time"], label, json.dumps(metadata, ensure_ascii=False)))
            self.store.db.commit()
        self.store.event(f"已保存 {label} 样本" + ("及局部特征" if roi else "（未设识别特征）"))
        return metadata

    def recognize(self, raw: bytes):
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or max(image.shape[:2]) > 8192:
            raise ValueError("无效图片或图片尺寸过大")
        scores = {}
        for sample in self.store.samples()[:100]:
            roi = sample.get("roi")
            if not roi or (sample["frame"]["width"], sample["frame"]["height"]) != (image.shape[1], image.shape[0]):
                continue
            feature = cv2.imdecode(np.fromfile(self.store.root / "samples" / sample["id"] / "feature.png", np.uint8), cv2.IMREAD_COLOR)
            x, y, w, h = roi
            if feature is None or feature.shape != image[y:y+h, x:x+w].shape:
                continue
            # Fixed-coordinate comparison penalizes blank/low-variance templates as well.
            difference = float(np.mean(cv2.absdiff(image[y:y+h, x:x+w], feature)))
            score = max(0, 1 - difference / 255)
            scores[sample["label"]] = max(scores.get(sample["label"], 0), score)
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        if not ranked:
            return {"label": "未分类", "score": None, "candidates": []}
        best, score = ranked[0]
        conflict = len(ranked) > 1 and score - ranked[1][1] < 0.03
        return {"label": best if score >= 0.96 and not conflict else "未分类", "score": round(score, 4),
                "conflict": conflict, "candidates": [{"label": label, "score": round(value, 4)} for label, value in ranked[:5]],
                "method": "固定区域像素相似度，仅用于采集核对"}

    def delete_sample(self, sid: str):
        import shutil
        if not any(s["id"] == sid for s in self.store.samples()):
            raise ValueError("样本不存在")
        with self.lock, self.store.lock:
            self.store.db.execute("DELETE FROM samples WHERE id=?", (sid,))
            self.store.db.commit()
            shutil.rmtree(self.store.root / "samples" / sid)
        self.store.event("已删除页面样本")

    def scan_colors(self, raw):
        try:
            return self.legacy.scan(self.legacy.decode(raw), self.color_profile)
        except ValueError as exc:
            return {"error": str(exc), "candidates": [], "candidate_only": True}

    def save_color_profile(self, profile, observing):
        with self.lock:
            self.color_profile = profile
            self.color_observing = observing
            self.config.update(color_profile=profile.model_dump(), color_observing=observing)
            atomic_json(self.store.root / "config.json", self.config)
            self.legacy_result = self.scan_colors(self.frame["png"]) if self.frame and observing else None
            if self.legacy_result is not None:
                self.legacy_result.update(frame_id=self.frame["id"], time=self.frame["time"])
        self.store.event("已保存原脚本颜色核对设置 · " + ("实时观察已开启" if observing else "实时观察已关闭"))
        return self.state()["legacy"]

    def save_fault(self, reason: str):
        with self.lock:
            fid = uuid.uuid4().hex
            folder = self.store.root / "faults" / fid
            folder.mkdir()
            atomic_json(folder / "state.json", {"reason": reason, "time": now(), "state": self.state()})
            if self.frame:
                (folder / "last-frame.png").write_bytes(self.frame["png"])
            atomic_json(folder / "events.json", self.store.events())
        self.store.event(f"已保存故障现场：{reason}", "warning")
        return fid

    def diagnostic(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("state.json", json.dumps(self.state(), ensure_ascii=False, indent=2))
            archive.writestr("events.json", json.dumps(self.store.events(), ensure_ascii=False, indent=2))
            archive.writestr("color-profile.json", json.dumps({"profile": self.color_profile.model_dump(), "observing": self.color_observing}, ensure_ascii=False, indent=2))
            archive.write(self.legacy.folder / "provenance.json", "legacy-provenance.json")
            if self.frame:
                archive.writestr("last-frame.png", self.frame["png"])
            for folder in ("samples", "faults", "sessions"):
                for file in (self.store.root / folder).rglob("*"):
                    if file.is_file():
                        archive.write(file, file.relative_to(self.store.root))
        return output.getvalue()

    # --- device methods (ported AzurPilot screenshot / control backends) ------------
    def device_state(self):
        from .emulator.device import CONTROL_METHODS, SCREENSHOT_METHODS
        return {'screenshot_method': self.config['screenshot_method'], 'control_method': self.config['control_method'],
                'mumu_path': self.config['mumu_path'], 'screenshot_methods': list(SCREENSHOT_METHODS),
                'control_methods': list(CONTROL_METHODS), 'ready': self.emulator is not None,
                'error': self.emulator_error, 'benchmark': deepcopy(self.benchmark)}

    def open_emulator(self, serial):
        """Create the method device for `serial`; on failure the ADB preview keeps working."""
        from .emulator.connection import DeviceConfig
        from .emulator.device import Device
        self.close_emulator()
        try:
            self.emulator = Device(DeviceConfig(
                Emulator_Serial=serial, Emulator_ScreenshotMethod=self.config['screenshot_method'],
                Emulator_ControlMethod=self.config['control_method'], EmulatorInfo_path=self.config['mumu_path'],
                AdbExecutable=self.adb.path if self.adb else ''))
            self.emulator_error = ''
        except Exception as exc:
            self.emulator, self.emulator_error = None, f'{type(exc).__name__}: {exc}'[:300]

    def close_emulator(self):
        if self.emulator is not None:
            try:
                self.emulator.release()
            except Exception:
                pass
        self.emulator = None

    def capture(self):
        """One preview/legacy frame: the configured method if available, else ADB PNG."""
        if self.emulator is None:
            return self.adb.screenshot(self.serial)
        started = time.monotonic()
        rgb = self.emulator.screenshot()
        cost = round((time.monotonic() - started) * 1000, 1)
        png = FrameRecord(rgb=rgb)['png']
        return png, {'width': rgb.shape[1], 'height': rgb.shape[0],
                     'backend': self.emulator.config.Emulator_ScreenshotMethod, 'capture_ms': cost,
                     'latency_ms': round((time.monotonic() - started) * 1000)}

    def publish_frame(self, rgb, **meta):
        """Native tasks publish every frame they decide on, for the live preview."""
        with self.lock:
            self.sequence += 1
            self.frame = FrameRecord(rgb=rgb, id=self.sequence, time=now(), serial=self.serial,
                                     width=rgb.shape[1], height=rgb.shape[0], **meta)
            self.recent_frames[self.sequence] = self.frame
            if len(self.recent_frames) > 8:
                del self.recent_frames[next(iter(self.recent_frames))]

    def save_device_settings(self, screenshot_method, control_method, mumu_path):
        from .emulator.device import CONTROL_METHODS, SCREENSHOT_METHODS
        if screenshot_method not in SCREENSHOT_METHODS or control_method not in CONTROL_METHODS:
            raise ValueError('未知的截图或控制方式')
        if mumu_path and not Path(mumu_path).exists():
            raise ValueError('MuMu 路径不存在')
        with self.io_lock:
            if self.automation.busy or self.benchmark['running']:
                raise ValueError('任务或测试运行中，不能切换方式')
            with self.lock:
                self.config.update(screenshot_method=screenshot_method, control_method=control_method,
                                   mumu_path=mumu_path)
                atomic_json(self.store.root / "config.json", self.config)
            if self.serial:
                self.open_emulator(self.serial)
        self.store.event(f'设备方式：截图 {screenshot_method} · 控制 {control_method}'
                         + (f' · 初始化失败：{self.emulator_error}' if self.emulator_error else ''))
        return self.device_state()

    def start_benchmark(self, kind, methods):
        """Screenshot tests send no input; click tests switch 出征 tabs (user-started only)."""
        from .emulator import benchmark
        from .emulator.device import CONTROL_METHODS, SCREENSHOT_METHODS
        allowed = SCREENSHOT_METHODS if kind == 'screenshot' else CONTROL_METHODS if kind == 'click' else ()
        if not allowed:
            raise ValueError('未知测试类型')
        methods = [m for m in methods if m in allowed] or list(allowed)
        with self.io_lock, self.lock:
            if self.emulator is None:
                raise ValueError('请先连接舰R实例' + (f'（{self.emulator_error}）' if self.emulator_error else ''))
            if self.automation.busy or self.benchmark['running']:
                raise ValueError('任务或测试运行中')
            if kind == 'click':
                self.adb.ensure_input_ready(self.serial)
            self.benchmark.update(running=True, kind=kind, progress='准备中', error='')
            previous = self.status
            self.status = 'paused'  # keep the preview loop off the device during the test

        def worker():
            from .ui.pages import PageDetector
            detector = PageDetector(self.resources / 'assets' / 'pages.json')

            def progress(text):
                self.benchmark['progress'] = text

            try:
                with self.io_lock:
                    if kind == 'screenshot':
                        results = benchmark.benchmark_screenshot(self.emulator, methods, detector, progress=progress)
                    else:
                        results = benchmark.benchmark_click(self.emulator, methods, detector, progress=progress)
                best = benchmark.recommend(results)
                with self.lock:
                    self.benchmark['results'][kind] = {'time': now(), 'results': benchmark.to_json(results),
                                                       'recommended': best}
                self.store.event(f'{"截图" if kind == "screenshot" else "点击"}测试完成，推荐 {best or "无可用方式"}')
            except Exception as exc:
                self.benchmark['error'] = f'{type(exc).__name__}: {exc}'[:500]
                self.store.event('设备方式测试失败：' + self.benchmark['error'], 'warning')
            finally:
                with self.lock:
                    self.benchmark.update(running=False, progress='')
                    if self.status == 'paused':
                        self.status = previous
                self.wake.set()

        threading.Thread(target=worker, name=f'benchmark-{kind}', daemon=True).start()
        self.store.event(f'开始{"截图" if kind == "screenshot" else "点击"}方式测试：{", ".join(methods)}')
        return self.device_state()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=25)
        if self.automation.native:
            self.automation.native.stop('后台退出')
        self.close_emulator()
        if not self.thread.is_alive():
            if self.adb:self.adb.close()
            self.store.close()
