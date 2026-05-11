# Alfred — 产品需求文档（PRD）

**版本：** v0.9 Draft  
**日期：** 2026-05-04  
**作者：** Richard  
**状态：** 内部讨论稿 · **Thread-Centric 架构重构版**

**变更摘要（v0.8 → v0.9）：**
- **[架构重构] Thread-Centric Architecture（以线索为中心）**
  - Thread 和 Reminder 合并为 **Unified Thread**，Reminder 不再是独立对象
  - Thread 新增 `trigger` 字段（时间 / 空间 / 循环触发器），替代原 `reminders` 表
  - 技能层「Nudge :8002」更名为「**Thread :8002**」，职责精确为：管理 Unified Thread 的完整生命周期
  - 「Nudge」保留为**输出行为**的术语（Brain 发出的激活消息），不再是服务名称
  - Brain 新增第⑥个工作器：**Trigger Monitor**，负责监控时间 / 地理触发器，触发条件满足时激活对应 Thread，并携带其全量 Weaving 上下文发送 Nudge
  - 数据层：删除 `reminders` 表，`threads` 表新增 `trigger` 嵌套结构
  - **Qdrant 合并为单一 Collection `threads_all`**，通过 payload `category` 字段过滤，查询时按分类动态应用相似度阈值；废除 `threads_pro / threads_life / threads_emo / threads_routine` 四个分库

**补丁（v0.9 patch）：**
- **[补丁 A] Misfire Handling**：Trigger Monitor 启动时扫描「本应触发但被停机错过」的 Thread，按延迟时长决定补发或标记 `expired`
- **[补丁 B] 自适应地理心跳**：Brain 根据活跃 geofence Thread 向 Gateway 下发动态心跳指令，接近目标区域时心跳从 5 分钟提升至 30 秒
- **[补丁 C] Qdrant 单 Collection**：合并四个分类 Collection 为 `threads_all`，彻底消除跨库 Weaving 盲区
- **[补丁 D] `firing` 原子状态**：Trigger Monitor 发送 Nudge 前先将 `ack_status` 置为 `firing`，防止网络重试或多线程导致同一提醒重复发送
- **[补丁 E] `interaction_rules`**：PersonaProfile 新增字段，记录 Kelly 的静默确认权重累积规则
- **[字段修正] `"service": "nudge"` → `"service": "thread"`**：事件 payload 中的服务标识与服务名统一

---

## 目录

