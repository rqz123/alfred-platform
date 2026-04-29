# WhatsApp 模拟器 — 需求与实现说明

## 1. 背景

Alfred Platform 是一个基于 WhatsApp 的助理系统。当前完整数据流：

```
用户手机 → WhatsApp → Bridge 服务(:3001) → Gateway(:8000) → Alfred 业务处理 → Bridge → WhatsApp → 用户手机
```

调试痛点：
- 每次测试都要用真实手机发消息，慢且容易遗漏边界场景
- 难以复现"多客户同时对话"的并发情况
- 多轮对话（PendingSession）的状态调试需要反复手发消息
- 回归测试只能靠手动操作

## 2. 目标

构建一个独立的 Python 程序"WhatsApp 模拟器"，能：

1. 模拟多个 WhatsApp 客户（虚拟号码）并发与 Gateway 交互
2. 通过 YAML 场景库驱动测试用例，便于回归
3. 在终端实时显示每个虚拟号与 Alfred 的对话
4. 支持 text + image 消息双向流转
5. 完全不依赖真实 WhatsApp / Bridge，零外部依赖

非目标（v1 不做）：性能压测、伪造 WhatsApp 协议本身、复杂 UI。

## 3. 架构

### 关键设计

模拟器同时扮演两个角色：

- **下游客户端**：调用 Gateway 的入站 webhook 模拟用户发消息
- **上游 Bridge**：监听 Gateway 的出站调用，接收 Alfred 的回复

通过修改 Gateway 的环境变量 `BRIDGE_API_URL` 指向模拟器，**Gateway 代码完全不需要修改**。

### 数据流

```
[模拟器]                                            [Gateway]
 虚拟号 Alice
   │
   │ ① POST /api/internal/bridge/messages
   │    X-Bridge-Key: <BRIDGE_API_KEY>
   │    {session_id, sender_phone=Alice, body, ...}
   ├──────────────────────────────────────────────────►
   │                                                  │
   │                                       204 No Content
   │ ◄────────────────────────────────────────────────┤
   │                                                  │
   │                                            Alfred 处理
   │                                                  │
   │ ② POST /sessions/{id}/messages/text              │
   │    {recipient_phone: Alice, body: "..."}         │
   │ ◄────────────────────────────────────────────────┤
   │                                                  │
   │    {provider_message_id: "..."}                  │
   ├──────────────────────────────────────────────────►
   │
   └─► 显示在 Alice 的对话窗口
```

## 4. 接口规范

### 4.1 模拟器调用 Gateway（入站方向）

```
POST http://localhost:8000/api/internal/bridge/messages
Headers:
  X-Bridge-Key: <BRIDGE_API_KEY>
  Content-Type: application/json
Body:
{
  "session_id":          "sim-session-001",
  "provider_message_id": "<每条唯一>",
  "sender_phone":        "+8613800138001",
  "sender_name":         "Alice",
  "message_type":        "text",
  "body":                "用户消息内容",
  "media_url":           "data:image/jpeg;base64,..."   // 仅 image
}
Response: 204 No Content
```

所有虚拟号共用同一个 `session_id`（在 .env 配置），靠 `sender_phone` 区分用户。

### 4.2 模拟器需要实现的 Bridge endpoint

监听端口默认 `9001`。

| Method | Path | 说明 |
|--------|------|------|
| POST | `/sessions/{session_id}/messages/text` | 接收文字回复 |
| POST | `/sessions/{session_id}/messages/media` | 接收图片回复 |
| GET | `/sessions` | 返回 session 列表 |
| GET | `/sessions/{id}` | 返回单个 session |
| POST | `/sessions` | 创建 session（返回固定值即可） |
| DELETE | `/sessions/{id}` | 删除 session（返回成功即可） |
| `*` | 任意未匹配路径 | 返回 200 + `{}` 并打印 WARN 日志 |

#### POST /sessions/{session_id}/messages/text

Request:
```json
{ "recipient_phone": "+8613800138001", "body": "Alfred 的回复" }
```
Response:
```json
{ "provider_message_id": "sim-out-<timestamp>" }
```
处理：按 `recipient_phone` 找到虚拟号 → 追加到对话历史 → UI 显示。

