# AGENTS.md

舰R助手 WarshipPilot：战舰少女R 电脑端自动化，结构参照 ALAS / AzurPilot（`H:\ALAS\AzurPilot`）。

游戏识别基于 **1280×720 横屏** 截图；非该尺寸的截图直接报 `ScreenSizeError`，不缩放。恢复的原脚本使用 **540×960 竖屏画布**、颜色写作 `BBGGRR`，坐标与颜色由 `module/vision/color.py` 转换，不要在业务代码里手算。

- Python 3.14，使用 uv 管理依赖（`uv.lock` 随仓库提交，安装用 `--frozen`）
- 前端使用 npm 管理依赖（Node ≥ 22.12）；运行电脑不装 Node，`frontend/dist` 随源码提交
- 面向用户的说明在 [README.md](README.md)，前端说明在 [frontend/README.md](frontend/README.md)

## 常用命令

| 用途 | 命令 |
| --- | --- |
| 安装依赖 | `uv sync --frozen` |
| 启动 | `.venv/Scripts/python.exe gui.py` |
| 后端测试 | `.venv/Scripts/python.exe -m unittest discover -s tests -v` |
| 生成配置和前端选项 | `.venv/Scripts/python.exe -m module.config.config_updater` |
| 前端构建 | `npm ci --prefix frontend` 后 `npm run build --prefix frontend` |
| 前端测试 | `npm test --prefix frontend`；手机端回归 `npm run test:mobile --prefix frontend` |
| 重建页面识别规则 | `uv run python dev_tools/legacy_extract/regenerate.py [截图glob ...]` |

## 配置与生成文件

参数定义的源文件在 `module/config/argument/`：

| 源文件 | 职责 |
| --- | --- |
| `task.yaml` | 菜单、任务、选项组映射与 `executable` |
| `argument.yaml` | 参数类型、选项、默认值与校验 |
| `default.yaml` | 用户可修改的任务特定默认值 |
| `override.yaml` | 强制覆盖及隐藏、只读等属性；与可修改默认值区分 |
| `gui.yaml` | 选项组显示名 |

- `args.json`、`menu.json`、`schema.json` 与 `config/template.json` 由 `config_updater` 生成，不手动编辑；改完 YAML 后运行生成命令并一起提交。
- 现在 YAML 才是源文件。`dev_tools/build_legacy_arguments.py` 只做了首次提取，之后接入战役、演习、决战、任务奖励时对 YAML 的修改它都没有同步，再运行会覆盖这些修改。
- 原脚本业务字段按原控件的选项次序和默认值生成；不迁移注册码、令牌等敏感项。
- 用户配置 `config/warship.json` 的层级是 `Tasks.<Task>.<Group>.<Argument>`，另有 `Device` 和 `Scheduler`（`Enable`、`NextRun`）。部署设置在 `config/deploy.yaml`（访问码、监听地址、Git/Python/uv/ADB 路径）。两者都不提交。
- 旧的扁平配置启动时迁移（`module/config/migration.py`），迁移时保留调度开关、间隔和下次运行时间。测试使用临时配置目录，不读写真实的 `config/`。

## 游戏交互

任务有两条执行路径：

- **原生任务**（远征 `module/expedition`）：用 `module/ui` 的页面图和 `UI` 导航（`ui_goto` / `ui_ensure`），识别规则来自 `assets/pages.json`。
- **原脚本任务**（方案 C 出征、战役、演习、决战、任务奖励）：由 `module/legacy/vm.py` 在 Lua 5.2 中执行恢复的 `assets/legacy/main.lua52.luac`。任务分支、坐标、触摸序列和延时都留在字节码里。适配层只实现旧引擎的平台操作（截图、比色、点击、记录文件等），不在适配层写任务路线。任务名到原函数的映射见 `vm.py` 中的 `ENTRIES`。

原生代码采用持续的「截图 → 识别 → 操作」状态循环：

