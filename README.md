# HyMail

HyMail 是一个本地 Windows 个人邮箱聚合管理工具。

当前目标：v0.0.1，交付“单账号 IMAP 同步引擎 + 可观测状态面板”的垂直切片。

## 仓库结构

apps/api        FastAPI 本地服务
apps/desktop    React + Tauri 桌面端
apps/mock-imap  可注入故障的 mock IMAP
packages        OpenAPI 生成的前端 client
docs            架构与演示文档