#### POST /sessions/{session_id}/messages/media

Request:
```json
{
  "recipient_phone": "+86...",
  "data": "<base64>",
  "mimetype": "image/jpeg",
  "caption": "可选"
}
```
Response: 同 text。
处理：把 base64 解码存到 `output/media/<phone>_<timestamp>.<ext>`，对话里显示 caption + 文件路径。

#### GET /sessions

```json
[
  { "id": "sim-session-001", "status": "connected", "connected_phone": "+8613800000000" }
]
```

#### GET /sessions/{id}

返回单个对象，结构同上。

#### POST /sessions / DELETE /sessions/{id}

返回成功即可，不做实际状态变更（v1 只用一个固定 session）。

#### 通配 fallback

```python
@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH"])
async def fallback(path: str, request: Request):
    body = await request.body()
    log.warning(f"Unmocked endpoint: {request.method} /{path}  body={body[:200]}")
    return {}
```

这能在 Gateway 调用未实现的接口时及时发现，而不是直接 404 让 Gateway 报错。

## 5. 实现要求

### 5.1 技术栈

- Python 3.11+
- FastAPI + uvicorn（Bridge mock server）
- httpx（异步 HTTP 客户端，调 Gateway）
- PyYAML（场景库解析）
- rich（终端 UI，分栏 + 颜色）
- 状态全部放内存，不需要数据库

### 5.2 目录结构

```
simulator/
├── README.md
├── requirements.txt
├── .env.example
├── config/
│   └── scenarios.yaml
├── src/
│   ├── main.py             # 入口
│   ├── settings.py         # 读取 .env
│   ├── bridge_mock.py      # FastAPI 假 Bridge
│   ├── gateway_client.py   # 调 Gateway 的客户端
│   ├── virtual_phone.py    # VirtualPhone 数据类
│   ├── scenarios.py        # 场景库加载 + 执行器
│   └── ui.py               # rich 终端显示
└── output/
    └── media/              # 接收的图片
```

### 5.3 核心数据结构

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass
class Message:
    direction: Literal["out", "in"]      # out = 模拟器发, in = Alfred 回
    timestamp: datetime
    body: str
    message_type: Literal["text", "image"] = "text"
    media_path: str | None = None

@dataclass
class VirtualPhone:
    phone: str                            # "+8613800138001"
    name: str
    conversation: list[Message] = field(default_factory=list)
    inbound_queue: "asyncio.Queue[Message]" = field(default_factory=asyncio.Queue)
    state: Literal["idle","sending","waiting_reply"] = "idle"

# 全局注册表
phones: dict[str, VirtualPhone] = {}      # key = phone (E.164 格式)
```

`inbound_queue` 用于场景执行器的 `expect_reply` 步骤等待回复。Bridge mock 收到出站消息时把 Message 推入对应虚拟号的队列。

### 5.4 启动流程

```
1. 读取 .env (BRIDGE_API_KEY, GATEWAY_URL, BRIDGE_PORT, SESSION_ID, DB_PATH)
2. 读取 config/scenarios.yaml，初始化 phones 字典
3. 检查 Gateway 数据库：whatsappconnection 表是否有 bridge_session_id = SESSION_ID 这一行
   - 没有则提示用户：sqlite3 <DB_PATH> "INSERT OR IGNORE INTO whatsappconnection (bridge_session_id, label, created_at) VALUES ('<SESSION_ID>', 'Simulator', datetime('now'));"
   - 或加 --auto-register 命令行参数自动 INSERT
4. 启动 FastAPI uvicorn server（线程或子任务）
5. 启动 scenario runner（每个虚拟号一个 asyncio.task）
6. 启动 rich UI（asyncio task，定期刷新）
7. 监听 Ctrl+C，优雅退出
```

### 5.5 场景库格式（config/scenarios.yaml）

```yaml
phones:
  - phone: "+8613800138001"
    name: "Alice"
  - phone: "+8613800138002"
    name: "Bob"

