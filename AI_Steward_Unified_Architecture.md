# Alfred
## 统一平台架构设计建议
### Monorepo · Unified Frontend · Shared Services

**版本 1.0  ·  2026 年 4 月**

---

> ## ⚠️ 命名说明（重要，请先阅读）
>
> 合并后存在两个层级的"Alfred"，为避免混淆，做如下区分：
>
> | 名称 | 含义 | 对应目录 |
> |---|---|---|
> | **Alfred**（平台） | 整体统一平台的名称，包含三个子服务 | 根目录 `alfred/` |
> | **gateway**（网关服务） | 原 Alfred 项目的 WhatsApp 后端，重命名为 gateway | `services/gateway/` |
>
> 原因：原项目"Alfred"升级为平台总名称后，其 WhatsApp 网关职能由子服务 **gateway** 承担。对外统称 **Alfred 平台**，内部服务标识符分别为 `gateway`（端口 8000）、`ourcents`（8001）、`nudge`（8002）。

---

## 目录

1. [现状分析：三个项目的问题](#1-现状分析三个项目的问题)
2. [建议架构：统一 Monorepo](#2-建议架构统一-monorepo)
3. [核心设计决策](#3-核心设计决策)
4. [变与不变：详细对比](#4-变与不变详细对比)
5. [统一前端设计](#5-统一前端设计)
6. [服务端口与运行方式](#6-服务端口与运行方式)
7. [迁移路线图](#7-迁移路线图)
8. [建议总结](#8-建议总结)

---

## 1. 现状分析：三个项目的问题

通过对原 Alfred（网关）、OurCents、Nudge 三个项目源代码的深度分析，识别出以下结构性问题。它们目前能独立运行，但作为一个协作平台，存在大量重复和不一致。

### 1.1 技术栈对比

| 组件 | gateway（原 Alfred） | OurCents | Nudge | 问题 |
|---|---|---|---|---|
| 后端框架 | FastAPI ✓ | ⚠ Streamlit ✗ | FastAPI ✓ | 🔴 OurCents 无 REST API |
| ORM / DB层 | SQLModel | SQLAlchemy (原生) | SQLAlchemy | ⚠ 两套写法，风格不统一 |
| 数据库 | SQLite (alfred.db) | SQLite (ourcents.db) | SQLite (nudge.db) | 三个独立 DB 文件 |
| 前端框架 | React + Vite ✓ | ⚠ Streamlit ✗ | React + Vite ✓ | 🔴 两套前端，OurCents 无 React |
| 认证系统 | JWT (python-jose) | ⚠ pyjwt 自建 | 🔴 无认证 ✗ | 🔴 三套不同认证！ |
| AI 能力 | OpenAI (STT) | OpenAI + Gemini | OpenAI (GPT-4o) | ⚠ OPENAI_API_KEY 配置了三次 |
| 配置管理 | .env (pydantic-settings) | .env (dotenv) | .env (dotenv) | ⚠ 三个 .env，无共享配置 |
| React 版本 | React 19 | — | React 18 | ⚠ 版本不统一 |
| 启动方式 | start-dev.sh | start.sh / start.ps1 | start_backend.bat | ⚠ 每个项目启动方式各异 |

### 1.2 核心问题汇总

> 🔴 **OurCents 使用 Streamlit** — 既无法被 Alfred 平台调用（无 REST API），也无法与其他项目共享前端。

> 🔴 **三套认证系统**：gateway(JWT)、OurCents(自建 pyjwt)、Nudge(无认证)。用户需要分别登录不同界面。

> ⚠ **两个独立的 React 前端**：gateway frontend 和 Nudge frontend 分别启动在不同端口，管理员体验割裂。

> ⚠ **OPENAI_API_KEY 在三个 .env 文件中重复配置**，密钥轮换需要改三个地方。

> ⚠ **ORM 风格不统一**：gateway 用 SQLModel，OurCents 和 Nudge 用原始 SQLAlchemy。

---

## 2. 建议架构：统一 Monorepo

将三个独立仓库合并为一个 Monorepo，根目录命名为 `alfred/`。明确分工：`services/` 负责后端逻辑，`web/` 负责统一前端，`bridge/` 保持不变，`shared/` 提供公共 Python 包。

### 2.1 目录结构

```
alfred/                              ← 根目录（Alfred 平台）
│
├── services/                        ← 所有 Python 后端服务
│   ├── gateway/                     ← WhatsApp 网关（原 Alfred/backend/，重命名）
│   │   ├── app/                     ← 代码几乎不变
│   │   │   ├── api/routes.py
│   │   │   ├── api/webhooks.py
│   │   │   ├── services/dispatch_service.py  ← 新增
│   │   │   └── main.py              ← 8000 端口
│   │   └── pyproject.toml
│   │
│   ├── ourcents/                    ← 财务服务（原 OurCents/，去掉 Streamlit）
│   │   ├── app/
│   │   │   ├── api/                 ← 新增 FastAPI 路由层
│   │   │   ├── domain/              ← 原样迁移（classification, deduction_rules...）
│   │   │   ├── models/              ← 原样迁移（schema.py）
│   │   │   ├── services/            ← 原样迁移（dashboard_service 等 4 个）
│   │   │   ├── storage/             ← 原样迁移（database.py, file_storage.py）
│   │   │   └── main.py              ← 新入口（FastAPI，替代 Streamlit app.py）
│   │   └── pyproject.toml
│   │
│   └── nudge/                       ← 提醒服务（原 Nudge/backend/，小调整）
│       ├── app/
│       │   ├── api/                 ← 原 routers/（重命名）
│       │   ├── models/              ← 原 models.py
│       │   ├── services/            ← 原 services/（parser.py 不变）
│       │   ├── db/                  ← 原 database.py（移入子目录）
│       │   └── main.py              ← 原 main.py（路径微调）
│       └── pyproject.toml
│
├── bridge/                          ← Node.js WA 网桥（完全不变）
│   └── src/server.mjs
│
├── web/                             ← 统一 React 前端（整合两个现有前端）
│   ├── src/
│   │   ├── pages/
│   │   │   ├── alfred/              ← WhatsApp 管理 UI（原 gateway frontend）
│   │   │   ├── ourcents/            ← 新建（替代 Streamlit UI，4 个页面）
│   │   │   └── nudge/               ← 原 Nudge/frontend/src/（3 个组件原样迁入）
│   │   ├── components/layout/       ← 新建：Sidebar、TopNav、AuthGuard
│   │   ├── lib/api/                 ← 整合现有 api.ts 文件
│   │   └── App.tsx                  ← React Router（新建路由配置）
│   └── package.json                 ← 统一为 React 19 + Vite 6
│
├── shared/                          ← 新建：Python 共享包
│   ├── auth.py                      ← JWT 逻辑（从 gateway 提取，三服务共用）
│   ├── config.py                    ← BaseSettings（各服务继承）
│   └── asi.py                       ← ASI 请求/响应模型
│
├── config/
│   └── services.yaml                ← gateway dispatch 注册表
│
├── data/                            ← 所有 SQLite 数据库集中存放
│   ├── alfred.db
│   ├── ourcents.db
│   └── nudge.db
│
├── docker-compose.yml               ← 一键启动所有服务
├── .env                             ← 统一根环境变量
└── README.md
```

---

## 3. 核心设计决策

### 决策 1：统一 React 前端（最高价值）

将 gateway frontend 和 Nudge frontend 合并为 `web/`，同时将 OurCents 的 Streamlit UI 重写为 React 组件。管理员只需打开一个 URL，通过侧边栏切换三个功能模块。

| 模块 | 来源 | 迁移工作量 | 说明 |
|---|---|---|---|
| Alfred 会话管理 | gateway/frontend/src/components/（4 个组件） | ✅ 低 | 原样复制，调整导入路径 |
| OurCents 财务看板 | OurCents/src/ui/pages/（Streamlit） | ⚠ 中 | 用 React 重写 4 个页面，API 数据来自 ourcents 服务 |
| Nudge 提醒管理 | Nudge/frontend/src/（3 个组件） | ✅ 低 | 原样复制，统一 API 前缀 |
| 共享布局 | 全新 | ✅ 低 | Sidebar + TopNav + AuthGuard（~200 行） |

> ℹ️ OurCents 的 Streamlit UI 主要做数据展示（图表、表格）。React 版用 recharts 替代 plotly，代码量相近，且与其他页面风格统一。

---

### 决策 2：统一认证（gateway JWT 为基准）

gateway 已有完善的 JWT 认证（python-jose）。将其提取到 `shared/auth.py`，OurCents 和 Nudge 直接 import 并使用相同的 `verify_token` 依赖项。管理员登录一次，token 在三个服务间通用。

| 当前 | 目标 |
|---|---|
| gateway: python-jose JWT | `shared/auth.py`（从 gateway 提取）→ 三服务共用 |
| OurCents: pyjwt 独立实现 | 删除 pyjwt，`import shared.auth` |
| Nudge: 无认证 | 添加 `Depends(verify_token)` 到所有端点 |

---

### 决策 3：统一 ORM（SQLModel 替换原始 SQLAlchemy）

OurCents 和 Nudge 目前使用原始 SQLAlchemy + 手写 Column 定义。gateway 使用 SQLModel（SQLAlchemy + Pydantic 的封装）。建议逐步将 OurCents 和 Nudge 迁移到 SQLModel，好处是：models 同时是 ORM 模型和 Pydantic schema，减少重复代码。

> ℹ️ 这是渐进式迁移，不需要立即完成。OurCents 业务逻辑代码（DashboardService 等）完全不受影响，只有 database.py 层需要调整。

---

### 决策 4：统一环境变量

三个 `.env` 合并为根目录一个 `.env`，变量名加服务前缀避免冲突。每个服务的 `config.py` 继承 `shared/config.py` 的 BaseSettings，只读取自己前缀的变量。

```env
# .env（根目录，统一管理）

# 共享变量
OPENAI_API_KEY=sk-xxx
SECRET_KEY=change-me

# Gateway（原 Alfred 后端）
GATEWAY_BRIDGE_API_KEY=xxx
GATEWAY_WHATSAPP_TOKEN=xxx
GATEWAY_WHATSAPP_PHONE_ID=xxx

# OurCents
OURCENTS_API_KEY=xxx         # gateway → OurCents
OURCENTS_GEMINI_API_KEY=xxx  # 如需 Gemini

# Nudge
NUDGE_API_KEY=xxx             # gateway → Nudge
```

`shared/config.py` 示例：

```python
class BaseAppSettings(BaseSettings):
    openai_api_key: str = ''
    secret_key: str = 'change-me'
    model_config = SettingsConfigDict(env_file='../../.env', extra='ignore')

class OurCentsSettings(BaseAppSettings):
    api_key: str = Field('', alias='OURCENTS_API_KEY')
    gemini_api_key: str = Field('', alias='OURCENTS_GEMINI_API_KEY')
```

---

### 决策 5：bridge/ 完全不变

> ✅ Node.js 桥接层是独立服务，无任何改动需求。只调整 `BACKEND_BASE_URL` 指向新的 gateway 服务地址。

---

## 4. 变与不变：详细对比

### 4.1 gateway（原 Alfred 后端）

| 文件/目录 | 变化 | 说明 |
|---|---|---|
| backend/app/api/ | ✅ 不变 | routes.py, webhooks.py 原样迁移到 services/gateway/app/api/ |
| backend/app/services/ | ✅ 不变 | 所有服务层文件原样迁移 |
| backend/app/models/ | ✅ 不变 | chat.py, auth.py 原样迁移 |
| backend/app/core/config.py | ⚠ 小改 | 继承 shared/config.py 的 BaseSettings，前缀改为 `GATEWAY_` |
| backend/app/core/security.py | ⚠ 迁移 | 提取到 shared/auth.py，本地 import |
| frontend/src/components/ | ⚠ 迁移 | 4 个组件移入 web/src/pages/alfred/，代码不变 |
| frontend/src/App.tsx | 🔄 替换 | 由 web/src/App.tsx（含路由）替代 |
| bridge/src/server.mjs | ✅ 不变 | 完全不动 |

---

### 4.2 OurCents（改动最大，但业务逻辑零变化）

| 文件/目录 | 变化 | 说明 |
|---|---|---|
| src/domain/ | ✅ 不变 | classification.py, deduction_rules.py, deduplication.py 原样迁移 |
| src/models/schema.py | ✅ 不变 | Pydantic 数据模型原样迁移 |
| src/services/ | ✅ 不变 | 4 个服务类（DashboardService 等）原样迁移 |
| src/storage/ | ✅ 不变 | database.py, file_storage.py 原样迁移 |
| app.py（Streamlit 入口） | 🔴 删除 | 替换为 services/ourcents/app/main.py（FastAPI 入口） |
| src/ui/pages/（Streamlit 页面） | 🔄 重写 | 用 React 重写为 web/src/pages/ourcents/（4 个组件） |
| requirements.txt | ⚠ 精简 | 删除 streamlit, plotly, pandas；新增 fastapi, uvicorn |
| 新增 app/api/routes.py | 🆕 新建 | FastAPI 路由（复用现有 services/） |

---

### 4.3 Nudge

| 文件/目录 | 变化 | 说明 |
|---|---|---|
| backend/services/parser.py | ✅ 不变 | OpenAI 解析逻辑原样迁移 |
| backend/models.py | ✅ 不变 | Pydantic 模型原样迁移 |
| backend/routers/nudge.py | ⚠ 迁移 | 移入 services/nudge/app/api/，代码不变 |
| backend/database.py | ⚠ 迁移 | 移入 services/nudge/app/db/，代码不变 |
| backend/main.py | ⚠ 小改 | 更新导入路径，继承 shared/config.py |
| frontend/src/components/ | ⚠ 迁移 | 3 个组件移入 web/src/pages/nudge/，代码不变 |
| frontend/src/App.tsx | 🔄 替换 | 由 web/src/App.tsx（含路由）替代 |

---

## 5. 统一前端设计

### 5.1 页面结构与路由

统一前端使用 React Router v6，侧边栏导航在三个功能区之间切换。所有页面共享同一个 Auth Context，登录一次即可访问所有功能。

```
web/src/
├── App.tsx                   ← 路由配置 + 全局 AuthContext
├── pages/
│   ├── alfred/               ← WhatsApp 管理（gateway 前端页面）
│   │   ├── ConversationList.tsx  ← 原样迁移
│   │   ├── MessageList.tsx       ← 原样迁移
│   │   ├── Composer.tsx          ← 原样迁移
│   │   └── ConnectionPanel.tsx   ← 原样迁移
│   │
│   ├── ourcents/             ← 财务管理
│   │   ├── Dashboard.tsx         ← 新建（替代 Streamlit dashboard.py）
│   │   ├── Upload.tsx            ← 新建（替代 Streamlit upload.py）
│   │   └── Receipts.tsx          ← 新建（替代 Streamlit receipts.py）
│   │
│   └── nudge/                ← 提醒管理
│       ├── NudgeInput.tsx        ← 原样迁移
│       ├── ParsePreview.tsx      ← 原样迁移
│       └── ReminderList.tsx      ← 原样迁移
│
├── components/layout/
│   ├── Sidebar.tsx               ← 新建（左侧导航栏）
│   └── AuthGuard.tsx             ← 新建（路由保护）
│
├── lib/api/
│   ├── gateway.ts               ← 整合 原Alfred/frontend/src/lib/api.ts
│   ├── ourcents.ts              ← 新建（调用 ourcents 服务的 API）
│   └── nudge.ts                 ← 整合 Nudge/frontend/src/api.ts
│
└── main.tsx
```

---

### 5.2 OurCents React 页面（Streamlit → React 替换）

这是唯一需要"重写"的 UI 部分。原 Streamlit 代码逻辑完整，React 版本只是换一个渲染框架，数据来源改为 API 调用。

| Streamlit 页面 | React 替代 | 核心变化 |
|---|---|---|
| dashboard.py（plotly 图表） | Dashboard.tsx（recharts） | 用 recharts BarChart/PieChart 替代 st.plotly_chart，数据从 GET /api/ourcents/dashboard 获取 |
| upload.py（st.file_uploader） | Upload.tsx（input[type=file]） | 标准 HTML file input + fetch 上传，逻辑完全相同 |
| receipts.py（st.dataframe） | Receipts.tsx（HTML table） | 简单表格组件，过滤器改用 React state |
| settings.py（st.text_input） | OurCents 设置合并到全局 Settings 页 | WhatsApp 绑定手机号等设置统一管理 |
| login.py（st.form） | 统一 LoginForm.tsx（gateway 已有） | 复用 gateway 已有的 LoginForm 组件 |

---

### 5.3 Sidebar 结构

```
┌─────────────────────┐
│  Alfred             │
├─────────────────────┤
│  💬 WhatsApp        │  → /alfred
│     对话列表         │
│     连接管理         │
├─────────────────────┤
│  💰 OurCents        │  → /ourcents
│     财务看板         │
│     上传收据         │
│     收据列表         │
├─────────────────────┤
│  🔔 Nudge           │  → /nudge
│     提醒管理         │
├─────────────────────┤
│  ⚙  设置            │  → /settings
│     账户绑定         │
│     连接管理         │
└─────────────────────┘
```

---

## 6. 服务端口与运行方式

### 6.1 端口规划

| 服务 | 目录 | 端口 | 启动命令 |
|---|---|---|---|
| gateway（WhatsApp 网关） | services/gateway/ | 8000 | `uvicorn app.main:app --port 8000` |
| OurCents 服务 | services/ourcents/ | 8001 | `uvicorn app.main:app --port 8001` |
| Nudge 服务 | services/nudge/ | 8002 | `uvicorn app.main:app --port 8002` |
| WhatsApp Bridge | bridge/ | 3001 | `node src/server.mjs` |
| 统一前端（开发） | web/ | 5173 | `vite` |
| 统一前端（生产） | services/gateway/ | 8000 | 由 gateway 静态文件服务 |

> ℹ️ **生产环境**：`vite build` 后将 `web/dist/` 复制到 gateway 静态目录，由 gateway 的 StaticFiles 挂载服务（Nudge 已有这个模式）。只需开放一个外网端口。

---

### 6.2 docker-compose.yml 概览

```yaml
version: '3.9'
services:
  gateway:
    build: services/gateway
    ports: ['8000:8000']
    env_file: .env
    volumes: ['./data:/data', './config:/config']
    depends_on: [bridge]

  ourcents:
    build: services/ourcents
    ports: ['8001:8001']
    env_file: .env
    volumes: ['./data:/data']

  nudge:
    build: services/nudge
    ports: ['8002:8002']
    env_file: .env
    volumes: ['./data:/data']

  bridge:
    build: bridge
    ports: ['3001:3001']
    env_file: .env
```

---

## 7. 迁移路线图

整个迁移过程分为 4 个阶段，每个阶段结束后平台都可以正常运行，不存在"大爆炸式"停工期。

---

### 阶段一：建立 Monorepo 骨架（1 天）

> ✅ 风险：极低。只是创建目录结构，原三个仓库不动。

1. 创建 `alfred/` 根目录，初始化 git（submodule 或直接合并历史）
2. 创建 `services/`、`web/`、`bridge/`、`shared/`、`data/`、`config/` 目录
3. 将根 `.env.example` 合并三个项目的环境变量
4. 编写 `docker-compose.yml` 骨架

---

### 阶段二：迁移后端（2-3 天）

> ✅ 风险：低。主要是移动文件和更新 import 路径。

1. 将原 `Alfred/backend/` 内容迁移到 `services/gateway/`，更新 `pyproject.toml`
2. 将 `OurCents/src/` 内容迁移到 `services/ourcents/app/`（不含 `ui/` 目录）
3. 将 `Nudge/backend/` 内容迁移到 `services/nudge/app/`
4. 新建 `shared/auth.py`（从 gateway security.py 提取），`shared/config.py`，`shared/asi.py`
5. 各服务 `config.py` 改为继承 `shared/config.py`
6. 新建 `services/ourcents/app/api/routes.py`（FastAPI 层，复用现有 services/）
7. 为 `services/ourcents/` 新建 `main.py`（FastAPI 入口）
8. 逐服务验证：pytest + curl 测试确认接口正常

---

### 阶段三：统一前端（3-4 天）

> ⚠ 风险：中。需要新建 OurCents React 组件，其余是移植。

1. 新建 `web/`，初始化 React 19 + Vite 6 + TypeScript + React Router
2. 将原 `Alfred/frontend/src/components/`（4 个）原样迁入 `web/src/pages/alfred/`
3. 将 `Nudge/frontend/src/components/`（3 个）原样迁入 `web/src/pages/nudge/`
4. 新建 `web/src/components/layout/Sidebar.tsx` 和 `AuthGuard.tsx`
5. 新建 `web/src/pages/ourcents/Dashboard.tsx`（recharts 替代 plotly）
6. 新建 `web/src/pages/ourcents/Upload.tsx` 和 `Receipts.tsx`
7. 整合三个 `api.ts` 到 `web/src/lib/api/`
8. 端到端测试：登录 → 切换三个模块 → 各功能验证

---

### 阶段四：清理与优化（1 天）

> ✅ 风险：极低。清理旧文件，不影响功能。

1. 归档原三个独立仓库（建议保留 git 历史，归入 `archive/` 分支）
2. 删除 OurCents 的 Streamlit 依赖（streamlit, plotly, pandas）
3. 统一 React 版本到 19
4. 更新 README.md 和启动文档
5. 验证 `docker-compose up` 一键启动全套

---

### 迁移工作量汇总

| 类别 | 工作内容 | 预估时间 | 风险 |
|---|---|---|---|
| 后端迁移 | 移动文件 + 更新 import 路径 + shared/ | ✅ 2-3 天 | ✅ 低（无逻辑变化） |
| OurCents FastAPI 层 | 新建 api/routes.py + main.py（复用现有 services） | ✅ 1 天 | ✅ 低（业务逻辑已存在） |
| Alfred/Nudge 前端迁移 | 复制组件 + 路径调整 | ✅ 半天 | ✅ 极低 |
| OurCents React UI | 用 React 重写 4 个 Streamlit 页面 | ⚠ 2-3 天 | ⚠ 中（新写代码） |
| 统一布局与路由 | Sidebar + AuthGuard + React Router | ✅ 1 天 | ✅ 低 |
| **合计** | — | **7-9 天** | **整体风险低** |

---

## 8. 建议总结

| 维度 | 当前状态 | 建议目标 | 价值 |
|---|---|---|---|
| 代码结构 | 3 个独立仓库 | 1 个 Monorepo（alfred/）+ 3 个服务 | 统一版本控制和 CI/CD |
| 前端 | 2 个 React 前端 + 1 个 Streamlit | 1 个 React 前端（3 个功能区） | 管理员单一入口，UX 一致 |
| 认证 | 3 套独立认证（1 有 + 1 旧 + 1 无） | 1 套 JWT（shared/auth.py） | 登录一次，访问全部 |
| 环境配置 | 3 个 .env 文件 | 1 个根 .env（命名空间隔离） | 密钥一处管理，不重复 |
| AI API Key | OPENAI_API_KEY 配置 3 次 | 配置 1 次，三服务共享 | 轮换密钥只需改 1 处 |
| ORM | SQLModel（gateway）+ 原始 SQLAlchemy×2 | 统一 SQLModel | 减少重复模型代码 |
| 启动方式 | 3 种不同启动脚本 | docker-compose up（或 1 个 start.sh） | 新人上手更快 |
| OurCents UI | Streamlit（无 API） | FastAPI + React | 可被 Alfred 平台调用，风格统一 |

> ✅ **所有业务逻辑代码**（DashboardService、ReceiptIngestionService、Parser、Bridge 等）**均无需修改**。迁移的是结构，不是功能。

> ℹ️ **OurCents 是改动最大的部分**，但改动集中在 UI 层（Streamlit → React）和入口层（app.py → main.py + api/routes.py）。核心 `src/` 目录原封不动。

---

*— 文档结束  ·  Alfred 统一架构建议 v1.0 —*
