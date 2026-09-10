# HyMail

HyMail 是一个本地 Windows 个人邮箱聚合管理工具。

v0.0.1 交付一条完整垂直切片：

- 单账号 IMAP 配置
- 163 / QQ / 自定义 IMAP
- Windows DPAPI 加密授权码
- 初始同步与增量同步
- SQLite + WAL 本地存储
- 同步状态机与游标持久化
- FastAPI 接口
- React 可观测面板
- Tauri dev sidecar
- Mock IMAP 与关键故障测试

## 仓库结构

    apps/api        FastAPI 本地服务
    apps/desktop    React + Tauri 桌面端
    packages        OpenAPI 生成的前端 client
    docs            架构与演示文档

## 环境要求

    Windows 10/11
    Node.js 24+
    pnpm 11+
    Python 3.12
    uv
    Rust stable-msvc
    Visual Studio 2022 Build Tools
    WebView2 Runtime

## 安装依赖

    Set-Location D:\HyMail

    pnpm install
    Set-Location apps\api
    uv sync

## 启动后端

    Set-Location D:\HyMail\apps\api
    uv run uvicorn hymail_api.main:app --reload --host 127.0.0.1 --port 8000

健康检查：

    Invoke-RestMethod http://127.0.0.1:8000/health

OpenAPI 文档：

    http://127.0.0.1:8000/docs

## 启动浏览器前端

    Set-Location D:\HyMail
    pnpm --filter @hymail/desktop dev --host 127.0.0.1

打开：

    http://127.0.0.1:5173

## 启动 Tauri dev

先停止其他占用 5173 / 8000 的 Vite 或 uvicorn 进程。

    Set-Location D:\HyMail\apps\desktop
    pnpm exec tauri dev

Tauri dev 会：

- 启动 Vite
- 启动 FastAPI sidecar
- 使用随机 loopback 端口
- 生成随机 Bearer token
- 等待 /health 后加载 UI
- 关闭窗口时停止 sidecar

## Demo

见：

    docs/demo.md

启动演示服务和 Mock IMAP：

    Set-Location D:\HyMail\apps\api
    uv run python scripts/run_demo_server.py --reset --messages 20

## 测试

后端：

    Set-Location D:\HyMail\apps\api
    uv run ruff check .
    uv run pytest

前端：

    Set-Location D:\HyMail
    pnpm --filter @hymail/desktop lint
    pnpm --filter @hymail/desktop typecheck
    pnpm --filter @hymail/desktop test
    pnpm --filter @hymail/desktop build
    pnpm --filter @hymail/desktop test:e2e

Tauri：

    Set-Location D:\HyMail\apps\desktop\src-tauri
    cargo check

## 已知限制

- 只支持一个账号
- 只实现收信，不实现发信、回复、转发、附件
- 不做旗标、删除、移动的完整对账
- 不支持 CONDSTORE / QRESYNC / MOVE / UIDPLUS / IDLE
- HTML 邮件暂未做 sandbox 和 DOMPurify 清洗
- 暂不提供安装包、自动更新、代码签名
- Tauri 仅开发模式集成

## 后续路线图

- v0.1：多文件夹、对账、持久化同步队列
- v0.2：Outbox、已读/星标/发信
- v0.3：FTS5 搜索与中文分词
- v0.4：多账号与 OAuth
- v0.5：CONDSTORE / QRESYNC / UIDPLUS / IDLE
- v1.0：Tauri 安装包、自动更新、安全渲染