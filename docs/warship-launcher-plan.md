# 舰R ALAS 启动器改造方案

> 对象：独立仓库 `a2893005741/WarshipPilotLauncher`（基于 `a2893005741/alas-launcher` / `wess09/AzurPilotLauncher`，Tauri 2 + Rust + React，版本 3.0.7）
> 目标：改造成“舰R助手启动器”，负责 WarshipPilot 的首次部署、启动/停止、更新、修复、托盘与开机自启。
> 后端：`a2893005741/WarshipPilot`（main，v0.12.0，Python 3.14 + uv，WebUI 已是 AzurPilot 界面）。
> 日期：2026-11-17（审查修订版）
> 实施目录：后端 `WarshipPilot`；启动器 `../WarshipLauncher`（fork）。

## 1. 结论

启动器的**外壳与机制可以几乎原样复用**：Tauri 窗口与托盘、首页状态机（检查更新 → 部署 → 启动 → 运行 → 停止/修复）、组件清单与 SHA-256 校验、组件原子安装与回滚、内嵌 uv 装 Python、进程组/Job 托管、已验证归属的残留进程清理、自更新、设置与选源、日志导出。

需要改的是**它和 AzurPilot 后端之间的“契约”**，集中在四处：

1. **启动阶段调用的 deploy 脚本**：AzurPilot 用 `deploy.git.GitManager().git_install()`、`deploy.app.ensure_frontend`（npm 构建）；WarshipPilot 的 deploy 模块接口不同，且前端产物 `frontend/dist` 已随仓库提交，不需要 Node.js。
2. **`config/deploy.yaml` 的结构**：AzurPilot 是 `Deploy.Webui.WebuiPort` 等；WarshipPilot 是 `WebUI.Port`、`Git.Executable`、`Python.Executable` 等。
3. **后端启动参数与端口**：AzurPilot `gui.py --host --port [--key --cdn --ssl-*]`、默认 22267；WarshipPilot `gui.py --root --host --port --no-browser`、默认 22680。
4. **分发与清单**：AzurPilot 用 `launcher-api.azurpilot.com/stable.json` + Cloudflare R2 + CNB；舰R需要自己的清单与下载源，并且必须考虑运行机直连 GitHub 超时（现在靠 `ghfast.top` 镜像）。

另外有一个**必须先定下来的设计点**：现在 WarshipPilot 的网页“更新”会自己拉起安装进程、杀掉并重启 `gui.py`；改由启动器托管后端后，后端的生命周期只能有一个主人（见 §4.3）。

建议范围：**只做 Windows x64**（MuMu、nemu_ipc、pythonw、计划任务都只在 Windows 上），删掉 macOS/Linux 构建与代码分支的发布，CI 和测试量都能减半以上。

## 2. 现有启动器速览

### 2.1 模块

| 模块 | 作用 | 改造程度 |
|---|---|---|
| `src/main.rs` | 入口、参数（`--lang`、`--skip-update`、`--start-minimized`）、窗口与标题栏注入、单实例 | 改名/品牌 |
| `src/launcher.rs` | 唯一状态机：`checking / update_available / updating / idle / deploying / starting / running / stopping / repairing / cancelling / error`，任务槽、进度、事件 | 基本不动 |
| `src/components.rs` | 读 `stable.json` 的 `runtime`：下载/校验/解压 `git`、`adb` 组件到 `.azurpilot/tools/`；按清单从仓库 raw 下载 `deploy/**` 与 `config/deploy.template*.yaml`；`deployment_required` 判定 | **改清单与引导文件列表** |
| `src/setup.rs` | 启动流程：内嵌 uv 装 Python 3.14 + `.venv` → `uv pip install requests` → 迁移 `deploy.yaml` → `deploy.git.GitManager` 拉源码 → `uv sync` → Node.js + `deploy.app` 构建前端 | **重写启动步骤** |
| `src/backend.rs` | 读 `deploy.yaml` 组装 `gui.py` 参数，清理端口占用，进程组拉起，TCP 就绪探测（5 分钟超时），兜底回收 | **改参数与配置路径** |
| `src/backend_env.rs` / `backend_process.rs` | `AP_/ALAS_LAUNCHER_PID`、Windows Job（允许模拟器脱离） | 不动 |
| `src/launcher_control.rs` / `launcher_protocol.rs` | 启动器 ↔ 后端 WS v2（`/api/v2/launcher/ws`）：`session.hello`、自启、通知、免密登录票据 | 不动（后端侧要实现） |
| `src/updater.rs` | 启动器自更新：stable/canary 通道、多源、分片下载、429 退避、原子替换 | **改地址** |
| `src/nodejs.rs` | 下载便携 Node.js 构建前端 | **舰R不需要，跳过** |
| `src/sources.rs` / `settings.rs` | CNB/GitHub 自动选源、Python/PyPI/Node 镜像、设置存 SQLite | 改仓库地址，去掉 Node 项 |
| `src/power.rs` / `tray_menu.rs` / `notify.rs` / `windows.rs` | 防睡眠、托盘、系统通知、WebUI 窗口与连接错误页 | 不动或改文案 |
| `frontend/` | 首页（背景视频、进度、设置/修复/错误对话框） | 品牌与文案 |
| `locales/*.yml` | 四语言文案，大量“AzurPilot” | 改文案（可只保留 zh-CN） |
| `.github/workflows/package.yml` | 三平台打包、组件构建、发布 stable.json 到 Worker、金丝雀 | **重写为 Windows 单平台** |
| `install.iss` | Inno Setup 安装包（`PrivilegesRequired=admin`） | 改名、改权限 |

