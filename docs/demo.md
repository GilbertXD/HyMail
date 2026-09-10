# HyMail v0.0.1 演示脚本

## 准备

启动演示 API 和 Mock IMAP：

    Set-Location D:\HyMail\apps\api
    uv run python scripts/run_demo_server.py --reset --messages 20

脚本会打印：

    API:  http://127.0.0.1:8000
    IMAP: 127.0.0.1:11430
    user: user@example.com
    pass: secret
    SSL:  off

另开终端启动前端：

    Set-Location D:\HyMail
    pnpm --filter @hymail/desktop dev --host 127.0.0.1

打开 http://127.0.0.1:5173。

## 1. 账号配置

进入 /setup：

- 邮箱：user@example.com
- 提供商：自定义 IMAP
- 用户名：user@example.com
- IMAP 服务器：127.0.0.1
- 端口：11430
- 不勾选 SSL
- 授权码：secret

点击测试连接，再保存账号。

## 2. 初始同步

进入 /sync：

- 点击手动同步
- 状态应变为 initial_sync，然后 IDLE
- 进入 /mail，可以看到 20 封演示邮件

## 3. 增量同步

停止 demo server，重新启动并增加邮件：

    uv run python scripts/run_demo_server.py --messages 25

保持数据库不重置，再次手动同步：

- 只拉取 last_uid 之后的新邮件
- 邮件列表变为 25 封

## 4. UIDVALIDITY 变化

停止 demo server，用新的 UIDVALIDITY 启动：

    uv run python scripts/run_demo_server.py --messages 25 --uidvalidity 2

再次手动同步：

- 触发 RESYNC
- 旧映射被清理
- 重新初始同步

## 5. 断网重试

停止 demo server，用 FETCH 中断场景启动：

    uv run python scripts/run_demo_server.py --messages 25 --disconnect-on-fetch

触发同步：

- 进入 ERROR_BACKOFF
- 状态面板显示错误和重试次数

再重新正常启动 demo server：

    uv run python scripts/run_demo_server.py --messages 25

触发同步后可以恢复。

## 6. 崩溃恢复

同步过程中直接结束 sidebar / uvicorn 进程，再重新启动：

    uv run python scripts/run_demo_server.py --messages 25

由于游标和数据在同一事务提交，会从最后一次成功提交的批次继续，不会漏信或重复。