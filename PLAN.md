# HyMail

## 背景与定位
受鸿蒙邮件启发，做本地 Windows 个人邮箱聚合管理工具。
采用前后端分离架构：Tauri 宿主 + React 前端 + FastAPI 本地服务。只监听 127.0.0.1，Bearer token，Host/Origin 校验。数据目录 %LOCALAPPDATA%\HyMail。

## 层
- 协议与邮件解析
- 本地存储与搜索
- 同步与增量更新
- 安全
- 桌面前端与宿主

## 核心深度锚点
本地邮件状态一致性引擎

### 主锚点：同步引擎
目标：把“收信”做成一个可解释、可恢复、可对账、可观测的状态机。

#### 状态机
每个账号 × 每个文件夹维护一个独立同步状态：
IDLE
  → INITIAL_SYNC
  → INCREMENTAL_SYNC
  → RECONCILE
  → RESYNC
  → ERROR_BACKOFF
  → IDLE
- INITIAL_SYNC：首次同步，拉 UIDNEXT、UIDVALIDITY、文件夹元数据，分批 FETCH。
- INCREMENTAL_SYNC：从 last UID 起拉新邮件。
- RECONCILE：轻量对账，检查旗标、删除、移动。
- RESYNC：UIDVALIDITY 变化或对账失败时，重新同步该文件夹。
- ERROR_BACKOFF：断网、认证失败、限流、服务器断连，指数退避。
- IDLE：等待下次轮询或触发。

#### 游标模型（SyncCursor）
按账号 + 文件夹保存：
- uidvalidity
- last_uid
- uidnext
- highest_modseq（支持 CONDSTORE 时）
- last_sync_at
- last_reconcile_at
- flags_reconcile_state
- delete_reconcile_state
- move_reconcile_state
- capability_snapshot（CONDSTORE/QRESYNC/MOVE/UIDPLUS/IDLE）

#### 能力协商
- 启动时探测服务器能力，写入 capability_snapshot：
- 支持 CONDSTORE/QRESYNC → 用 MODSEQ 增量同步旗标。
- 支持 MOVE → 移动用 MOVE，否则 COPY + STORE \Deleted + EXPUNGE。
- 支持 UIDPLUS → 用 COPYUID 校验移动结果。
- 支持 IDLE → 可选实时推送，v0.0.1 不启用。

#### 对账策略
- 旗标对账：本地已读/星标 vs 远端 FLAGS。
- 删除对账：远端 EXPUNGE 后本地标记删除。
- 移动对账：UID 变化 + COPYUID 或重新扫描。
- 新邮件对账：UIDNEXT 变化但 last UID 未覆盖。
- 丢失 UID：本地有、远端无，标记 remote_missing。

#### 失败与恢复
- 断点续传：每批 FETCH 后写游标，崩溃后从 last UID 续传。
- UIDVALIDITY 变化：清空该文件夹本地映射，重新 INITIAL_SYNC。
- 认证失败：标记账号 auth_expired，暂停该账号，UI 提示重新授权。
- 限流：退避 + 降并发，账号级串行。
- 崩溃恢复：启动时扫描 Job 和 SyncCursor，恢复未完成状态。

#### 并发模型
- 账号级互斥：同一账号同一时间只有一个同步任务。
- 多账号并行：不同账号可并行，但限制总并发（如 2～3）。
- 任务优先级：用户触发的同步 > 定时轮询 > 对账 > 索引重建。
- 取消与背压：用户切换账号时取消低优先级任务。

#### 可观测
- 每个文件夹的同步状态、最后同步时间、错误原因。
- 同步日志脱敏，记录 UID 范围、耗时、FETCH 数量。
- UI 显示：同步中 / 已同步 / 重试中 / 认证过期 / UIDVALIDITY 变化。

### 副锚点 1：可靠 Outbox
目标：把“已读、星标、发信”做成可靠动作流水线，而不是“点一下发个请求”。

#### 动作模型（OutboxAction）
- id：本地 UUID
- account_id
- type：mark_read / star / send / append_sent
- target：message UID 或草稿 ID
- payload：动作参数
- idempotency_key：防重复
- state：pending / inflight / success / failed / abandoned
- attempts
- next_retry_at
- last_error
- created_at / updated_at

#### 流水线
- 本地乐观更新（UI 立即反映）。
- 写 OutboxAction，state = pending。
- 调度器取任务，state = inflight。
- 远端回写。
- 成功 → success；失败 → 指数退避，重试。
- 超过最大重试 → failed，UI 显示手动重试/丢弃。

