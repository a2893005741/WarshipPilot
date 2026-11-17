# WarshipPilot 交接方案（2026-11-17，接手：Codex）

## 1. 基本信息

| 项 | 值 |
|---|---|
| 仓库 | `H:\ALAS舰R版本\WarshipPilot`，GitHub `a2893005741/WarshipPilot`，**只有 `main` 一条分支**，发布打 tag `vX.Y.Z` |
| 当前版本 | `v0.10.1`（修复提交 `28fdeed`，收尾记录见第7节），本地与 GitHub 同步、工作区干净（除本文件） |
| 远端运行机 | `DESKTOP-3F63TNA`，安装目录 `D:\WarshipPilot`，MuMu `127.0.0.1:16416`，WebUI `127.0.0.1:22680` |
| 远端凭据 | `%LOCALAPPDATA%\Codex\Credentials\DESKTOP-3F63TNA.xml`（`Import-Clixml` 后 `Invoke-Command -ComputerName DESKTOP-3F63TNA -Credential`） |
| API 鉴权 | `Authorization: Bearer <deploy.yaml 的 WebUI.AccessCode>` |
| 测试 | `.\.venv\Scripts\python.exe -m unittest discover -s tests`（当前 112 项全过） |
| 参考源 | 用户维护的 ALAS 分支 `H:\ALAS\AzurPilot`（OCR 等结构照它移植）；原脚本提取物 `H:\ALAS舰R版本\旧脚本提取`（`原函数\*.lua` 为反编译结果，`main-prototype.json` 为常量） |

### 部署流程（每次改动后都要实机验证）
1. 本地测试通过 → 改 `module/version.py` 与 `pyproject.toml` 版本 → `uv lock` → commit → `git tag -a vX.Y.Z` → `git push origin main --tags`
2. 远端：`POST /api/update-check`，再 `POST /api/update-install`（Body `{}`），轮询 `GET /health` 直到 `version` 变成新版本（更新器会 `git reset --hard` + `uv sync --frozen`，失败自动回滚）
3. 手动跑一次任务：`POST /api/task-control` Body `{"action":"start","task":"<expedition|campaign|reward|sortie>"}`，轮询 `GET /api/state` 的 `automation.running/status/error`
4. 看事件：远端 `D:\WarshipPilot\log\records.sqlite3` 表 `events(time, level?, message)`

注意：远端是 PowerShell 5.1（无三元运算符）；把含中文的 Python 脚本通过 stdin 管道传过去会乱码，打印时用 `m.encode('unicode_escape').decode()`，本地再 `[regex]::Unescape()`。

## 2. 本次会话已完成

- 分支整理：`main` 快进到最新，删除 `native-rewrite`、`refactor/source-deployment`，远端安装也切到 `main`；补齐 v0.4.0～v0.10.0 标签。
- 清理：删除日志、旧打包、缓存约 2.7 GB；停掉本机遗留的冒烟测试实例。
- v0.8.x 远征按游戏倒计时调度：`module/ocr/`（照 AzurPilot 移植 Ocr/Digit/DigitCounter/Duration + alocr-en-us-v2.6 ONNX 模型 + OCR 字形模板快速路径与自动学习）、`module/expedition/timer.py`、逐章翻页读倒计时；章节切换用“选中章节图块”判断（整列判断在实机上会误判）。
- v0.9.0 利用游戏的远征自动跳转：`module/expedition/memory.py` 记录各章各舰队结束时刻（`log/expedition-timers.json`），之后只补读本轮收取过的章节，没有完成的远征时零输入；记录过期（12h）、认不出章节、有舰队超时未收时全部重读。实机验证了“全部重读”和“沿用记录”两条路径。
- v0.10.0 战役与任务奖励：执行原 Lua 函数 `打战役` / `收任务`（`module/legacy/vm.py` 的 `ENTRIES`），新任务键 `reward`；LegacyVM 支持画布切换（SDK 191）并只在 `战役剩余次数` 内让 GetScreen(44) 返回物理尺寸；拒绝原脚本的结束/重启游戏（SDK 177/222），战役SL 固定关闭；`controller.legacy_next_run` 按原函数状态排下次（次数用完→次日计划时间；泡澡→原脚本 900000ms 后；其他→重试间隔）。
- **收任务已实机验证通过**（09:55：点任务→一键领取→处理“获得资源”→返回港区，12 秒）。

## 3. 交接时待办（3.1～3.4 已完成，结果见第7节）

