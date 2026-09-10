# HyMail 架构说明

## 1. 总览

HyMail v0.0.1 采用：

- Tauri 宿主
- React 前端
- FastAPI 本地服务
- SQLite 本地存储
- Mock IMAP / 真实 IMAP

数据流：

    React
      -> OpenAPI TypeScript client
      -> FastAPI /api/v1
      -> SyncEngine
      -> ImapClient
      -> IMAP Server

    SyncEngine
      -> SQLite (message / sync_cursor / sync_event)

## 2. 同步状态机

每个账号 x 每个文件夹维护一个同步游标：

    IDLE
      -> INITIAL_SYNC
      -> INCREMENTAL_SYNC
      -> RESYNC
      -> ERROR_BACKOFF
      -> AUTH_EXPIRED
      -> IDLE

状态含义：

- IDLE：等待触发
- INITIAL_SYNC：首次同步
- INCREMENTAL_SYNC：从 last_uid + 1 拉取新邮件
- RESYNC：UIDVALIDITY 变化后清空旧映射并重新同步
- ERROR_BACKOFF：网络、限流、服务端断连后退避重试
- AUTH_EXPIRED：认证失败后暂停自动重试

## 3. 游标模型

sync_cursor 最小字段：

- account_id
- folder_id
- uidvalidity
- last_uid
- uidnext
- state
- attempts
- last_error
- last_sync_at
- updated_at

游标只会在批次事务提交成功后前进。

## 4. 同步队列

v0.1 把「还要同步什么」从内存搬进数据库（`sync_job` 表），这样排队、退避和
取消都能跨进程重启存活。

    入队 queued
      -> 认领 running（带租约）
      -> success / failed / cancelled
      -> 可重试错误则退避后回到 queued

- **批次**：一次「同步全部」的 N 个任务共享一个 `batch_id`，批次进度按它聚合。
- **优先级**：数值越小越先。用户触发 0，轮询 10，对账 20，索引 30。
- **账号级互斥**：认领语句排除掉已有 `running` 任务的账号，因此同一账号任何时刻
  只有一个任务在跑；不同账号可以并行。v0.1 只开一个 worker，所以文件夹之间也是串行。
- **租约与崩溃恢复**：认领时写入 `lease_expires_at`；进程启动时把所有 `running`
  且租约过期的任务排回 `queued`。任务因此不需要「优雅关闭」也能恢复。
- **连接复用**：worker 按 `batch_id` 复用同一条 IMAP 连接，一个批次只 LOGIN 一次。
- **失败分类驱动调度**，而不是只记日志：
  - 认证失败 → 账号标记 `auth_expired`，该账号整个队列取消（继续跑只会重复失败）
  - 文件夹不存在 → 直接 `failed`，不消耗重试次数
  - 网络 / 限流 → 指数退避后重新排队

任务与游标的分工：**任务说「还要做什么」，游标说「已经做到哪」**。事务边界没有变，
所以任务重跑不会重复拉取。

## 5. 对账（RECONCILE）

对账回答的是另一个问题：**服务器上少了什么**。增量同步只会往前追加，永远发现不了
「远端删掉了」。

一次对账分两段，都跑在同一个任务里：

1. **增量同步**：复用 `sync_folder`，所以新邮件照常拉取，UIDVALIDITY 变化照常走 RESYNC。
2. **比对 UID 集合**：`UID SEARCH ALL` 拿到远端全集，与本地 UID 集合做差集：

       远端有、本地无   -> 新邮件（第一段已经拉进来了）
       本地有、远端无   -> 标记 remote_missing = true
       两边都有         -> 如果之前被标记过，取消标记

- 标记而不是删除：变化是可解释的，也能撤销。消息在别的文件夹重新出现时标记会自动清掉。
- 只更新真正变化的行。把「两边都有」的全部重写一遍会在每次对账时重写整张表。
- **安全阀**：如果 SELECT 报告文件夹里有邮件，而 SEARCH 一条 UID 都列不出来，判定为
  自相矛盾的答复并跳过标记。反过来，服务器说文件夹是空的（EXISTS 0）就是一个真实
  答案，照常对账——否则小文件夹一旦被清空就永远学不到。跳过时会记 `skipped=inconsistent`。

