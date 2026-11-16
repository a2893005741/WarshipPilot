# 源码部署验证（2026-11-17）

本次从 native-rewrite 建立 refactor/source-deployment，将 v0.5.2 的打包安装改为 v0.6.0 的仓库安装。原识别素材保持不变：101 个页面名称、149 个匹配分支；原生远征与恢复的 Lua 出征仍使用原执行路径。

## 已验证

- 搬迁前、仅搬迁后：原有 57 项测试均通过。
- 集中配置、复制迁移和 Git 更新完成后：66 项回归通过，包含 WAL 数据复制、旧数据不覆盖新配置、迁移幂等、并发配置段保存、Git 分叉/本地修改保护、镜像拉取、任务结束后更新和依赖失败恢复原提交。
- TypeScript 检查、Vite 生产构建通过；frontend/dist 随仓库提交。
- 源码 WebUI 的启动、访问码鉴权、接口和干净退出通过。
- scripts/check-source-update.py 使用真实本地 bare 仓库验证：克隆后启动 GUI，推送新提交，通过 update-check/update-install 发起更新，后台进程退出后由安装器拉取并重启；确认进程号改变、提交更新、调度开关/下次运行时间/访问码保持、无依赖变化时跳过同步。
- 对便携环境强制执行 uv sync 验证通过；Python 标准库、OpenCV、Lupa Lua5.2 从包含在环境内的解释器正常加载。

## 初次部署要点

普通 Windows 虚拟环境中的 Python 可能包含开发电脑解释器的绝对路径。prepare-runtime.ps1 使用系统基础 Python、完整复制其标准库和 DLL，并替换 uv 的 Windows 重定向程序；启动器通过 rebase-runtime.ps1 为当前安装目录更新 pyvenv.cfg。

远端当前使用 D:\WarshipPilot-0.5.2-win-x64，最新数据在它的 data 下。初次部署按 22680 监听进程定位实际目录，优先复制该数据，保留旧安装和数据。旧 D:\WarshipPilot 会以带时间戳的目录备份。

远端 GitHub 直连超时，GitHub 镜像入口与清华 PyPI 可访问；deploy.yaml 的 Git.Repository 允许为该运行电脑配置镜像，Git.Branch 对应推送分支。安装器还会使用实际便携 Git 验证更新源，成功后才切换旧安装。

首次部署使用 scripts/deploy-remote.ps1，必须在已提交、干净的源码仓库运行。计划任务和桌面快捷方式通过隐藏窗口包装运行 WarshipPilot.bat，MuMu IPC 保持在已登录用户会话中。

记录、故障图片和便携运行环境不提交。后续仅提交和推送代码，运行电脑从网页或下次启动时更新。
