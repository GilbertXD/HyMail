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

## 9. 对账（远端删除）

先在 demo server 上删掉一封邮件。用 curl 或 PowerShell：

    $body = '{"uid": 1, "mailbox": "INBOX"}'
    Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/__e2e/messages/remove -Body $body -ContentType application/json

（这个控制接口只存在于 `scripts/run_e2e_server.py`，正式服务里没有。）

回到 /mail 点击「对账」：

- 新邮件照常拉取，随后比对远端 UID 集合
- 服务器上已不存在的邮件在列表和详情里显示「远端已删除」
- 本地行保留，不是删除——这样变化可解释，也能撤销
- 把邮件加回去再点一次「对账」，标记会自动消失

自动化测试覆盖：

    uv run pytest tests/sync/test_engine_reconcile.py -v

## 10. 双向旗标与 Outbox

打开一封邮件，点「标为已读」或「加星」：

- 界面立刻变化（乐观更新），同时排进 Outbox
- 展开「同步详情」，最下面「待发送的修改」能看到这条改动
- 稍后它变成「已发送」，说明服务器已经收到

验证真的写到了服务器：用控制接口读回来

    Invoke-RestMethod "http://127.0.0.1:8000/__e2e/messages/flags?uid=2&mailbox=INBOX"

反过来，在服务器上改旗标再点「对账」，本地会跟着变：

    $body = '{"uid": 2, "mailbox": "INBOX", "flags": ["\\Flagged"], "add": true}'
    Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/__e2e/messages/flags -Body $body -ContentType application/json

**失败与丢弃**：把 demo server 停掉再点「加星」，改动会进入重试；超过最大重试后
在 Outbox 里显示「发送失败」，可以「重试」或「丢弃」。丢弃会把本地值改回服务器
最后一次报告的状态。

自动化测试覆盖：

    uv run pytest tests/sync/test_outbox.py tests/api/test_outbox_api.py -v

## 11. 移动对账

用控制接口把一封邮件从 INBOX 移到 Sent：

    $body = '{"uid": 3, "from_mailbox": "INBOX", "to_mailbox": "Sent"}'
    Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/__e2e/messages/move -Body $body -ContentType application/json

回到 /mail 点「对账」，然后：

- 在 INBOX 里那封邮件会显示「可能已移动到 Sent」，而不是笼统的「远端已删除」
- 切到 Sent 能看到它确实在那里
- 顶部筛选选「只看远端异常」可以只看这类行

说明是「可能」而不是「就是」：检测靠 Message-ID 推断，因为服务器没告诉我们
COPYUID（那是 UIDPLUS 的能力）。命中多个文件夹时不会给结论。

自动化测试覆盖：

    uv run pytest tests/sync/test_engine_moves.py -v

## 12. 同步指标

跑过几轮同步和对账之后，展开「同步详情」，最下面是「同步指标」：

- 最近 24 小时的同步次数、失败率、拉取邮件数、重试次数
- 平均耗时与 P95 耗时（P95 用 nearest-rank，SQLite 没有百分位函数）
- 待发送修改的数量，以及其中多少发送失败
- 每个文件夹一行的下钻：同步次数、失败、拉取量、平均耗时、最后同步时间

也可以直接看接口：

    Invoke-RestMethod "http://127.0.0.1:8000/api/v1/metrics?window_hours=24" | ConvertTo-Json -Depth 4

想看失败率不是 0 的样子，用 `--disconnect-on-fetch` 启动 demo server 同步几次，
再换回正常模式：指标里会留下失败与重试的计数。

自动化测试覆盖：

    uv run pytest tests/api/test_metrics_api.py tests/test_metric_math.py -v