- 每一步都根据新截图判断。用当前画面的正向状态确认退出，点击后回到循环取新帧；不要用固定休眠猜界面已就绪，也不要盲目重放点击。
- 导航每帧重新规划。页面图之外的结果页、弹窗和对话框使用原脚本对该页的默认处理（`assets/page_handlers.json`，见 `UI.handle_default`）。
- 卡死保护用现有的 `GameStuckError`、`UnknownPageError`（`module/ui/navigation.py`）、`ScreenSizeError`，以及 `module/exception.py` 中的 `RequestHumanTakeover`、`EmulatorNotRunningError`、`ScriptError`。同一页面重复点击无变化时停止，不要靠吞异常或无限重试绕过。
- 设备 I/O 只有一个所有者（`module/runtime/runtime.py`）。任务通过 `module/runtime/native.py` 的 `GatedDevice` 截图和点击，停止请求以 `TaskStopped` 抛出；任务代码不直接创建 ADB 或截图连接。
- 日志使用 `logging.getLogger('warship.<模块>')`。截图、日志和测试夹具中不要带入账号信息和密钥。

## 资源与识别

- `assets/pages.json`（101 个页面的 AND/OR/NOT 识别规则）和 `assets/page_handlers.json` 由 `dev_tools/legacy_extract/` 从原字节码生成，不手动编辑。真实画面漏判时，先把截图传给 `regenerate.py` 合入 `seeds.json`，再重新生成。
- `assets/game/` 是新版游戏界面的模板裁剪（1280×720 屏幕坐标），登记在 `templates.json`；`assets/legacy/` 是原脚本字节码、资源包与提取记录。
- 点击目标用 `module/ui/assets.py` 的 `Button`，写明坐标来源（原脚本函数或实测截图）。

## 设备

- `module/device` 是从 AzurPilot 移植的截图与控制方式。默认截图 `nemu_ipc`、控制 `ADB`，这两项已实机验证；另支持 ADB_nc、DroidCast、uiautomator2、scrcpy、MaaTouch、minitouch。
- 只连接配置里明确指定的舰R Serial，不切换其他游戏实例。设备离线时先重连目标端口，确认 ADB 服务异常后才重启服务，两次自动重启至少间隔 `ADB_RESTART_COOLDOWN`（120 秒）。

## WebUI 与接口

- 前端取自 AzurPilot（React 19 + Tailwind 4 + Radix），删掉了碧蓝专用页面；舰R独有页面放在 `frontend/src/warship/`。改前端时同时提交 `frontend/dist`。
- 业务通信使用 `/api/v1/ws`（`module/api/alas` 移植了 AzurPilot 的 RPC 网关），截图与下载使用带鉴权的 HTTP。后端接口在 `module/api/`，运行与调度服务在 `module/runtime/`。
- `frontend/src/api/generated.ts` 取自 AzurPilot，没有生成器（`dev_tools.export_api_schema` 已在 77462fe 删除）。新增或修改 RPC 方法时，需要手动同步 `generated.ts` 和 `module/api/alas` 的注册与参数模型，并用 `tests/test_webui_protocol.py` 和前端测试验证。

## 移植来源与许可

- 从 AzurPilot / ALAS 移植代码时，在 `docs/ALAS-PORT.json`（后端）或 `docs/ALAS-WEBUI-PORT.json`（前端）登记 `source`、`commit`、`sha256`、`destination` 和 `changes`。尽量原样移植，只改必要的导入路径和依赖。
- ALAS 移植部分按 GPLv3 提供；恢复的旧脚本产物权利归原作者。

## 测试

- 后端测试使用标准库 `unittest`，不连接设备。原脚本任务用 `tests/synthetic.py` 合成画面后回放字节码（参考 `tests/test_exercise.py`、`tests/test_decisive.py`）。
- 修改调度、配置迁移、更新器或启动器协议时，运行对应的 `test_scheduler`、`test_migration`、`test_updater`、`test_launcher*`。

## 仓库与提交

- 仓库只发布程序源码（参照 ALAS 的 `.gitignore`）：`log/`、`screenshots/`、`evidence/`、`config/*.json|yaml`（模板除外）、`docs/*`（许可与移植来源除外）和过程文档都不提交。
- 提交信息使用 `feat(scope): …` / `fix(scope): …` / `docs: …` 格式，前缀之后的标题和正文都用中文。用户可见的行为变化同步更新 README.md。
- 发布只需推送代码，WebUI 的“软件更新”会拉取远端分支，不需要打包 EXE。