#### 幂等
- 发信：idempotency_key 写入邮件头 X-HyMail-Idempotency，重试前先查 Sent。
- 旗标：STORE 幂等，重复执行无副作用。
- 移动：用 COPYUID 校验，避免重复移动。

#### 失败分类
- 网络：可重试。
- 认证：暂停账号，提示重新授权。
- 协议：记录，有限重试。
- 永久失败：标记 failed，不自动重试。

#### 崩溃恢复
- 启动时扫描 inflight，超过超时时间重置为 pending。
- 发信 inflight 需先查远端 Sent，避免重复发送。

### 副锚点 2：本地索引
- 目标：把搜索做成可增量、可重建、可观测的索引系统。

#### 表设计
- message：主表，存元数据、正文纯文本、路径。
- message_fts：FTS5 虚拟表，external content。
- attachment：元数据 + 文件路径。
- index_job：索引任务队列。

#### 增量索引
- 本地写入邮件后，写 index_job。
- 后台线程批量处理，更新 FTS5。
- 失败重试，超过阈值标记 index_failed。
- 全量重建：清空 FTS5，按 message 表重建。

#### 中文方案
- 待验证：FTS5 trigram tokenizer vs jieba 分词。
- trigram：支持子串，索引大，短查询有限制。
- jieba：分词后写入 FTS5，查询也分词。
- 先用 trigram，验证效果。

#### 一致性
- message 表与 FTS5 异步一致，允许短暂延迟。
- 提供“重建索引”入口。
- 索引状态可观测：已索引 / 待索引 / 失败。

### 跨层展示
深度不能只在后端，要贯穿前端、宿主、测试、可观测。

#### 前端
- 同步状态面板：账号、文件夹、状态、最后同步、错误。
- Outbox 面板：pending / inflight / failed，手动重试/丢弃。
- 索引状态：已索引 / 待索引 / 失败，重建按钮。
- 冲突提示：UIDVALIDITY 变化、认证过期、远端缺失。
- 乐观更新：已读/星标立即反馈，失败回滚并提示。

#### Tauri 宿主
- 单实例锁：用户级互斥体 + 锁文件。
- 启动 sidecar：随机端口，token 通过 stdin/管道传递。
- 健康检查：等待 /health 就绪再加载 UI。
- 关闭：先调用 /shutdown，超时 kill，Job Object 防僵尸。
- 启动失败页：退出码、stderr 末尾、重试、打开日志目录。

#### 安全
- DPAPI 保护授权码。
- Bearer token 只存内存。
- Host/Origin 校验。
- HTML sandbox + DOMPurify + 默认屏蔽远程图片。
- 日志脱敏：token、邮件内容不落日志。

#### 测试
- mock IMAP/SMTP：模拟 UIDVALIDITY 变化、断连、限流、认证失败。
- 故障注入：同步中断、Outbox 失败、索引失败。
- 一致性测试：本地 vs 远端旗标对账。
- 性能基准：同步 1k/10k 邮件耗时，索引构建耗时。
- 前端：Vitest + Playwright，覆盖同步状态、Outbox、搜索。

#### CI
GitHub Actions：lint、pytest、Vitest、Playwright、Tauri build。
产出 Windows 安装包 + 测试报告。

## v0.0.1

> 定位：面试展示用的非旗舰全栈项目，只交付“单账号同步引擎 + 可观测状态面板”这一条可运行、可解释、可测试的垂直切片。先证明核心链路和工程质量，再逐步扩展其他能力。

### 目标

- 打通“单账号配置 → IMAP 连接 → 初始同步 / 增量同步 → SQLite 本地存储 → FastAPI 状态接口 → React 可观测面板”的完整链路。
- 让同步过程可解释、可恢复、可观测：每次状态变化都有持久化游标、结构化日志和 UI 反馈。
- 用 mock IMAP 覆盖关键故障，证明增量同步、UIDVALIDITY 变化、断网重试、崩溃恢复这些核心行为是可测试的。
- 数据模型仍按“账号 × 文件夹”设计，为后续多账号和更多文件夹留出空间，但 v0.0.1 只开放一个账号。
- 为后续 Outbox、本地索引、多账号、高级 IMAP 能力预留接口，但不在 v0.0.1 提前实现。

### 版本范围

#### 后端与同步引擎

