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

## 4. 事务边界

每批 FETCH 后，以下操作在同一个 SQLite 事务中提交：

1. message upsert
2. sync_cursor 更新
3. sync_event 写入

这样可以保证：

- 游标不会超过已落库数据
- 崩溃后可以从最后一批继续
- 重复同步不会产生重复 message

## 5. 认证与安全

- 授权码使用 Windows DPAPI 加密
- 本地 API 只监听 127.0.0.1
- Tauri dev 模式随机端口 + 随机 Bearer token
- Host 默认只允许 loopback
- Origin 使用允许列表

## 6. Tauri sidecar

Tauri 启动时：

1. 选择随机 loopback 端口
2. 生成随机 token
3. 启动 uv + uvicorn sidecar
4. 前端轮询 /health
5. 调用 get_api_config 获取 baseUrl 和 token
6. 关闭窗口时 kill sidecar