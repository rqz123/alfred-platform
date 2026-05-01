# Alfred Note 功能 — 技术设计文档

> **版本**: v1.3  
> **用途**: 供 Claude programming tool 实现  
> **依赖**: alfred-account-system-design.md（账号体系）

---

## 1. 功能定位

Note 是 Alfred 的**事件记录库**，核心目标：

1. 记录用户发生的事件，结构化存储
2. Note 之间可以建立关联（Obsidian 风格双向链接）
3. 用户用自然语言提问时，Alfred 能检索并返回相关记录
4. **主动提醒信息关联性**：存入或检索 Note 时，Alfred 自动识别涉及的人/地/事，呈现历史关联上下文（"这是你第 3 次记录关于王医生的事"）

Note 是**纯个人信息**，不在 Family 成员间共享。

---

## 2. Note 数据结构

### 2.1 字段定义

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT | 主键，`note_<ulid>` |
| `short_id` | INTEGER | 用户维度自增短 ID（如 42），Bot 命令引用用 `#42` |
| `user_id` | TEXT | 创建者，关联 `alfred_users.id` |
| `title` | TEXT | 标题，LLM 自动生成，允许重复 |
| `content` | TEXT | 完整原始内容（文字或语音转录文字） |
| `summary` | TEXT | 摘要；内容 ≤ 100 字时 summary = content，否则 LLM 生成 |
| `keywords` | TEXT[] | 关键词数组，LLM 自动提取（3~8 个） |
| `entities` | JSONB | LLM 提取的结构化实体：`{"people":[], "places":[], "orgs":[]}` |
| `event_time` | TIMESTAMPTZ | 用户提交 Note 的时间（即记录时间） |
| `audio_path` | TEXT | 语音文件在本地存储的路径（非语音则为 NULL） |
| `source` | TEXT | 来源类型：`text` / `voice` |
| `embedding` | vector(1536) | 语义向量，用于语义检索（pgvector） |
| `created_at` | TIMESTAMPTZ | 记录写入时间（同 event_time，保留作审计） |

> **说明**：`event_time` 即用户提交时间，系统写入，无需用户填写或 LLM 推断。

### 2.2 数据库 Schema

```sql
-- 启用 pgvector 扩展（PostgreSQL）
CREATE EXTENSION IF NOT EXISTS vector;

-- 用户维度短 ID 计数器
CREATE TABLE alfred_note_seq (
  user_id   TEXT PRIMARY KEY REFERENCES alfred_users(id) ON DELETE CASCADE,
  last_seq  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE alfred_notes (
  id         TEXT PRIMARY KEY,                         -- note_<ulid>
  short_id   INTEGER NOT NULL,                         -- 用户维度自增，如 42
  user_id    TEXT NOT NULL REFERENCES alfred_users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  content    TEXT NOT NULL,
  summary    TEXT NOT NULL,
  keywords   TEXT[] NOT NULL DEFAULT '{}',
  entities   JSONB NOT NULL DEFAULT '{"people":[],"places":[],"orgs":[]}',
  event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  audio_path TEXT,                                     -- 本地存储路径
  source     TEXT NOT NULL DEFAULT 'text',             -- 'text' | 'voice'
  embedding  vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 实体检索索引（按 people/places/orgs 中的具体值查找）
CREATE INDEX idx_alfred_notes_entities ON alfred_notes USING GIN(entities);

-- short_id 在用户维度唯一
CREATE UNIQUE INDEX idx_alfred_notes_user_short_id ON alfred_notes(user_id, short_id);

-- 检索索引
CREATE INDEX idx_alfred_notes_user_id    ON alfred_notes(user_id);
CREATE INDEX idx_alfred_notes_event_time ON alfred_notes(event_time DESC);
CREATE INDEX idx_alfred_notes_keywords   ON alfred_notes USING GIN(keywords);

-- 全文检索索引（title + content + summary）
CREATE INDEX idx_alfred_notes_fts ON alfred_notes
  USING GIN(to_tsvector('simple', title || ' ' || content || ' ' || summary));

-- 语义检索索引（pgvector HNSW，适合大数据量）
CREATE INDEX idx_alfred_notes_embedding ON alfred_notes
  USING hnsw(embedding vector_cosine_ops);
```

### 2.3 short_id 分配逻辑