### 2.2 两段式流程（保留）

- **部署**（首页按钮）：只下载 git/adb 组件和 `deploy/**` 引导脚本 + 当前系统模板，提交 `.azurpilot/installed.json`。
- **启动**（首页按钮）：内嵌 uv 装 Python 与 `.venv` → 迁移 `config/deploy.yaml` → 拉源码 → `uv sync` → 校验仓库自带前端 → 启动 `gui.py` → 端口就绪后打开 WebUI 窗口、隐藏首页。
- **修复**：重下组件和引导脚本、删除重建 `.venv`，保留代码、配置、日志。
- 仓库目录 = 启动器 exe 所在目录（便携式）。

## 3. WarshipPilot 现状与差异

| 项 | AzurPilot（启动器现假设） | WarshipPilot（现状） | 处理 |
|---|---|---|---|
| 平台 | Win/macOS/Linux | 仅 Windows | 只发 `windows-x86_64` |
| Python | 3.14，uv 创建 `.venv` | 3.14，uv；现网是“复制的便携 Python + `.venv`” | 改为启动器用 uv 创建，迁移时重建 `.venv` |
| 依赖 | `uv sync --no-dev --no-install-project` | `uv sync --frozen --no-dev`（`deploy/pip.py`，按 lock+pyproject 哈希跳过） | 启动器调用 WarshipPilot 的同步入口 |
| 源码获取 | `deploy.git.GitManager().git_install()`（含 GitOverCDN） | `deploy/git.py` 的 `Git(root).fetch/apply`，**要求已是 git 仓库** | 新增 `deploy/bootstrap.py`：空目录/非仓库首装 |
| 前端 | 启动时 npm 构建 | `frontend/dist` 随仓库提交 | 跳过 Node.js 与前端构建 |
| 配置 | `config/deploy.yaml`：`Deploy.Webui.*` | `config/deploy.yaml`：`Git / Python / Adb / WebUI / Update` | 改 `backend.rs` 与迁移逻辑 |
| 工具路径 | `.azurpilot/tools/git`、`.azurpilot/tools/adb` | `.venv/git/cmd/git.exe`、`.venv/adb/adb.exe` | 改为 `.warship/tools/...`，迁移时写回 `deploy.yaml` |
| 启动命令 | `gui.py --host --port [--key …]`，端口 22267 | `gui.py --root <dir> --host --port --no-browser`，端口 22680 | 改 `WebuiLaunchConfig` |
| 鉴权 | 启动器打开 `/?launcherTicket=…`，`auth.launcher` | 本机免密；`auth.launcher` 目前直接拒绝 | 第一阶段靠本机免密；第二阶段实现票据 |
| 启动器 WS v2 | 后端实现 `/api/v2/launcher/ws` | 未实现；`launcher.*` RPC 是空实现 | 第二阶段移植 |
| 网页内更新 | AzurPilot 的更新器 | WarshipPilot 自己的 Git 更新器，会自己重启 `gui.py` | **改为委托启动器**（§4.3） |
| 开机运行 | 启动器自启 + `--start-minimized` | 计划任务 `WarshipPilot-Preview`（登录时运行 `hidden.ps1`） | 迁移时禁用计划任务，改用启动器自启 |
| 实例锁 | — | `log/instance.lock`，重复启动会打开已有控制台 | 保留；只回收当前启动器 Job，外部端口占用报错 |
| 网络 | 自动选 CNB/GitHub | 运行机直连 GitHub 超时，用 `ghfast.top` 镜像；PyPI 用清华 | 清单 `urls` 与 `deploy.bases` 都要有国内可达源 |

