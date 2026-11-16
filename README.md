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

远征收取亮起槽位并继续原舰队远征，完成后回港。常用图仍为原方案 C：6-1、第二舰队、α入口、第一战单横、不夜战，关闭大破出征／进击。战役、演习尚未接入。

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