- **账号**：单账号；凭证使用应用密码 / 授权码模式，Windows 下用 DPAPI 加密存储。
- **邮件提供商**：v0.0.1 先适配一个真实 IMAP 提供商，其他提供商放到后续版本。
- **IMAP 能力**：CAPABILITY、LIST、SELECT、UIDNEXT、UIDVALIDITY、UID FETCH；先使用成熟 IMAP 客户端库，不手写协议解析。
- **初始化同步**：读取 UIDNEXT / UIDVALIDITY，分批 FETCH 邮件头与正文，逐批写入本地。
- **增量同步**：从 `last_uid + 1` 开始拉取新邮件，避免全量重复拉取。
- **同步状态机子集**：
  - `IDLE`：等待手动或定时触发。
  - `INITIAL_SYNC`：首次拉取文件夹元数据和邮件。
  - `INCREMENTAL_SYNC`：只拉取 `last_uid` 之后的新邮件。
  - `RESYNC`：UIDVALIDITY 变化时清除本地映射并重新初始化同步。
  - `ERROR_BACKOFF`：网络、限流、服务端断连等错误按指数退避重试。
  - `AUTH_EXPIRED`：认证失败时暂停同步，UI 提示重新配置账号。
- **暂不实现**：RECONCILE 完整对账、旗标/删除/移动同步、CONDSTORE、QRESYNC、MOVE、UIDPLUS、IDLE。
- **游标模型（v0.0.1 最小字段）**：
  - `account_id`
  - `folder_id`
  - `uidvalidity`
  - `last_uid`
  - `uidnext`
  - `state`
  - `attempts`
  - `last_error`
  - `last_sync_at`
  - `updated_at`
- **事务边界**：每批 FETCH 后，将 `message` upsert、`sync_cursor` 更新、`sync_event` 写入放在同一个 SQLite 事务中，避免游标与数据不一致。
- **本地存储**：SQLite + WAL；核心表：`account`、`folder`、`message`、`sync_cursor`、`sync_event`。
- **日志与可观测**：结构化日志，每次同步 run 带 `trace_id`；记录账号、文件夹、状态、UID 范围、FETCH 数量、耗时、重试次数、错误类型；不记录 token、密码、邮件正文。
- **API**：健康检查、账号配置与连接测试、文件夹列表、邮件列表与详情、手动触发同步、取消同步、同步状态、同步事件流。
- **接口契约**：FastAPI 输出 OpenAPI，前端生成 TypeScript client，避免手写类型和接口漂移。

#### 前端与可观测面板

- **账号配置页**：填写邮箱、IMAP 服务器、授权码，支持连接测试和错误提示。
- **文件夹列表**：显示 v0.0.1 已同步的文件夹。
- **最小邮件列表和阅读页**：证明同步结果真实可用；只读收信，不做写信、回复、转发、附件。
- **同步状态面板**：
  - 当前状态：IDLE / 同步中 / 重试中 / 认证过期 / UIDVALIDITY 变化。
  - 当前文件夹、最后同步时间、UID 游标摘要。
  - 当前批次、FETCH 数量、已处理 UID 范围。
  - 错误原因、重试次数、下次重试倒计时。
  - 手动触发同步 / 取消同步。
- **同步事件时间线**：按时间展示状态迁移、游标更新、失败与恢复过程。
- **状态刷新**：v0.0.1 先用轮询（1～2 秒）降低实现复杂度；如果时间允许，再升级为 SSE。
- **暂不实现**：Outbox 面板、索引状态面板、搜索页、冲突提示中的移动/删除对账、HTML 完整保真渲染。

#### 宿主与运行方式

- Tauri 宿主在开发模式下完成基本集成：启动 FastAPI sidecar、健康检查、关闭 sidecar。
- 安装包、单实例锁、Job Object、自动更新、代码签名放到后续版本。

#### 测试与验收

- **mock IMAP**：模拟初始同步、增量同步、UIDVALIDITY 变化、FETCH 中断、断连、限流、认证失败。
- **后端测试**：API、游标事务、重复同步幂等性、UIDVALIDITY 重置、退避与恢复。
- **前端测试**：Vitest 覆盖同步状态面板、错误态、重试倒计时；Playwright 覆盖一条端到端演示路径。
- **验收标准**：
  1. 首次同步 1k 封测试邮件后，邮件数量与远端一致，重复同步不产生重复记录。
  2. 新增邮件后触发增量同步，只请求 `last_uid` 之后的新 UID。
  3. 修改服务器 UIDVALIDITY 后触发 RESYNC，旧游标被安全重置，面板明确提示。
  4. 同步中断或断网后进入 ERROR_BACKOFF，恢复后能从已提交游标继续，不漏信、不重复。
  5. 认证失败进入 AUTH_EXPIRED，停止自动重试并提示重新授权。
  6. 同步过程中杀掉后端进程再启动，能从最后一次已提交事务恢复。
  7. 状态面板能在 2 秒内反映状态变化，错误信息可读。
  8. README 提供 mock IMAP 启动方式、演示步骤和已知限制。