## 4. 关键设计决定

### 4.1 复用方式：长期 fork，改契约不改机制

舰R启动器在独立仓库 `a2893005741/WarshipPilotLauncher`、本地 `../WarshipLauncher` 维护；原 ALAS 启动器保留在 `a2893005741/alas-launcher`、本地 `../ALASLauncher-Original`。两者 Git 元数据、main 分支、CI、Release、清单、自更新地址、产品标识、设置数据库和自启项全部独立。仅按需参考或移植上游修复，不把舰R改动推送回原 ALAS 仓库。环境协议前缀保留 AP_/ALAS_ 兼容，不表示共享后端或分发。

### 4.2 独立引导与稳定命令入口

`deploy/launcher.py` 在首装阶段只依赖 Python 标准库，禁止顶层导入 `module/**` 或依赖完整环境的 deploy 模块。启动器部署阶段仅下载固定提交的入口与模板，Git/ADB 及引导文件位于 `.warship/`；通过绝对脚本路径调用，避免覆盖源码和首次 checkout 冲突。

```text
python <bootstrap>/launcher.py bootstrap --root <dir> --git <g> --repository <url> --branch main
python <root>/deploy/launcher.py config --root <dir> --python <p> --uv <u> --git <g> --adb <a>
python <root>/deploy/launcher.py update --root <dir> [--target <sha>] [--skip-update]
python <root>/deploy/launcher.py sync --root <dir>
python <root>/deploy/launcher.py commit --root <dir>
python <root>/deploy/launcher.py rollback --root <dir>
```

- 首装：在同卷临时目录 init/fetch/checkout，配置 main upstream 和单分支 fetch 映射，验证项目标记后安装；目标同名源码文件只接受内容一致，否则中止并保留用户文件。config/log 等状态目录保留；仅提交本次创建的 Git 元数据，失败撤销本次写入。
- 已有仓库：验证根目录、项目标记、分支和工作区；不对不明 Git 仓库执行覆盖。
- 在任何 Git 干净检查前，为本安装明确拥有的 `.warship/`、`WarshipPilot.exe`、`.venv.old-*` 添加本地 `.git/info/exclude`。仓库 `.gitignore` 同步声明；用户源码仍受未提交/未跟踪保护。
- `config` 原子保留用户键并更新工具路径；首装生成非空访问码。首次 bootstrap 不依赖 config。
- `update`/`sync` 共用 `log/instance.lock`，记录旧提交和事务阶段到 `.warship/transaction.json`，依赖或 ADB 校验失败立即回退；成功后保留待健康确认状态。启动器验证 `/health` 的 product、pid、commit 后调用 `commit`。新后端失败先停止它，再执行 `rollback`，重新同步旧依赖并恢复旧后端。下次启动先处理未完成事务。
- 启动时遵守 `Git.AutoUpdate`；无网络时如果已有有效安装且未进行源码切换，可使用现有版本启动；显式指定目标的更新失败必须报告，不伪装成功。
- `--json` 使用独立 JSON 行事件，其他工具输出进入日志；保留明确退出码。

### 4.3 后端只有一个主人：网页“更新”委托给启动器

现状：WebUI 点“更新” → `Updater._handover()` 起 `deploy.installer --restart` → 结束 `gui.py` → 安装器更新后自己再拉起 `gui.py`。在启动器下这会被当成“后端意外退出”，进入连接错误页，且新进程不在启动器的 Job 里。

方案：

- 启动器启动后端时已注入 `AP_LAUNCHER_PID`。WarshipPilot 检测到它即进入“托管模式”。
- 托管模式下，`Updater.install()` 不再自己 handover，而是在当前任务结束后，经启动器 WS v2 发送一个**后端 → 启动器**的新命令 `backend.update`（`{target: <sha>}`）。
- 启动器收到后：任务排空后正常停止后端（不算错误）→ 执行事务 update + sync → 启动后端 → `/health` 确认身份和提交 → commit → 打开 WebUI；任一步失败执行 rollback 并恢复旧后端。进度在首页显示。
- 非托管模式（脚本、计划任务、开发）保持现有自更新逻辑不变。
- 这需要先完成 §5.2 的 WS v2。从 P1 第一次托管启动起（必须与启动器同时交付）：托管模式下网页更新按钮提示“请在启动器中更新”，启动器每次点击“启动”都会先 `update`。

