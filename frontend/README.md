# 舰R助手 WebUI

界面取自 AzurPilot（H:\ALAS\AzurPilot\frontend，React 19 + Tailwind 4 + Radix），删去碧蓝专用页面后由 WarshipPilot 后端 `module/api/alas` 以 AzurPilot 的 WebSocket RPC 协议提供数据。舰R独有的设备页与工具页在 `src/warship/`。

```bash
npm ci
npm run dev        # 开发：代理到 AZURPILOT_BACKEND（默认 http://127.0.0.1:22267）
npm run build      # 产物 dist/ 随仓库提交，运行机不需要 Node
npm test           # vitest 单元测试
npm run test:mobile # 构建后运行手机端浏览器回归（需要 Playwright Chromium）
```

手机和平板直接访问现有 WebUI 地址，宽度不超过 950px 时自动使用底部导航。总览可切换运行任务和日志画面；“任务”打开可搜索的任务列表，“更多”进入工具、故障记录、更新和设置。参数页顶部可横向滑动选择分组，运行状态与任务计划按需展开。手机与电脑使用同一访问码和配置。

手机回归使用临时配置和真实后端接口，后台设备循环暂停，不连接模拟器。覆盖菜单、调度器启停、参数保存、320–950px 页面布局和桌面切换。