#### 明确不做的内容

- 多账号并发。
- Outbox 写操作与乐观更新。
- 发信、草稿、附件、通讯录。
- FTS5 全文搜索与中文分词。
- 旗标、删除、移动、丢失 UID 的完整对账。
- CONDSTORE / QRESYNC / MOVE / UIDPLUS / IDLE。
- Windows 安装包签名、自动更新、多平台支持。

### 交付物

- 可运行的 monorepo：FastAPI 后端 + React 前端 + Tauri 宿主 + mock IMAP。
- 数据库 migration 与初始化脚本。
- OpenAPI 文档和自动生成的 TypeScript client。
- pytest、Vitest、Playwright 关键路径测试。
- 一页架构说明：同步状态迁移图、事务边界、游标模型。
- 一页演示脚本：初始同步 → 增量同步 → 断网重试 → UIDVALIDITY 变化 → 崩溃恢复。
- README：本地启动、测试、演示、已知限制、后续路线图。

## 计划的可能更新

> 原则：每个版本只引入一个可以独立演示、独立测试、独立回滚的能力；不破坏 v0.0.1 已稳定的同步链路和数据库迁移路径。

### v0.1：同步引擎补全

- 多文件夹同步与文件夹级独立状态机。
- RECONCILE 轻量对账：新邮件、丢失 UID、远端删除。
- 旗标对账：本地已读/星标与远端 FLAGS 对齐。
- 删除与移动对账：EXPUNGE、UID 变化、COPYUID 校验。
- 持久化同步队列：任务状态、优先级、取消、租约、崩溃恢复。
- 账号级互斥、多文件夹串行/并行策略。
- 结构化指标：同步耗时、FETCH 数量、失败率、重试次数。

### v0.2：可靠 Outbox

- 引入 `OutboxAction` 表与调度器。
- 支持 `mark_read`、`star` 等幂等写操作。
- 前端乐观更新、失败回滚、手动重试/丢弃。
- Outbox 崩溃恢复：`inflight` 超时重置，避免重复副作用。
- 移动邮件：优先 MOVE，否则 COPY + STORE + EXPUNGE，并用 COPYUID 校验。
- 发信与 `append_sent`：使用 Message-ID 和本地 Sent 查询做去重；明确“至少一次 + 用户可见不确定状态”，不承诺严格 exactly-once。

### v0.3：本地索引与搜索

- SQLite FTS5 索引表和 `index_job` 队列。
- 邮件写入后异步增量索引，支持失败重试和全量重建。
- 中文搜索方案验证：trigram 与 jieba 分词对比。
- 搜索结果页、关键词高亮、按账号/文件夹过滤。
- 索引状态可观测：已索引 / 待索引 / 失败 / 重建中。
- 附件文本提取与索引作为可选扩展。

### v0.4：多账号与提供商适配

- 多账号数据隔离、并发限制、账号级限流。
- 提供商适配矩阵：QQ 邮箱、163、Gmail、Outlook 等。
- OAuth2 授权、refresh token 管理、账号重新授权流程。
- 账号级代理和证书配置。
- 账号删除、数据导出和本地数据清理。

### v0.5：高级 IMAP 能力

- CAPABILITY 能力协商快照。
- CONDSTORE / QRESYNC：基于 MODSEQ 的旗标增量同步。
- UIDPLUS：COPYUID 校验和更可靠的移动/追加结果确认。
- IDLE：可选实时推送，默认关闭，避免连接数和耗电问题。
- 服务器兼容性测试矩阵和降级策略。

### v1.0：桌面产品化

- Tauri 安装包、单实例锁、Job Object、优雅关闭和崩溃重启。
- 代码签名、自动更新、日志目录和启动失败页。
- HTML 邮件安全渲染：sandbox iframe、CSP、DOM 清理、远程图片默认屏蔽、外链确认。
- 写信、回复、转发、附件、草稿箱、签名。
- 地址簿、收件规则、通知、快捷键等体验功能。

### 长期候选，不进入当前主线

- PGP / S-MIME 加密邮件。
- 邮件规则与过滤器。
- 跨平台（macOS / Linux）。
- 云同步或端到端加密同步。
- 插件系统。
- 企业邮箱 / Exchange / JMAP 支持。
- AI 摘要、分类、智能回复等增强能力。

### 每次更新前的检查清单

- 这个能力能否独立演示？
- 是否有对应的 mock、单元测试和故障注入？
- 是否会破坏现有游标语义或需要数据库迁移？
- 失败后能否回滚，且不影响 v0.0.1 的同步主链路？
- 是否值得进入主线，还是应该继续放在候选池？