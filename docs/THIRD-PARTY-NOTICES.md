# 第三方组件

v0.4 的 backend/alas 迁移了 AzurPilot 的 Timer、Page、Button.match、NemuIpcImpl 及其线程池，设备输入参考其 ADB 实现。源文件哈希见 ALAS-PORT.json，按 GPLv3 提供，完整许可随包分发。WebUI 按 ALAS 布局独立实现。

主要组件：React（MIT）、Vite（MIT）、TypeScript（Apache-2.0）、Lucide（ISC）、Starlette（BSD-3-Clause）、Uvicorn（BSD-3-Clause）、Pydantic（MIT）、Pillow（HPND）、NumPy（BSD-3-Clause）、OpenCV（Apache-2.0）、wsproto（MIT）、Lupa（MIT）、Lua 5.2（MIT）、PyInstaller（GPL-2.0-or-later，含分发生成程序的例外）。实际 Python 依赖及其元数据随 _internal 目录提供；锁定版本见 uv.lock、frontend/package-lock.json。

ADB 为 Android platform-tools 的组件，以官方授权条款为准。随包 ADB 来自构建机器已有 C:\adb，未修改二进制。

舰R画面归游戏权利人所有；页面样本属于用户本机运行资料，不随公开源码或通用发布包分发。

目录版内含用户提供的“舰娘肝帝6.7.7”脚本中恢复的400个函数、筛选后的业务设置、颜色表达式、函数/变量名及说明素材，用于本次个人迁移；其权利归原权利人，未另行授予公开再分发许可。assets/legacy内不含旧APK、私人注册码或取证工具。