### 4.4 分发：GitHub Release 为主，国内镜像为必需的备用

- `stable.json` 放在启动器仓库的 GitHub Release（固定 tag `manifest`）里，或 GitHub Pages；启动器内置多个地址：GitHub 直连 + `ghfast.top` / `gh-proxy` 包装地址。运行机直连 GitHub 超时，**镜像必须在列表里**。
- 组件 ZIP（MinGit、platform-tools）同样传到 Release，`urls` 写“直连 + 镜像”两条。
- `deploy.bases` 写 WarshipPilot 的 raw 地址：`https://raw.githubusercontent.com/a2893005741/WarshipPilot/<完整提交SHA>` + 镜像包装。
- 清单包含完整源码提交 SHA 和引导协议版本，所有引导文件与 SHA-256 均来自该提交；禁止从移动中的 main 读取清单对应内容。清单发布使用并发锁，保留启动器载荷与 runtime 字段；先上传资产，最后发布清单。
- 源码 Git 远端沿用现网做法：`deploy.yaml` 的 `Git.Repository` 可配镜像（现网是 `https://ghfast.top/https://github.com/a2893005741/WarshipPilot.git`）。
- 不再需要 Cloudflare Worker / R2 / CNB；要更稳可以以后加 CNB 镜像仓库。
- 取消上游的“时间炸弹”和遥测类配置（若 fork 中仍有）。

### 4.5 权限

上游 Windows 清单是 `requireAdministrator`，安装器 `PrivilegesRequired=admin`。WarshipPilot 现网以普通桌面用户运行（MuMu IPC 也需要在交互桌面会话里），管理员身份反而会导致每次启动弹 UAC、托盘/计划任务归属错位。建议改为 `asInvoker`，安装器改为当前用户安装（`PrivilegesRequired=lowest`，默认目录 `%LOCALAPPDATA%\WarshipPilot` 或让用户选 D 盘）。端口可配置，不按端口号直接杀进程。先通过 `/health` 验证 WarshipPilot、PID、安装目录，再核对实际进程命令行；本启动器子进程按 Job 回收。其他进程占用端口时报告错误，不结束它。旧实例接管先排空任务并停止原包装/计划任务，然后取得安装锁。

## 5. 改造清单

### 5.1 启动器（alas-launcher）

| # | 文件 | 改动 |
|---|---|---|
| L1 | `Cargo.toml`、`tauri.conf.json`、`Info.plist`、`install.iss`、`icons/`、`frontend/public/icon.png` | 产品名“舰R助手”，`identifier` 改为 `com.warshippilot.launcher`，exe 名 `WarshipPilot.exe`，新图标（可用 WebUI 里的锚形图标放大），去掉时间炸弹段（如有） |
| L2 | `src/setup.rs` | `azurpilot_repo_dir` → `warship_repo_dir`；启动步骤改为：uv 装 Python 3.14 + `.venv` → 标准库 bootstrap → 安装固定 PyYAML → config → 事务 update/sync → 健康验证 → commit（失败 rollback）；删除 `git_update`(GitManager) 与 `app_update`(Node+前端) 两步；修复流程同样改调用 |
| L3 | `src/components.rs` | 引导只下载固定提交的 `deploy/launcher.py` 到 `.warship/bootstrap/launcher.py` 与模板；不覆盖已有源码；`BOOTSTRAP_MARKER` 使用独立引导路径；工具目录 `.azurpilot/` → `.warship/`；只保留 windows-x86_64 |
| L4 | `src/backend.rs` | `WebuiLaunchConfig::from_deploy_config` 读 `WebUI.Host/Port`（默认 `0.0.0.0` / 22680；就绪探测仍连 127.0.0.1）；`args()` 改为 `gui.py --root <dir> --host <h> --port <p> --no-browser`；超时提示中的端口改为实际端口（上游写死了 22267） |
| L5 | `src/nodejs.rs`、设置里的 Node 源 | 不再调用；设置项隐藏（保留代码便于合并上游） |
| L6 | `src/sources.rs`、`src/updater.rs` | 清单地址、启动器更新载荷地址改为 §4.4 的 GitHub + 镜像列表；自动选源“国内”判定时镜像优先 |
| L7 | `src/windows.rs` | WebUI 地址 `http://127.0.0.1:<port>/`；托管窗口标题“舰R助手”；连接错误页文案 |
| L8 | `locales/zh-CN.yml`（其他语言可先删或保持同步） | “AzurPilot / 碧蓝航线”相关文案改为舰R；`tips` 换成舰R的使用提示 |
| L9 | `frontend/`、`bg/` | 首页品牌；`bg.mp4`（10 MB）换成舰R静态图或删除以减小体积 |
| L10 | `.github/workflows/package.yml`、`test.yml`、`tools/build_components.py` | 只保留 windows-x86_64：构建 MinGit/adb 组件 ZIP、生成 `deploy.files`（固定 WarshipPilot SHA 的独立入口与模板）、上传 Release、生成并上传 `stable.json`；去掉 Worker/R2/CNB/金丝雀（金丝雀可后续再加）|
| L11 | 测试 | 保留 `launcher_ws`、`backend_process`、组件安装事务等测试；新增：WarshipPilot 参数组装、`deploy.yaml` 新结构读取、启动步骤命令序列 |