每次创建 Note 时，用以下事务保证原子性分配：

```sql
-- 1. 更新计数器并取得新值
INSERT INTO alfred_note_seq (user_id, last_seq)
VALUES (:user_id, 1)
ON CONFLICT (user_id) DO UPDATE
  SET last_seq = alfred_note_seq.last_seq + 1
RETURNING last_seq;

-- 2. 用返回的 last_seq 作为 short_id 写入 alfred_notes
```

`short_id` 在用户维度严格自增，删除 Note 后不复用（保持引用稳定性）。

### 2.4 Note 连接表

```sql
CREATE TABLE alfred_note_links (
  note_id        TEXT NOT NULL REFERENCES alfred_notes(id) ON DELETE CASCADE,
  linked_note_id TEXT NOT NULL REFERENCES alfred_notes(id) ON DELETE CASCADE,
  link_type      TEXT NOT NULL DEFAULT 'related', -- 'related' | 'followup' | 'contradicts'
  created_by     TEXT REFERENCES alfred_users(id) ON DELETE SET NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (note_id, linked_note_id),
  CHECK (note_id != linked_note_id)               -- 不能自己连接自己
);

-- 双向查询索引
CREATE INDEX idx_alfred_note_links_linked ON alfred_note_links(linked_note_id);
```

**连接是逻辑双向的**：插入 `(A, B)` 时同时插入 `(B, A)`，保证双向可查。

### 2.4 语音文件存储

语音文件存储在本地文件系统，数据库只保存路径。

```
存储根目录: {DATA_DIR}/audio/notes/
文件命名:   {user_id}/{note_id}.ogg   （保留 WA 原始格式）
示例:       /data/audio/notes/usr_01J.../note_01J....ogg
```

`audio_path` 字段存相对路径（不含根目录），方便迁移：

```
audio_path = "usr_01J.../note_01J....ogg"
```

---

## 3. 输入流程

### 3.1 文字输入

```
用户发文字消息（非命令）
  → 意图识别层：判断是否为 Note（见 §5）
  → 确认是 Note
  → LLM 提取 {title, keywords, summary}
  → 生成 embedding（调用 OpenAI text-embedding-3-small 或同类模型）
  → 写入 alfred_notes
  → 检索相关 Note（见 §6.3），找到则推荐关联
  → 回复用户确认

回复示例：
  ✅ 已记录：#42 「王医生复诊」
  🔑 关键词：王医生、复诊、健康
  📎 可能相关：#38「健康检查结果 [2026-02-28]」，要关联吗？回复 Y 确认，N 跳过
```

### 3.2 语音输入

```
用户发语音消息
  → 意图识别层：source='voice'，直接进入 Note 流程（不走意图识别）
  → 下载语音文件到本地存储
  → Whisper API 转录为文字（content）
  → 同文字流程：LLM 提取 {title, keywords, summary} + embedding
  → audio_path 写入数据库
  → 回复用户确认

回复示例：
  🎙 语音已保存并转录
  ✅ 已记录：#43 「和 Alice 讨论项目进度」
  🔑 关键词：Alice、项目、进度
```

### 3.3 LLM 提取 Prompt 模板

```
你是一个信息提取助手。根据以下用户消息，提取结构化信息。

用户消息：
"""
{content}
"""

请返回 JSON，格式如下：
{
  "title": "简短标题，10字以内",
  "keywords": ["关键词1", "关键词2", ...],  // 3~8个，名词为主
  "summary": "摘要，50字以内",              // 内容本身很短时直接返回原文
  "entities": {
    "people": ["王医生", "Alice"],          // 人名（含称谓）
    "places": ["协和医院", "北京"],         // 地点
    "orgs":   ["华为", "项目组A"]           // 组织/公司/团队
  }
}

要求：
- title 要具体，避免"记录"、"备注"等无意义词
- keywords 包含人名、地点、事件类型、关键动词
- summary 保留核心事实，去除冗余修饰
- entities 只填明确出现的实体，不要推断或补全，无则留空数组
```

---

## 4. Note Bot 命令

命令中 Note 的引用统一用 `#<short_id>`，如 `#42`。