### 3.1 确认战役实机运行结果【已完成】
09:56 手动启动了 `campaign`，10:07 时仍在运行（战斗中，104 次输入，“战役战斗中 n/200”计数持续归零=画面有进展，无报错）。设置为：战列 / 困难 / 复纵 / 大破快修。
需要做：
1. 查事件里是否出现 `完成：原脚本打战役；下次 …（今日战役次数已用完）`。若原因不是“今日次数已用完”，说明 `战役剩余次数` 没识别到 0 次——到远端保存战役页截图，用 `tests/test_legacy_tasks.py` 里同样的方式核对原 720 分支点集 `103|225|424242,...` 在 1280×720 画面上的位置（`pixel()` 在 720×1280 画布下是 1:1 映射：屏幕 X=y，Y=719-x）。
2. 若任务 `fault`：看 `error` 和 `log/` 下的故障截图；常见可能：原函数用到尚未适配的 SDK 号（`vm.sdk` 抛 “原脚本运行接口尚未适配：N”）→ 查 `原函数\打战役.lua` 中该号用法后在 `vm.sdk` 实现；页面长时间无进展（controller 非战斗页 150s、战斗页 360s 看门狗）。
3. `打战役` 内部遇到远征完成会调用原 Lua `收远征`，这会让原生远征的计时记录与实际不符；预期行为是下一次原生远征检测到“有舰队超时未收/认不出”后自动全部重读。确认这一点（看下一轮远征事件是否为“全部章节重新读取”且无故障）。

### 3.2 新任务的默认值没生效【已修复】
远端 `reward` 运行后显示“间隔 60 分钟”，而 schema 默认是 30；`campaign` 计划时间远端仍是 `00:00`（schema 默认已改为 `00:10`）。原因：`module/config/task_settings.py` 的 `read_tasks` 在没有保存值时用 `TaskDraft` 的通用默认（interval 60、start 00:00），没有用 `schema()['args'][task]` 里各字段的 `value`。
修法：`read_tasks` 对缺失字段用 schema 默认值填充（`storage == 'task'` 的字段按 `key` 映射）；补测试：全新 root 下 `read_tasks()['reward']['interval_minutes'] == 30`、`['campaign']['start_time'] == '00:10'`。已保存过的实例值保持不变。远端的 campaign 已有保存值 `00:00`，部署后用 `save_field` 或网页改成 `00:10`（0 点刷新后留余量）。

### 3.3 在调度器里启用两项任务【用户已同意，已启用】
远端目前只启用了 `expedition`（调度器已开，`Scheduler.Enable=true`）。战役确认正常后，经用户同意再启用 `campaign.Scheduler.Enable` 与 `reward.Scheduler.Enable`（API：`POST /api/config-field` 或网页任务页）。启用前确认 campaign 的 StartTime 已是 `00:10`。

### 3.4 远征“只补读”路径首次实机确认【已完成】
v0.9.0 的“只补读本轮收取的章节”还没在实机上走过（测试已覆盖）。下一次远征到点（原定 10:30，可能被战役推迟）后看事件：应为“远征逐章倒计时（只补读本轮收取的章节，其余沿用记录）”且无“上一章/下一章”翻页点击。若因 3.1 第 3 点触发全部重读也属正常，再等下一轮。

### 3.5 其他（未开始，用户未要求）
演习（`exercise`）、决战（`decisive`）、方案 A/B 仍是“只保存配置、不执行”。若后续要做，沿用同一路径：`vm.ENTRIES` 加入口（原函数 `打演习`、`决战` 等），在 `task.yaml` 设 `executable: true`，在 `controller.SUPPORTED/NAMES/SOURCES` 与 `task_settings.EXECUTABLE` 登记，再按原函数里的时间戳/状态写 `legacy_next_run` 规则，先单测再实机。

## 4. 关键文件