scenarios:
  - name: 简单消费记录
    weight: 5
    steps:
      - send: "花了${amount}吃${meal}"
        vars:
          amount: [25, 40, 80, 120]
          meal: ["午饭", "晚饭", "夜宵"]
      - expect_reply:
          contains_any: ["记录", "已收到", "$"]
          timeout: 10

  - name: 多轮澄清
    weight: 2
    steps:
      - send: "记一笔"
      - expect_reply:
          contains_any: ["金额", "多少", "?"]
          timeout: 10
      - send: "${amount}元"
        vars:
          amount: [50, 88, 200]
      - expect_reply:
          contains_any: ["完成", "已记"]
          timeout: 10

  - name: 查询余额
    weight: 1
    steps:
      - send: "本月花了多少"
      - expect_reply:
          contains_any: ["¥", "$", "元"]
          timeout: 10

runner:
  mode: "interval"                 # interval | once | manual
  interval_seconds: [5, 15]        # 每个号码每 5-15s 触发一个场景
```

### 5.6 场景执行逻辑

```python
async def run_phone_loop(phone: VirtualPhone, scenarios: list, runner_cfg):
    while not stop_event.is_set():
        await asyncio.sleep(random.uniform(*runner_cfg.interval_seconds))
        scenario = weighted_random_pick(scenarios)
        for step in scenario.steps:
            if "send" in step:
                body = render_template(step["send"], step.get("vars", {}))
                await gateway_client.send_text(phone.phone, phone.name, body)
                phone.conversation.append(Message("out", now(), body))
            elif "expect_reply" in step:
                cfg = step["expect_reply"]
                try:
                    msg = await asyncio.wait_for(
                        phone.inbound_queue.get(),
                        timeout=cfg["timeout"]
                    )
                    if not any(kw in msg.body for kw in cfg["contains_any"]):
                        log.warning(f"[{scenario.name}] FAIL: '{msg.body}' 不含 {cfg['contains_any']}")
                    else:
                        log.info(f"[{scenario.name}] PASS")
                except asyncio.TimeoutError:
                    log.error(f"[{scenario.name}] TIMEOUT 等待回复")
                    break  # 当前场景终止，下个 cycle 再来
```

### 5.7 Bridge mock server 关键代码骨架

```python
from fastapi import FastAPI, Request
app = FastAPI()

@app.post("/sessions/{session_id}/messages/text")
async def receive_text(session_id: str, payload: dict):
    phone_key = normalize(payload["recipient_phone"])
    phone = phones.get(phone_key)
    if phone is None:
        log.warning(f"出站消息发给未知号码 {phone_key}")
        return {"provider_message_id": f"sim-out-{uuid4().hex[:8]}"}
    msg = Message("in", now(), payload["body"])
    phone.conversation.append(msg)
    await phone.inbound_queue.put(msg)
    return {"provider_message_id": f"sim-out-{uuid4().hex[:8]}"}

@app.post("/sessions/{session_id}/messages/media")
async def receive_media(session_id: str, payload: dict):
    # 类似 text，但要先 base64 解码存盘，body 用 caption
    ...

@app.get("/sessions")
async def list_sessions():
    return [{"id": SESSION_ID, "status": "connected", "connected_phone": "+8613800000000"}]

@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH"])
async def fallback(path: str, request: Request):
    log.warning(f"Unmocked: {request.method} /{path}")
    return {}
```

### 5.8 Gateway client

```python
class GatewayClient:
    def __init__(self, base_url, api_key, session_id):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10)
        self.api_key = api_key
        self.session_id = session_id

    async def send_text(self, phone, name, body):
        await self.client.post(
            "/api/internal/bridge/messages",
            headers={"X-Bridge-Key": self.api_key},
            json={
                "session_id": self.session_id,
                "provider_message_id": f"sim-{phone}-{uuid4().hex[:8]}",
                "sender_phone": phone,
                "sender_name": name,
                "message_type": "text",
                "body": body,
            },
        )

    async def send_image(self, phone, name, caption, image_path):
        data_url = encode_image_as_data_url(image_path)
        await self.client.post(...)  # message_type=image, media_url=data_url
