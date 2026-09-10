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
- IMAP 服务器：127.0.0.1
- 端口：11430
- 不勾选 SSL
- 授权码：secret

用户名不需要单独填写，保存时会自动使用邮箱地址。

点击测试连接，再保存账号。

## 2. 初始同步

进入 /mail，在左侧选择 INBOX：

- 点击「同步」
- 状态应从 initial_sync 变为 IDLE
- 邮件列表出现 20 封演示邮件
- 点击「同步详情」可以展开同步状态面板和同步事件时间线

如果是从旧版本升级上来的数据库，先点一次「刷新文件夹」，让历史遗留的
modified UTF-7 乱码文件夹名就地修复。

## 3. 增量同步

停止 demo server，重新启动并增加邮件：

    uv run python scripts/run_demo_server.py --messages 25

保持数据库不重置，再次点击「同步」：

- 只拉取 last_uid 之后的新邮件
- 邮件列表变为 25 封

## 4. UIDVALIDITY 变化

停止 demo server，用新的 UIDVALIDITY 启动：

    uv run python scripts/run_demo_server.py --messages 25 --uidvalidity 2

再次点击「同步」：

- 触发 RESYNC
- 旧映射被清理
- 重新初始同步
- 状态面板显示「UIDVALIDITY 变化，重新同步」

## 5. 断网重试

停止 demo server，用 FETCH 中断场景启动：

    uv run python scripts/run_demo_server.py --messages 25 --disconnect-on-fetch

触发同步：

- 进入 ERROR_BACKOFF，状态显示「重试中」
- 展开「同步详情」可以看到错误原因和下次重试倒计时

再重新正常启动 demo server：

    uv run python scripts/run_demo_server.py --messages 25

触发同步后可以恢复。

## 6. 崩溃恢复

同步过程中直接结束 sidebar / uvicorn 进程，再重新启动：

    uv run python scripts/run_demo_server.py --messages 25

由于游标和数据在同一事务提交，会从最后一次成功提交的批次继续，不会漏信或重复。

这一条也有自动化测试覆盖：

    uv run pytest tests/sync/test_engine_crash_recovery.py -v

## 7. 一键同步整个邮箱

进入 /mail，点击「同步全部」：

- 所有远端仍存在的文件夹排成一个批次，按账号串行执行
- 进度条显示「同步全部 3/13」和当前正在同步的文件夹
- 展开「同步详情」可以看到同步队列里每个任务的状态、尝试次数和错误原因
- 批次结束后进度条显示「已完成」

整个批次只 LOGIN 一次，而不是每个文件夹一次。

## 8. 队列崩溃恢复

「同步全部」跑到一半时直接结束 uvicorn 进程，再重新启动：

    uv run python scripts/run_demo_server.py --messages 25

后端启动时会把所有处于 running 且租约已过期的任务重新排回队列，所以重新打开
页面点「同步详情」能看到任务继续跑完，不需要手工重来。

自动化测试覆盖：

    uv run pytest tests/sync/test_scheduler.py -v
