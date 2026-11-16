"""Device frames and original-script execution share a single device I/O owner."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import uuid
import zipfile

import cv2
import numpy as np
from PIL import Image

from .device import Adb, find_adb
from .store import Store, atomic_json, now
from .legacy import ColorProfile, LegacyVision
from .automation import TaskController

LABELS = ("母港", "出征选择", "关卡选择", "舰队准备", "地图节点", "索敌", "阵型", "战斗", "夜战", "结算", "远征", "战役", "演习", "修理", "补给", "弹窗", "未分类")


class Runtime:
    def __init__(self, data: Path, resources: Path):
        self.store = Store(data)
        self.resources = resources
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        config = data / "config.json"
        self.config = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {"schema_version": 1, "serial": "", "interval": 3, "adb_path": ""}
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
        self.store.event("舰R助手 v0.4 已启动 · 已接入原Lua远征、出征、点击及滑动函数")
        self.thread.start()

    def state(self):
        with self.lock:
            return {"version": "0.4.0", "status": self.status, "error": self.error, "serial": self.serial,
                    "legacy": {"profile": self.color_profile.model_dump(), "observing": self.color_observing,
                               "result": deepcopy(self.legacy_result), "stats": self.legacy.catalog["stats"]},
                    "last_serial": self.config.get("serial", ""), "adb_path": self.adb.path if self.adb else "",
                    "frame": {k: v for k, v in self.frame.items() if k != "png"} if self.frame else None,
                    "profile": deepcopy(self.profile), "recognition": self.recognition, "session": deepcopy(self.session),
                    "automation": self.automation.state(),
                    "session_count": self.session_count, "labels": LABELS, "read_only": False,
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
        with self.io_lock:
            if self.automation.vm:
                raise ValueError('请先停止当前任务，再切换设备')
            if not self.adb:
                raise ValueError(self.setup_error)
            devices = self.adb.discover()
            if not any(d["serial"] == serial and d["game_installed"] and d["state"] == "device" for d in devices):
                raise ValueError("请选择在线且已安装战舰少女R的实例")
            profile = self.adb.profile(serial)
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
        self.store.event(f"已连接舰R实例 {serial} · 游戏版本 {profile['version']} · 原脚本任务可运行")
        self.wake.set()
        return profile

    def control(self, action: str):
        with self.io_lock, self.lock:
            if action == "pause":
                if not self.serial:
                    raise ValueError("请先连接舰R实例")
                self.status = "paused"
                if self.automation.vm:
                    self.automation.result['status'] = 'paused'
            elif action == "resume":
                if not self.serial:
                    raise ValueError("请先连接舰R实例")
                self.status = "live"
                self.failures = 0
                self.error = ""
            elif action == "disconnect":
                self.automation.scheduler = False
                self.automation.stop('已断开设备并停止任务')
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
                        raw, meta = self.adb.screenshot(self.serial)
                        with self.lock:
                            if not self.frame or self.frame.get('backend')!=meta.get('backend'):
                                self.store.event('截图方式：'+meta.get('backend','adb_png')+
                                                 (' · '+meta['ipc_error'] if meta.get('ipc_error') else ''))
                            self.sequence += 1
                            self.frame = {"png": raw, "id": self.sequence, "time": now(), "serial": self.serial, **meta}
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
            return dict(selected)

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

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=25)
        if not self.thread.is_alive():
            if self.adb:self.adb.close()
            self.store.close()
