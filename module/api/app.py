import asyncio
from module.version import VERSION
from contextlib import asynccontextmanager
import io
import json
import re
import secrets
import base64
import os

from PIL import Image
from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute, Mount
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from module.runtime.runtime import Runtime
from module.vision.legacy import ColorProfile
from module.config.task_settings import EXECUTABLE, TaskSettingsRequest, read_tasks, save_task
from module.config.schema import schema
from module.api.config_service import ConfigService
from module.api.alas.router import Router
from module.api.alas.socket import Gateway


class SampleRequest(BaseModel):
    label: str
    roi: tuple[int, int, int, int] | None = None
    frame_id: int
    note: str = Field(default="", max_length=400)


class ColorSettingsRequest(BaseModel):
    profile: ColorProfile
    observing: bool = False


class ColorCheckRequest(BaseModel):
    profile: ColorProfile
    image_base64: str = Field(min_length=1, max_length=22_000_000)
    rule_id: str | None = Field(default=None, max_length=64)


class ConsoleFiles(StaticFiles):
    """The page itself is never cached (a new release must show at once);
    hashed build assets are cached for good."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.startswith('assets/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response


def create_app(runtime: Runtime, key: str, shutdown):
    configuration = ConfigService(runtime)
    def authorized(request: Request):
        return secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + key)

    async def health(request):
        return JSONResponse({"product": "WarshipPilot", "version": VERSION, "read_only": False,
                             "pid": os.getpid(), "commit": getattr(runtime, 'commit', '')})

    async def api(request: Request):
        if not authorized(request):
            return JSONResponse({"error": "请输入启动器生成的控制台访问码"}, status_code=401)
        action = request.path_params["action"]
        if request.method == "GET":
            if action == 'schema':
                return JSONResponse(configuration.schema())
            if action == 'config':
                return JSONResponse(configuration.get(request.query_params.get('task', '')))
            if action == "task-configs":
                with runtime.lock:
                    return JSONResponse({'tasks': read_tasks(runtime.store.root), 'executable': True, 'supported': EXECUTABLE})
            if action == "legacy-catalog":
                return JSONResponse(runtime.legacy.index())
            if action == "legacy-rule":
                return JSONResponse(runtime.legacy.detail(request.query_params.get("id", "")))
            if action == "legacy-identifiers":
                return FileResponse(runtime.legacy.folder / "identifiers.json", media_type="application/json")
            if action == "legacy-download":
                return FileResponse(runtime.legacy.folder / "resources.zip", media_type="application/zip", filename="WarshipPilot-legacy-resources.zip")
            if action == "state":
                return JSONResponse(await asyncio.to_thread(runtime.state))
            if action == "events":
                return JSONResponse(runtime.store.events())
            if action == "frame":
                with runtime.lock:
                    frame = runtime.frame
                if not frame:
                    return JSONResponse({"error": "尚无截图"}, status_code=404)
                return Response(frame["png"], media_type="image/png", headers={"Cache-Control": "no-store", "X-Frame-Id": str(frame["id"])})
            if action == "samples":
                return JSONResponse(runtime.store.samples())
            if action == "sample-image":
                sid = request.query_params.get("id", "")
                if not re.fullmatch(r"[a-f0-9]{32}", sid):
                    raise ValueError("无效样本编号")
                file = runtime.store.root / "screenshots" / "samples" / sid / "screen.png"
                if not file.is_file():
                    raise ValueError("样本不存在")
                return FileResponse(file, media_type="image/png")
            if action == "diagnostic":
                content = await asyncio.to_thread(runtime.diagnostic)
                return Response(content, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="WarshipPilot-diagnostic.zip"'})
        if request.method == "POST":
            if action == "legacy-check" and int(request.headers.get("content-length", "0")) > 23_000_000:
                raise ValueError("图片不能大于16MB")
            if action == "replay":
                if int(request.headers.get("content-length", "0")) > 16_000_000:
                    raise ValueError("图片不能大于 16MB")
                raw = await request.body()
                if len(raw) > 16_000_000:
                    raise ValueError("图片不能大于 16MB")
                with Image.open(io.BytesIO(raw)) as image:
                    if max(image.size) > 8192:
                        raise ValueError("图片尺寸不能超过 8192 像素")
                    image.verify()
                return JSONResponse(await asyncio.to_thread(runtime.recognize, raw))
            body = await request.json()
            if action == 'config-field':
                return JSONResponse(configuration.set(str(body.get('path', '')), body.get('value')))
            if action == 'task-control':
                def task_control():
                    with runtime.io_lock, runtime.lock:
                        return runtime.automation.control(str(body.get('action','')), str(body.get('task','')))
                return JSONResponse(await asyncio.to_thread(task_control))
            if action == 'task-config':
                settings = TaskSettingsRequest.model_validate(body)
                with runtime.lock:
                    result = save_task(runtime.store.root, settings.task, settings.settings)
                runtime.store.event('已保存任务参数草稿：' + settings.task)
                return JSONResponse(result)
            if action == "legacy-settings":
                settings = ColorSettingsRequest.model_validate(body)
                return JSONResponse(await asyncio.to_thread(runtime.save_color_profile, settings.profile, settings.observing))
            if action == "legacy-check":
                check = ColorCheckRequest.model_validate(body)
                try:
                    raw = base64.b64decode(check.image_base64, validate=True)
                except ValueError:
                    raise ValueError("图片编码无效")
                if len(raw) > 16_000_000:
                    raise ValueError("图片不能大于16MB")
                def evaluate_colors():
                    image = runtime.legacy.decode(raw)
                    if check.rule_id:
                        return runtime.legacy.evaluate(image, check.rule_id, check.profile)
                    return runtime.legacy.scan(image, check.profile)
                return JSONResponse(await asyncio.to_thread(evaluate_colors))
            if action == "devices":
                return JSONResponse(await asyncio.to_thread(runtime.discover, str(body.get("adb_path", ""))))
            if action in ("update-check", "update-install", "update-settings"):
                if not runtime.updater:
                    raise ValueError("更新组件未初始化")
                if action == "update-check":
                    return JSONResponse(await asyncio.to_thread(runtime.updater.check))
                if action == "update-install":
                    return JSONResponse(await asyncio.to_thread(runtime.updater.install))
                return JSONResponse(runtime.updater.save_settings(auto_check=body.get("auto_check")))
            if action == "serial":
                return JSONResponse(await asyncio.to_thread(runtime.set_serial, str(body.get("serial", ""))))
            if action == "device-config":
                return JSONResponse(await asyncio.to_thread(
                    runtime.save_device_settings, str(body.get("screenshot_method", "")),
                    str(body.get("control_method", "")), str(body.get("mumu_path", ""))))
            if action == "benchmark":
                methods = [str(m) for m in body.get("methods", [])][:10]
                return JSONResponse(await asyncio.to_thread(runtime.start_benchmark, str(body.get("kind", "")), methods))
            if action == "connect-adb":
                if not runtime.adb:
                    raise ValueError("请先设置 ADB 路径")
                def connect():
                    with runtime.io_lock:
                        return runtime.adb.connect(str(body.get("serial", "")))
                return JSONResponse({"message": await asyncio.to_thread(connect)})
            if action == "select":
                return JSONResponse(await asyncio.to_thread(runtime.select, str(body.get("serial", ""))))
            if action == "control":
                await asyncio.to_thread(runtime.control, str(body.get("action", "")))
            elif action == "session-start":
                await asyncio.to_thread(runtime.start_session)
            elif action == "session-stop":
                runtime.stop_session()
            elif action == "sample":
                value = SampleRequest.model_validate(body)
                return JSONResponse(await asyncio.to_thread(runtime.save_sample, value.label, list(value.roi) if value.roi else None, value.frame_id, value.note))
            elif action == "sample-delete":
                sid = str(body.get("id", ""))
                if not re.fullmatch(r"[a-f0-9]{32}", sid):
                    raise ValueError("无效样本编号")
                await asyncio.to_thread(runtime.delete_sample, sid)
            elif action == "fault":
                return JSONResponse({"id": await asyncio.to_thread(runtime.save_fault, str(body.get("reason", "手动保存现场"))[:300])})
            elif action == "legacy-report":
                return JSONResponse(legacy_report(runtime, body))
            elif action == "shutdown":
                runtime.store.event("已收到退出后台请求")
                shutdown()
            elif action not in ("control", "session-start", "session-stop"):
                return JSONResponse({"error": "接口不存在"}, status_code=404)
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "接口不存在"}, status_code=404)

    async def error(request, exc):
        if isinstance(exc, ValidationError):
            message = "设置格式不正确：" + str(exc).splitlines()[0]
        else:
            message = str(exc)[:700]
        runtime.store.event(message, "warning")
        return JSONResponse({"error": message}, status_code=400)

    # AzurPilot's WebUI protocol for the reused ALAS frontend (module/api/alas).
    gateway = Gateway(Router(runtime), key)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(runtime.close)

    return Starlette(routes=[Route("/health", health), Route("/api/{action}", api, methods=["GET", "POST"]),
                              WebSocketRoute('/api/v1/ws', gateway.endpoint), Mount("/", ConsoleFiles(directory=runtime.resources / "frontend" / "dist", html=True))],
                     exception_handlers={ValueError: error, RuntimeError: error, ValidationError: error, OSError: error}, lifespan=lifespan)


def legacy_report(runtime: Runtime, body: dict):
    """Describe every source key, without retaining account/registration values or activating tasks."""
    values = body.get("config")
    if not isinstance(values, dict) or len(values) > 2000:
        raise ValueError("请选择 JSON 对象格式的 script.cfg")
    fields = json.loads((runtime.resources / "assets" / "legacy-fields.json").read_text(encoding="utf-8"))["fields"]
    report = []
    known = set()
    configurable = {name for groups in schema()['args'].values() for group in groups.values() for name in group}
    for field in fields:
        name = field["legacy_key"]
        known.add(name)
        private = name == 'SPT' or bool(re.search("注册码|密码|账号|帐号|token|密钥|邮箱|手机", name, re.I))
        platform = private or bool(re.search("包名|云日志|广告|变速|注入|悬浮|音量|亮度|锁屏|屏蔽读取", name))
        configured = name in configurable
        status = "不适用" if platform else "可配置" if configured else "本版暂不支持"
        row = {"key": name, "page": field["page"], "present": name in values,
               "status": status, "reason": "不保存敏感值及旧安卓环境设置" if platform else "可在对应任务参数页配置；本次核对不导入" if configured else "尚未接入执行"}
        if not platform and name in values:
            value = values[name]
            # Enum labels are supplied by the static inventory when available.
            row["source_type"] = type(value).__name__
            row["options"] = field.get("legacy_options_in_order", [])
            if row["options"]:
                try:
                    index = int(value)
                    if isinstance(value, bool) or str(index) != str(value) or not 0 <= index < len(row["options"]):
                        raise ValueError()
                    row["decoded_option"] = row["options"][index]
                except (ValueError, TypeError):
                    row["status"] = "需要核对"
                    row["reason"] = "旧枚举索引不在已知范围；不生成可执行默认值"
        report.append(row)
    for name in values.keys() - known:
        report.append({"key": str(name)[:200], "page": "未知", "present": True, "status": "需要核对", "reason": "未收录的字段；不保存值"})
    return {"schema_version": 1, "total_known": len(fields), "received": len(values), "activated": False,
            "counts": {status: sum(row["status"] == status for row in report) for status in ("可配置", "已迁移", "已转换", "本版暂不支持", "不适用", "需要核对")}, "fields": report}
