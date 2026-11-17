# 舰R助手 WebUI

界面取自 AzurPilot（H:\ALAS\AzurPilot\frontend，React 19 + Tailwind 4 + Radix），删去碧蓝专用页面后由 WarshipPilot 后端 `module/api/alas` 以 AzurPilot 的 WebSocket RPC 协议提供数据。舰R独有的设备页与工具页在 `src/warship/`。

```bash
npm ci
npm run dev        # 开发：代理到 AZURPILOT_BACKEND（默认 http://127.0.0.1:22267）
npm run build      # 产物 dist/ 随仓库提交，运行机不需要 Node
npm test           # vitest 单元测试
```
