# Alfred 多应用平台 — 整体架构设计与 API 规范

> **版本 1.1** · 基于代码库实际分析 · 2026 年 4 月

---

## 目录

1. [代码分析：现状与差距](#1-代码分析现状与差距)
2. [修订后的系统架构图](#2-修订后的系统架构图)
3. [Alfred 需要新增/修改的文件](#3-alfred-需要新增修改的文件)
4. [OurCents 新增 FastAPI 层](#4-ourcents-新增-fastapi-层)
5. [ASI 通信契约（正式规范）](#5-asi-通信契约正式规范)
6. [部署与环境变量](#6-部署与环境变量)

---

## 1. 代码分析：现状与差距

### 1.1 Alfred 现有架构（已完成）

| 组件 | 路径 | 端口 | 职责 | 状态 |
|------|------|------|------|------|
| FastAPI 后端 | `backend/` | 8000 | 业务逻辑、消息持久化、Auth（JWT） | ✅ 已完成 |
| Node.js Bridge | `bridge/src/server.mjs` | 3001 | whatsapp-web.js 适配器，管理 WA 会话 | ✅ 已完成 |
| React 前端 | `frontend/src/` | 5173 | 管理员 Web UI，QR 扫码、对话浏览 | ✅ 已完成 |

> **注意**：Alfred 支持两种 WhatsApp 模式：`WHATSAPP_MODE=bridge`（whatsapp-web.js）或 `cloud`（Meta Cloud API），由环境变量切换。

### 1.2 关键发现：Alfred 的消息处理缺口

在 `whatsapp_service.py` 的 `process_webhook_payload` 中，收到的消息仅被持久化，没有任何后续处理：

```python
# backend/app/services/whatsapp_service.py（当前代码）
def process_webhook_payload(session: Session, payload: dict) -> None:
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for message in value.get('messages', []):
                _persist_inbound_message(session, message, ...)  # ← 仅存储，无路由
```

> ⚠️ **缺失**：没有意图识别、没有服务路由、没有自动回复。所有智能化处理需要新增。

### 1.3 关键发现：OurCents 是 Streamlit 应用，无 REST API

OurCents 目前是纯 Streamlit Web 应用（`app.py` 入口），没有任何 REST API 端点。Alfred 无法直接调用它。

| 文件 | 内容 | 说明 |
|------|------|------|
| `app.py` | Streamlit 入口 | 仅 UI，无 API |
| `src/services/dashboard_service.py` | DashboardService 类 | 已有完整业务逻辑，可复用 |
| `src/services/receipt_ingestion_service.py` | ReceiptIngestionService | AI 收据解析，可复用 |
| `src/models/schema.py` | Pydantic 数据模型 | family_id / user_id 体系 |
| `src/storage/database.py` | SQLite 操作 | 独立数据库 |

> ⚠️ 需要为 OurCents 新增一个 FastAPI 层（运行在独立端口），Alfred 通过该层调用业务逻辑。

### 1.4 已有的好基础

- ✅ `docs/architecture.md` 已规划 `POST /api/external/messages`，说明作者预见了这个扩展方向
- ✅ Alfred 已有 STT 能力，可自动转录语音消息，大大简化意图识别
- ✅ Alfred 已有完整的消息发送基础设施（`send_text_via_bridge` / `send_text_message`），dispatch 层可直接复用
- ✅ OurCents 的 `DashboardService`、`ReceiptIngestionService` 业务逻辑完整，只需包装 API 层

---

## 2. 修订后的系统架构图

### 2.1 整体拓扑

```
                 ┌──────────────────────────────┐
                 │   WhatsApp (用户手机)          │
                 └──────────┬───────────────────┘
                            │ 消息/语音/图片
                            ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                 ALFRED  (:8000)                             │
  │                                                             │
  │  ┌─────────────┐    ┌────────────────────────────────────┐  │
  │  │  Bridge     │    │  FastAPI Backend                   │  │
  │  │  :3001      │    │                                    │  │
  │  │ (Node.js /  │◀──▶│  webhooks.py                       │  │
  │  │  WA-Web.js) │    │   ↓ process_webhook_payload        │  │
  │  └─────────────┘    │   ↓ [NEW] dispatch_service         │  │
  │                     │       ↓ intent_service              │  │
  │  ┌─────────────┐    │       ↓ service_registry (yaml)    │  │
  │  │  Frontend   │    │       ↓ HTTP call → ASI             │  │
  │  │  :5173      │    │       ↓ send_reply                  │  │
  │  │  (React)    │    │                                    │  │
  │  └─────────────┘    │  [NEW] POST /api/internal/push     │  │
  │                     └────────────────────────────────────┘  │
  └─────────────────────────┼───────────────────────────────────┘
                   │                         │
          REST (X-Alfred-API-Key)    REST (X-Alfred-API-Key)
                   │                         │
                   ▼                         ▼
  ┌────────────────────────┐   ┌───────────────────────────┐
  │  OurCents  (:8001)     │   │  OurSchedule  (:8002)     │
  │  [NEW] FastAPI 层      │   │  [待开发] FastAPI 层       │
  │  ┌──────────────────┐  │   │                           │
  │  │  ASI 端点         │  │   │  ASI 端点                 │
  │  │  /health          │  │   │  /health                  │
  │  │  /alfred/execute  │  │   │  /alfred/execute          │
  │  └──────────────────┘  │   │                           │
  │  ┌──────────────────┐  │   └───────────────────────────┘
  │  │  现有业务逻辑     │  │
  │  │  DashboardService │  │
  │  │  ReceiptIngestion │  │
  │  └──────────────────┘  │
  │  SQLite                │
  └────────────────────────┘
```

### 2.2 消息处理流程（新增 dispatch 层后）

```
用户发送 WhatsApp 消息（文字/语音/图片）
  │
  │ 1. Bridge 接收 → POST /api/internal/bridge/messages
  ▼
process_webhook_payload()  — 现有代码
  │
  │ 2. 持久化消息到 DB（现有逻辑不变）
  │ 3. [NEW] 调用 dispatch_service.dispatch(message, contact)
  ▼
dispatch_service.dispatch()
  │
  │ 4. 读取消息文本（语音则使用 transcript 字段）
  │ 5. 调用 intent_service.detect(text) → intent + entities
  │ 6. 查询 service_registry → 找到目标服务 URL
  │ 7. POST {service_url}/alfred/execute  (X-Alfred-API-Key)
  ▼
目标微服务 (OurCents / OurSchedule / ...)
  │
  │ 8. 执行业务逻辑 → 返回 {status, message, quick_replies}
  ▼
dispatch_service 收到响应
  │
  │ 9. 调用 send_text_via_bridge() 或 send_text_message()
  ▼
用户收到 WhatsApp 回复
```

---

## 3. Alfred 需要新增/修改的文件

### 3.1 修改清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **MODIFY** | `backend/app/services/whatsapp_service.py` | 在 `process_webhook_payload` 末尾添加 dispatch 调用（约 3 行） |
| **NEW** | `backend/app/services/dispatch_service.py` | 消息分发核心：识别意图 → 路由 → 调用服务 → 回复 |
| **NEW** | `backend/app/services/intent_service.py` | 意图识别：关键词匹配或 LLM 调用 |
| **NEW** | `backend/app/services/service_registry.py` | 加载 services.yaml，提供 intent→URL 映射 |
| **NEW** | `backend/config/services.yaml` | 服务注册表配置文件 |
| **NEW ENDPOINT** | `backend/app/api/routes.py` | 添加 `POST /api/internal/push`（供微服务主动推送） |
| **ADD ENV** | `backend/.env` | 新增 `OURCENTS_API_KEY`、`OURSCHEDULE_API_KEY` 等 |

### 3.2 修改 whatsapp_service.py

仅需在 `process_webhook_payload` 中添加 3 行：

```python
from app.services.dispatch_service import dispatch_message  # ← 新增 import

def process_webhook_payload(session: Session, payload: dict) -> None:
    entries = payload.get('entry', [])
    for entry in entries:
        for change in entry.get('changes', []):
            value = change.get('value', {})
            contacts_by_wa_id = { ... }  # 现有代码不变

            for message in value.get('messages', []):
                stored = _persist_inbound_message(session, message, contacts_by_wa_id)
                if stored:                                      # ← 新增
                    dispatch_message(session, stored, message)  # ← 新增

            for status_item in value.get('statuses', []):  # 现有代码不变
                ...
```

> 注意：`_persist_inbound_message` 目前返回 `None`，需修改为返回存储后的 `Message` 对象。

### 3.3 新增 dispatch_service.py

```python
# backend/app/services/dispatch_service.py
import logging
from sqlmodel import Session
import httpx
from app.models.chat import Message, Contact, Conversation
from app.services.service_registry import ServiceRegistry
from app.services.intent_service import detect_intent
from app.services.bridge_service import send_text_via_bridge
from app.core.config import get_settings
from uuid import uuid4
from datetime import datetime, timezone

logger = logging.getLogger('alfred.dispatch')
registry = ServiceRegistry()

def dispatch_message(session: Session, message: Message, raw: dict) -> None:
    """Route an inbound message to the appropriate service and reply."""
    # 1. Get text (prefer transcript for audio messages)
    text = message.transcript or message.body
    if not text:
        return

    # 2. Get sender phone
    conv = session.get(Conversation, message.conversation_id)
    contact = session.get(Contact, conv.contact_id)
    phone = contact.phone_number

    # 3. Detect intent
    result = detect_intent(text)
    if result is None:
        return

    intent, entities = result['intent'], result['entities']

    # 4. Find target service
    service = registry.find_service(intent)
    if service is None:
        return

    # 5. Call ASI /alfred/execute
    payload = {
        'request_id': str(uuid4()),
        'user_id': phone,
        'whatsapp_id': phone,
        'intent': intent,
        'entities': entities,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = httpx.post(
            f"{service['url']}/alfred/execute",
            json=payload,
            headers={'X-Alfred-API-Key': service['api_key']},
            timeout=15.0,
        )
        r.raise_for_status()
        resp = r.json()
    except Exception as exc:
        logger.error('Dispatch to %s failed: %s', service['name'], exc)
        return

    # 6. Send reply back to WhatsApp user
    reply_text = resp.get('message', '')
    if quick := resp.get('quick_replies'):
        reply_text += '\n\n' + '  '.join(f'[{q}]' for q in quick)

    settings = get_settings()
    if settings.whatsapp_mode == 'bridge' and conv.connection_id:
        conn = session.get_connection_by_id(conv.connection_id)
        send_text_via_bridge(conn.bridge_session_id, phone, reply_text)
```

### 3.4 新增 intent_service.py（关键词版 v1）

```python
# backend/app/services/intent_service.py
import re
from typing import Optional

KEYWORD_MAP = [
    (['花了', '消费', '买', '付了', '支出', '记账'], 'add_expense'),
    (['收入', '工资', '收到', '入账'],                'add_income'),
    (['余额', '还剩', '账户'],                        'get_balance'),
    (['本月', '月报', '月度', '消费报告'],             'monthly_report'),
    (['提醒', '提示', 'remind', '别忘了'],            'add_reminder'),
    (['日程', '今天有什么', '安排'],                   'get_schedule'),
]

def detect_intent(text: str) -> Optional[dict]:
    t = text.lower()
    for keywords, intent in KEYWORD_MAP:
        if any(k in t for k in keywords):
            return {'intent': intent, 'entities': _extract_entities(t, intent)}
    return None

def _extract_entities(text: str, intent: str) -> dict:
    entities = {}
    m = re.search(r'[¥$]?([0-9]+(?:\.[0-9]{1,2})?)', text)
    if m:
        entities['amount'] = float(m.group(1))
    if '今天' in text: entities['date'] = 'today'
    elif '明天' in text: entities['date'] = 'tomorrow'
    return entities
```

### 3.5 新增 service_registry.py + services.yaml

```yaml
# backend/config/services.yaml
services:
  ourcents:
    name: OurCents
    url: http://localhost:8001
    api_key_env: OURCENTS_API_KEY
    intents:
      - add_expense
      - add_income
      - get_balance
      - monthly_report

  ourschedule:
    name: OurSchedule
    url: http://localhost:8002
    api_key_env: OURSCHEDULE_API_KEY
    intents:
      - add_reminder
      - list_reminders
      - get_schedule
```

```python
# backend/app/services/service_registry.py
import yaml, os
from pathlib import Path

class ServiceRegistry:
    def __init__(self):
        cfg_path = Path(__file__).parents[3] / 'config/services.yaml'
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        self._map: dict[str, dict] = {}
        for svc_id, svc in cfg['services'].items():
            api_key = os.environ.get(svc['api_key_env'], '')
            for intent in svc['intents']:
                self._map[intent] = {
                    'name': svc['name'],
                    'url': svc['url'],
                    'api_key': api_key,
                }

    def find_service(self, intent: str) -> dict | None:
        return self._map.get(intent)
```

### 3.6 新增端点：POST /api/internal/push

供 OurSchedule 等服务在触发提醒时主动推送：

```python
# 追加到 backend/app/api/routes.py

class PushRequest(BaseModel):
    user_phone: str        # WhatsApp 手机号
    message: str           # 消息内容
    source_service: str    # 来源服务标识
    quick_replies: list[str] = []

@internal_router.post('/internal/push', status_code=204)
def receive_service_push(
    payload: PushRequest,
    x_alfred_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    settings = get_settings()
    valid_keys = [os.environ.get(k, '') for k in ['OURCENTS_API_KEY', 'OURSCHEDULE_API_KEY']]
    if x_alfred_api_key not in valid_keys:
        raise HTTPException(401, 'Invalid key')
    # 查找 Contact → send via bridge or cloud API
    ...
    return Response(status_code=204)
```

---

## 4. OurCents 新增 FastAPI 层

OurCents 目前是纯 Streamlit 应用，需新增一个 FastAPI 服务，**完全复用**现有业务逻辑，不改动 `src/` 下任何代码。

### 4.1 新增文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **NEW** | `alfred_api/main.py` | FastAPI 应用入口，运行于 :8001 |
| **NEW** | `alfred_api/router.py` | ASI 端点：`/health`、`/alfred/capabilities`、`/alfred/execute` |
| **NEW** | `alfred_api/schemas.py` | 请求/响应 Pydantic 模型 |
| **NEW** | `alfred_api/user_bridge.py` | WhatsApp 手机号 → family_id 映射 |
| **MODIFY** | `requirements.txt` | 新增 `fastapi`、`uvicorn` |

### 4.2 alfred_api/main.py

```python
# OurCents/alfred_api/main.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fastapi import FastAPI
from alfred_api.router import router

app = FastAPI(title='OurCents Alfred API')
app.include_router(router)

# 启动: uvicorn alfred_api.main:app --port 8001
```

### 4.3 alfred_api/router.py

```python
# OurCents/alfred_api/router.py
import os
from fastapi import APIRouter, Header, HTTPException, Depends
from alfred_api.schemas import ExecuteRequest, ExecuteResponse
from alfred_api.user_bridge import get_family_by_phone
from storage.database import Database
from services.dashboard_service import DashboardService

router = APIRouter()
ALFRED_API_KEY = os.environ['ALFRED_API_KEY']

def verify(x_alfred_api_key: str = Header(...)):
    if x_alfred_api_key != ALFRED_API_KEY:
        raise HTTPException(401, 'Unauthorized')

@router.get('/health')
def health():
    return {'service': 'ourcents', 'status': 'ok', 'version': '1.0.0'}

@router.get('/alfred/capabilities')
def capabilities(_ = Depends(verify)):
    return {
        'service': 'ourcents',
        'display_name': 'OurCents 家庭财务',
        'capabilities': [
            {
                'intent': 'add_expense',
                'description': '记录支出',
                'required_entities': [
                    {'name': 'amount', 'type': 'float', 'prompt_cn': '金额是多少？'}
                ],
                'optional_entities': [
                    {'name': 'category', 'type': 'string', 'prompt_cn': '类别？'},
                    {'name': 'date', 'type': 'date', 'prompt_cn': '日期（默认今天）'}
                ]
            },
            {'intent': 'get_balance', 'description': '查询本月支出汇总'},
            {'intent': 'monthly_report', 'description': '月度消费报告'},
        ]
    }

@router.post('/alfred/execute', response_model=ExecuteResponse)
def execute(req: ExecuteRequest, _ = Depends(verify)):
    db = Database()
    family = get_family_by_phone(db, req.whatsapp_id)
    if not family:
        return ExecuteResponse(
            request_id=req.request_id, status='error',
            error_code='UNAUTHORIZED',
            message='您的手机号尚未绑定 OurCents 账户。请先登录网页版完成绑定。'
        )

    family_id = family['family_id']
    svc = DashboardService(db)

    if req.intent == 'get_balance':
        data = svc.get_period_dashboard(family_id, 'month')
        msg = f"本月支出：¥{data['total_amount']:.2f}（共 {data['receipt_count']} 笔）"
        top = list(data['category_breakdown'].items())[:3]
        if top:
            msg += '\n主要类别：' + '、'.join(f'{k} ¥{v:.0f}' for k, v in top)
        return ExecuteResponse(
            request_id=req.request_id, status='success', message=msg,
            data=data, quick_replies=['月度报告', '添加支出', '查看记录']
        )

    if req.intent == 'monthly_report':
        data = svc.get_family_dashboard(family_id)
        msg = (f"本月支出 ¥{data.total_expenses_month:.2f} / 本周 ¥{data.total_expenses_week:.2f}\n"
               f"可抵税金额：¥{data.deductible_amount_month:.2f}")
        return ExecuteResponse(
            request_id=req.request_id, status='success', message=msg,
            quick_replies=['查看分类明细', '添加支出']
        )

    if req.intent == 'add_expense':
        amount = req.entities.get('amount')
        if not amount:
            return ExecuteResponse(
                request_id=req.request_id, status='error',
                error_code='INSUFFICIENT_DATA',
                message='请告诉我金额，例如：花了50元'
            )
        msg = f"✅ 已记录支出 ¥{amount:.2f}"
        return ExecuteResponse(
            request_id=req.request_id, status='success',
            message=msg, quick_replies=['查看本月', '继续添加']
        )

    return ExecuteResponse(
        request_id=req.request_id, status='error',
        error_code='NOT_FOUND', message='未知操作'
    )
```

### 4.4 user_bridge.py — 手机号 ↔ family_id 映射

新增 `phone_mappings` 表到 OurCents SQLite：

```sql
CREATE TABLE phone_mappings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    phone     TEXT UNIQUE NOT NULL,
    user_id   INTEGER NOT NULL,
    family_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (family_id) REFERENCES families(id)
);
```

```python
# OurCents/alfred_api/user_bridge.py
def get_family_by_phone(db, phone: str) -> dict | None:
    normalized = ''.join(c for c in phone if c.isdigit())
    with db.get_connection() as conn:
        row = conn.execute(
            'SELECT user_id, family_id FROM phone_mappings WHERE phone=?', (normalized,)
        ).fetchone()
    return dict(row) if row else None
```

### 4.5 alfred_api/schemas.py

```python
from pydantic import BaseModel
from typing import Any, Optional

class ExecuteRequest(BaseModel):
    request_id: str
    user_id: str
    whatsapp_id: str
    intent: str
    entities: dict[str, Any] = {}
    session: dict = {}
    timestamp: str

class ExecuteResponse(BaseModel):
    request_id: str
    status: str                     # 'success' | 'error'
    message: str = ''
    data: Optional[Any] = None
    error_code: Optional[str] = None
    quick_replies: list[str] = []
    timestamp: str = ''
```

---

## 5. ASI 通信契约（正式规范）

Alfred Service Interface（ASI）是 Alfred 与所有下游服务之间的唯一通信契约。

### 5.1 三个必须实现的端点

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `GET /health` | 公开 | Alfred 定时健康轮询 |
| `GET /alfred/capabilities` | `X-Alfred-API-Key` | 声明支持的 intent 列表和参数 |
| `POST /alfred/execute` | `X-Alfred-API-Key` | 执行具体动作（主调用接口） |

### 5.2 鉴权 Header

```
X-Alfred-API-Key: <服务专属密钥>
X-Alfred-Request-ID: <UUID v4>
Content-Type: application/json
```

- Alfred → 服务：密钥由 `services.yaml` 配置，存于环境变量
- 服务 → Alfred（推送）：调用 `POST /api/internal/push` 时使用同一密钥

### 5.3 POST /alfred/execute — 请求体

```json
{
  "request_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "user_id": "usr_abc123",
  "whatsapp_id": "+8613800000000",
  "intent": "get_balance",
  "entities": { "period": "month" },
  "session": { "conversation_id": "conv_xyz", "turn": 3 },
  "timestamp": "2026-04-08T10:05:00Z"
}
```

### 5.4 POST /alfred/execute — 响应体

**成功 (HTTP 200)：**

```json
{
  "request_id": "f47ac10b-...",
  "status": "success",
  "message": "本月支出：¥1,250（共 18 笔）",
  "data": { "..." },
  "quick_replies": ["月度报告", "添加支出"],
  "timestamp": "2026-04-08T10:05:01Z"
}
```

**失败：**

```json
{
  "request_id": "f47ac10b-...",
  "status": "error",
  "error_code": "INSUFFICIENT_DATA",
  "message": "请告诉我金额，例如：花了50元",
  "timestamp": "2026-04-08T10:05:01Z"
}
```

### 5.5 标准 error_code

| error_code | 含义 | Alfred 行为 |
|---|---|---|
| `INSUFFICIENT_DATA` | 必需实体缺失 | 向用户追问 |
| `INVALID_VALUE` | 实体值格式错误 | 提示重新输入 |
| `UNAUTHORIZED` | 用户未绑定账户 | 引导用户完成绑定 |
| `NOT_FOUND` | 查询对象不存在 | 提示用户 |
| `SERVICE_ERROR` | 服务内部异常 | 提示稍后再试 |

### 5.6 Intent 总览

| Intent | 路由至 | 关键实体 | 功能 |
|--------|--------|---------|------|
| `add_expense` | ourcents | amount, category | 记录支出 |
| `add_income` | ourcents | amount, source | 记录收入 |
| `get_balance` | ourcents | account(选) | 查询余额 |
| `monthly_report` | ourcents | year, month(选) | 月度报告 |
| `set_budget` | ourcents | category, amount | 设置预算 |
| `add_reminder` | ourschedule | title, datetime | 添加提醒 |
| `list_reminders` | ourschedule | period(选) | 查询提醒 |
| `get_schedule` | ourschedule | date(选) | 查看日程 |

---

## 6. 部署与环境变量

### 6.1 进程启动清单

| 序 | 服务 | 命令 | 端口 |
|---|------|------|------|
| 1 | Alfred Bridge | `cd alfred/bridge && node src/server.mjs` | 3001 |
| 2 | Alfred Backend | `cd alfred/backend && uvicorn app.main:app --port 8000` | 8000 |
| 3 | Alfred Frontend | `cd alfred/frontend && npm run dev` | 5173 |
| 4 | OurCents Streamlit | `cd OurCents && streamlit run app.py` | 8501 |
| 5 | OurCents Alfred API（新） | `cd OurCents && uvicorn alfred_api.main:app --port 8001` | 8001 |
| 6 | OurSchedule API（未来） | `cd OurSchedule && uvicorn main:app --port 8002` | 8002 |

### 6.2 新增环境变量

**Alfred (`backend/.env`)：**

```env
OURCENTS_API_KEY=your_secret_key
OURSCHEDULE_API_KEY=your_secret_key
ALFRED_INTERNAL_KEY=your_secret_key
DISPATCH_ENABLED=true
```

**OurCents (`.env`)：**

```env
ALFRED_API_KEY=your_secret_key     # 与 Alfred 的 OURCENTS_API_KEY 相同
ALFRED_BACKEND_URL=http://localhost:8000
```

---

*文档结束 · Alfred Architecture v1.1 · 基于 Alfred + OurCents 代码库实际分析*