### 5.2 WarshipPilot

| # | 文件 | 改动 |
|---|---|---|
| W1 | `deploy/launcher.py`（新） | §4.2 的四个子命令与 `--json` 进度输出；首装阶段仅依赖标准库，配置/更新子命令按需导入完整仓库模块 |
| W2 | `deploy/launcher.py` 首装分支 | 首装实现放入独立 launcher.py，临时目录拉取、冲突检查和失败撤销；不另造依赖完整仓库的 bootstrap 模块 |
| W3 | `module/config/config.py` / `deploy` 配置 | 工具路径默认值支持 `.warship/tools/git/cmd/git.exe`、`.warship/tools/adb/adb.exe`；旧路径继续兼容 |
| W4 | `module/api/update_service.py` | 托管模式（存在 `AP_LAUNCHER_PID`）下 `install()` 走 §4.3：第一阶段返回“请在启动器中更新”；第二阶段发送 `backend.update` |
| W5 | 启动器 WS v2（第二阶段） | 从 AzurPilot 移植 `module/api/launcher_api.py`、`launcher_protocol.py`、`module/runtime/launcher.py`、`launcher_trust.py`：实现 `/api/v2/launcher/ws`（`session.hello`、`state.report`、`login.issue`、`notifications.ack`、`system.ping`，以及新增 `backend.update`）；`module/api/alas/router.py` 的 `launcher.*` 接上真实服务；`auth.launcher` 接受票据；恢复设置页的“启动器”卡片 |
| W6 | 通知（第二阶段，可选） | 调度器连续失败停止、远征全部读不出等事件 POST `/api/v2/internal/notifications`，启动器弹系统通知 |
| W7 | 测试 | `deploy.launcher` 各子命令（含空目录首装、已有配置保留、镜像回退）；托管模式更新分支；WS v2 握手与票据 |

### 5.3 不改的

- WarshipPilot 的任务、OCR、调度、WebUI 前端。
- 启动器的 Job 与组件事务核心。状态机需接入更新事务提交/回退；新增 backend.update 必须同时修改 Rust 协议验证、能力协商、命令派发和测试，不能声称原样不动。

## 6. 现有安装的迁移（D:\WarshipPilot）

目标：用户把新启动器 `WarshipPilot.exe` 放进 `D:\WarshipPilot`（与 `.git`、`config/`、`log/` 同级），双击后接管现有安装，不丢配置、调度状态、访问码、远征计时记录。

1. 只读预检：通过健康接口和实际进程路径定位安装，核对 Git 分支/脏文件、当前任务、计划任务、快捷方式和写权限；仅 `gui.py` 文件存在不足以证明可接管。
2. 排空当前任务，保存调度状态，停止旧后台及包装并等待退出；暂时禁用旧计划任务防止重启。取得安装锁后备份 `deploy.yaml`、计划任务 XML、快捷方式和旧环境；备份位于仓库外且有恢复记录。
3. 只部署工具与独立引导。为旧仓库补齐本地 exclude 后检查工作区，准备 uv 环境和工具配置，再执行事务更新与依赖同步。新环境切换失败自动恢复旧配置和环境；不删除旧备份。
4. `/health` 确认产品、PID、安装目录和提交，原调度/访问码/计时记录保持，commit 后才改快捷方式并启用启动器自启。旧计划任务保留为禁用。
5. 回退：退出启动器并停止其后台 → 按迁移记录恢复旧提交/环境/工具配置/快捷方式/计划任务 XML → 恢复原计划任务启用状态 → 验证健康和调度。备份仅在显式清理时删除。