```

### 5.9 终端 UI（rich）

最简版：所有事件按时间顺序滚动打印，号码用不同颜色：

```
[10:23:01] Alice → "花了40吃午饭"
[10:23:02] Alice ← "已记录支出 ¥40 餐饮"
[10:23:05] Bob   → "本月花了多少"
[10:23:06] Bob   ← "本月共支出 ¥320"
[10:23:08] [scenario PASS] Alice/简单消费记录
```

进阶版（可选）：rich.live + Layout，左栏号码列表，右栏选中号码的对话，底部场景执行日志。v1 先做最简版即可。

### 5.10 .env.example

```
GATEWAY_URL=http://localhost:8000
BRIDGE_API_KEY=change-me-bridge-key
BRIDGE_PORT=9001
SESSION_ID=sim-session-001
DB_PATH=/path/to/alfred.db
```

### 5.11 README.md 内容（启动步骤）

```bash
# 1. 安装依赖
cd simulator
pip install -r requirements.txt

# 2. 配置
cp .env.example .env
# 编辑 .env，BRIDGE_API_KEY 必须与 Gateway 的 .env 一致

# 3. 修改 Gateway 的 .env，让它指向模拟器
BRIDGE_API_URL=http://localhost:9001

# 4. 在 Gateway 数据库登记 simulator session（首次运行）
python src/main.py --auto-register
# 或手动：
sqlite3 alfred.db "INSERT OR IGNORE INTO whatsappconnection (bridge_session_id, label, created_at) VALUES ('sim-session-001', 'Simulator', datetime('now'));"

# 5. 重启 Gateway

# 6. 启动模拟器
python src/main.py

# 切回真实 Bridge：把 Gateway .env 的 BRIDGE_API_URL 改回 http://localhost:3001
```

## 6. 待确认问题（实现时验证）

实现 claude 在动手前，需要先回答以下几个问题（看代码或试运行就能确定）：

1. **Conversation 表字段确认**：`services/gateway/app/models/chat.py` 的 `Conversation` 模型中，与 `WhatsAppConnection` 关联的字段叫什么？Gateway 在出站时是从这里读 `bridge_session_id` 还是从其他地方？如果是从 Conversation 读，那么 v1 所有虚拟号共用一个 session 完全 OK。

2. **Gateway 启动会调哪些 Bridge endpoint**：跑起来后看 fallback 日志，把所有 WARN 的路径都补全实现。

3. **`provider_message_id` 去重逻辑**：Gateway 是否会按这个字段去重？模拟器内部要保证每条消息这个 id 全局唯一（用 uuid4 即可）。

4. **PendingSession 的 key**：`services/gateway/app/services/intent_service.py`（或类似文件）中 `_store: dict[str, PendingSession]` 的 key 是用 normalized phone（纯数字）还是 E.164（带 +）？模拟器发 `sender_phone` 时格式要匹配，否则多轮会失败。

## 7. 验收标准

v1 完成的 7 个标志：

1. 启动模拟器 + 修改 Gateway 的 `BRIDGE_API_URL` 后，Gateway 能正常启动不报错
2. 单虚拟号发"花了 40 吃午饭"，能在终端看到 Alfred 的回复
3. 2 个以上虚拟号并发发消息，回复能正确路由到对应号码（不串）
4. 多轮场景（"记一笔" → 等"金额？" → "50"）能跑通，PendingSession 状态正确
5. 图片消息从模拟器发出，Gateway 不报错，OCR 服务能正常处理
6. Alfred 回复图片时（如有此场景），模拟器能存到 `output/media/`
7. `expect_reply` 超时能正确报 FAIL 并继续下个 cycle，不卡住

## 8. v2 路线（先不做，留作扩展）

- Web UI：浏览器里查看每个号码的实时对话，类似 WhatsApp Web
- 录制/回放：记录真实对话，回放为测试用例
- 断言增强：支持正则、JSON path、外部 LLM 判断"语义是否符合预期"
- 性能模式：单进程拉到 100+ 虚拟号并发，输出 P50/P99 延迟
- CI 集成：场景库作为冒烟测试，每次 Gateway 部署前跑一遍