| 命令 | 说明 |
|------|------|
| `/note <内容>` | 创建 Note（等同于直接发文字，走意图识别） |
| `/note list [n]` | 列出最近 n 条 Note（默认 5 条） |
| `/note get #<id>` | 查看 Note 详情 |
| `/note delete #<id>` | 删除 Note（需二次确认） |
| `/link #<id_A> #<id_B> [type]` | 手动关联两条 Note |
| `/unlink #<id_A> #<id_B>` | 取消关联 |
| `/note links #<id>` | 查看某条 Note 的所有关联 |
| `/find <query>` | 搜索 Note（自然语言，见 §6） |

---

## 5. 意图识别层

### 5.1 设计原则

每条用户消息进入统一意图识别层，分发到对应功能模块：

| 意图 | 分发目标 | 示例 |
|------|----------|------|
| `cmd_note` | Note 模块（创建） | `/note 今天见了医生` |
| `cmd_find` | Note 模块（检索） | `/find 王医生` |
| `cmd_expense` | OurCents 模块 | `午饭 $15` |
| `cmd_reminder` | Reminder 模块 | `明天下午3点提醒我开会` |
| `cmd_system` | 系统命令 | `/status`, `/add user` |
| `note_create` | Note 模块（创建） | 自然语言事件陈述 |
| `question` | Note 检索 + 其他模块 | "上次我去看医生是什么时候？" |
| `unclear` | 询问用户 | 无法判断 |

### 5.2 识别逻辑

```
收到消息
  ├─ 以 / 开头 → 命令路由（精确匹配，见命令表）
  ├─ 语音消息 → 直接进入 Note 创建流程
  └─ 普通文字 → LLM 意图分类

LLM 意图分类 Prompt：
  判断用户消息属于哪种意图：
  - note_create：描述一件发生过的事（过去时态，陈述句）
  - question：提问，想查找某信息
  - expense：记录花费（金额 + 用途）
  - reminder：设置提醒（未来时间点）
  - unclear：无法判断

  返回 JSON：{"intent": "note_create", "confidence": 0.9}
```

### 5.3 不确定时询问用户

当 `confidence < 0.7` 或 `intent = unclear` 时，回复：

```
🤔 我不太确定你想做什么，请选择：

1️⃣ 记录一条 Note
2️⃣ 查找之前的记录
3️⃣ 记录一笔账
4️⃣ 设置提醒

回复 1/2/3/4
```

用户回复数字后，保存上下文继续处理原始消息。

---

## 6. 检索设计

### 6.1 检索触发

用户通过以下方式触发检索：

- 发送 `/find <query>`（明确检索）
- 发送自然语言问句（意图识别为 `question`）

### 6.2 可见性规则

检索时，用户只能看到自己创建的 Note。

SQL 过滤条件：

```sql
WHERE user_id = :current_user_id
```

### 6.3 三层检索策略

**第一层：关键词全文检索**

```sql
SELECT id, title, summary, event_time,
       ts_rank(
         to_tsvector('simple', title || ' ' || content || ' ' || summary),
         plainto_tsquery('simple', :query)
       ) AS rank
FROM alfred_notes
WHERE <可见性过滤>
  AND to_tsvector('simple', title || ' ' || content || ' ' || summary)
      @@ plainto_tsquery('simple', :query)
ORDER BY rank DESC
LIMIT 10;
```

**第二层：语义检索**

```sql
SELECT id, title, summary, event_time,
       1 - (embedding <=> :query_embedding) AS similarity
FROM alfred_notes
WHERE <可见性过滤>
ORDER BY embedding <=> :query_embedding
LIMIT 10;
```

**第三层：合并排名**

```python
def merge_results(keyword_results, semantic_results):
    # 线性加权合并，关键词权重 0.4，语义权重 0.6
    scores = {}
    for r in keyword_results:
        scores[r.id] = scores.get(r.id, 0) + r.rank * 0.4
    for r in semantic_results:
        scores[r.id] = scores.get(r.id, 0) + r.similarity * 0.6
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
```

### 6.4 检索返回格式

当检索结果集中在同一实体（人/地/事）时，按时间线排列，附带关联上下文：

