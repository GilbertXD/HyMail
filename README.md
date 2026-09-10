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

v0.1 把同步做成一个可排队、可恢复的过程：

- 持久化同步队列（`sync_job`），进程重启后继续未完成的任务
- 账号级互斥：同一账号同一时间只有一个同步任务
- 任务优先级：用户触发 > 轮询 > 对账 > 索引
- 租约与崩溃恢复：worker 死亡后过期租约自动回收
- **一键同步整个邮箱**：串行跑完所有远端仍存在的文件夹，带进度
- 连接复用：一个批次一次 LOGIN，而不是每个文件夹一次
- 失败分类驱动调度：认证失败暂停账号并清空队列，文件夹不存在直接失败不重试

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

## 数据库迁移

后端不会自动建表，首次运行（或升级后）必须先应用迁移：

    Set-Location D:\HyMail\apps\api
    uv run alembic upgrade head

当前 head 是 `0002_sync_job`。数据库默认在
`%LOCALAPPDATA%\HyMail\hymail.db`，可用 `HYMAIL_DATABASE_URL` 覆盖。

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

## 可观测面板

- `/mail`：左侧文件夹、中间邮件列表、右侧邮件详情。
- 邮件列表顶部内嵌同步状态（状态、last UID）和「同步」/「同步全部」/「取消」按钮。
- 「同步全部」把该账号所有远端仍存在的文件夹排成一个批次串行同步，
  下方进度条显示「同步全部 3/13」和当前文件夹。
- 点击「同步详情」在右侧展开同步状态面板、同步事件时间线和同步队列
  （每个任务的文件夹、状态、尝试次数和错误原因）。
- `/setup`：账号配置与连接测试。
- 文件夹名按 IMAP modified UTF-7 解码后显示。旧版本写进数据库的乱码名
  会在点击一次「刷新文件夹」时自动就地修复。
- HTML 正文在 sandbox iframe 中渲染，邮件自带的字体和样式不会影响应用界面；
  远程图片默认屏蔽，可在正文上方手动放行。
- 左下角可在日间／夜间模式之间切换，选择记在 localStorage；没有手动切换过
  时跟随系统设置。邮件正文始终用白底渲染，因为邮件是按浅色画布排版的。

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
- 不做旗标、删除、移动的完整对账（v0.1 尚未实现 RECONCILE）
- 不支持 CONDSTORE / QRESYNC / MOVE / UIDPLUS / IDLE
- 更换邮箱后不会清理上一个邮箱遗留的文件夹和邮件，需等 v0.4 多账号一并解决
  （「同步全部」会跳过远端已不存在的文件夹，所以不会因此产生一堆失败）
- 队列默认单 worker；调高 `max_workers` 后每个 worker 会各占一条空闲连接，
  「一批一次 LOGIN」只在默认单 worker 下严格成立（任务仍按账号串行）
- HTML 正文已做 sandbox 隔离和远程图片屏蔽，但尚未接入 DOMPurify 清洗
- 暂不提供安装包、自动更新、代码签名
- Tauri 仅开发模式集成

## 后续路线图

- v0.2：RECONCILE 对账（新邮件 / 丢失 UID / 远端删除）
- v0.3：旗标对账（已读 / 星标）、Outbox
- v0.4：多账号与 OAuth
- v0.5：CONDSTORE / QRESYNC / UIDPLUS / IDLE
- v1.0：Tauri 安装包、自动更新、安全渲染