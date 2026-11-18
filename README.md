# 舰R助手 WarshipPilot

Python 3.14 源码运行，ALAS 式 WebUI。安装目录就是 Git 仓库，运行环境放在 `.venv`，前端产物随源码提交，运行电脑不需要 Node。

## 安装和启动

Windows x64 推荐使用[舰R独立启动器](https://github.com/a2893005741/WarshipPilotLauncher/releases/tag/v3.0.7)：下载 `WarshipPilot.exe` 放在可写目录，点击“部署”，完成后点击“启动”。环境修复、托盘和开机自启在启动器中管理。原 ALAS 使用自己的启动器仓库，两者独立发布。

开发时执行 `uv sync --frozen` 后直接运行 `.venv/Scripts/python.exe gui.py`。

默认监听 `0.0.0.0:22680`，首次启动生成 `config/deploy.yaml`，访问码在 `WebUI.AccessCode`。本机自动打开网页，局域网浏览器填写同一访问码。只允许本机访问时将 `WebUI.Host` 改为 `127.0.0.1`。关闭网页不停止后台，右上角电源按钮退出。

局域网访问需要放行 WebUI 端口：以管理员身份运行一次 `powershell -ExecutionPolicy Bypass -File deploy\launcher\allow-lan-access.ps1`（TCP 22680，仅本地子网）。启动器以普通用户运行，无法自行修改防火墙；缺少规则时后台日志会提示。

手机连接同一局域网后，用浏览器打开 `http://运行电脑的局域网IP:22680`，填写同一访问码。小屏自动显示“总览、任务、设备、更多”底部导航，可启停调度器、查看日志和截图、修改任务参数；不需要安装手机应用。

## 配置和记录

- `config/deploy.yaml`：Git 分支、更新源、Git/Python/uv/ADB 路径、监听地址和访问码。不提交到仓库。
- `config/warship.json`：Device 中的模拟器 Serial、截图/控制方式和 MuMu 路径，Tasks 中的任务参数，以及 Scheduler.Enable 和 Scheduler.NextRun。
- `log/records.sqlite3`：运行记录；`log/error`：故障现场；`screenshots`：任务截图、采集会话与样本。

首次启动识别安装目录的 `data` 和旁边的 `WarshipPilot-data`（包括 D:\WarshipPilot-data），复制配置、SQLite 和截图。访问码、任务参数、调度开关和下次运行时间保留；旧目录不改动，新配置不被旧数据覆盖。迁移完成记录在 `log/migration.json`。

## 更新

网页“软件更新”比较当前提交与远端分支，列出新提交的说明。“更新并重启”会等待当前任务结束，暂不调度下一项，退出后拉取源码、同步依赖并自动重启。调度状态保存在 warship.json 中，重启后继续使用。Git 或依赖同步失败会记录到 `log/update-result.json`；代码更新后的依赖或启动检查失败会尝试恢复原提交。

网页更新由后台自己的安装进程执行，不再切换到启动器安装界面。`gui.py` 的轻量常驻进程在网页服务重启期间保持运行，启动器仍可停止整组进程。旧运行端首次获取此实现后需重新启动后台一次，之后网页更新使用这条链路。

只需推送代码，无需打包 EXE 或上传 Release。Git.Repository 留空表示使用 origin；可填远端能访问的镜像仓库地址。私有仓库通过 Git 凭据管理器配置身份，不把令牌放入 WebUI。更新源需要与本地历史一致，自动更新拒绝未提交修改、分支不一致和提交分叉。

## 自动化能力

101 个页面的识别规则位于 `assets/pages.json`；`module/ui` 负责页面图和导航，`module/vision` 保留原引擎比色/找色。`module/device` 保留 ALAS 移植的截图和控制方式，`module/expedition` 执行原生远征，原方案 C 出征仍通过 `module/legacy/vm.py` 执行恢复的 Lua 5.2 函数。

远征收取亮起槽位并继续原舰队远征，完成后回港。方案 C 默认仍为 6-1、第二舰队、α入口、第一战单横、不夜战；原方案参数可在网页修改，下一次任务启动生效。大破出征／进击固定关闭。

战役使用原脚本打完当天次数，有船泡澡时稍后继续，打完后次日计划时间再检查；任务奖励按间隔检查港区任务红点并领取。演习使用原“打演习”函数，支持选择第一至第四舰队、阵型和避潜艇，沿用原快修及继续夜战流程。每轮处理两页可挑战对手，确认回港后等待下一个 0、12、18 点刷新；可在演习参数页启用自动调度或立即运行。

决战使用原“决战”函数（开启换票时先执行原“决战换票”）：按决战方案选关，战备舰队优先选潜艇和指定舰船，满编后按勾选选 BUFF，道中与 BOSS 分别按阵型、夜战和快修设置作战，捞船锁定沿用通用设置中的捞船、截图和拆船选项。原脚本按 BOSS 战计数（3 次算一次决战），每日计数保存在 `log/legacy-files/记录文件.txt`；打满每日限制次数或决战票用完后回港，次日计划时间再检查。捞船截图保存在 `screenshots/decisive/`。“新船上锁停止”会停止调度器；澡堂满时原脚本等待最长 15 分钟，桌面版在等待期间不穿插方案 C 出征。方案 A/B 目前只保存配置。

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

仓库只发布程序源码（参照 ALAS 的 `.gitignore`）：运维脚本、过程文档、运行数据和本地配置不提交。

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
