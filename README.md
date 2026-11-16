# 舰R助手 WarshipPilot

Windows EXE + ALAS 式 WebUI。直接运行从舰娘肝帝 6.7.7 恢复的原 Lua 函数，接入远征收取与继续派遣、原方案 C 出征。当前目标：DESKTOP-3F63TNA 上的 MuMu 舰R实例 127.0.0.1:16416、1280×720。碧蓝实例 emulator-5554 不参与输入。

## 使用

双击完整发布目录中的 WarshipPilot.exe，到“设备设置”发现并选择舰R实例。停止旧脚本后运行任务。

- “远征”→“运行一次”：**原生 Python 任务**（backend/tasks/expedition.py）。港区有远征完成标记时进入远征页，收取亮起的槽位，确认原舰队继续派遣，返回母港结束；页面识别与坐标取自原脚本（assets/pages.json、backend/ui）。
- “设备设置”→“截图与控制方式”：截图 nemu_ipc / ADB / ADB_nc / DroidCast / DroidCast_raw / uiautomator2 / scrcpy，控制 nemu_ipc / MaaTouch / minitouch / ADB / uiautomator2 / scrcpy（移植自 ALAS）。“测试全部截图方式”只截图、不点击，并与 ADB 无损截图比对全部颜色检查；“测试全部控制方式”在出征页远征/演习标签之间切换以确认游戏响应。默认截图 nemu_ipc、控制 ADB。
- “常用图”→“运行一次”：原方案 C，6-1、第二舰队、α入口、第一战单横、不夜战；沿用原撤退和快速修理设置，关闭大破出征／进击。执行次数连接原“战斗次数限制”，达到原条件后转收远征并回母港。
- 运行中可以暂停、恢复、立即停止。启用任务后再启动调度器，按优先级、首次计划时间和完成后的间隔运行。计划时间使用运行电脑的本地时间。
- 总览切换日志／截图；按设置保留任务截图，异常自动保存现场。战役、演习尚未接入。

顶部实例标签、左侧任务树、调度区及参数页沿用 ALAS 的界面结构。原函数直接识别当前游戏画面，无需用户预先采集整套素材。工具页保留可选的样本和素材核对。

## 原脚本复用

assets/legacy/main.lua52.luac 包含恢复的 400 个原函数。转换仅调整指令编号和标准 Lua 5.2 序列化格式，未改原函数的分支、坐标、滑动参数或延时。由 Lupa 的 Lua 5.2 引擎执行。

backend/legacy_vm.py 适配旧 SDK 的截图、查色、配置、字符串、日期和文件操作；backend/automation.py 将原函数产生的点击与触控序列接到 ADB。原出征遇到远征完成或次数限制会返回，随后调用原收远征函数回港。

兼容差异：当前游戏新增的“继续远征”确认框由标题和问题模板识别，再调用原固定延时点击函数；旧引擎变速插件未移植，按游戏原速运行。未知接口会停止并保存现场。仅迁移原业务设置，不执行原账户、注册或云服务初始化。

当前仅开放固定原方案 C；其它关卡和舰队尚未开放。assets/legacy 也保留 624 条颜色规则和出处。

## 文件夹与局域网

和 ALAS 一样，所有内容都在程序文件夹里：

```
WarshipPilot\
  WarshipPilot.exe
  _internal\    程序文件
  data\         access.json 访问码、config.json（模拟器 Serial、截图/控制方式）、task-drafts.json 任务配置、
                scheduler.json 调度状态、records.sqlite3 日志、runs 任务截图、faults 故障资料、updates 更新
```

0.5.1 及以前的数据在程序旁的 WarshipPilot-data；新版首次启动时复制进 data\（旧目录不改动）。
启动后自动连接「设备设置」里填写的模拟器 Serial；调度器开关会保存，重启或更新后自动恢复。
双击新版本时，旧版本若在运行会被通知退出并由新版接管。关闭网页不停止后台；右上角电源按钮退出。
MuMu IPC 要求后台与 MuMu 位于同一桌面用户会话。

默认监听 0.0.0.0:22680，局域网浏览器访问需要 data\access.json 里的访问码；只允许本机访问时在 data\config.json 写 `"host": "127.0.0.1"` 或用 `--host 127.0.0.1` 启动。不要分享 access.json、console-url.txt 或私人游戏截图。

## 内置更新

左侧「软件更新」：检查 GitHub Release，下载 `WarshipPilot-<版本>-win-x64.zip` 并按 SHA-256 校验后，后台退出并**原地更新**——robocopy 只覆盖有变化的文件，data\ 不动，旧程序文件备份在 data\updates\backup，新版本启动失败自动恢复。私有仓库需要只读访问令牌（fine-grained token，仅此仓库 Contents: Read）。发布：改 backend/version.py 后运行 scripts/release.ps1。

## 开发与构建

开发需要 Python 3.14、uv 和 Node.js 20.19+/22.12+；运行 EXE 无需安装这些工具。

```powershell
uv sync --frozen --group build
cd frontend
npm ci
npm run build
cd ..
uv run python main.py
pwsh -File scripts/build.ps1 -OutputRoot dist-v0.4
```

目录版包含 Lua 5.2、ADB、前端及必需资源。MuMu截图直接复用ALAS的NemuIpcImpl与线程池，读取运行电脑已有IPC SDK；不可用时回退ADB并记录原因。识别帧按原KeepCapture指令更新，点击和延时不额外截图。scripts/upgrade-remote.ps1 备份程序和数据后更新，启动失败回滚。scripts/run-legacy-remote.py 是开发实机入口，运行同一个任务控制器，没有独立任务路径。

ALAS 迁移代码及其修改按 GPLv3 提供，见 LICENSE 和 docs/ALAS-PORT.json。旧脚本恢复产物仅用于本次个人迁移，权利归原作者。未做长时间挂机验收。
