# 舰R助手 WarshipPilot

Python 3.14 源码运行，ALAS 式 WebUI。安装目录就是 Git 仓库，运行环境放在 `.venv`，前端产物随源码提交，运行电脑不需要 Node。

## 安装和启动

首次在开发电脑执行 `uv sync --frozen`，再运行 `scripts/prepare-runtime.ps1`。它按同一份 uv.lock 准备 Python、依赖、Git、uv 和 ADB，并把 Python 标准库一并带上；仅复制普通虚拟环境不能离开开发电脑运行。

把仓库和准备好的 `.venv` 放到同一目录，运行 `WarshipPilot.bat`。启动器修正便携 Python 路径，运行安装器获取 Git 提交，有依赖变化才同步，再检查 ADB、启动 `gui.py`。安装器需要干净工作区和正确的更新分支。开发时直接运行 `.venv/Scripts/python.exe gui.py`。

默认监听 `0.0.0.0:22680`，首次启动生成 `config/deploy.yaml`，访问码在 `WebUI.AccessCode`。本机自动打开网页，局域网浏览器填写同一访问码。只允许本机访问时将 `WebUI.Host` 改为 `127.0.0.1`。关闭网页不停止后台，右上角电源按钮退出。

## 配置和记录

- `config/deploy.yaml`：Git 分支、更新源、Git/Python/uv/ADB 路径、监听地址和访问码。不提交到仓库。
- `config/warship.json`：Device 中的模拟器 Serial、截图/控制方式和 MuMu 路径，Tasks 中的任务参数，以及 Scheduler.Enable 和 Scheduler.NextRun。
- `log/records.sqlite3`：运行记录；`log/error`：故障现场；`screenshots`：任务截图、采集会话与样本。

首次启动识别安装目录的 `data` 和旁边的 `WarshipPilot-data`（包括 D:\WarshipPilot-data），复制配置、SQLite 和截图。访问码、任务参数、调度开关和下次运行时间保留；旧目录不改动，新配置不被旧数据覆盖。迁移完成记录在 `log/migration.json`。

## 更新

网页“软件更新”比较当前提交与远端分支，列出新提交的说明。“更新并重启”会等待当前任务结束，暂不调度下一项，退出后拉取源码、同步依赖并自动重启。调度状态保存在 warship.json 中，重启后继续使用。Git 或依赖同步失败会记录到 `log/update-result.json`；代码更新后的依赖或启动检查失败会尝试恢复原提交。

只需推送代码，无需打包 EXE 或上传 Release。Git.Repository 留空表示使用 origin；可填远端能访问的镜像仓库地址。私有仓库通过 Git 凭据管理器配置身份，不把令牌放入 WebUI。更新源需要与本地历史一致，自动更新拒绝未提交修改、分支不一致和提交分叉。

## 自动化能力

101 个页面的识别规则位于 `assets/pages.json`；`module/ui` 负责页面图和导航，`module/vision` 保留原引擎比色/找色。`module/device` 保留 ALAS 移植的截图和控制方式，`module/expedition` 执行原生远征，原方案 C 出征仍通过 `module/legacy/vm.py` 执行恢复的 Lua 5.2 函数。

远征收取亮起槽位并继续原舰队远征，完成后回港。方案 C 默认仍为 6-1、第二舰队、α入口、第一战单横、不夜战；原方案参数可在网页修改，下一次任务启动生效。大破出征／进击固定关闭。方案 A/B、战役、演习、决战目前保存配置，尚未接入执行。

设备配置默认截图 nemu_ipc、控制 ADB；支持 ADB、ADB_nc、DroidCast、uiautomator2、scrcpy，以及 MaaTouch/minitouch 控制。首次部署只连接明确配置的舰R Serial，不切换其它游戏实例。MuMu IPC 要求后台位于已登录桌面用户的会话。

## 开发验证

```powershell
uv sync --frozen
.venv/Scripts/python.exe -m unittest discover -s tests -v
npm ci --prefix frontend
npm run build --prefix frontend
.venv/Scripts/python.exe gui.py
```

提交前端修改时同时提交 `frontend/dist`。源码入口为 `gui.py`，调度入口为 `alas.py`，部署代码位于 `deploy`，原脚本提取工具位于 `dev_tools/legacy_extract`。

`scripts/deploy-remote.ps1` 负责首次源码部署、备份旧安装、迁移和计划任务切换。无需重复部署，此后的更新由 Git 完成。

ALAS 移植部分按 GPLv3 提供，见 LICENSE 与 docs/ALAS-PORT.json；旧脚本恢复产物的权利归原作者。


## WebUI 与配置结构

WebUI 复用本机 AzurPilot 的现代样式、外壳和参数页结构：总览使用共享调度器、任务计划及日志/截图面板；参数页使用设置卡、独立参数目录和共享调度区。来源提交与文件见 docs/ALAS-WEBUI-PORT.json。

前端按 `app/`、`pages/`、`components/`、`api/`、`config/`、`styles/` 分目录；后端接口位于 `module/api/`，运行与调度服务位于 `module/runtime/`，共用异常位于 `module/exception.py`。业务请求通过 `/api/v1/ws`，截图与下载保留鉴权 HTTP。

原脚本业务字段共 506 项，按原控件的选项次序和默认值生成；不迁移注册码、令牌等敏感项。定义在 `module/config/argument/task.yaml`、`argument.yaml`、`default.yaml`、`override.yaml`、`gui.yaml`。运行以下命令生成，避免直接编辑生成文件：

```powershell
.venv/Scripts/python.exe -m module.config.config_updater
.venv/Scripts/python.exe -m dev_tools.export_api_schema
```

`config/warship.json` 的 `Tasks.<任务>.<参数组>.<参数>` 对齐 ALAS 配置层级。旧扁平任务配置启动时自动转换，原调度开关、间隔和下次运行时间保留。修改字段后自动保存，出错提示留在对应字段旁；运行任务前等待保存完成。

浏览器回归脚本 `frontend/tests/alas-layout.mjs` 覆盖真实后台的桌面、手机、深色布局、参数目录、原脚本字段持久化和非法值恢复。它使用本地隔离的 `.deployment/alas-webui-preview` 后台（22685 端口），不向模拟器发送输入。
