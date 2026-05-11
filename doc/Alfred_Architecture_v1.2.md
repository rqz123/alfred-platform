# Alfred 平台架构设计与 API 规范

> **版本 1.2** · 基于代码库实际状态 · 2026 年 5 月

---

## 目录

1. [系统概览](#1-系统概览)
2. [整体拓扑图](#2-整体拓扑图)
3. [消息处理流程](#3-消息处理流程)
4. [模块详解](#4-模块详解)
   - 4.1 Gateway（:8000）
   - 4.2 Nudge（:8002）
   - 4.3 OurCents（:8001）
   - 4.4 Bridge（:3001）
   - 4.5 Web 前端（:5173）
   - 4.6 wa-sim（测试模拟器）
5. [Intent 路由总表](#5-intent-路由总表)
6. [ASI 通信契约](#6-asi-通信契约)
7. [管理员 Bot 命令](#7-管理员-bot-命令)
8. [环境变量](#8-环境变量)
9. [进程启动清单](#9-进程启动清单)

---

## 1. 系统概览

Alfred 是一个基于 WhatsApp 的个人 AI 助手平台，采用微服务架构。用户通过 WhatsApp 发送文字、语音或图片，Alfred 自动识别意图并将请求路由到相应的业务服务，再将结果回复给用户。

### 1.1 服务一览

| 服务 | 目录 | 端口 | 技术栈 | 职责 |
|------|------|------|--------|------|
| **Gateway** | `services/gateway/` | 8000 | Python / FastAPI | 核心协调层：消息接收、意图识别、路由调度、账户管理、Web UI 托管 |
| **Nudge** | `services/nudge/` | 8002 | Python / FastAPI | 提醒闹钟 + 线索（Thread/Note）管理 |
| **OurCents** | `services/ourcents/` | 8001 | Python / FastAPI | 家庭财务记账（支出、收入、余额、月报、收据 OCR） |
| **Bridge** | `bridge/` | 3001 | Node.js | whatsapp-web.js 适配器，管理 WhatsApp Web 会话 |
| **Web 前端** | `web/` | 5173（dev）| React + TypeScript + Vite | 管理员 Web UI，托管于 Gateway（生产环境） |
| **Shared** | `shared/` | — | Python | JWT 鉴权工具，被 Gateway 和 Nudge 共享 |
| **wa-sim** | `wa-sim/` | — | Python | WhatsApp 模拟器，用于集成测试 |

### 1.2 核心设计原则

- **单一入口**：所有 WhatsApp 消息通过 Gateway 统一接收和分发。
- **ASI 契约**：下游服务（OurCents、Nudge）实现统一的 Alfred Service Interface（ASI），Gateway 通过标准接口调用。
- **Note = Thread**：从用户角度，"note" 和 "thread" 完全等同，系统内部统一使用 Thread。
- **多轮对话**：通过 `PendingSession` 机制支持多轮信息收集，无需用户一次说全所有参数。
- **双模 WhatsApp**：支持 `bridge` 模式（whatsapp-web.js）和 `cloud` 模式（Meta Cloud API），由环境变量切换。

---

## 2. 整体拓扑图

```
                     ┌─────────────────────────┐
                     │   WhatsApp（用户手机）    │
                     └────────────┬────────────┘
                                  │ 文字 / 语音 / 图片
                    ┌─────────────▼────────────┐
                    │   Bridge  :3001 (Node.js) │  ← whatsapp-web.js
                    │   管理 WA Web 会话         │
                    └─────────────┬────────────┘
                                  │ POST /api/internal/bridge/messages
                                  │ (X-Bridge-Key)
          ┌───────────────────────▼──────────────────────────┐
          │                 GATEWAY  :8000                    │
          │                                                   │
          │  ┌──────────────────────────────────────────────┐ │
          │  │  receive_bridge_message (routes.py)          │ │
          │  │    → STT（语音转文字，Whisper/gpt-4o-mini）   │ │
          │  │    → dispatch_message (dispatch_service.py)  │ │
          │  └─────────────────────┬────────────────────────┘ │
          │                        │                          │
          │  ┌─────────────────────▼────────────────────────┐ │
          │  │  dispatch_service                             │ │
          │  │    1. 账户身份校验                             │ │
          │  │    2. Bot 命令检测（/ 开头）                   │ │
          │  │    3. 图片 → OurCents receipt                 │ │
          │  │    4. 意图识别（LLM + 关键词）                 │ │
          │  │    5. PendingSession（多轮对话）               │ │
          │  │    6. 路由 → 下游服务 /alfred/execute          │ │
          │  │    7. 发送回复                                 │ │
          │  └───────────┬─────────────┬─────────────────────┘ │
          │              │             │                        │
          │  REST (X-Alfred-API-Key)   │                        │
          │              │             │                        │
          └──────────────┼─────────────┼────────────────────────┘
                         │             │
               ┌─────────▼──┐   ┌──────▼──────┐
               │  OurCents  │   │    Nudge    │
               │   :8001    │   │    :8002    │
               │            │   │             │
               │ /alfred/   │   │ /alfred/    │
               │ execute    │   │ execute     │
               │            │   │             │
               │ 家庭财务    │   │ 提醒 +      │
               │ 记账/收据   │   │ 线索管理    │
               └────────────┘   └──────┬──────┘
                                       │ POST /api/internal/push
                                       │ (提醒到期时主动推送)
                                       ▼
                                   GATEWAY
                                   → Bridge → 用户
```

---

## 3. 消息处理流程

### 3.1 标准流程（新意图）

```
用户 → WhatsApp → Bridge
                    │
                    ▼ POST /api/internal/bridge/messages
                 Gateway
                    │
                    ├─ [语音消息] STT 转录 → transcript 字段
                    │
                    ├─ create_inbound_message_for_contact()  持久化到 DB
                    │
                    └─ dispatch_message()
                         │
                         ├─ [未注册用户] 提示联系管理员，返回
                         │
                         ├─ [/ 开头] handle_bot_command()  Bot 命令处理，返回
                         │
                         ├─ [图片消息] _handle_image() → OurCents 收据识别，返回
                         │
                         ├─ detect_intent()
                         │   ├─ LLM（gpt-4o-mini）主路径 —— 结构化 JSON 输出
                         │   └─ 关键词匹配 备用路径
                         │
                         ├─ [intent=None, 短文本+肯定语] → acknowledge_reminder
                         │
                         ├─ [intent=None] → llm_chat_reply()  自然对话兜底
                         │
                         └─ _call_service() → POST {url}/alfred/execute
                                │
                                ├─ [status=success] → _reply() → Bridge / Cloud API
                                │
                                └─ [error_code=INSUFFICIENT_DATA]
                                      → save_pending()
                                      → _reply() (追问提示)
```

### 3.2 多轮对话流程（INSUFFICIENT_DATA）

```
用户说："提醒我" （缺少时间）
  → detect_intent: add_reminder
  → _call_service: INSUFFICIENT_DATA，message="What time?"
  → save_pending(phone, intent=add_reminder, entities={}, service=nudge)
  → 回复用户："What time should I remind you?"

用户说："明天早上9点"
  → get_pending(phone) → 有 pending
  → detect_intent("明天早上9点") → None（纯时间，无意图）
  → _handle_followup:
      extract_entities("明天早上9点", "add_reminder") → {date: "tomorrow", time: "09:00"}
      merged = {date: "tomorrow", time: "09:00"}
      _call_service(merged) → success
      clear_pending(phone)
  → 回复用户确认
```

### 3.3 提醒主动推送流程

```
Nudge 后台循环（每分钟）
  → 检查 reminders 表：nextFireAt <= now AND status IN (active, awaiting)
  → 对到期提醒：POST /api/internal/push {user_phone, message, quick_replies}
  → Gateway 找到 Bridge 连接 → 发送 WhatsApp 消息
  → 更新 reminder 状态为 awaiting（等待用户回复 OK）

用户回复 "OK" / "✓ OK"
  → dispatch → detect_intent → acknowledge_reminder
  → Nudge 将 reminder 状态改为 done 或计算下次 cron 触发时间
```

---

## 4. 模块详解

### 4.1 Gateway（:8000）

**目录**：`services/gateway/`  
**入口**：`app/main.py`

#### 路由层（`app/api/`）

| 模块 | 路由前缀 | 主要端点 |
|------|---------|---------|
| `routes.py` → `auth_router` | `/api/auth` | `POST /login`，`GET /me`，`GET /logs/{service}` |
| `routes.py` → `conversation_router` | `/api/conversations` | CRUD 会话列表及详情 |
| `routes.py` → `message_router` | `/api/conversations/{id}/messages` | 发消息、收消息、发图片、清除记录 |
| `routes.py` → `connection_router` | `/api/connections` | Bridge 连接的创建/删除/列表 |
| `routes.py` → `internal_router` | `/api/internal` | Bridge 内部接口（见下表） |
| `account_routes.py` → `alfred_router` | `/api/alfred` | 账户管理 REST（用户、家庭、角色） |
| `webhooks.py` → `webhook_router` | `/webhook` | WhatsApp Cloud API Webhook |
| `main.py` | `/*` | 托管 React SPA（`web/dist/`） |

#### 内部接口（仅 Bridge/服务调用）

| 端点 | 鉴权 Header | 用途 |
|------|------------|------|
| `POST /api/internal/bridge/messages` | `X-Bridge-Key` | Bridge 推送入站消息（含 STT） |
| `POST /api/internal/bridge/outbound` | `X-Bridge-Key` | Bridge 同步出站消息到 DB |
| `POST /api/internal/bridge/ack` | `X-Bridge-Key` | 消息已读/已送达回调 |
| `POST /api/internal/push` | `X-Alfred-API-Key` | 下游服务主动推送消息给用户 |

#### 服务层（`app/services/`）

| 模块 | 职责 |
|------|------|
| `dispatch_service.py` | 消息分发核心：身份校验 → Bot命令 → 意图识别 → 路由 → 回复 |
| `intent_service.py` | 意图识别：LLM（gpt-4o-mini）主路径 + 关键词匹配备用 |
| `service_registry.py` | 加载 `config/services.yaml`，提供 intent → 服务URL/Key 映射 |
| `pending_sessions.py` | 内存中的多轮对话状态（PendingSession），含重试次数上限 |
| `account_bot_service.py` | Bot 命令解析与执行（`/` 开头命令，含管理员命令和用户命令） |
| `bridge_service.py` | Bridge HTTP 客户端：创建/删除 Session、发送文字/图片 |
| `whatsapp_service.py` | Cloud API 发送（文字、语音 TTS） |
| `chat_service.py` | LLM 自然对话兜底（无意图时的通用回复） |
| `stt_service.py` | 语音转文字（Whisper / gpt-4o-mini-transcribe / mock） |
| `media_service.py` | 媒体文件本地存储与读取 |
| `auth_service.py` | JWT 生成与验证 |

#### 数据模型（`app/models/`）

| 模型 | 表 | 关键字段 |
|------|----|---------|
| `Contact` | `contacts` | `phone_number`, `display_name` |
| `Conversation` | `conversations` | `contact_id`, `connection_id`, `updated_at`, `unread_count` |
| `Message` | `messages` | `conversation_id`, `direction`, `message_type`, `body`, `transcript`, `media_url`, `delivery_status` |
| `WhatsAppConnection` | `whatsapp_connections` | `bridge_session_id`, `label` |
| `AlfredUser` | `alfred_users` | `phone`, `display_name`, `role` (admin/user), `family_id` |
| `AlfredFamily` | `alfred_families` | `name`, `created_by` |
| `AdminUser` | `admin_users` | `username`（Web UI 登录用，与 AlfredUser 无关） |

#### 意图识别（`intent_service.py`）

两条路径，LLM 优先：

1. **LLM 路径**：发送 `gpt-4o-mini` 结构化 JSON 请求，schema 定义了所有 intent 枚举和 entities 字段（含 `short_id`、`confirmed` 等），返回 `{intent, entities}` 或 `{intent: null}`。
2. **关键词路径**（LLM 未配置或失败时）：有序列表匹配，更具体的 intent 排在前面（例如 `thread_delete` 先于 `add_thread`）。

**KEYWORD_MAP 顺序**（重要！更具体的 intent 必须排在前面）：

```
monthly_report → set_budget → list_reminders → add_expense → add_income
→ get_balance → acknowledge_reminder → cancel_reminder
→ thread_delete → search_threads → list_threads → add_thread
→ add_reminder → get_schedule
```

#### Note = Thread 用户同义词

从用户角度，"note" 和 "thread" 完全等同：
- 自然语言："note: dentist tomorrow" → `add_thread`；"delete note 3" → `thread_delete`
- Bot 命令：`/note get #3` 自动规范化为 `/thread get #3`
- LLM Prompt：说明 note 和 thread 是同义词
- 系统内部：统一使用 Thread

---

### 4.2 Nudge（:8002）

**目录**：`services/nudge/`  
**入口**：`main.py`

#### 路由（前缀 `/api/nudge`）

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `GET /health` | 公开 | 健康检查 |
| `GET /alfred/capabilities` | `X-Alfred-API-Key` | 声明支持的 intent |
| `POST /alfred/execute` | `X-Alfred-API-Key` | 执行 intent（见下表） |
| `POST /parse` | JWT | AI 解析提醒自然语言 |
| `POST /reminders` | JWT | 创建提醒（Web UI 用） |
| `GET /reminders` | JWT | 列出提醒（Web UI 用） |
| `PATCH /reminders/{id}` | JWT | 更新提醒 |
| `DELETE /reminders/{id}` | JWT | 删除提醒 |
| `POST /threads` | JWT | 创建线索（Web UI 用） |
| `GET /threads` | JWT | 列出线索（Web UI 用） |
| `GET /threads/{id}` | JWT | 获取线索详情 |
| `DELETE /threads/{id}` | JWT | 删除线索 |

#### `/alfred/execute` 支持的 Intent

| Intent | 核心逻辑 | 关键实体 |
|--------|---------|---------|
| `add_reminder` | AI 解析自然语言时间 → 存入 reminders 表 | `title`, `date`, `time`, `timezone` |
| `list_reminders` | 查询 status=active 的提醒，按 nextFireAt 排序，最多 5 条 | — |
| `get_schedule` | 查询今/明/昨的提醒 | `date` (today/tomorrow/yesterday) |
| `cancel_reminder` | 按编号或名称取消提醒（改为 cancelled 状态） | `ref`（编号或名称） |
| `acknowledge_reminder` | 用户回复 OK，将 awaiting → done，或计算 cron 下次触发 | — |
| `add_thread` | 保存线索：AI 生成 title/entities/related，赋 shortId | `content` |
| `list_threads` | 按时间倒序列出用户线索 | `limit`（默认 5） |
| `search_threads` | 全文搜索线索内容 | `query` |
| `thread_delete` | 两步确认删除线索（无 `confirmed` → INSUFFICIENT_DATA 追问） | `short_id`, `confirmed` |
| `thread_get` | 获取线索详情（Bot 命令内部调用） | `short_id` |
| `thread_link` / `thread_unlink` | 关联/解除关联两个线索 | `thread_a`, `thread_b` |
| `thread_links` | 列出线索的所有关联 | `short_id` |

#### 后台任务

- **提醒触发循环**：每分钟运行一次，向到期提醒的用户发送 WhatsApp 推送（通过 `POST /api/internal/push`）。
- **重推机制**：发送失败（网络）最多重试 3 次，每次间隔 60 秒。
- **确认重推**：用户未回复 OK，最多重推 3 次，间隔 5 分钟，之后状态改为 `expired`。

#### 数据库（SQLite）

| 表 | 关键字段 |
|----|---------|
| `reminders` | `id`, `title`, `body`, `type`, `fireAt`, `cronExpression`, `nextFireAt`, `status` (active/awaiting/done/cancelled/expired), `triggerSource`（手机号）, `shortName`（宠物名）, `ackRetries`, `pushRetries` |
| `threads` | `id`, `shortId`（短整数 ID）, `title`, `content`, `entities`（JSON）, `related`（JSON）, `triggerSource`, `createdAt` |
| `thread_links` | `thread_a_id`, `thread_b_id` |

---

### 4.3 OurCents（:8001）

**目录**：`services/ourcents/`  
**入口**：`main.py`

家庭财务记账服务，实现 ASI 接口供 Gateway 调用。

#### `/alfred/execute` 支持的 Intent

| Intent | 功能 | 关键实体 |
|--------|------|---------|
| `add_expense` | 记录支出 | `amount`, `category`, `date` |
| `add_income` | 记录收入 | `amount`, `source`, `date` |
| `get_balance` | 查询账户余额/本月支出汇总 | — |
| `monthly_report` | 月度消费报告 | `year`, `month` |
| `set_budget` | 设置分类预算 | `category`, `amount` |
| `process_receipt_image` | 收据图片 OCR（AI 识别金额、日期、类别） | `image_data`（base64）, `mime_type` |

---

### 4.4 Bridge（:3001）

**目录**：`bridge/`  
**技术**：Node.js + whatsapp-web.js

管理一个或多个 WhatsApp Web 会话（每个实体手机号对应一个 Session）。

#### 主要接口（Gateway 调用）

| 端点 | 用途 |
|------|------|
| `POST /sessions` | 创建新的 WA 会话（返回 QR 码） |
| `DELETE /sessions/{id}` | 删除会话 |
| `GET /sessions` | 列出所有会话及状态 |
| `GET /sessions/{id}` | 获取单个会话详情（含 QR 码、连接状态） |
| `POST /sessions/{id}/messages` | 发送文字消息 |
| `POST /sessions/{id}/images` | 发送图片消息 |

#### 回调（Bridge 推送到 Gateway）

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `POST /api/internal/bridge/messages` | `X-Bridge-Key` | 入站消息（用户发来的） |
| `POST /api/internal/bridge/outbound` | `X-Bridge-Key` | 出站消息同步（Alfred 发出的，用于 UI 记录） |
| `POST /api/internal/bridge/ack` | `X-Bridge-Key` | 消息送达状态回调 |

#### Bridge 监控

- Gateway 启动时恢复所有 DB 中的 Bridge Session。
- **Bridge Watchdog**：后台协程每 30 秒检查一次，若 DB 中的 Session 在 Bridge 中丢失（Bridge 重启），自动重建。

---

### 4.5 Web 前端（:5173）

**目录**：`web/`  
**技术**：React + TypeScript + Vite

管理员 Web 界面，生产环境由 Gateway 静态托管（`web/dist/`），开发环境独立运行。

#### 主要页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 登录 | `/login` | 管理员登录（JWT） |
| 对话列表 | `/` | WhatsApp 会话浏览，实时消息查看 |
| 管理面板 | `/admin` | 账户管理（用户/家庭/角色）、WhatsApp 连接管理、日志查看、危险操作区 |
| 线索面板 | `/nudge` | 线索（Thread/Note）列表、搜索、详情 |
| 提醒管理 | `/nudge` | 提醒列表（集成在 Nudge 面板） |

#### API 调用

前端通过 `/api/*` 调用 Gateway REST 接口，使用 JWT Cookie 鉴权。

---

### 4.6 wa-sim（测试模拟器）

**目录**：`wa-sim/`

模拟 WhatsApp 用户发送消息并验证回复，用于集成测试。

#### 组成

| 模块 | 功能 |
|------|------|
| `src/main.py` | 入口：支持 `--daemon`（持续运行）和 `--scenario`（单场景测试）模式 |
| `src/virtual_phone.py` | 虚拟手机：调用 Gateway `/api/internal/bridge/messages` 模拟入站消息 |
| `src/gateway_client.py` | HTTP 客户端封装 |
| `src/scenarios.py` | 场景加载与执行 |
| `src/bridge_mock.py` | 模拟 Bridge 接收 Gateway 出站消息（用于捕获 Alfred 的回复） |
| `config/scenarios.yaml` | 场景定义（按 group 分组：reminders、threads 等） |
| `output/results.jsonl` | 测试结果记录 |
| `output/errors.jsonl` | 错误记录 |

**注意**：`run.sh` 总是附加 `--daemon` 标志，因此 `--scenario` 与 `run.sh` 不兼容，需直接调用 `python -m src.main --scenario <name>`。

---

## 5. Intent 路由总表

`config/services.yaml` 定义了 intent → 服务的映射，Gateway 的 `ServiceRegistry` 在启动时加载。

| Intent | 路由至 | 关键实体 | 功能 |
|--------|--------|---------|------|
| `add_expense` | OurCents (:8001) | amount, category, date | 记录支出 |
| `add_income` | OurCents (:8001) | amount, source, date | 记录收入 |
| `get_balance` | OurCents (:8001) | — | 查询余额/汇总 |
| `monthly_report` | OurCents (:8001) | year, month | 月度报告 |
| `set_budget` | OurCents (:8001) | category, amount | 设置预算 |
| `process_receipt_image` | OurCents (:8001) | image_data, mime_type | 收据 OCR |
| `add_reminder` | Nudge (:8002) | title, date, time | 添加提醒 |
| `list_reminders` | Nudge (:8002) | — | 列出提醒 |
| `get_schedule` | Nudge (:8002) | date | 查看日程 |
| `cancel_reminder` | Nudge (:8002) | ref | 取消提醒 |
| `acknowledge_reminder` | Nudge (:8002) | — | 确认提醒（回复 OK） |
| `add_thread` | Nudge (:8002) | content | 保存线索/笔记 |
| `list_threads` | Nudge (:8002) | limit | 列出线索 |
| `search_threads` | Nudge (:8002) | query | 搜索线索 |
| `thread_delete` | Nudge (:8002) | short_id, confirmed | 删除线索（需确认） |

---

## 6. ASI 通信契约

Alfred Service Interface（ASI）是 Gateway 与下游服务之间的标准接口。

### 6.1 三个必须实现的端点

| 端点 | 鉴权 | 说明 |
|------|------|------|
| `GET /health` | 公开 | 健康检查，返回 `{service, status, version}` |
| `GET /alfred/capabilities` | `X-Alfred-API-Key` | 声明支持的 intent 列表（含参数说明） |
| `POST /alfred/execute` | `X-Alfred-API-Key` | 执行具体操作（主接口） |

### 6.2 请求体（POST /alfred/execute）

```json
{
  "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "user_id": "+8613800000000",
  "whatsapp_id": "+8613800000000",
  "intent": "add_thread",
  "entities": {
    "content": "明天买降压药",
    "short_id": null,
    "confirmed": null
  },
  "session": { "conversation_id": 42 },
  "timestamp": "2026-05-03T10:05:00Z"
}
```

### 6.3 响应体

**成功（HTTP 200）：**

```json
{
  "request_id": "f47ac10b-...",
  "status": "success",
  "message": "✅ Thread #7 saved: 明天买降压药",
  "data": {},
  "quick_replies": ["List threads", "Find thread"],
  "timestamp": "2026-05-03T10:05:01Z"
}
```

**需要追问（INSUFFICIENT_DATA）：**

```json
{
  "request_id": "f47ac10b-...",
  "status": "error",
  "error_code": "INSUFFICIENT_DATA",
  "message": "🗑 Delete Thread #7?\n\"明天买降压药\"\n\nReply yes to confirm.",
  "timestamp": "2026-05-03T10:05:01Z"
}
```

### 6.4 标准 error_code

| error_code | 含义 | Gateway 行为 |
|------------|------|-------------|
| `INSUFFICIENT_DATA` | 必需实体缺失或需要确认 | 保存 PendingSession，向用户追问 |
| `INVALID_VALUE` | 实体值格式错误 | 提示重新输入 |
| `UNAUTHORIZED` | 用户未绑定账户 | 引导用户完成绑定 |
| `NOT_FOUND` | 查询对象不存在 | 提示用户 |
| `SERVICE_ERROR` | 服务内部异常 | 提示稍后再试 |

### 6.5 服务主动推送（Nudge → Gateway）

当提醒到期时，Nudge 主动调用：

```
POST http://localhost:8000/api/internal/push
X-Alfred-API-Key: <NUDGE_API_KEY>
Content-Type: application/json

{
  "user_phone": "+18005550001",
  "message": "🐾 Mochi — 买降压药\nReply \"OK\" to confirm.",
  "source_service": "nudge",
  "quick_replies": ["✓ OK"]
}
```

---

## 7. 管理员 Bot 命令

管理员通过 WhatsApp 向 Alfred 发送 `/` 开头的命令。所有命令由 `account_bot_service.py` 处理。

### 7.1 所有注册用户可用（Thread/Note 命令）

> Note 和 Thread 在命令中完全等同：`/note X` 自动转换为 `/thread X`。

| 命令 | 功能 |
|------|------|
| `/thread get #<id>` | 查看线索详情 |
| `/thread list [N]` | 列出最近 N 条线索（默认 5） |
| `/thread delete #<id>` | 删除线索（两步确认：先询问，再 Y 确认） |
| `/thread links #<id>` | 查看线索关联 |
| `/note get #<id>` | 同 `/thread get` |
| `/note list [N]` | 同 `/thread list` |
| `/note delete #<id>` | 同 `/thread delete` |
| `/note links #<id>` | 同 `/thread links` |
| `/find <关键词>` | 全文搜索线索 |
| `/link #<id_A> #<id_B>` | 关联两个线索 |
| `/unlink #<id_A> #<id_B>` | 解除两个线索关联 |

### 7.2 仅管理员（admin 角色）可用

| 命令 | 功能 |
|------|------|
| `/add user +phone [名字]` | 注册新用户 |
| `/remove user +phone` | 删除用户（两步确认） |
| `/list users` | 列出所有用户（含角色和家庭） |
| `/set role +phone admin\|user` | 修改用户角色 |
| `/create family "名字"` | 创建家庭组 |
| `/dissolve family fam_xxx` | 解散家庭组（成员数据保留） |
| `/family add +phone fam_xxx` | 将用户加入家庭 |
| `/family remove +phone` | 将用户从家庭移除 |
| `/list families` | 列出所有家庭 |
| `/status` | 查看平台状态（用户数、家庭数、管理员） |

---

## 8. 环境变量

所有服务从项目根目录 `.env` 读取（优先级：根目录 `.env` → 服务目录 `.env`）。

### 8.1 Gateway（`services/gateway/`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | JWT 签名密钥 | `change-me` |
| `ADMIN_USERNAME` | Web UI 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | Web UI 管理员密码 | `admin123` |
| `DATABASE_URL` | SQLite 路径 | `sqlite:///./alfred.db` |
| `WHATSAPP_MODE` | `bridge` 或 `cloud` | `bridge` |
| `BRIDGE_API_URL` | Bridge 地址 | `http://127.0.0.1:3001` |
| `BRIDGE_API_KEY` | Bridge 内部鉴权 Key | — |
| `DISPATCH_ENABLED` | 是否启用消息路由 | `false` |
| `OURCENTS_API_KEY` | OurCents 服务 Key | — |
| `NUDGE_API_KEY` | Nudge 服务 Key | — |
| `ALFRED_INTERNAL_KEY` | 内部推送接口 Key | — |
| `INTENT_OPENAI_API_KEY` | 意图识别 OpenAI Key | — |
| `INTENT_OPENAI_MODEL` | 意图识别模型 | `gpt-4o-mini` |
| `STT_PROVIDER` | 语音转文字提供商（`openai`/`mock`） | `mock` |
| `STT_OPENAI_API_KEY` | Whisper API Key | — |
| `TTS_PROVIDER` | 文字转语音（`openai`/`disabled`） | `disabled` |
| `WHATSAPP_ACCESS_TOKEN` | Cloud API 模式：WA 访问令牌 | — |
| `WHATSAPP_PHONE_NUMBER_ID` | Cloud API 模式：手机号 ID | — |
| `FRONTEND_ORIGIN` | CORS 允许的前端地址 | `http://localhost:5173` |

### 8.2 Nudge（`services/nudge/`）

| 变量 | 说明 |
|------|------|
| `NUDGE_API_KEY` | 与 Gateway 的 `NUDGE_API_KEY` 相同 |
| `GATEWAY_URL` | Gateway 地址（用于主动推送） |
| `OPENAI_API_KEY` | AI 解析提醒用的 OpenAI Key |
| `NUDGE_REFIRE_INTERVAL_SECONDS` | 未确认提醒重推间隔（默认 300s） |
| `NUDGE_MAX_ACK_RETRIES` | 最大重推次数（默认 3） |
| `FRONTEND_ORIGIN` | CORS 允许的前端地址 |

### 8.3 OurCents（`services/ourcents/`）

| 变量 | 说明 |
|------|------|
| `OURCENTS_API_KEY` | 与 Gateway 的 `OURCENTS_API_KEY` 相同 |
| `OPENAI_API_KEY` | 收据 OCR 用的 OpenAI Key |

---

## 9. 进程启动清单

本地开发环境（按顺序启动）：

| 序 | 服务 | 启动命令 | 端口 |
|---|------|---------|------|
| 1 | Bridge | `cd bridge && node src/server.mjs` | 3001 |
| 2 | Gateway | `cd services/gateway && uvicorn app.main:app --port 8000 --reload` | 8000 |
| 3 | OurCents | `cd services/ourcents && uvicorn main:app --port 8001 --reload` | 8001 |
| 4 | Nudge | `cd services/nudge && uvicorn main:app --port 8002 --reload` | 8002 |
| 5 | Web 前端（开发） | `cd web && npm run dev` | 5173 |

生产环境：Web 前端通过 `npm run build` 构建后由 Gateway 静态托管，无需单独启动。

**`DISPATCH_ENABLED=true` 必须在 `.env` 中设置，否则 Gateway 不会路由任何消息。**

---

*文档结束 · Alfred Architecture v1.2 · 基于实际代码库分析 · 2026 年 5 月*