```
🔍「王医生」相关记录（共 3 条）：

1. #43 王医生复诊 [2026-04-28] ← 最近
   "血压恢复正常，三个月后复查"

2. #38 健康检查结果 [2026-02-28]
   "血压偏高，医生建议减少盐分摄入"
   🔗 关联：#43

3. #31 初次就诊 [2025-11-10]
   "首次测量，偏高"

💡 时间跨度：6 个月 | 共记录 3 次
回复 /note get #43 查看详情
```

结果不集中于单一实体时，按相关度降序展示（现有格式）。

**实体聚合 SQL**（检测查询词是否命中某个实体）：

```sql
-- 检查 query 是否命中 entities 中的人名/地点/组织
SELECT id, title, summary, event_time, entities
FROM alfred_notes
WHERE user_id = :user_id
  AND (
    entities->'people' ? :query   OR
    entities->'places' ? :query   OR
    entities->'orgs'   ? :query
  )
ORDER BY event_time DESC;
```

若命中实体记录 ≥ 2 条，使用实体时间线格式；否则用常规三层检索。

### 6.5 新建 Note 时自动推荐关联

每次创建 Note 后，执行两类检查：

**① 实体上下文提醒**（优先）

提取本次 Note 的 `entities`，查询历史中出现相同实体的 Note：

```sql
SELECT id, short_id, title, event_time
FROM alfred_notes
WHERE user_id = :user_id
  AND id != :new_note_id
  AND (
    entities->'people' ?| ARRAY[:people...]  OR
    entities->'places' ?| ARRAY[:places...]  OR
    entities->'orgs'   ?| ARRAY[:orgs...]
  )
ORDER BY event_time DESC
LIMIT 3;
```

有历史记录时，回复附加实体上下文：

```
✅ 已记录：#43 「王医生复诊」
🔑 关键词：王医生、复诊、血压

📋 关于「王医生」的历史记录（共 2 条）：
  • #38 健康检查结果 [2026-02-28] — 血压偏高，建议减少盐分
  • #31 初次就诊 [2025-11-10] — 首次测量，偏高
```

**② 语义相似关联建议**（实体上下文之后）

执行语义检索 Top 3，相似度 > 0.85 且不在实体历史列表中的，追加建议：

```
📎 还发现相似记录，要关联吗？
   #29「体检预约 [2025-10-20]」  回复 Y 确认，N 跳过
```

用户回复 Y → 写入 `alfred_note_links`（双向插入）

### 6.6 关联性提醒设计原则

Alfred 的关联提醒应遵循以下原则：

| 场景 | Alfred 行为 |
|------|-------------|
| 新建 Note 涉及已知人物 | 自动列出该人物的历史 Note 时间线 |
| 新建 Note 涉及已知地点/组织 | 同上 |
| `/find <人名>` | 优先展示该人物所有 Note 的时间线，而非相关度列表 |
| 两条 Note 被手动关联后 | 检索任一条时，自动展示关联的另一条 |
| 历史记录 ≥ 5 条同一实体 | 提示："你已记录关于 X 的事件 5 次，是否整理成摘要？" |

**目标**：用户不需要主动管理连接，Alfred 通过实体识别自动把碎片信息串联成一个关于"人"或"事"的连续故事。

---

## 7. REST API 设计