1. [产品愿景](#1-产品愿景)
2. [核心设计哲学](#2-核心设计哲学)
3. [目标用户](#3-目标用户)
4. [核心概念定义](#4-核心概念定义)
5. [功能需求（技能层）](#5-功能需求技能层)
6. [用户界面设计](#6-用户界面设计)
7. [功能需求（大脑层）](#7-功能需求大脑层)
8. [Onboarding 设计](#8-onboarding-设计)
9. [技术架构](#9-技术架构)
10. [Alfred 三层架构](#10-alfred-三层架构)
11. [Brain 服务规格](#11-brain-服务规格)
12. [非功能性需求](#12-非功能性需求)
13. [开放问题与待讨论项](#13-开放问题与待讨论项)
14. [版本路线图](#14-版本路线图)

---

## 1. 产品愿景

**Alfred 是一个「懂这个家」的 AI 管家平台。**

它的结构和任何真正的智能体一样，分三个部分：

```
大脑（Brain）   — 思考、学习、主动关心
感官（Senses）  — 感知世界、开口说话、倾听回应
技能（Skills）  — 帮你做具体的事
```

Nudge 是一个输入——你对 Alfred 说的话，一条 Thread。  
Nudge 也是一个输出——Alfred 在正确的时机，把记忆唤醒送到你面前。

> 最终目标：让你们感到即便年纪渐长、记忆衰退，生活依然在掌控之中，且充满被理解的温暖。

**产品名称：** Thread（面向用户的品牌名）/ Alfred（整体平台）  
**核心服务：** Brain（大脑）/ Gateway（感官）/ Thread + OurCents（技能）  
**核心动词：** Weave（编织）  
**核心动作：** Nudge（激活 · 唤醒）

---

## 2. 核心设计哲学

### 2.1 三层架构信念

- **大脑负责思考，感官负责感知，技能负责执行。** 三者职责不能混淆。
- **所有输入都是 Thread。** 「明天两点开会」和「Kelly 想买绿植」本质上是同一种对象，只是触发属性不同。
- **Reminder 是 App 思维，Trigger 是大脑思维。** 闹钟只是激活记忆的一种方式，记忆本身才是核心。
- **家庭是最小认知单元。** Brain 以 Family 为作用域，感官和技能按用户独立运作。
- **好的 AI 知道什么时候该沉默。** Brain 的输出受密度和情感预算双重约束。
- **正向叙事塑造行为。** 永远用「动能」代替「拖延」。
- **认知必须有遗忘才能保持活力。** 过期的弱关联应当被清理。
- **用户的纠正是最高权重的信号。** Brain 的推演可以被错，错了必须能被改且被记住。

### 2.2 语言规范

| ❌ 禁止使用 | ✅ 使用替代 |
|-----------|-----------|
| 拖延指数 | 动能（Momentum）|
| 你在拖延 | 当前动能较低 |
| 记录任务 | 把线索缝起来 |
| 操作层 / 智能层 | 感官 / 技能 / 大脑 |
| 设置提醒 | 给这条线索加个触发器 |
| Reminder（服务）| Thread（Unified）|

---

## 3. 目标用户

| 属性 | Richard | 太太（Kelly）|
|------|---------|------------|
| 核心输入界面 | Web 看板 | WhatsApp（首选）|
| 启动阻力 | 低 | 高（需动能积累策略）|
| 对「被管理」的感受 | 中性 | **高度敏感，易产生防御**|
| Weaving 确认方式 | 显式点击确认 | 静默确认（Implicit Ack）优先 |

---

## 4. 核心概念定义

### 4.1 三类对象的关系

```
Thread（线索）      ─── 是 ───→  Brain 的原材料（节点）
Weaving（编织）     ─── 是 ───→  Brain 建立的关系（边）
Nudge（激活）       ─── 是 ───→  Brain 的输出行为（唤醒一条 Thread 及其上下文）
```

**Thread 是唯一的输入对象。** 它可以是静态的（无触发器），也可以是动态的（带时间 / 空间 / 循环触发器）。两者在 Brain 眼中是同等的认知节点，可以被编织，可以被激活。

### 4.2 Unified Thread（统一线索）*(v0.9 核心重构)*

```json
{
  "thread_id": "uuid",
  "content": "明天下午 2 点提醒我开季度复盘会",
  "category": "pro",       // pro | life | emo | routine
  "person": "richard",
  "priority": "high",
  "status": "active",      // active | sleeping | archived
  "snooze_count": 0,
  "location_tag": null,
  "source": "whatsapp",    // whatsapp | web | voice | geofence
  "created_at": "...",
  "updated_at": "...",

  "trigger": {
    "type": "once",          // none | once | recurring | geofence
    "fire_at": "2026-05-05T14:00:00",   // once 类型使用
    "cron": null,            // recurring 类型使用，标准 cron 表达式
    "location": null,        // geofence 类型使用，{ lat, lng, radius_m }
    "ack_status": "pending",  // pending | awaiting | acknowledged | snoozed | dismissed | expired
    "ack_timeout_at": null    // awaiting 状态的超时时间（默认触发后 2 小时）
  },

  "vectors": {
    "fact": [0.12, -0.34, ...],    // 事实向量（由 Embedding 生成）
    "intent": {
      "urgency": 0.85,
      "social_bond": 0.3,
      "goal_alignment": 0.7
    }
  },

  "tags": ["季度复盘", "项目管理"]
}
```

**trigger.type 四种类型：**

| 类型 | 含义 | 示例 |
|------|------|------|
| `none` | 纯静态线索，无时空触发 | 「Kelly 想买绿植」|
| `once` | 一次性时间触发 | 「明天下午 2 点开会」|
| `recurring` | 循环触发（cron 表达式）| 「每周日检查阳台植物」|
| `geofence` | 进入某地理区域触发 | 「到药店提醒买感冒药」|

**trigger.ack_status 完整状态机：**

```
pending           等待触发（trigger 条件尚未满足）
  │
  │ trigger 条件满足，Nudge 已送出，设置 ack_timeout_at = now + 2h
  ▼
awaiting          已响铃，等用户接（Nudge 在 WhatsApp 上等着）
  │
  ├─▶ acknowledged   用户主动回应（「好的」「知道了」）
  │     │
  │     ├─ once:      触发器完成 → 终态（Thread 继续活跃于图谱）
  │     └─ recurring: croniter 计算下次触发时间 → pending
  │
  ├─▶ snoozed        用户主动推迟（「等下」「30 分钟后再说」）
  │     │             snooze_count++，fire_at = now + snooze_delay
  │     └─▶ pending  重新进入等待
  │
  ├─▶ dismissed      用户主动取消（「不用了」「关掉」）
  │     │             触发器关闭，Thread 本身继续留在图谱
  │     ├─ once:      终态
  │     └─ recurring: 停止循环，除非用户重新启用
  │
  └─▶ expired        超时无响应（ack_timeout_at 到达，系统自动判定）
        │             ≠ snoozed：用户没有表态，系统不能替用户 snooze
        ├─ once:      触发器失效，Thread 继续活跃于图谱
        │             Brain 可稍后发送轻量 L1 询问：
        │             「你早上 8 点的提醒没看到，要重新定还是不需要了？」
        └─ recurring: croniter 计算下次触发时间 → pending（不打扰）

【补丁 D：firing 原子状态】*(v0.9 patch 新增)*
pending / awaiting 之间还有一个极短暂的事务态：

  awaiting → [Nudge 即将发出] → firing（原子写入，防重复）→ 发送成功 → awaiting
                                                           → 发送失败 → 回滚至 awaiting

firing 是实现层保护态，不暴露给用户，仅用于防止多线程或网络重试导致同一 Nudge 发出两次。
```

**geofence 类型的 expired 判定：** 用户离开围栏区域且未响应 → `expired`（而非超时，无需 ack_timeout_at）

**类型判断规则（AI 自动解析）：**
- 「明天下午 2 点……」→ `once` + `fire_at`
- 「每周一……」/ 「每天早上……」→ `recurring` + `cron`
- 「到……的时候」/ 「路过……」→ `geofence` + `location`
- 无时空标记 → `none`

**旧 Reminder 的工程迁移：**

| 旧 `reminders` 表字段 | 新 `threads` 表对应 |
|---------------------|-------------------|
| `reminder_id` | `thread_id` |
| `content` | `content` |
| `fire_at` | `trigger.fire_at` |
| `recurrence_rule` | `trigger.cron` |
| `location` | `trigger.location` |
| `status` | `trigger.ack_status` |

### 4.3 Weaving（编织关系）

> 无变化。Thread 合并后，Brain 面对的是统一的 Context Pool，Weaving 质量提升——带触发器的 Thread（如「量血压」的循环 Thread）与静态 Thread（如「最近压力大」）可以直接被编织，不再被隔离在不同的对象类型中。

| 类型 | 视觉 | 含义 |
|------|------|------|
| 语义关联（Semantic） | 白色实线 | 内容语义相关 |
| 冲突预警（Conflict） | 红色虚线 + 呼吸动效 | 时间或资源冲突 |
| 主动编织（Proactive） | 蓝色虚线 | Brain 推演的关联 |
| 时序依赖（Sequential） | 橙色流动箭头 | A 必须先于 B |
| 空间关联（Spatial） | 紫色点线 | 物理位置接近 |
| 跨技能关联（Cross-skill） | 金色实线 | Thread ↔ OurCents 跨域关联 |
| 用户纠正边（Corrected） | 灰色删除线 | 用户断开的错误关联，永久保留为历史 |

### 4.4 Nudge（激活）— 输出行为定义

Nudge 是 Brain 唤醒一条 Thread 的动作。它有两种来源：

| 来源 | 触发条件 | 携带的上下文 |
|------|---------|------------|
| **显式激活**（Trigger-driven）| `trigger.type != none` 且条件满足 | Thread 内容 + 所有已编织的相关 Thread 摘要 |
| **隐式激活**（Brain-driven）| Brain 发现编织洞察，主动生成 | 洞察描述 + 关联 Thread 摘要 |

**关键区别：** 触发器满足时，Nudge 不只是闹钟，而是「唤醒这条记忆，同时带上它在图谱里的所有朋友」。

**情感重量分级：**

| 级别 | 类型 | 情感消耗值 |
|------|------|-----------|
| L1 | 轻量提示 | 0.5 |
| L2 | 任务推动 | 1.0 |
| L3 | 冲突预警 | 2.0 |
| L4 | 情感深度 | 3.0 |

---

## 5. 功能需求（技能层）

> **v0.9 更新：** 「Nudge 技能」更名为「Thread 技能」，职责精确化为：管理 Unified Thread 的完整生命周期（CRUD + 触发器解析 + snooze/dismiss）。输出行为「Nudge」由 Brain 统一发出，不再由技能层直接触发。

### 5.1 认知图谱视图（前端展现层）

**Ego-centric 默认模式（5-7 节点）：**
- 节点评分 = `时间紧迫度(60%) × 关联强度(40%)`
- 带 `trigger.fire_at` 的节点，紧迫度随时间临近线性上升
- 卫星节点：Cosine Similarity > 0.85 的非紧迫节点悬停边缘

**全局模式（Full Graph）：** 上限 20 节点，四象限聚簇

**视觉动效：**

| 元素 | 动效 |
|------|------|
| 冲突节点 | 呼吸缩放 0.95 ↔ 1.05，周期 2s |
| 带触发器的节点 | 节点右上角显示小时钟图标（once）/ 循环图标（recurring）/ 定位图标（geofence）|
| 时序依赖边 | 橙色粒子流动 |
| Sub-thread 完成 | 能量波动至父节点，发光 0.5s |
| 卫星节点 | ±3px 浮动，周期 4s |
| 跨技能关联边 | 金色脉冲，每 5s 一次 |
| 用户纠正边 | 灰色删除线，透明度 40% |

### 5.2 Thread 操作（Thread 技能）

**录入：** 自然语言 → AI 解析 → 自动填充 `trigger` 字段 → 用户一键确认

**AI 解析示例：**

| 用户输入 | 解析结果 |
|---------|---------|
| 「Kelly 想买绿植」| `trigger.type = none` |
| 「明天两点开会」| `trigger.type = once, fire_at = 明天 14:00` |
| 「每周日浇花」| `trigger.type = recurring, cron = "0 10 * * 0"` |
| 「到超市提醒买牛奶」| `trigger.type = geofence, location = 用户常去超市位置` |

**生命周期：**
```
active（活跃）
  → sleeping（7 天无更新，或 trigger 被 dismissed）
  → archived（用户归档，或 Brain 熵减提议后确认）
  
recurring Thread：触发后 ack_status 重置，永远保持 active，除非用户主动归档
```

**Sub-threading：** Snooze ≥ 3 次触发微粒化（将 Thread 拆解为子 Thread，每个可独立携带 trigger）

### 5.3 Persona 推演引擎

```
PersonaProfile {
  user_id, communication_style, cognitive_mode,
  work_pattern, nudge_preference, personality_tags,
  momentum_score: float,
  motivation_style: "logic" | "emotion" | "reward",
  implicit_ack_enabled: bool,
  emotional_budget_24h: float,

  // 补丁 E：静默确认的权重累积规则
  interaction_rules: {
    implicit_ack_weight_increment: 0.1,  // 每次静默确认后 Weaving 权重增加量
    implicit_ack_weight_cap: 0.8,        // 通过静默累积的权重上限，超过后需显式确认
    silence_veto_phrase: ["不对", "取消", "别发这个"],  // 触发 USER_CORRECTION 的关键词
    inactivity_pause_days: 30            // 连续 N 天无互动后暂停静默确认，等待用户重新激活
  }
}
```

**momentum_score 关怀信号：**

| 区间 | 行为 |
|------|------|
| 首次跌破 0.3 | 触发情感类 Nudge（不推任务）|
| 持续 < 0.3 | 激活 Sub-threading + 心愿单激励 |

### 5.4 WhatsApp 接口

- **自然语言录入**：无论是线索还是提醒，统一录入为 Thread，AI 解析 trigger 字段
- **语音输入**：Whisper API 转录 → 同一解析流程
- **渐进式唤醒**：Trigger-driven Nudge 在触发前 30 分钟以话题形式引入，不直接提醒

### 5.5 拖延深度干预

- **Sub-threading**：微粒化任务 + 多米诺能量动效
- **关联激励**：心愿单驱动，每日最多 1 次

### 5.6 心愿单系统

- 「我想去……」→ AI 识别 → 加入心愿单（以 `trigger.type = none` 的 Thread 存储）
- 激励匹配：时间 + 地理 + 情感三维匹配
- 完成后生成情感 Thread，成为记忆回溯素材

### 5.7 情感价值链

- **记忆回溯**：晨间 Nudge，朋友分享语气
- **情感总线**：跨用户情感信号 → 另一方 Nudge
- **Kill Switch**：单击断开，无弹窗，优雅降级

### 5.8 技能事件双向量标准

```json
{
  "event_type": "add_thread",
  "service": "thread",
  "entities": {
    "content": "特斯拉最近保养费越来越贵了",
    "category": "life",
    "trigger_type": "none",
    "fact_context": "Thread 关于特斯拉保养费用",
    "intent_context": "对家庭支出感到压力（焦虑感）",
    "intent_vector": {
      "urgency": 0.4,
      "social_bond": 0.3,
      "goal_alignment": 0.5
    }
  }
}
```

**Intent Vector 三个维度：**

| 维度 | 含义 |
|------|------|
| **Urgency** | 紧迫感（0=随口一提，1=今天截止）|
| **Social_Bond** | 情感联结强度（0=纯事务，1=强情感关联）|
| **Goal_Alignment** | 与家庭长期目标的契合度 |

---

## 6. 用户界面设计

### 6.1 三层视图

```
层级一：今日卡片视图（默认）
  ↓ 切换
层级二：家庭图谱视图（Ego-centric ↔ Full Graph）
  ↓ 点击节点
层级三：节点详情视图（含 trigger 状态 + Weaving 关联列表）
```

### 6.2 家庭图谱视图

- 带触发器的节点与静态节点共同出现在图谱中，视觉区分仅靠图标
- Brain 发现「量血压（recurring Thread）」与「最近压力大（emo Thread）」有 Weaving，两者之间显示编织关联边
- 家庭健康度指示：Brain 每日计算图谱状态，看板顶部可视化

### 6.3 自适应热力图视图

**节点热度公式（trigger 节点额外加权）：**
```
热度 = 最近 Nudge 引用 × 0.4
     + 最近 7 天浏览/编辑 × 0.3
     + 地理相关度 × 0.2
     + 时间段相关度 × 0.1
     + (距 trigger.fire_at < 24h ? 0.3 : 0)  // 临近触发的节点额外加热
```

| 热度区间 | 节点表现 |
|---------|---------|
| 高热（> 0.7） | 全亮、较大、浮动 ±5px |
| 中热（0.3–0.7）| 正常亮度 |
| 低热（0.1–0.3）| 透明度 60%，缩小 15% |
| 冷却（< 0.1）| 透明度 30%，缩小 25%，悬停才显示标签 |

### 6.4 时间透视（Time Perspective）

- **历史回放**（左滑）：过去某天的图谱快照
- **当前视图**（默认）：实时热力图
- **未来推演**（右滑）：Brain 推演的未来图景，虚线轮廓，最长 30 天

### 6.5 Weaving 纠正交互

- 右键点击 Weaving 边 → 「断开这条关联」→ 触发 USER_CORRECTION 事件
- 断开的边变为灰色删除线，永久保留为历史记录

---

## 7. 功能需求（大脑层）

### 7.1 Brain 的核心职责

1. **持续观察**：接收技能层事件（CREATE / INVALIDATE / USER_CORRECTION）
2. **建立图谱**：在 Qdrant 中维护家庭认知图谱（Unified Thread 全量）
3. **发现洞察**：分析 Active Pool，发现 Weaving 机会
4. **监控触发器**：扫描待触发的 Thread，条件满足时激活并发出上下文丰富的 Nudge
5. **仲裁推送**：所有 Nudge（显式 + 隐式）经 Decision Arbiter + 情感预算双重过滤
6. **接受纠正**：USER_CORRECTION 作为最高权重负反馈更新认知
7. **维护图谱健康**：熵减进程清理弱关联

### 7.2 Brain 的六个后台工作器 *(v0.9 新增第⑥个)*

**① 事件处理器（Event Processor）— 实时**
- 处理 CREATE / INVALIDATE / USER_CORRECTION 三类事件
- CREATE：双向量解析 → Qdrant 写入（原子锁）→ Active Pool
- INVALIDATE：标记 `needs_reweave`
- USER_CORRECTION：权值归零 → 负样本记忆 → 撤销关联 Nudge

**② 语义聚类器（Semantic Clusterer）— 每周**
- 仅扫描 Active Pool，Intent Vector 点积 + Fact Cosine 双重评分
- 点积 > 0.7 且 Fact Cosine > 分类阈值 → 生成 Weaving 提议
- 提议通过 Decision Arbiter 审核后推送用户

**③ 主动 Nudge 生成器（Proactive Nudge Generator）— 每日**
- 分析 Active Pool 状态，生成隐式激活候选
- 经 Decision Arbiter + 情感预算过滤，每日最多 1-2 条送达

**④ 决策仲裁器（Decision Arbiter）— 实时，前置于所有推送**

```python
async def arbitrate(candidate_nudge, family_id):
    # 检查 1：时间窗口密度
    # 检查 2：情感预算（扣除对应消耗值）
    # 检查 3：语义冲突（合并或丢弃矛盾 Nudge）
    # 检查 4：情绪负载（Kill Switch / momentum < 0.2 时转为情感类）
    # 检查 5：USER_CORRECTION 历史（基于纠正过的关联的 Nudge → SUPPRESS）
```

| 仲裁结果 | 含义 |
|---------|------|
| `APPROVED` | 立即推送 |
| `DEFER` | 延迟 |
| `SUPPRESS` | 丢弃 |
| `CONVERT_TO_EMOTIONAL` | 任务语气 → 关怀语气 |
| `RESOLVE_CONFLICT` | 合并冲突 Nudge |
| `DOWNGRADE_TO_SILENT` | 降级为静默提醒 |

**⑤ 熵减进程（Entropy Reduction）— 每月**
- 清理权值 < 0.15 且超 6 个月未激活的弱关联边
- 跳过用户纠正边（永久保留）
- 双端归档的边直接清理；半活跃边推送用户确认

**⑥ Trigger Monitor（触发器监控）— 实时扫描** *(v0.9 新增)*

> 这是合并 Reminder 后最关键的新工作器。它接管了原 Nudge 技能中的定时提醒逻辑，但做得比闹钟更多。

```python
async def on_startup():
    """
    补丁 A：服务启动时执行漏发检查（Misfire Handling）
    解决停机期间错过的触发器，防止 Thread 被永久遗漏。
    """
    misfired = await db.query("""
        SELECT * FROM threads
        WHERE trigger_type IN ('once', 'recurring')
        AND trigger_ack_status = 'pending'
        AND trigger_fire_at < NOW()
    """)
    for thread in misfired:
        delay = now() - thread.trigger_fire_at
        if delay <= timedelta(minutes=15):
            # 延迟 ≤ 15 分钟：仍然相关，立即补发（带「稍晚了一点」的语气标记）
            await enqueue_trigger(thread, late=True)
        elif delay <= timedelta(hours=2):
            # 延迟 15 分钟 ~ 2 小时：发轻量询问，让用户决定
            await schedule_misfire_inquiry(thread)
        else:
            # 延迟 > 2 小时：直接标记 expired，once 类型额外发 L1 询问
            await db.update_thread_trigger_status(thread.thread_id, ack_status="expired")
            if thread.trigger_type == "once":
                await schedule_expiry_followup(thread, delay_minutes=30)
            elif thread.trigger_type == "recurring":
                next_fire = croniter(thread.trigger_cron).get_next(datetime)
                await db.update(thread.thread_id,
                                trigger_fire_at=next_fire, ack_status="pending")


async def run_trigger_monitor():
    """
    每分钟运行一次（生产环境可用消息队列优化）
    """
    # 1. 查询所有即将触发的 Thread（fire_at 在未来 5 分钟内）
    due_threads = await db.query("""
        SELECT * FROM threads
        WHERE trigger_type IN ('once', 'recurring')
        AND trigger_ack_status = 'pending'
        AND trigger_fire_at BETWEEN NOW() AND NOW() + INTERVAL '5 minutes'
    """)

    # 2. 处理地理围栏触发（从 Gateway 接收的 Geofence 入境事件）
    geofence_threads = await get_pending_geofence_activations()

    for thread in due_threads + geofence_threads:
        # 3. 补丁 D：原子写入 firing 状态，防止多线程重复发送
        updated = await db.atomic_update(
            table="threads",
            where={"thread_id": thread.thread_id, "trigger_ack_status": "pending"},
            set={"trigger_ack_status": "firing"}
        )
        if not updated:
            continue  # 已被其他进程抢先处理，跳过

        try:
            # 4. 从 Qdrant threads_all 获取该 Thread 的已确认 Weaving（上下文）
            weavings = await qdrant.get_weavings_for_thread(
                thread.thread_id,
                min_weight=0.3,
                limit=3
            )

            # 5. 构建富上下文 Nudge
            nudge = await build_contextual_nudge(thread, weavings)
            # 示例输出：
            # 「📅 季度复盘会快开始了。
            #  顺便提一下，你上次记下的「API 性能瓶颈」笔记和这次议程有关——
            #  要带进去讨论吗？」

            # 6. 经 Decision Arbiter 审核
            result = await arbitrate(nudge, thread.family_id)
            if result == APPROVED:
                await push_to_gateway(nudge)
                # 发送成功 → 进入 awaiting（acknowledged 由用户回应后 Gateway 回调设置）
                await db.update_thread_trigger_status(
                    thread.thread_id,
                    ack_status="awaiting",
                    ack_timeout_at=now() + timedelta(hours=2)
                )
            else:
                # 仲裁未通过 → 回滚至 pending，等待下一个窗口
                await db.update_thread_trigger_status(thread.thread_id, ack_status="pending")
        except Exception:
            # 发送异常 → 回滚至 pending，避免卡死在 firing
            await db.update_thread_trigger_status(thread.thread_id, ack_status="pending")

    # 7. 补丁 B：自适应地理心跳——根据活跃 geofence Thread 动态调整手机端位置回传频率
    await update_geofence_heartbeat()
```

**补丁 B：自适应地理心跳（Adaptive Geofence Heartbeat）**

```python
async def update_geofence_heartbeat():
    """
    Brain 扫描所有活跃的 geofence Thread，计算每位用户距各目标地点的距离，
    向 Gateway 下发心跳频率指令。
    Gateway 将指令转发给手机端 SDK，动态调整位置回传间隔。
    """
    active_geofence_threads = await db.query("""
        SELECT DISTINCT user_id, trigger_location, trigger_radius
        FROM threads
        WHERE trigger_type = 'geofence'
        AND trigger_ack_status = 'pending'
    """)

    for user_id, targets in group_by_user(active_geofence_threads):
        last_known = await get_last_known_location(user_id)
        if last_known is None:
            continue

        min_distance = min(
            haversine(last_known, t.trigger_location) for t in targets
        )

        if min_distance < 500:       # 进入 500m 内：30 秒心跳（几乎实时）
            heartbeat_interval = 30
        elif min_distance < 1000:    # 500m ~ 1km：1 分钟心跳
            heartbeat_interval = 60
        elif min_distance < 5000:    # 1km ~ 5km：3 分钟心跳
            heartbeat_interval = 180
        else:                        # > 5km：5 分钟心跳（省电模式）
            heartbeat_interval = 300

        await gateway_client.set_location_heartbeat(user_id, heartbeat_interval)
```

Brain 同时暴露一个只读端点供 Gateway 查询：`GET /brain/active_geofences/{user_id}`，返回该用户当前所有待触发的 geofence Thread 及目标坐标，Gateway 据此初始化心跳参数。

**Trigger Monitor 的五个核心特性：**

| 特性 | 说明 |
|------|------|
| **上下文注入** | 触发时自动附带相关 Weaving 摘要（最多 3 条），不只是提醒内容本身 |
| **仲裁保护** | 显式触发同样过 Decision Arbiter，动能极低时可转为情感关怀语气 |
| **Snooze 感知** | Snooze 后重新计算 fire_at（默认 +30 分钟），snooze_count 累加 |
| **漏发补偿** | 启动时扫描停机期间错过的触发器，按延迟时长决定补发 / 询问 / 过期 |
| **重复发送防护** | `firing` 原子状态确保同一 Nudge 不会因重试或多线程被发出两次 |

**awaiting 超时扫描（Trigger Monitor 同步处理）：**
```python
# 每分钟同时扫描超时的 awaiting Thread
timed_out = await db.query("""
    SELECT * FROM threads
    WHERE trigger_ack_status = 'awaiting'
    AND ack_timeout_at < NOW()
""")
for thread in timed_out:
    await db.update_thread_trigger_status(thread.thread_id, ack_status="expired")
    if thread.trigger_type == "recurring":
        # recurring 过期后静默重置，不打扰用户
        next_fire = croniter(thread.trigger_cron).get_next(datetime)
        await db.update(thread.thread_id, trigger_fire_at=next_fire, ack_status="pending")
    elif thread.trigger_type == "once":
        # once 过期后，Brain 稍后发一条轻量询问（L1，低情感消耗）
        await schedule_expiry_followup(thread, delay_minutes=30)
```

**geofence 过期处理（Gateway 接收离境事件时触发）：**
```python
async def on_geofence_exit(user_id, location):
    awaiting_geo = await db.query("""
        SELECT * FROM threads
        WHERE user_id = :user_id
        AND trigger_type = 'geofence'
        AND trigger_ack_status = 'awaiting'
        AND ST_Distance(trigger_location, :location) < trigger_radius
    """, user_id=user_id, location=location)
    for thread in awaiting_geo:
        await db.update_thread_trigger_status(thread.thread_id, ack_status="expired")
```

**recurring Thread 正常触发后的重置逻辑：**
```python
# acknowledged 或 expired 后，recurring 均需计算下次触发时间
next_fire = croniter(thread.trigger_cron).get_next(datetime)
await db.update(thread_id, trigger_fire_at=next_fire, ack_status="pending", ack_timeout_at=None)
```

### 7.3 情感预算（Emotional Budget）

- 每位用户 24 小时初始值：10.0 分
- 消耗：L1=0.5 / L2=1.0 / L3=2.0 / L4=3.0
- 用户主动发起对话时不计入预算
- momentum < 0.2 时，L1/L2 消耗减半（系统保护模式）

### 7.4 逆向编织（USER_CORRECTION）

- 用户断开 Weaving 边 → 权值归零 → 负样本记忆（永不过期）→ penalty 系数 0.1
- correction_memory 永久保存，熵减进程不处理纠正边

### 7.5 激活池（Active Pool）

- 纳入标准：30 天内有更新 / 被 Nudge 引用 / 与当前 Geofence 相关 / 用户置顶
- 退出：连续 30 天无激活 → Archive Pool
- 容量上限：1000 节点/Family

### 7.6 Weaving 完整生命周期

```
Thread 创建（any trigger type）→ Event Processor → Qdrant → Active Pool

触发路径：
  显式触发：trigger 条件满足
    → Trigger Monitor 检测
    → 附加 Weaving 上下文
    → Decision Arbiter（可转情感类 / 降级静默）
    → Gateway → 用户

  隐式触发：Brain 发现洞察
    → Proactive Nudge Generator
    → Decision Arbiter
    → Gateway → 用户

Weaving 建立：
  → Semantic Clusterer（Active Pool）
    → Intent 点积 + Fact Cosine 双重评分
    → Weaving 提议 → Decision Arbiter → 用户确认
    → 显式确认 / 静默确认（Kelly）→ confirmed
    → 用户断开 → USER_CORRECTION → 负样本记忆

维护：
  → 30 天无激活 → Archive Pool（热力图冷却）
  → 每月熵减 → 弱关联边清理（跳过纠正边）
```

---

## 8. Onboarding 设计

### 8.1 Persona 冷启动脚本（Kelly 版）

**Step 1：建立连接**
```
「嘿 Kelly 👋 我是 Thread。
Richard 把我安在这里，说你是他们家的生活大导演——
但导演也有需要人帮着盯场的时候对吧？

我不是来催你干活的，就是帮你把散掉的线索缝一缝。
不管是随口一说，还是要记下来的事，都告诉我就好。

你希望我平时说话，是像个能懂你情绪的朋友，
还是干干净净说重点就好？」
```

**Step 2：探索动能**
```
「如果一件事你一直没动，
你更想我帮你把它拆成小步子，
还是先给你找个奖励来撑着走？」
```

**Step 3：心愿单初始化**
```
「最近有什么特别想去的地方，或者想看的电影吗？
随口说一两个就好。
下次当你动能不足的时候，我好有个理由来帮你换换心情 😊」
```

**Step 4：Kill Switch 主动披露**
```
「对了，还有件事先说清楚——
你看到聊天框顶部那个小心形了吗？
点一下，我就隐身了。不通知 Richard，不留痕迹。

你是这里的主人，我只是那根帮你缝线索的线 🪡」
```

### 8.2 24 小时旅程

| 时间点 | 动作 |
|--------|------|
| T+0 | 冷启动脚本（四步）|
| T+1h | 引导发送第一条 Thread，立即图谱反馈 |
| T+8h | 第一次「隐形编织」Aha! 时刻（跨 Thread Weaving）|
| T+24h | 动能复盘，正向收尾 |

### 8.3 成功指标

| 指标 | 目标 |
|------|------|
| 冷启动完成率 | > 80% |
| T+1h 首条录入率 | > 70% |
| T+8h Aha! 体验率 | > 60% |
| D7 留存率 | > 50% |

### 8.4 静默确认（Implicit Ack）

- 适用对象：`implicit_ack_enabled = true` 的用户（Kelly 默认开启）
- 触发条件：L1/L2 Weaving 提议 + 30 分钟内无反对 + 用户继续活跃
- 不适用：L3/L4 提议 / 跨技能 Weaving 首次创建 / 涉及修改已有 Weaving
- 撤销窗口：24 小时内可说「刚才那个取消」→ Brain 执行 USER_CORRECTION

---

## 9. 技术架构

### 9.1 Alfred 整体拓扑

```
┌────────────────────────────────────────────────────────┐
│                   【大脑层】BRAIN  :8003                 │
│                                                        │
│  后台工作器：                                           │
│  ① Event Processor（实时，含原子锁）                     │
│  ② Semantic Clusterer（每周，Intent+Fact 双评分）        │
│  ③ Proactive Nudge Generator（每日，隐式激活）           │
│  ④ Decision Arbiter（实时，5 项检查）                    │
│  ⑤ Entropy Reduction（每月，跳过纠正边）                 │
│  ⑥ Trigger Monitor（实时扫描，显式激活 + 上下文注入）    │
│                                                        │
│  存储：                                                 │
│  SQLite：weavings / nudge_log / correction_memory /    │
│          graph_snapshots                               │
│  Active Pool（内存，1000 节点 LRU）                     │
│  Qdrant :6333：threads_all + weaving_map（单 Collection）│
└──────────────────────┬─────────────────────────────────┘
                       │  CREATE / INVALIDATE / USER_CORRECTION
                       │  Geofence 入境事件
                       │  主动推送 /api/internal/push
                       ▼
┌────────────────────────────────────────────────────────┐
│                  【感官层】SENSES                        │
│   WhatsApp → Bridge :3001 → GATEWAY :8000               │
│   广播：CREATE / INVALIDATE / USER_CORRECTION           │
│   地理围栏：OS 原生事件 → Gateway → Brain               │
└───────────┬─────────────────┬──────────────────────────┘
            ▼                 ▼
┌───────────────────────────────────────────────────────┐
│                    【技能层】SKILLS                     │
│                                                       │
│   Thread :8002              OurCents :8001            │
│   ─────────────             ──────────────            │
│   Unified Thread CRUD       财务记账                  │
│   Trigger 解析（AI）        收据 OCR                  │
│   Sub-threading             跨技能事件输出            │
│   snooze / dismiss 逻辑                               │
│                                                       │
│   事件输出：Fact Vector + Intent Vector（三维）        │
│   双技能均实现 ASI 接口                                │
└───────────────────────────────────────────────────────┘
                             │
                       ┌─────▼────────────┐
                       │     Web 前端     │
                       │  ・今日卡片      │
                       │  ・家庭图谱      │
                       │    - 热力图      │
                       │    - 时间透视    │
                       │    - 纠正交互    │
                       │  ・知识库        │
                       └──────────────────┘
```

### 9.2 三层对比

| 维度 | 大脑层 | 感官层 | 技能层 |
|------|--------|--------|--------|
| 主要职责 | 思考/编织/激活/仲裁/纠错 | 感知/路由/广播 | 执行 Thread CRUD / 财务 |
| 状态性 | 有状态（图谱 + Pool + 负样本 + 快照）| 无状态 | 无状态 |
| 作用域 | 家庭（Family）| 单用户通道 | 单用户 |
| 触发方式 | 事件驱动 + 定时任务 + 实时扫描 | 用户消息 | 感官层派发 |
| 延迟 | 可接受分钟级 | < 3 秒 | < 3 秒 |

### 9.3 Gateway 事件广播（三类）

```python
# ① CREATE — 技能执行成功
# ② INVALIDATE — 数据删除或大幅修改（>50% 内容变更）
# ③ USER_CORRECTION — 用户在 Web 端断开 Weaving
# + Geofence 入境事件（OS 推送到 Gateway → 转发 Brain Trigger Monitor）
```

### 9.4 Qdrant 原子锁

- 写入前标记 `lock_status = "processing"`，完成后释放为 `"ready"`
- 前台查询只返回 `"ready"` 节点
- 5 秒超时自动解锁，防死锁

### 9.5 数据层

```
SQLite（技能层）
  ├── Gateway: contacts, conversations, messages, alfred_users, families
  ├── Thread:  threads（含 trigger 嵌套字段）, thread_links
  │            注：v0.9 废除 reminders 表，trigger 字段替代
  └── OurCents: expenses, incomes, budgets

SQLite（大脑层）
  ├── brain_events:       事件队列（event_action: CREATE/INVALIDATE/USER_CORRECTION）
  ├── weavings:           id, family_id, title, core_knowledge,
  │                       source_thread_ids, source_skill_events,
  │                       edge_weights, last_activated_at, status
  ├── nudge_log:          推送记录 + 情感重量（供预算计算）
  ├── correction_memory:  用户纠正记录（永不过期）
  └── graph_snapshots:    每日图谱快照（保留 90 天，供时间透视）

内存（Brain 进程）
  └── active_pool:        热节点集合（LRU，1000 上限）

Qdrant :6333（补丁 C：合并为单一 Collection）
  ├── threads_all   — 所有 Thread 统一存储，payload 含 category / trigger_type / lock_status
  │                   查询时按 category 动态应用相似度阈值（见下）
  └── weaving_map   — 家庭认知图谱（边 + 权值 + 纠正标记）

// 废除：threads_pro / threads_life / threads_emo / threads_routine（四分库）
// 原因：分库导致 Weaving 跨类搜索时出现盲区（如 routine Thread 无法和 emo Thread 编织）

// 分类阈值改为查询时动态应用：
CATEGORY_THRESHOLDS = {
    "pro":     0.80,
    "life":    0.72,
    "emo":     0.65,
    "routine": 0.75
}

// 单分类搜索（精确）：
results = qdrant.search("threads_all",
    query_vector=embedding,
    query_filter={"category": "emo"},
    score_threshold=0.65)

// 跨分类搜索（Weaving 编织用）：
candidates = qdrant.search("threads_all", query_vector=embedding, limit=50)
filtered = [r for r in candidates if r.score >= CATEGORY_THRESHOLDS[r.payload["category"]]]
```

### 9.6 技术选型

| 层级 | 选型 |
|------|------|
| 前端 | React + D3.js + TypeScript |
| 感官层 | Python FastAPI + Node.js（Bridge）|
| 技能层 | Python FastAPI（Thread :8002 / OurCents :8001）|
| 大脑层 | Python FastAPI（Brain :8003）|
| 定时任务 | APScheduler（Trigger Monitor 每分钟 / 其他工作器定时）|
| 关系数据库 | SQLite |
| 向量数据库 | Qdrant（本地，:6333）|
| AI 推演 | Claude API |
| 意图识别 + Trigger 解析 | gpt-4o-mini |
| Embedding | text-embedding-3-small |
| 语音转录 | Whisper API |
| 消息推送 | WhatsApp Business API / Bridge |
| 位置服务 | iOS/Android Geofencing 原生 API |
| Cron 解析 | croniter（Python）|

---

## 10. Alfred 三层架构

### 10.1 架构全景

```
Alfred = 大脑（Brain）+ 感官（Senses）+ 技能（Skills）
```

| Alfred 命名 | 智能体术语 | 核心问题 |
|------------|-----------|---------|
| 大脑（Brain）| Reasoning / Memory | Alfred 怎么思考、学习和纠错？|
| 感官（Senses）| Perception / Action | Alfred 怎么感知和表达？|
| 技能（Skills）| Tool / Capability | Alfred 能做什么？|

### 10.2 Thread-Centric 的架构意义 *(v0.9 新增)*

**旧模型（App 思维）：**
```
用户输入 → 判断：这是 Thread 还是 Reminder？
  → Thread：进入 Nudge 服务 threads 表
  → Reminder：进入 Nudge 服务 reminders 表
Brain 编织 Thread，但无法直接关联 Reminder
```

**新模型（大脑思维）：**
```
用户输入 → 统一成 Thread（AI 自动解析 trigger）
  → 进入 Thread 服务，统一存储
Brain 的 Context Pool = 所有 Thread（无论是否有触发器）
Trigger Monitor 在触发时：不只提醒，而是唤醒整条记忆线索
```

**最直接的体感差异：**

旧模式下，「开会提醒」到点响一声，任务完成。  
新模式下，「开会提醒」到点时，Alfred 说：  
*「季度复盘会快开始了。你上次记下的「API 性能瓶颈」和这次议题有关——要带进去吗？另外，Kelly 上周说你最近工作压力有点大，开完会也许可以早点回家。」*

### 10.3 各层职责边界

**大脑层（Brain :8003）**
- 六个工作器，家庭维度，异步
- Trigger Monitor 是新核心：显式激活 + 上下文注入 + 仲裁保护
- 三类信号权重：技能事件（低）< 感官广播（中）< 用户纠正（最高）

**感官层（Gateway + Bridge）**
- 三类广播 + Geofence 事件转发
- 不执行业务逻辑，不主动发起 Nudge

**技能层（Thread + OurCents）**
- Thread :8002：Unified Thread 完整生命周期管理
- OurCents :8001：财务领域逻辑
- 标准 ASI 接口 + 双向量输出

### 10.4 扩展成本（不变）

- **新增技能**：ASI 接口 + services.yaml + 双向量输出
- **新增感官通道**：Bridge 转换 + Gateway 接收
- **Brain 代码**：两种扩展均不需要修改

### 10.5 对现有代码的改动总结

| 文件 / 目录 | 改动内容 | 改动量 |
|-----------|---------|--------|
| `services/nudge/` | 更名为 `services/thread/`；删除 `reminders` 相关代码；Thread 数据模型新增 `trigger` 字段；新增 AI trigger 解析逻辑 | ~改动 40% |
| `dispatch_service.py` | 三类广播 + Geofence 事件转发 | +26 行 |
| `services.yaml` | 服务名 nudge → thread；新增 Brain 服务 | +8 行 |
| `services/brain/` | 新增第⑥工作器 Trigger Monitor | +150 行 |
| `database/` | 废除 reminders 表；threads 表新增 trigger 字段；Brain DB 新增 correction_memory / graph_snapshots 表 | 迁移脚本 |
| `web/src/` | 图谱页（热力图 + 时间透视 + 纠正交互）| 新建 |

---

## 11. Brain 服务规格

### 11.1 服务信息

| 属性 | 值 |
|------|---|
| 端口 | :8003 |
| 技术栈 | Python / FastAPI / APScheduler |
| 数据库 | SQLite + Qdrant + 内存 Active Pool |

### 11.2 API 端点

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `GET /health` | 公开 | 健康检查 |
| `GET /alfred/capabilities` | API-Key | 声明 intent |
| `POST /alfred/execute` | API-Key | 执行 Brain intent |
| `POST /brain/events` | API-Key | 接收三类事件 |
| `POST /brain/geofence` | API-Key | 接收 Geofence 入境事件 → Trigger Monitor |
| `GET /brain/graph/{family_id}` | JWT | 图谱数据（含热度 + lock 过滤）|
| `GET /brain/graph/{family_id}/snapshot/{date}` | JWT | 历史快照 |
| `GET /brain/graph/{family_id}/forecast` | JWT | 未来推演 |
| `GET /brain/weavings/{family_id}` | JWT | Weaving 列表 |
| `POST /brain/weavings/{id}/confirm` | JWT | 显式确认 |
| `POST /brain/weavings/{id}/correct` | JWT | 用户纠正 |
| `GET /brain/active_pool/{family_id}` | JWT | 调试：Active Pool 状态 |
| `GET /brain/emotional_budget/{user_id}` | JWT | 调试：情感预算余量 |
| `GET /brain/active_geofences/{user_id}` | API-Key | 补丁 B：Gateway 查询当前活跃 geofence Thread 及目标坐标，用于初始化心跳频率 |

### 11.3 工作器总览

| 工作器 | 频率 | 核心职责 | 资源上限 |
|--------|------|---------|---------|
| ① Event Processor | 实时 | 三类事件处理，原子锁写 Qdrant | < 500ms |
| ② Semantic Clusterer | 每周 | Active Pool 扫描，双评分 Weaving | 500 节点 |
| ③ Proactive Nudge Generator | 每日 | 隐式激活候选，情感预算过滤 | 1-2 条/日 |
| ④ Decision Arbiter | 实时（前置）| 5 项检查 | < 100ms |
| ⑤ Entropy Reduction | 每月 | 弱关联清理（跳过纠正边）| 50 条/次 |
| ⑥ Trigger Monitor | 实时扫描（每分钟）| 显式触发检测 + 上下文注入 | 每次扫描 < 200ms |

---

## 12. 非功能性需求

### 12.1 隐私与安全
- 向量数据本地存储（Qdrant 自托管）
- Brain 跨用户分析仅限同一 Family
- Kill Switch + 优雅降级
- 私密 Thread 不进入 Qdrant
- USER_CORRECTION 记忆永久保留

### 12.2 性能
- 技能层响应：< 3 秒
- Brain 事件处理：CREATE < 500ms / INVALIDATE < 200ms / USER_CORRECTION < 300ms
- Decision Arbiter：< 100ms
- Trigger Monitor 轮询：每分钟一次（可用消息队列进一步优化）
- 图谱查询：< 200ms
- 历史快照查询：< 500ms
- 动效帧率：≥ 60fps

### 12.3 克制原则
- Nudge 日均上限：4 条（含显式 + 隐式）
- 情感预算：24 小时总消耗 10.0 分
- Brain 每周最多提议 3 个 Weaving
- 拒绝的 Weaving 主题，3 个月内不重提
- Trigger Monitor 生成的 Nudge 不豁免情感预算（但 L2 显式触发有最高优先级，几乎不会被 SUPPRESS）
- 时间透视未来推演最长 30 天
- Sub-threading 的子 Thread 可独立携带触发器，但不额外消耗情感预算

---

## 13. 开放问题与待讨论项

| # | 问题 | 优先级 |
|---|------|-------|
| Q1 | Thread 休眠阈值（建议 7 天，可配置）| 高 |
| Q2 | Ego-centric 节点评分权重（建议 6:4）| 高 |
| Q3 | Kill Switch 断开时 UI 细节 | 高 |
| Q4 | 卫星节点阈值（0.85 待 A/B 测试）| 高 |
| Q5 | ✅ WhatsApp Onboarding | 已解决 |
| Q6 | Geofence 半径（建议 500m）| 中 |
| Q7 | Sub-thread 拆解主导权 | 中 |
| Q8 | Brain 每周 Weaving 提议上限（建议 3 个）| 中 |
| Q9 | Brain 的 Qdrant：与 Thread 服务共用实例还是独立？| 中 |
| Q10 | ✅ Persona 冷启动脚本 | 已解决 |
| Q11 | Brain 提议 Weaving 时，如何让用户轻松修改标题？| 中 |
| Q12 | 跨技能关联边（金色）密度控制 | 低 |
| Q13 | Spark 状态的定义和生命周期 | 低 |
| Q14 | Active Pool 容量上限（建议 1000）及 30 天冷热边界 | 中 |
| Q15 | Intent Vector 冷启动期默认值；goal_alignment 如何在无明确长期目标时计算？| 中 |
| Q16 | 熵减弱边阈值（< 0.15 + 6 个月）是否过于激进？| 低 |
| Q17 | 情感预算初始值（10.0）和各级消耗值是否合理？Kelly / Richard 是否应有不同上限？| 中 |
| Q18 | 静默确认的 30 分钟超时窗口；WhatsApp 端如何告知「不回复即同意」？| 中 |
| Q19 | Trigger Monitor 每分钟轮询是否足够实时？是否需要引入消息队列（如 Redis）优化时间精度？| 中 |
| Q20 | recurring Thread 的 cron 表达式由 AI 自动生成，误解率如何？是否需要可视化 cron 编辑器辅助确认？| 中 |

---

## 14. 版本路线图

### v0.1–v0.8 ✓（已完成，设计封存）

### v0.9 ✓ — Thread-Centric 架构重构（当前）
- [x] Unified Thread 对象模型（`trigger` 字段，废除独立 Reminder）
- [x] Nudge 技能更名为 Thread 技能，职责精确化
- [x] Brain 第⑥工作器：Trigger Monitor（显式激活 + 上下文注入）
- [x] 数据迁移方案（reminders → threads.trigger）
- [x] Qdrant threads_routine 含义扩展
- [x] APScheduler 引入（定时任务统一管理）

---

### 🏁 v1.0 — MVP 最小闭环（下一个实施里程碑）

**目标：在图谱上出现第一根金色的线**

```
「特斯拉最近保养费越来越贵了」
  ↓ Thread 技能保存（trigger.type = none，category = life）
  ↓ 感官层广播 CREATE 事件
  ↓ Brain Event Processor → Qdrant → Active Pool
  ↓ Brain 发现 OurCents「特斯拉保养 ¥3200」记录
    Intent 点积 > 0.7，Fact Cosine > 0.72 ✓
  ↓ Decision Arbiter 通过，情感预算充足
  ↓ Brain 提议 Weaving：[特斯拉用车成本]
  ↓ Web 端：两个节点之间，连出一根金色的线
```

**v1.0 实施任务清单：**
- [ ] Unified Thread CRUD（含 trigger 字段）+ WhatsApp Bot 基础版
- [ ] AI trigger 解析（gpt-4o-mini，识别四种 trigger.type）
- [ ] 今日卡片视图 + 基础热力图
- [ ] Persona Profile 冷启动（Kelly Implicit Ack 开启）
- [ ] Ego-centric 图谱（含卫星节点）
- [ ] **Brain 基础版**：Event Processor + Qdrant + Active Pool + 原子锁
- [ ] **Trigger Monitor 基础版**：once / recurring 两种类型（geofence 推后）
- [ ] **Decision Arbiter 基础版**：密度 + Kill Switch + 情感预算（三项检查）
- [ ] **最小 Weaving 闭环**：Thread ↔ OurCents 跨技能金色线
- [ ] Qdrant 本地 Docker 部署

### v1.1 — AI 编织核心
- [ ] Semantic Clusterer（每周聚类 + Weaving 提议）
- [ ] Decision Arbiter 完整版（语义冲突 + 纠正历史过滤）
- [ ] 静默确认完整实现
- [ ] USER_CORRECTION 逆向编织 + 负样本记忆
- [ ] Intent Vector 三维完整标注（告别冷启动默认值）
- [ ] Trigger Monitor：geofence 触发支持
- [ ] WhatsApp 语音录入

### v1.2 — 情感与干预层
- [ ] 情感总线 + Kill Switch + 优雅降级
- [ ] 记忆回溯（晨间 Nudge）
- [ ] Sub-threading + 多米诺动效
- [ ] 心愿单 + 关联激励
- [ ] Proactive Nudge Generator（每日主动推送）
- [ ] INVALIDATE_EVENT 级联失效完整实现
- [ ] Entropy Reduction 熵减进程
- [ ] 时间透视（历史回放 + 未来推演）

### v1.3 — 空间与跨技能层
- [ ] Geofencing 完整实现（Trigger Monitor geofence 类型）
- [ ] 跨技能三角 Weaving（Thread ↔ OurCents ↔ recurring Thread）
- [ ] 家庭知识库 Web UI（热力图完整版）
- [ ] 规律统计学习

### v1.4 — 完整体验
- [ ] 规律预测模型（时序 AI）
- [ ] 移动端原生 App
- [ ] 动态阈值个性化（贝叶斯）
- [ ] Health 技能接入（Apple Health）
- [ ] Health × Emo Thread 跨技能 Weaving（压力感 × 血压读数）

---

*本文档为活文档，随产品讨论持续迭代。*  
*v0.9 完成了从 v0.1 到今天的最后一次底层对象模型重构。核心对象只有一个：Thread。*  
*v1.0 的任务只有一个：让一根金色的线，出现在图谱上。*