### 移动归属

一封邮件从 A 消失，往往只是去了 B。没有 UIDPLUS 的 COPYUID，唯一能抓的线索是
Message-ID，所以这是一条**推断**而不是事实，两个方向各补一次：

- **新邮件到达时**：刚写进来的 Message-ID 会回填到其它文件夹里同样 Message-ID、
  且已被标记 `remote_missing` 的行上。
- **标记缺失时**：反查其它文件夹里同样 Message-ID 且**未被标记缺失**的行。

两个方向合起来，一次全账号对账里不管先处理哪个文件夹都能得出结论。

只在**目标唯一**时才下结论。Message-ID 本来就可能合法地重复——抄送自己的邮件同时
存在于「已发送」和「收件箱」——所以命中多个文件夹时宁可不说。每次对账都会重算，
因此目标不再持有该邮件时，旧的说明也会被清掉。

界面上写作「**可能**已移动到 X」正是因为这个原因。`moved_to_folder_id` 用
`ON DELETE SET NULL`，删掉目标文件夹不会连带删掉邮件本身。

对账是一次 `sync_job`（`kind = reconcile`），所以排队、优先级、取消和崩溃恢复
与普通同步完全共用一套机制。

## 6. Outbox（本地写回）

已读和星标是双向的：对账把远端状态拉下来，而用户的点击要送上去。送上去这件事
放在 `outbox_action` 表里，而不是直接发一个请求。

    pending -> inflight -> success
                       -> failed        （超过最大重试，等用户决定）
                       -> abandoned     （用户丢弃，同时把本地改回服务器状态）

三条规则：

- **先落库再改界面**。乐观更新只有在意图能扛过进程崩溃时才诚实，所以「写本地值」
  和「入队」在同一个事务里提交。
- **新意图覆盖旧意图**。同一条消息同一个属性的 `pending` 动作会被最新值取代，
  所以「标已读 → 标未读」只发一次写，而不是两条互相矛盾的写。
- **不撤销用户的操作**。永久失败只标记 `failed` 并在界面上提示，等用户重试或丢弃，
  而不是自动回滚——服务器可能只是暂时不可用，静默改回用户的点击更糟。

丢弃会把本地值恢复成 `flags_json` 里的内容，那始终是服务器最后一次报告的旗标。

**账号级互斥是跨服务共享的**：Outbox 认领时排除掉「有 running 的 `sync_job`」的账号，
也排除掉自己已有 inflight 动作的账号。所以同一个账号永远不会同时开两条 IMAP 连接。

## 8. 指标

`GET /api/v1/metrics` 汇总一个滚动窗口（默认 24 小时）内同步实际做了什么：

- **运行数 / 失败数 / 失败率** 来自 `sync_job`——只有它知道重试次数和终态。
- **拉取量 / 耗时** 来自 `sync.completed` 事件——只有它知道这一趟拉了多少封信。
  两个来源各取所长，不是从同一张表里硬凑。

每个数字都能下钻到文件夹。耗时用 nearest-rank 取 P95（SQLite 没有百分位函数）。

这里也修掉了一个一直存在的缺口：`sync_event.duration_ms` 从 v0.0.1 起就是个
永远为 NULL 的参数——列在，没人填。现在每次成功同步都会写入本次尝试的耗时。

## 9. 事务边界

每批 FETCH 后，以下操作在同一个 SQLite 事务中提交：

1. message upsert
2. sync_cursor 更新
3. sync_event 写入

这样可以保证：

- 游标不会超过已落库数据
- 崩溃后可以从最后一批继续
- 重复同步不会产生重复 message

## 10. 认证与安全

- 授权码使用 Windows DPAPI 加密
- 本地 API 只监听 127.0.0.1
- Tauri dev 模式随机端口 + 随机 Bearer token
- Host 默认只允许 loopback
- Origin 使用允许列表

## 11. Tauri sidecar

Tauri 启动时：

1. 选择随机 loopback 端口
2. 生成随机 token
3. 启动 uv + uvicorn sidecar
4. 前端轮询 /health
5. 调用 get_api_config 获取 baseUrl 和 token
6. 关闭窗口时 kill sidecar