前缀：`/api/alfred/notes`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/alfred/notes` | 创建 Note | 当前用户 |
| `GET` | `/api/alfred/notes` | 列出 Note（含可见性过滤） | 当前用户 |
| `GET` | `/api/alfred/notes/:id` | 查看 Note 详情 | 可见性检查 |
| `PATCH` | `/api/alfred/notes/:id` | 更新 Note（title/keywords/共享状态） | 创建者 |
| `DELETE` | `/api/alfred/notes/:id` | 删除 Note | 创建者 |
| `POST` | `/api/alfred/notes/search` | 检索 Note | 当前用户 |
| `POST` | `/api/alfred/notes/:id/links` | 添加 Note 关联 | 创建者 |
| `DELETE` | `/api/alfred/notes/:id/links/:linked_id` | 删除 Note 关联 | 创建者 |
| `GET` | `/api/alfred/notes/:id/links` | 查看 Note 的所有关联 | 可见性检查 |

### 7.1 POST /api/alfred/notes

Request Body:

```json
{
  "content": "今天和王医生复诊，血压恢复正常，下次检查在三个月后",
  "source": "text"
}
```

服务端处理（不由客户端传入）：
- `title`, `keywords`, `summary` → LLM 提取
- `embedding` → 调用 embedding 模型
- `event_time` → 服务端写入当前时间

Response:

```json
{
  "success": true,
  "note": {
    "id": "note_01J...",
    "short_id": 42,
    "title": "王医生复诊",
    "summary": "血压恢复正常，三个月后复查",
    "keywords": ["王医生", "复诊", "血压", "健康"],
    "event_time": "2026-04-28T10:30:00Z",
    "source": "text"
  },
  "suggested_links": [
    {
      "id": "note_01H...",
      "short_id": 38,
      "title": "健康检查结果",
      "event_time": "2026-02-28T00:00:00Z",
      "similarity": 0.91
    }
  ]
}
```

### 7.2 POST /api/alfred/notes/search

Request Body:

```json
{
  "query": "王医生上次说了什么",
  "limit": 5
}
```

Response:

```json
{
  "success": true,
  "results": [
    {
      "id": "note_01J...",
      "title": "王医生复诊",
      "summary": "血压恢复正常，三个月后复查",
      "event_time": "2026-04-28T10:30:00Z",
      "score": 0.93,
      "source": "text"
    }
  ]
}
```

### 7.3 语音上传接口

```
POST /api/alfred/notes/voice
Content-Type: multipart/form-data

Fields:
  audio: <binary>        -- 语音文件（ogg/mp4/m4a）
```

服务端流程：
1. 保存文件到 `{DATA_DIR}/audio/notes/{user_id}/{note_id}.ogg`
2. 调用 Whisper 转录，得到 `content`
3. 同创建文字 Note 后续流程

---

## 8. 可见性规则汇总

Note 是纯个人信息，只有创建者本人可以访问。

| 操作 | Note |
|------|------|
| 创建者本人 | ✅ 完全访问（读、写、删） |
| 其他任何用户 | ❌ 不可见 |
| Admin | ✅（仅系统管理需要时） |

---

## 9. 实现检查清单

### Phase 1 — 基础存储

- [ ] 创建 `alfred_notes` 表（含 pgvector 扩展）
- [ ] 创建 `alfred_note_links` 表
- [ ] 配置本地语音文件存储目录
- [ ] 实现 Note CRUD API（不含 embedding）
- [ ] 实现可见性过滤逻辑

### Phase 2 — LLM 集成

- [ ] 实现 LLM 提取（title / keywords / summary / **entities**）的 Prompt + 调用
- [ ] 集成 embedding 模型（text-embedding-3-small 或等价）
- [ ] 创建 Note 时自动触发 LLM 提取 + embedding
- [ ] 实现语义检索 API
- [ ] 实现实体查询：按 people/places/orgs 的 JSONB 检索（§6.4）
- [ ] 创建 Note 后的实体上下文提醒（§6.5 ①）
- [ ] 创建 Note 后的语义关联建议（§6.5 ②）
- [ ] 检索时若命中实体，使用时间线格式返回（§6.4）

### Phase 3 — 语音支持

- [ ] 集成 Whisper API 转录
- [ ] 实现语音上传接口（存储 + 转录 + 写 Note）
- [ ] 语音文件路径管理（创建 / 删除同步）

### Phase 4 — Bot 命令 + 意图识别

- [ ] 实现意图识别层（LLM 分类 + 置信度阈值）
- [ ] 不确定时的交互确认流程
- [ ] 实现所有 `/note` 命令
- [ ] 实现 `/find` 命令（三层检索 + 合并排名）
- [ ] 新建 Note 后自动推荐关联（相似度阈值 0.85）
- [ ] 实现 `/link` / `/unlink` 命令（双向插入/删除）

---

## 10. 技术依赖

| 组件 | 用途 | 推荐 |
|------|------|------|
| PostgreSQL + pgvector | 向量存储与检索；JSONB 用于实体索引 | pgvector ≥ 0.5 |
| OpenAI Whisper | 语音转录 | `whisper-1` API |
| OpenAI Embeddings | 语义向量生成 | `text-embedding-3-small` |
| OpenAI Chat | LLM 提取 + 意图识别 | `gpt-4o-mini`（低成本） |
| 本地文件系统 | 语音文件存储 | `{DATA_DIR}/audio/notes/` |

---

*文档结束 — Alfred Note Feature Design v1.0*