需要在远端实机验证：迁移前后 `config/warship.json`、`config/deploy.yaml` 的访问码、`Scheduler.Enable/NextRun`、`log/expedition-timers.json` 不变；自动连接 MuMu；远征/战役/任务奖励按时运行一轮。

## 7. 分阶段计划与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 品牌与契约 | L1–L8、W1–W4 第一阶段、事务更新与归属检查；Windows 单平台；本地构建可运行 | 空目录：部署 → 启动 → 打开 WebUI，总览可用；已有仓库目录：不重新克隆，配置保留；停止/再启动/修复可用；关闭首页最小化到托盘 |
| P2 分发 | L6、L10；Release 上的 `stable.json` 与组件；镜像地址 | 运行机（GitHub 直连超时）上首装与启动器自更新都能完成；校验失败会回退备用源 |
| P3 迁移远端 | §6；已有安装接管与完整回退 | D:\WarshipPilot 被接管，旧计划任务禁用，开机自启生效，三项任务按时运行，数据不丢 |
| P4 启动器协议 | W5、W4 第二阶段、W6 | 网页“更新”由启动器执行并自动重启；启动器开 WebUI 免密（票据）；设置页可开关开机自启；任务失败有系统通知 |

每阶段都要在远端实机跑一遍，并保留截图与事件日志。

## 8. 风险与需要确认的问题

1. **分发地址**：是否接受 GitHub Release + `ghfast.top` 等公共镜像？公共镜像不保证长期可用，建议至少两家；或另建 CNB/Gitee 镜像仓库（需要账号）。
2. **代码签名**：未签名的 exe 可能触发 SmartScreen 提示。上游有 `docs/windows-signing.md` 与签名脚本，需要证书；不签名的话首次运行要手动“仍要运行”。
3. **安装位置与权限**：采用 §4.5 的 `asInvoker` + 当前用户安装是否可以？
4. **语言**：只保留简体中文可以减少维护；保留四语言需要同步翻译。
5. **上游跟进**：长期 fork 后，上游的协议或状态机若大改，合并成本会上升；建议每次合并前跑完 §5.1 L11 的测试。
6. **防睡眠**：启动器的“阻止计算机自动睡眠”对挂机有用，建议默认开启并在设置中保留。
7. **多实例**：启动器与 WebUI 都按单实例设计，如将来要多开 MuMu 需另行设计。

## 9. 参考

- 启动器文档：`docs/launcher-ui.md`、`docs/runtime-components.md`、`docs/backend-lifecycle.md`、`docs/launcher-protocol-v2.md`（alas-launcher 仓库）
- WarshipPilot：`deploy/installer.py`、`deploy/git.py`、`deploy/pip.py`、`module/api/update_service.py`、`module/api/alas/`、`docs/source-deployment.md`
- AzurPilot 后端的启动器实现（移植来源）：`H:\ALAS\AzurPilot\module\api\launcher_api.py`、`launcher_protocol.py`、`module/runtime/launcher.py`、`launcher_trust.py`

## 10. 实施记录（2026-11-17）

- 已实现 Windows 启动器与后端入口，源码在相邻 WarshipLauncher。已移除后端 Node 构建调用，普通用户运行，品牌/图标与独立设置、自启项分离。
- 独立首装、固定提交与摘要、事务更新/回退、环境备份、真实 Job 身份健康检查均已落地。额外处理 uv Windows 跳板的真实 PID，以及后台握手早于启动任务完成的竞态。
- WS v2、一次性票据、自启设置、网页任务排空后委托更新、调度停止通知已接入。
- 150 项 Python、109 项启用的 Rust 测试、22 项启动器前端与10项打包工具测试通过。后端前端另有原305项和新增LauncherCard状态机覆盖。
- EXE 隔离实测：首装、重复启动、修复保留旧环境、拒绝外部端口、坏提交健康失败回退均通过。网页→Python WS→Rust→停止/更新/回退/重启的真实进程验证通过。
- 迁移入口 scripts/migrate-launcher.ps1 默认只读，Apply 才排空任务、备份旧入口并接管，Rollback 可恢复。远端切换结果另记验收报告，不以本地测试代替。

- 用户明确的隔离要求：原 ALAS 与舰R启动器使用独立仓库。原 alas-launcher 内容已恢复到改造前版本；舰R分发迁至 WarshipPilotLauncher。
