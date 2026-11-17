# 舰R独立启动器交付验收

日期：2026-11-17；平台：Windows x64；启动器：3.0.7。

## 仓库与产品隔离

| 用途 | 本地源码 | GitHub 仓库 |
|---|---|---|
| 原 ALAS 启动器 | `H:\ALAS舰R版本\ALASLauncher-Original` | `a2893005741/alas-launcher` |
| 舰R启动器 | `H:\ALAS舰R版本\WarshipLauncher` | `a2893005741/WarshipPilotLauncher` |
| 舰R后端 | `H:\ALAS舰R版本\WarshipPilot` | `a2893005741/WarshipPilot` |

原启动器恢复提交29daac9的文件树与改造前185e8ad一致，工作区干净，原Release未改动。舰R独立仓库的origin仅关联WarshipPilotLauncher；产品标识、设置、自启项、组件与自更新清单独立。

## 发布与本地验证

- 独立启动器提交：074c466e7568bf9d458944f8b6acdb1046344c53。
- 测试工作流44058877112、发布工作流44059355516均成功。
- 发布位置：[舰R启动器3.0.7](https://github.com/a2893005741/WarshipPilotLauncher/releases/tag/v3.0.7)。runtime和manifest Release均位于同一独立仓库。
- 正式EXE：41,282,048字节；SHA-256：`361eb60dbd6485c72ba62d887797e255b4ee8e721f755d9e8e760d6b49e04676`。本地release/WarshipPilot.exe与远端实际使用文件均核对该摘要。
- 发布清单引导固定后端66646052eaa2a9b5671e12156ebf041879e6f607；清单内EXE/组件地址没有指向原alas-launcher仓库。
- Python150项、后端前端313项、启用的Rust109项、启动器前端22项通过。打包工具11项中10项通过，Unix软链接布局测试在Windows跳过。
- 真实EXE隔离验证通过：空目录首装、再次启动、修复保留旧环境、拒绝外部端口、坏提交启动失败回退。真实网页更新协议链的坏提交回退验证通过。

本地证据：`.deployment/launcher-smoke-20261117-160029/acceptance.json`、同目录`native-update-acceptance.json`、`native-ui.log`；发布清单快照为`.deployment/published-launcher-manifest.json`。

## 远端接管与更新

目标：DESKTOP-3F63TNA的`D:\WarshipPilot`。本次迁移未操作原ALAS安装。

1. 排空当前任务，保留调度开关；禁用旧WarshipPilot-Preview计划任务，再由交互式桌面任务部署组件和启动新后台。
2. 迁移前后`warship.json`完整摘要、任务参数、访问码摘要、Scheduler.Enable/NextRun和远征计时文件摘要完全一致。Git工作区干净。
3. 运行环境切换为uv管理，Git/ADB使用`.warship/tools`。旧环境保留在`.warship/backups/environment-20261117-180728-331679300/.venv`，备份记录已提交且旧环境目录存在。
4. 迁移后台PID由12416变为20852；产品、根目录和提交核对正确。WebUI返回200，MuMu自动连接就绪，截图nemu_ipc、控制ADB。
5. 启动器WS v2报告已连接，版本3.0.7，具备autostart、notifications、login和backend.update能力；当前用户自启已启用，指向`D:\WarshipPilot\WarshipPilot.exe --start-minimized`。旧计划任务保持禁用。
6. 从网页更新接口请求f64f5e2更新至87c79a4f27ad469767c3081ce7d0bdcbb20a9504，启动器9400保持运行，后台PID20852→23820，新提交健康检查通过，事务文件已清除。该次HTTP请求在后台重启时连接关闭，成功结论依据重启后的PID、提交、健康状态与WS重连。
7. 更新后通过真实WebUI任务接口调用远征，任务正常完成回港，调度保持开启；现场没有待收远征，记录收取0、输入0。未额外触发战役或等待全部自然任务周期，因此不把此次验收写成长期挂机或战役实战验收。

迁移时发现计划任务的上次运行时间落后于系统时间，旧脚本会继续等待已经完成的组件部署；当前脚本改为比较运行记录是否变化，避免跨时钟同步比较。脚本PowerShell语法检查通过；现场通过重新执行幂等组件检查完成迁移。

恢复入口备份：`D:\WarshipPilot-launcher-backup-20261117-180451`。其中保存deploy.yaml、旧任务XML、快捷方式和迁移记录；新环境与原环境都保留。迁移脚本支持Rollback指定该目录。

远端证据：`D:\WarshipPilot-launcher-evidence`。本地副本：`.deployment/launcher-before-remote.json`、`launcher-after-remote.json`、`launcher-migration-comparison.json`、`launcher-remote-verification.json`、`launcher-remote-expedition.png`。访问码仅保存摘要。