| 文件 | 作用 |
|---|---|
| `module/legacy/vm.py` | 原 Lua 执行器：`ENTRIES`、配置覆盖、SDK 适配（44/191/177/222 等）、画布映射 `pixel()` |
| `module/runtime/controller.py` | 调度与任务生命周期：`SUPPORTED`、`complete()`、`legacy_next_run()`、`next_run()`（远征）、`chapter_summary()` |
| `module/runtime/native.py` | 原生任务线程（远征），传 `survey_dir`/`memory_file` |
| `module/expedition/expedition.py` / `timer.py` / `memory.py` | 原生远征、倒计时识别、计时记录 |
| `module/ocr/` | OCR（AzurPilot 结构）+ 模板 |
| `module/config/argument/{task,argument,override}.yaml` | 任务与字段定义；改完运行 `.\.venv\Scripts\python.exe -m module.config.config_updater` 生成 args/menu/schema/template |
| `module/config/task_settings.py` | `TASKS`、`EXECUTABLE`、`read_tasks`（见 3.2） |
| `docs/source-deployment.md` | 各版本设计说明（v0.8～v0.10 已追加） |
| `H:\ALAS舰R版本\旧脚本提取\原函数\打战役.lua` 等 | 本次新反编译：打战役、收任务、战役剩余次数、任务特征、点亮标签、返回键（生成方式：lupa 载入 `assets/legacy/main.lua52.luac` → `string.dump` 全局函数 → `java -cp tools\unluac-build unluac.Main` → `dev_tools/legacy_extract/readable.py`） |

## 5. 约束与习惯（用户偏好）

- 功能优先套用 `H:\ALAS\AzurPilot` 的结构，并先查原脚本是否已有对应数据/逻辑；原脚本没有的要明确说明。
- 改完必须部署到远端并实机跑一次，单测通过不算完成（本次远征翻页两次在实机上才暴露问题）。
- 不要让程序结束/重启游戏；不要改游戏或模拟器设置。
- 远端更新器要求远端工作区干净：不要往 `D:\WarshipPilot` 的受版本控制路径写文件，缓存放 `log/`。
- 提交信息结尾加：`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`（换成 Codex 时按其约定）。

## 6. Codex 接手记录（本节取代上文的交接时状态）

- 2026-11-17 10:13 现场核查：战役已于 10:09:57 正常回港；完成原因为“今日战役次数已用完”，原任务138次输入，无异常。3.1 的战役结果已确认。
- 用户在本次接手会话中明确同意：启用战役和任务奖励的自动调度。
- 默认值错误已通过回归复现：空任务和部分分组配置错误取60分钟/00:00；现先读取任务schema默认值，再覆盖已保存参数。保留已存60分钟/00:00的回归也通过；全套112项通过。
- 本次版本 v0.10.1；后续部署与远征现场结果继续在本节记录。

## 7. 现场验证进度（2026-11-17，UTC+8）

| 事项 | 结果 |
|---|---|
| 战役原运行结果 | 10:09:57 完成回港，138次输入，今日次数已用完，无错误 |
| 默认值修复 | 缺失字段使用任务schema，显式旧值保持；112项回归通过 |
| 发布与部署 | main 28fdeed / v0.10.1 已推送，远端更新后自动重启 |
| 部署后战役复跑 | 10:20:08 正常结束，11次输入，今日次数已用完 |
| 部署后任务奖励 | 10:20:43 领取奖励并处理获得资源后回港，8次输入 |
| 部署后远征 | 10:20:44 无完成项，零输入沿用记录，4支远征在外 |
| 自动调度 | 用户已同意并启用战役、任务奖励；保留远征，总计3项 |
| 战役计划 | 00:10，下一次为11月18日00:10 |
| 奖励间隔 | 30分钟；10:21复跑后实际计划10:51，无红点零输入 |
| 远征部分补读 | 10:30:31 自动收取1个远征并继续派遣，5次输入，partial路径完成，无故障；下一次10:52:27 |

原脚本内若代收远征，计时记录过期舰队没有被本轮原生任务收取时，现有代码会通过 overdue 集合检查退回全读；该分支已有回归测试。本次战役后的无完成项远征记录仍可用，不需要强行全读。


收尾核验：

- 10:30:31 的事件1383明确为“远征逐章倒计时（只补读本轮收取的章节，其余沿用记录）”。本轮5次输入完成进出远征、收取和继续派遣，没有全章翻页；4支远征在外，其余章节结束时间沿用。
- 战役当天次数已用完的两次实测均正常回港；没有出现原接口未适配、任务故障或游戏重启。
- 分支整理遗留的远端Git fetch映射仍指向已删的refactor/source-deployment。本次已将fetch映射修正为main，并使main跟踪origin/main；工作区干净，同步差异0/0。
- 本次未接入演习、决战或方案A/B；不属于交接收尾范围。
- 远端实测记录：log/handoff-20261117-campaign.json、reward.json、expedition.json，以及log/handoff-20261117-acceptance.json；本地材料在.deployment/handoff-20261117/。
