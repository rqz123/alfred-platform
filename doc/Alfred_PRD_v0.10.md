# Alfred — 产品需求文档（PRD）

**版本：** v0.11 Draft  
**日期：** 2026-05-11  
**作者：** Richard  
**状态：** ✅ **设计封版** · 前端与分析层现代化 + 架构战略留白版

**变更摘要（v0.9 → v0.10）：**
- **[M8] User Expansion Layer（用户扩展层）** *(v0.10 核心新增)*
  - 管理员主导的邀请流程：WhatsApp 发送「邀请 [姓名]」→ Alfred 返回邀请卡 → 管理员转发给新用户
  - 邀请令牌握手：Token 时效 7 天，Gateway 解析器识别 `(Token:XXXX)` 格式，完成身份绑定
  - `invite_tokens` 数据表（Gateway SQLite 层新增）
  - `wa.me` 深链接标准格式规范
  - Shared Weaving as Entry Hook：新用户入场时即见第一条家庭图谱上下文
- **[Thread ACL] 线索访问控制列表**
  - Unified Thread 新增 `acl` 字段：`tier: family_private | shared | user_private`
  - `created_by` + `visible_to` 字段，支持跨用户可见性精细控制
- **[Onboarding 参数化] 冷启动脚本模板化**
  - 移除硬编码「Kelly」/「Richard」，改为 `{{user_name}}` / `{{admin_name}}` 模板变量
  - 适用于任意新用户的 Onboarding 渲染
- **[Section 3] 用户模型泛化**
  - 目标用户从「Richard + Kelly」扩展为「管理员 + 受邀用户」通用模型

**变更摘要（v0.10 → v0.11）：**
- **[架构留白 A] NATS JetStream 预留位**：v1.0 维持 Webhook，但所有事件 Payload 结构提前适配 NATS Subject 命名规范，升级时只换通信模块
- **[架构留白 B] LangGraph 局部化**：明确作用域仅为 Proactive Nudge Generator + Semantic Clusterer 内部推演子任务；Trigger Monitor / Entropy Reduction 等确定性工作器不引入
- **[分析引擎分层] DuckDB**：OurCents 技能层引入 DuckDB 作为 OLAP 分析引擎，SQLite 保留 OLTP 事务写入
- **[前端现代化] React Flow + PWA**：图谱视图从纯 D3.js 迁移至 React Flow；Web 端构建为 PWA，新增 Web Push 作为 WhatsApp 之外的第二 Nudge 通道
- **[M8 补丁] Shadow User 身份对齐**：管理员邀请时展示「待关联实体」清单（从历史 Thread 提取的影子节点），确认后新用户入场即继承关联认知
- **[ACL 修订] 共享热度关联**：废弃「私密晋升」，改为检测共享 Thread 上的跨用户互动热度，Brain 据此提议更深层 Weaving，不触碰 `user_private` 节点
- **[Decision Arbiter 第⑥检查] Observer Mode**：Gateway 流量传感器——检测到家庭密集对话时，Brain 自动冻结非紧急 Nudge，体现「懂进退」的管家礼仪

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
9. [M8 用户扩展层](#9-m8-用户扩展层)
10. [技术架构](#10-技术架构)
11. [Alfred 三层架构](#11-alfred-三层架构)
12. [Brain 服务规格](#12-brain-服务规格)
13. [非功能性需求](#13-非功能性需求)
14. [开放问题与待讨论项](#14-开放问题与待讨论项)
15. [版本路线图](#15-版本路线图)

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
- **信任通过邀请建立。** 新用户通过管理员的引荐进入图谱，不是自注册——这是家庭场景的天然门槛。
- **基础设施先行，LLM 编排局部化，隐私边界物理化。** 确定性逻辑不引入 LLM，私密数据不进跨用户查询，消息通信接口提前适配异步架构。

### 2.2 语言规范

| ❌ 禁止使用 | ✅ 使用替代 |
|-----------|-----------|
| 拖延指数 | 动能（Momentum）|
| 你在拖延 | 当前动能较低 |
| 记录任务 | 把线索缝起来 |
| 操作层 / 智能层 | 感官 / 技能 / 大脑 |
| 设置提醒 | 给这条线索加个触发器 |
| Reminder（服务）| Thread（Unified）|
| 注册账号 | 加入家庭图谱 |
| 邀请链接 | 引荐入口（邀请卡）|

---

## 3. 目标用户

### 3.1 通用角色模型（v0.10 泛化）

Alfred 的家庭场景以「管理员」为核心，通过引荐机制扩展「受邀用户」。每个 Family 有且仅有一位管理员，受邀用户数量不限。

| 角色 | 权限 | 入场方式 |
|------|------|---------|
| **管理员（Admin）** | 完整读写；可邀请新用户；可管理 ACL；可删除 Family 级内容 | 系统初始化时创建 |
| **受邀用户（Invited User）** | 读写自己的 Thread；按 ACL 阅读共享 Thread；不可邀请他人（默认）| 管理员生成邀请卡 → 接受邀请 |

### 3.2 当前实例（Richard + Kelly）

| 属性 | Richard（管理员）| Kelly（受邀用户）|
|------|----------------|----------------|
| 角色 | Admin | Invited User |
| 核心输入界面 | Web 看板 | WhatsApp（首选）|
| 启动阻力 | 低 | 高（需动能积累策略）|
| 对「被管理」的感受 | 中性 | **高度敏感，易产生防御**|
| Weaving 确认方式 | 显式点击确认 | 静默确认（Implicit Ack）优先 |
| Persona 特殊设定 | — | `implicit_ack_enabled = true` |

> **设计原则：** Section 3.2 只是一个当前实例，Alfred 的代码和 Onboarding 脚本不应硬编码任何个人名字。所有姓名通过模板变量 `{{user_name}}` / `{{admin_name}}` 在运行时注入。

---

## 4. 核心概念定义

### 4.1 三类对象的关系

```
Thread（线索）      ─── 是 ───→  Brain 的原材料（节点）
Weaving（编织）     ─── 是 ───→  Brain 建立的关系（边）
Nudge（激活）       ─── 是 ───→  Brain 的输出行为（唤醒一条 Thread 及其上下文）
```

**Thread 是唯一的输入对象。** 它可以是静态的（无触发器），也可以是动态的（带时间 / 空间 / 循环触发器）。两者在 Brain 眼中是同等的认知节点，可以被编织，可以被激活。

### 4.2 Unified Thread（统一线索）*(v0.9 核心重构，v0.10 新增 ACL)*

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
    "ack_status": "pending",  // pending | firing | awaiting | acknowledged | snoozed | dismissed | expired
    "ack_timeout_at": null    // awaiting 状态的超时时间（默认触发后 2 小时）
  },

  "acl": {
    "tier": "shared",              // family_private | shared | user_private
    "created_by": "richard",       // 创建者 user_id
    "visible_to": []               // 空数组 = 全体家庭成员（适用于 family_private / shared）
                                   // 指定数组 = 仅对列出的 user_id 可见（user_private）
  },

  "vectors": {
    "fact": [0.12, -0.34, "..."],  // 事实向量（由 Embedding 生成）
    "intent": {
      "urgency": 0.85,
      "social_bond": 0.3,
      "goal_alignment": 0.7
    }
  },

  "tags": ["季度复盘", "项目管理"]
}
```

**acl.tier 三档可见性：**

| 档位 | 可见范围 | 可编辑范围 | 典型使用场景 |
|------|---------|----------|------------|
| `family_private` | 全体家庭成员 | 全体家庭成员 | 共同计划、家庭事项 |
| `shared` | 全体家庭成员 | 仅创建者 | 个人想法共享、不希望被他人修改 |
| `user_private` | 仅 `visible_to` 列表 | 仅创建者 | 礼物策划、私人日记、敏感事项 |

**默认行为：**
- 新建 Thread 默认为 `shared`
- 用户可在录入时或录入后修改 `acl.tier`
- Brain 的 Semantic Clusterer 编织时：`user_private` Thread 仅对创建者本人展示 Weaving；跨用户 Weaving 只使用 `family_private` / `shared` 级别的 Thread

**trigger.ack_status 完整状态机：**

```
pending           等待触发（trigger 条件尚未满足）
  │
  │ [补丁 D] 原子写入 firing，防重复发送
  ▼
firing            事务保护态（极短暂，不暴露给用户）
  │ Nudge 发送成功 → awaiting
  │ Nudge 发送失败 → 回滚至 pending
  ▼
awaiting          已响铃，等用户接（Nudge 在 WhatsApp 上等着）
  │ ack_timeout_at = now + 2h
  │
  ├─▶ acknowledged   用户主动回应（「好的」「知道了」）
  │     ├─ once:      触发器完成 → 终态
  │     └─ recurring: croniter 计算下次 → pending
  │
  ├─▶ snoozed        用户主动推迟（「等下」「30 分钟后再说」）
  │     │             snooze_count++，fire_at = now + snooze_delay
  │     └─▶ pending  重新进入等待
  │
  ├─▶ dismissed      用户主动取消（「不用了」「关掉」）
  │     ├─ once:      终态
  │     └─ recurring: 停止循环，除非用户重新启用
  │
  └─▶ expired        超时无响应（ack_timeout_at 到达，系统自动判定）
        │             ≠ snoozed：用户没有表态，系统不能替用户 snooze
        ├─ once:      触发器失效，Brain 稍后发 L1 询问
        └─ recurring: croniter 计算下次触发 → pending（不打扰）
```

**geofence 类型的 expired 判定：** 用户离开围栏区域且未响应 → `expired`（无需 ack_timeout_at）

**trigger.type 四种类型：**

| 类型 | 含义 | 示例 |
|------|------|------|
| `none` | 纯静态线索，无时空触发 | 「Kelly 想买绿植」|
| `once` | 一次性时间触发 | 「明天下午 2 点开会」|
| `recurring` | 循环触发（cron 表达式）| 「每周日检查阳台植物」|
| `geofence` | 进入某地理区域触发 | 「到药店提醒买感冒药」|

### 4.3 Weaving（编织关系）

> Thread 合并后，Brain 面对的是统一的 Context Pool，Weaving 质量提升——带触发器的 Thread（如「量血压」的循环 Thread）与静态 Thread（如「最近压力大」）可以直接被编织，不再被隔离在不同的对象类型中。

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

  // 静默确认的权重累积规则（补丁 E）
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
- **管理员指令**：`邀请 [姓名]` 命令由 Gateway 拦截，触发 M8 邀请流程（详见 Section 9）

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
    "acl_tier": "shared",
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
层级三：节点详情视图（含 trigger 状态 + ACL 标识 + Weaving 关联列表）
```

### 6.2 家庭图谱视图

- 带触发器的节点与静态节点共同出现在图谱中，视觉区分仅靠图标
- Brain 发现「量血压（recurring Thread）」与「最近压力大（emo Thread）」有 Weaving，两者之间显示编织关联边
- 家庭健康度指示：Brain 每日计算图谱状态，看板顶部可视化
- `user_private` Thread：图谱上对非授权用户**不可见**，不渲染节点，不渲染关联边

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
2. **建立图谱**：在 Qdrant 中维护家庭认知图谱（Unified Thread 全量，按 ACL 过滤查询结果）
3. **发现洞察**：分析 Active Pool，发现 Weaving 机会
4. **监控触发器**：扫描待触发的 Thread，条件满足时激活并发出上下文丰富的 Nudge
5. **仲裁推送**：所有 Nudge（显式 + 隐式）经 Decision Arbiter + 情感预算双重过滤
6. **接受纠正**：USER_CORRECTION 作为最高权重负反馈更新认知
7. **维护图谱健康**：熵减进程清理弱关联

### 7.2 Brain 的六个后台工作器

**① 事件处理器（Event Processor）— 实时**
- 处理 CREATE / INVALIDATE / USER_CORRECTION 三类事件
- CREATE：双向量解析 → Qdrant 写入（原子锁）→ Active Pool
- INVALIDATE：标记 `needs_reweave`
- USER_CORRECTION：权值归零 → 负样本记忆 → 撤销关联 Nudge

**② 语义聚类器（Semantic Clusterer）— 每周**
- 仅扫描 Active Pool，Intent Vector 点积 + Fact Cosine 双重评分
- 点积 > 0.7 且 Fact Cosine > 分类阈值 → 生成 Weaving 提议
- 跨用户 Weaving 仅基于 `shared` / `family_private` 级别的 Thread
- 提议通过 Decision Arbiter 审核后推送用户

**③ 主动 Nudge 生成器（Proactive Nudge Generator）— 每日**
- 分析 Active Pool 状态，生成隐式激活候选
- 经 Decision Arbiter + 情感预算过滤，每日最多 1-2 条送达

**④ 决策仲裁器（Decision Arbiter）— 实时，前置于所有推送**

```python
OBSERVER_MODE_THRESHOLD = 10  # 5 分钟内超过此消息数，进入观察者模式

async def arbitrate(candidate_nudge, family_id):
    # 检查 1：时间窗口密度
    recent_nudges = await nudge_log.count_recent(family_id, window_minutes=60)
    if recent_nudges >= NUDGE_DENSITY_LIMIT:
        return DEFER

    # 检查 2：情感预算（扣除对应消耗值）
    budget = await get_emotional_budget(candidate_nudge.user_id)
    if budget < candidate_nudge.emotional_weight:
        return DOWNGRADE_TO_SILENT if candidate_nudge.level == "L2" else SUPPRESS

    # 检查 3：语义冲突（合并或丢弃矛盾 Nudge）
    conflict = await detect_semantic_conflict(candidate_nudge, family_id)
    if conflict:
        return RESOLVE_CONFLICT

    # 检查 4：情绪负载（Kill Switch / momentum < 0.2 时转为情感类）
    persona = await get_persona(candidate_nudge.user_id)
    if persona.momentum_score < 0.2:
        return CONVERT_TO_EMOTIONAL

    # 检查 5：USER_CORRECTION 历史（基于纠正过的关联的 Nudge → SUPPRESS）
    if await has_correction_conflict(candidate_nudge, family_id):
        return SUPPRESS

    # 检查 6：Observer Mode — 家庭密集对话时，冻结非紧急 Nudge（v0.11 新增）
    traffic = await gateway_client.get_recent_traffic(family_id, window_minutes=5)
    if traffic.message_count >= OBSERVER_MODE_THRESHOLD:
        if candidate_nudge.level not in ("L3", "L4"):  # 仅 L3/L4 冲突预警和情感深度可穿透
            return DEFER  # 延迟至流量平息后重试，不直接丢弃

    return APPROVED
```

> **Observer Mode 设计原则：** 进入观察模式不代表 Nudge 被丢弃，而是进入「等待下一个静默窗口」队列。Gateway 每 60 秒向 Brain 汇报流量状态；当 5 分钟窗口内消息数降至阈值以下，队列中被 DEFER 的 Nudge 按优先级重新进入仲裁流程。L3/L4 级别（冲突预警 / 情感深度）不受 Observer Mode 限制，因为这类 Nudge 的时效性高于「不打扰」原则。

| 仲裁结果 | 含义 |
|---------|------|
| `APPROVED` | 立即推送 |
| `DEFER` | 延迟（等待静默窗口）|
| `SUPPRESS` | 丢弃 |
| `CONVERT_TO_EMOTIONAL` | 任务语气 → 关怀语气 |
| `RESOLVE_CONFLICT` | 合并冲突 Nudge |
| `DOWNGRADE_TO_SILENT` | 降级为静默提醒 |

**⑤ 熵减进程（Entropy Reduction）— 每月**
- 清理权值 < 0.15 且超 6 个月未激活的弱关联边
- 跳过用户纠正边（永久保留）
- 双端归档的边直接清理；半活跃边推送用户确认

**⑥ Trigger Monitor（触发器监控）— 实时扫描**

```python
async def on_startup():
    """
    补丁 A：服务启动时执行漏发检查（Misfire Handling）
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
            # 【补丁 H】断线补课语气标记 — late=True 时，Nudge 消息前附加补课说明
            # build_contextual_nudge() 检测 late=True 时，在正文前插入：
            # 「（抱歉，我刚才短暂离线，现在补上这个提醒）」
            await enqueue_trigger(thread, late=True)
        elif delay <= timedelta(hours=2):
            await schedule_misfire_inquiry(thread)
        else:
            await db.update_thread_trigger_status(thread.thread_id, ack_status="expired")
            if thread.trigger_type == "once":
                await schedule_expiry_followup(thread, delay_minutes=30)
            elif thread.trigger_type == "recurring":
                next_fire = croniter(thread.trigger_cron).get_next(datetime)
                await db.update(thread.thread_id,
                                trigger_fire_at=next_fire, ack_status="pending")


async def run_trigger_monitor():
    """每分钟运行一次"""
    due_threads = await db.query("""
        SELECT * FROM threads
        WHERE trigger_type IN ('once', 'recurring')
        AND trigger_ack_status = 'pending'
        AND trigger_fire_at BETWEEN NOW() AND NOW() + INTERVAL '5 minutes'
    """)
    geofence_threads = await get_pending_geofence_activations()

    for thread in due_threads + geofence_threads:
        # 补丁 D：原子写入 firing 状态，防止多线程重复发送
        updated = await db.atomic_update(
            table="threads",
            where={"thread_id": thread.thread_id, "trigger_ack_status": "pending"},
            set={"trigger_ack_status": "firing"}
        )
        if not updated:
            continue

        try:
            weavings = await qdrant.get_weavings_for_thread(
                thread.thread_id, min_weight=0.3, limit=3
            )
            nudge = await build_contextual_nudge(thread, weavings)
            result = await arbitrate(nudge, thread.family_id)
            if result == APPROVED:
                await push_to_gateway(nudge)
                await db.update_thread_trigger_status(
                    thread.thread_id,
                    ack_status="awaiting",
                    ack_timeout_at=now() + timedelta(hours=2)
                )
            else:
                await db.update_thread_trigger_status(thread.thread_id, ack_status="pending")
        except Exception:
            await db.update_thread_trigger_status(thread.thread_id, ack_status="pending")

    # 补丁 B：自适应地理心跳
    await update_geofence_heartbeat()
```

**补丁 H：断线补课语气规范（build_contextual_nudge late 模式）**

```python
async def build_contextual_nudge(thread: Thread, weavings: list,
                                  recipient_user_id: str,
                                  late: bool = False) -> Nudge:
    """
    构建富上下文 Nudge。
    late=True（补课模式）：在正文前插入断线说明，不影响 Weaving 上下文内容。
    """
    late_prefix = (
        "（抱歉，我刚才短暂离线，现在补上这个提醒）\n\n"
        if late else ""
    )

    context_threads = []
    for w in weavings:
        related = await db.get_thread(w.related_thread_id)
        if is_visible(related, recipient_user_id):
            context_threads.append(related)

    body = await ai_compose_nudge(thread, context_threads)
    return Nudge(content=late_prefix + body, level=thread.nudge_level, ...)
```

> 补课语气刻意使用第一人称「我」和「抱歉」——这不是系统错误，而是 Alfred 在承认自己的缺席，维持了「管家有温度」的人设。

**补丁 B：自适应地理心跳（Adaptive Geofence Heartbeat）**

```python
async def update_geofence_heartbeat():
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

        if min_distance < 500:
            heartbeat_interval = 30
        elif min_distance < 1000:
            heartbeat_interval = 60
        elif min_distance < 5000:
            heartbeat_interval = 180
        else:
            heartbeat_interval = 300

        await gateway_client.set_location_heartbeat(user_id, heartbeat_interval)
```

Brain 同时暴露只读端点：`GET /brain/active_geofences/{user_id}`，返回该用户当前所有待触发的 geofence Thread 及目标坐标，Gateway 据此初始化心跳参数。

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
timed_out = await db.query("""
    SELECT * FROM threads
    WHERE trigger_ack_status = 'awaiting'
    AND ack_timeout_at < NOW()
""")
for thread in timed_out:
    await db.update_thread_trigger_status(thread.thread_id, ack_status="expired")
    if thread.trigger_type == "recurring":
        next_fire = croniter(thread.trigger_cron).get_next(datetime)
        await db.update(thread.thread_id, trigger_fire_at=next_fire, ack_status="pending")
    elif thread.trigger_type == "once":
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
    → 附加 Weaving 上下文（按 ACL 过滤）
    → Decision Arbiter（可转情感类 / 降级静默）
    → Gateway → 用户

  隐式触发：Brain 发现洞察
    → Proactive Nudge Generator
    → Decision Arbiter
    → Gateway → 用户

Weaving 建立：
  → Semantic Clusterer（Active Pool，ACL 过滤跨用户数据）
    → Intent 点积 + Fact Cosine 双重评分
    → Weaving 提议 → Decision Arbiter → 用户确认
    → 显式确认 / 静默确认 → confirmed
    → 用户断开 → USER_CORRECTION → 负样本记忆

维护：
  → 30 天无激活 → Archive Pool（热力图冷却）
  → 每月熵减 → 弱关联边清理（跳过纠正边）
```

---

## 8. Onboarding 设计

> **v0.10 更新：** 本节所有脚本已参数化，移除硬编码用户名。`{{user_name}}` 在渲染时替换为受邀用户的真实姓名，`{{admin_name}}` 替换为邀请者的姓名。
>
> 当前实例：`{{user_name}} = Kelly`，`{{admin_name}} = Richard`。

### 8.1 Persona 冷启动脚本（通用版）

**Step 1：建立连接**
```
「嘿 {{user_name}} 👋 我是 Thread。
{{admin_name}} 把我安在这里，说你是他们家的生活大导演——
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
点一下，我就隐身了。不通知 {{admin_name}}，不留痕迹。

你是这里的主人，我只是那根帮你缝线索的线 🪡」
```

### 8.2 24 小时旅程

| 时间点 | 动作 |
|--------|------|
| T+0 | 冷启动脚本（四步）|
| T+1h | 引导发送第一条 Thread，立即图谱反馈 |
| T+8h | 第一次「隐形编织」Aha! 时刻（跨 Thread Weaving）|
| T+24h | 动能复盘，正向收尾 |

**如果入场时附带了 Weaving Entry Hook（见 Section 9.7）：**

| 时间点 | 动作 |
|--------|------|
| T+0 | 冷启动脚本（四步）|
| T+0 (尾部) | 渲染 Entry Hook Weaving：「{{admin_name}} 想让你第一眼看到这个...」|
| T+1h | 引导发送第一条 Thread |
| T+8h | Aha! 时刻（新用户的第一条 Thread 与 Entry Hook 产生 Weaving）|

### 8.3 成功指标

| 指标 | 目标 |
|------|------|
| 冷启动完成率 | > 80% |
| T+1h 首条录入率 | > 70% |
| T+8h Aha! 体验率 | > 60% |
| D7 留存率 | > 50% |

### 8.4 静默确认（Implicit Ack）

- 适用对象：`implicit_ack_enabled = true` 的用户（Kelly 默认开启；新用户由管理员在邀请时配置，默认关闭，完成 Onboarding 后可自行开启）
- 触发条件：L1/L2 Weaving 提议 + 30 分钟内无反对 + 用户继续活跃
- 不适用：L3/L4 提议 / 跨技能 Weaving 首次创建 / 涉及修改已有 Weaving
- 撤销窗口：24 小时内可说「刚才那个取消」→ Brain 执行 USER_CORRECTION

---

## 9. M8 用户扩展层

### 9.1 设计动机

Alfred 是一个「家庭」产品——Brain 以 Family 为作用域，认知图谱的价值随参与人数而增加。v0.9 只支持 Richard 一个管理员和 Kelly 一个伴侣，是硬编码的双人模式。

M8 的目标是让任何家庭都可以通过管理员引荐机制，安全、低摩擦地扩展到多个成员（亲友、家庭成员、看护等），同时保持图谱的私密性边界。

**核心设计原则：**
- **入场必须经由管理员引荐**，不开放自注册
- **邀请流程最短路径**：管理员一句话发出邀请，Alfred 返回卡片，管理员转发给新用户
- **新用户入场即有上下文**：可选择附带一条 Weaving 作为「入场礼」

### 9.2 邀请流程（Admin-Forwarded Invite Card）

```
┌─────────────────────────────────────────────────────────┐
│  管理员端（Admin WhatsApp）                               │
│                                                         │
│  1. Admin → Alfred："邀请 Sarah"                         │
│                                                         │
│  2. Alfred 生成令牌，返回邀请卡给 Admin：                  │
│     [卡片内容见 Section 9.4]                             │
│                                                         │
│  3. Admin 将卡片转发给 Sarah（任意渠道：                   │
│     WhatsApp / 微信 / 短信 / Email 均可）                 │
└──────────────────────────┬──────────────────────────────┘
                           │ 转发
                           ▼
┌─────────────────────────────────────────────────────────┐
│  新用户端（Sarah WhatsApp）                               │
│                                                         │
│  4. Sarah 点击卡片中的 wa.me 深链接，或手动将卡片中的      │
│     「发送这条消息给 Alfred」文本发送给 Alfred             │
│                                                         │
│  5. Alfred 收到含 (Token:ALFRED-XXXXXX) 的消息           │
│     → Gateway Token 解析器识别 → 身份绑定                 │
│     → 触发参数化 Onboarding（{{user_name}} = Sarah,      │
│       {{admin_name}} = Richard）                         │
└─────────────────────────────────────────────────────────┘
```

**指令识别规则（Gateway 侧）：**
```python
INVITE_COMMAND_PATTERN = re.compile(r'^邀请\s+(.+)$')

async def handle_admin_command(user_id, message_text, family_id):
    match = INVITE_COMMAND_PATTERN.match(message_text.strip())
    if match and is_admin(user_id, family_id):
        invitee_name = match.group(1).strip()
        await generate_invite_card(
            admin_id=user_id,
            family_id=family_id,
            invitee_name=invitee_name
        )
        return True
    return False
```

### 9.3 invite_tokens 数据表

> 新增至 Gateway SQLite，与 `alfred_users` / `families` 同库。

```sql
CREATE TABLE invite_tokens (
    token_id        TEXT PRIMARY KEY,       -- 格式：ALFRED-{6位大写字母数字}，如 ALFRED-A7X3K2
    family_id       TEXT NOT NULL,
    created_by      TEXT NOT NULL,          -- 管理员 user_id
    invitee_name    TEXT NOT NULL,          -- 管理员指定的被邀请者姓名
    status          TEXT DEFAULT 'pending', -- pending | used | expired
    weaving_hook_id TEXT,                   -- 可选：入场时携带的 Weaving ID（Entry Hook）
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME NOT NULL,      -- 默认：created_at + 7 天
    used_at         DATETIME,               -- 被使用的时间戳
    used_by_user_id TEXT,                   -- 实际注册的用户 user_id

    FOREIGN KEY (family_id) REFERENCES families(family_id),
    FOREIGN KEY (created_by) REFERENCES alfred_users(user_id)
);

CREATE INDEX idx_invite_tokens_status ON invite_tokens(status, expires_at);
```

**令牌生成规则：**
```python
import secrets, string

def generate_invite_token() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(alphabet) for _ in range(6))
    return f"ALFRED-{suffix}"  # e.g., ALFRED-A7X3K2
```

### 9.4 邀请卡设计

Alfred 返回给管理员的消息（管理员直接转发给新用户）：

```
🛡️ Alfred 家居管家 · 引荐

{{admin_name}} 在用 Alfred 管理家里的事，
想邀请你加入这个家庭的认知图谱。

你的专属入口 👇
https://wa.me/{{bot_number}}?text=Hi%20Alfred%2C%20joining%20{{admin_name_encoded}}%27s%20family.%20(Token%3A{{token_id}})

或者把下面这句话发给 Alfred：
「Hi Alfred, joining {{admin_name}}'s family. (Token:{{token_id}})」

有效期：7 天（截止 {{expires_at_date}}）

📌 提示：Alfred 不储存你的私人信息。
你随时可以断开连接，{{admin_name}} 不会收到通知。
```

**渲染参数说明：**

| 模板变量 | 值 | 示例 |
|---------|---|------|
| `{{admin_name}}` | 管理员姓名 | Richard |
| `{{admin_name_encoded}}` | URL 编码后的管理员姓名 | Richard |
| `{{bot_number}}` | Alfred WhatsApp Bot 号码 | +1xxxxxxxxxx |
| `{{token_id}}` | 生成的令牌 | ALFRED-A7X3K2 |
| `{{expires_at_date}}` | 到期日期（人类可读）| 2026-05-18 |

**wa.me 深链接完整格式：**
```
https://wa.me/{{bot_number}}?text=Hi%20Alfred%2C%20joining%20{{admin_name_encoded}}%27s%20family.%20(Token%3A{{token_id}})
```

### 9.5 Gateway Token 解析器更新

```python
import re

TOKEN_PATTERN = re.compile(r'\(Token:([A-Z0-9\-]+)\)')

async def handle_incoming_message(sender_id, message_text, family_id=None):
    """
    Gateway 主消息处理入口。
    在所有其他逻辑之前，先检查是否为邀请令牌激活消息。
    """
    token_match = TOKEN_PATTERN.search(message_text)
    if token_match:
        token_id = token_match.group(1)
        invite = await db.get_invite_token(token_id)

        if not invite:
            await send_message(sender_id, "这个邀请码不存在，请向管理员重新获取。")
            return

        if invite.status == 'expired' or invite.expires_at < now():
            await db.update_invite_status(token_id, 'expired')
            await send_message(sender_id, "这个邀请码已过期，请让管理员重新生成一个。")
            return

        # 【补丁 G】原子写入单次失效 — 防止群组转发场景下多人同时激活同一 Token
        # 使用数据库 CAS（Compare-And-Swap），只有成功将 pending → used 的请求才继续
        # 第二个点击的人得到的是 status='used' 的记录，直接拒绝
        claimed = await db.atomic_update(
            table="invite_tokens",
            where={"token_id": token_id, "status": "pending"},
            set={"status": "used", "used_at": now(), "used_by_user_id": sender_id}
        )
        if not claimed:
            # Token 在极短时间内被另一个请求抢先激活（竞争失败）或已使用
            await send_message(sender_id,
                "这个邀请码已经被使用了。如果你已经加入，直接和我说话就好 😊\n"
                "如果还没有，请让管理员重新生成一个专属给你的邀请码。")
            return

        # 原子写入成功 → 令牌物理失效，继续 Onboarding
        await activate_invite(sender_id=sender_id, invite=invite)
        return

    # 非令牌消息：走正常处理流程
    await route_message(sender_id, message_text, family_id)


async def activate_invite(sender_id: str, invite: InviteToken):
    """
    完成用户身份绑定，并启动参数化 Onboarding。
    """
    # 1. 创建或关联用户记录
    user = await db.get_or_create_user(sender_id, family_id=invite.family_id)
    await db.update_user_role(user.user_id, role='invited_user')

    # 2. 标记令牌为已使用
    await db.update_invite_token(invite.token_id,
        status='used',
        used_at=now(),
        used_by_user_id=user.user_id
    )

    # 3. 获取管理员姓名
    admin = await db.get_user(invite.created_by)

    # 4. 触发参数化 Onboarding
    await trigger_onboarding(
        user_id=user.user_id,
        template_vars={
            "user_name": invite.invitee_name,
            "admin_name": admin.display_name
        },
        weaving_hook_id=invite.weaving_hook_id  # 可能为 None
    )

    # 5. 通知管理员
    await send_message(
        admin.sender_id,
        f"✅ {invite.invitee_name} 已接受邀请，正在完成接入。"
    )
```

### 9.6 Thread ACL（访问控制列表）

> ACL 字段已在 Section 4.2 的 Unified Thread 数据模型中定义。本节补充 ACL 的执行规则。

**Brain 查询时的 ACL 过滤：**

```python
async def get_threads_for_brain(family_id: str, requesting_user_id: str) -> list[Thread]:
    """
    Brain 获取 Active Pool 节点时，只返回对该用户可见的 Thread。
    用于 Semantic Clusterer 和 Proactive Nudge Generator。
    """
    all_threads = await db.query("""
        SELECT * FROM threads
        WHERE family_id = :family_id
        AND status = 'active'
    """, family_id=family_id)

    return [t for t in all_threads if is_visible(t, requesting_user_id)]


def is_visible(thread: Thread, user_id: str) -> bool:
    tier = thread.acl.tier
    if tier == 'family_private':
        return True  # 全家可见
    if tier == 'shared':
        return True  # 全家可见（写操作另行检查）
    if tier == 'user_private':
        return (user_id == thread.acl.created_by
                or user_id in thread.acl.visible_to)
    return False
```

**【补丁 F】Weaving 交集可见性原则（Intersection Rule）**

> **核心安全规则：** Weaving 节点的可见性 = 所有构成该编织的 Thread 之访问权限的**交集**。只要编织中包含一个对某用户不可见的 Thread，该用户在图谱上完全看不到这整个 Weaving 节点及其摘要。这是隐私保护的最后一道物理屏障——防止「智能关联」成为隐私泄露的侧信道。

```python
def is_weaving_visible(weaving: Weaving, requesting_user_id: str,
                        thread_cache: dict[str, Thread]) -> bool:
    """
    交集可见性：编织中任意一个 Thread 不可见 → 整个 Weaving 不可见。
    Fail-closed 原则：宁可少显示，不可泄露。

    thread_cache: 预加载的 Thread 对象字典，避免 N+1 查询。
    """
    for thread_id in weaving.source_thread_ids:
        thread = thread_cache.get(thread_id)
        if thread is None:
            return False  # Thread 已归档或不存在，视为不可见
        if not is_visible(thread, requesting_user_id):
            return False  # 任意一条不可见 → 整个 Weaving 不可见
    return True


async def get_weavings_for_user(family_id: str, requesting_user_id: str) -> list[Weaving]:
    """
    返回对 requesting_user_id 可见的 Weaving 列表。
    应用于：图谱渲染、Nudge 上下文构建、Semantic Clusterer 结果过滤。
    """
    all_weavings = await db.get_weavings(family_id)
    thread_ids = {tid for w in all_weavings for tid in w.source_thread_ids}
    thread_cache = await db.get_threads_by_ids(list(thread_ids))

    return [w for w in all_weavings
            if is_weaving_visible(w, requesting_user_id, thread_cache)]
```

**典型场景验证：**

| 场景 | Thread A | Thread B | Kelly 是否看到 Weaving |
|------|---------|---------|----------------------|
| Richard 给 Kelly 的惊喜礼物 ↔ Kelly 心愿单 | `user_private`（Richard 创建）| `shared` | ❌ 不可见（A 不可见于 Kelly）|
| 共同旅行计划 ↔ 家庭预算 | `family_private` | `shared` | ✅ 可见 |
| Kelly 的私人日记 ↔ Kelly 的心愿单 | `user_private`（Kelly 创建）| `shared` | ✅ Kelly 自己可见（两者她都可见）|

**共享热度关联（v0.11 修订版 ACL 信任感应）：**

Brain 不会提议「打开私密内容」，但会检测跨用户在共享 Thread 上的互动热度——当两位用户在同一批 `shared` Thread 上的互动频率（编辑、回应、Nudge 确认）超过阈值，Semantic Clusterer 会在下次周期内提议在这些 Thread 之间建立更深层的 Weaving，体现「关系升温」而不侵入各自私域。

```python
# Semantic Clusterer 内的共享热度检测
async def detect_shared_interaction_heat(family_id: str) -> list[HeatCluster]:
    """
    检测同一 Family 中多位用户高度共同关注的 shared Thread 集群。
    返回热度超过阈值的 Thread 对，供 Semantic Clusterer 优先考虑 Weaving。
    """
    interactions = await db.query("""
        SELECT thread_id, user_id, COUNT(*) as interaction_count
        FROM thread_interactions           -- 编辑 / Nudge确认 / 回应
        WHERE family_id = :family_id
          AND acl_tier IN ('shared', 'family_private')
          AND created_at > datetime('now', '-7 days')
        GROUP BY thread_id, user_id
    """, family_id=family_id)

    # 找出被多位用户高频互动的 Thread 对
    thread_user_map = group_by_thread(interactions)
    heat_clusters = []
    for thread_id, users in thread_user_map.items():
        if len(users) >= 2 and sum(u.interaction_count for u in users) >= HEAT_THRESHOLD:
            heat_clusters.append(HeatCluster(thread_id=thread_id, active_users=users))
    return heat_clusters
```

**Nudge 发送时的 ACL 检查：**

当 Brain 构建富上下文 Nudge 时（附带关联 Weaving 的 Thread 摘要），只有 `visible_to` 包含接收者的 Thread 会被包含在上下文摘要中。

```python
async def build_contextual_nudge(thread: Thread, weavings: list, recipient_user_id: str):
    context_threads = []
    for w in weavings:
        related = await db.get_thread(w.related_thread_id)
        if is_visible(related, recipient_user_id):
            context_threads.append(related)
    # 构建 Nudge 内容，只使用 context_threads 中的摘要
    ...
```

**ACL 变更规则：**
- 只有 `created_by` 可以修改 Thread 的 `acl.tier`
- 管理员可以降级任何 Thread 的 ACL（如将 `user_private` 改为 `shared`），但会触发一次通知给创建者
- 不支持将他人 Thread 从 `shared` 改为 `family_private`（防止无意间扩大可见性）

### 9.7 Shared Weaving as Entry Hook（入场引荐钩）

管理员在发出邀请时，可以选择附带一条 Weaving 作为新用户入场后的第一个上下文体验。

**触发方式（WhatsApp 指令扩展）：**
```
邀请 Sarah，带上"特斯拉用车成本"这条线索
```

Gateway 解析器在识别到「带上」/「附上」/「一起给」等关键词时，尝试从家庭图谱中匹配 Weaving 名称，将 `weaving_hook_id` 写入 `invite_tokens` 表。

**新用户入场时的体验：**

完成 Onboarding Step 1 后，Alfred 附加渲染：

```
「对了，{{admin_name}} 还想让你第一眼看到家里的一条线索——

📎 [{{weaving_title}}]
{{weaving_summary}}

这是家里图谱里一直有的背景，你现在也是图谱的一部分了 🪡」
```

**Entry Hook 的数据流：**
```
activate_invite()
  → weaving_hook_id 存在
  → 查询 Weaving 详情 + 关联 Thread 摘要（按 ACL 过滤）
  → 渲染 Entry Hook 消息
  → 附加在 Onboarding Step 1 之后发出
```

**限制：**
- Entry Hook 只支持 `shared` / `family_private` 级别的 Weaving（不允许将 `user_private` 线索作为 Hook）
- 若管理员指定的 Weaving 不存在或权限不足，忽略 Hook，不影响 Onboarding 流程

### 9.8 Shadow User — 影子节点与身份对齐 *(v0.11 新增)*

**场景动机：** Alfred 使用前期，Richard 记录的 Thread 里可能已经多次提到「Alyssa 的生日」「妈妈的体检」等尚未加入 Alfred 的成员。这些实体在图谱中以「影子节点」形式存在——有认知，无身份。当这些人真正被邀请加入时，他们应该感受到「Alfred 早就认识我了」。

**shadow_entities 数据表：**

```sql
CREATE TABLE shadow_entities (
    shadow_id           TEXT PRIMARY KEY,      -- 格式：SHADOW-{uuid}
    family_id           TEXT NOT NULL,
    display_name        TEXT NOT NULL,         -- 从 Thread 内容中 AI 提取的实体名称
    mention_count       INT DEFAULT 1,         -- 在 Thread 中被提及的次数
    first_mentioned_at  DATETIME NOT NULL,
    last_mentioned_at   DATETIME NOT NULL,
    linked_user_id      TEXT DEFAULT NULL,     -- 完成对齐后填入 alfred_users.user_id
    alignment_confirmed_by TEXT DEFAULT NULL,  -- 执行身份对齐确认的管理员 user_id
    alignment_confirmed_at DATETIME DEFAULT NULL,

    FOREIGN KEY (family_id) REFERENCES families(family_id)
);

CREATE INDEX idx_shadow_entities_family ON shadow_entities(family_id, linked_user_id);
```

**影子节点的创建（Event Processor 侧）：**

```python
async def extract_shadow_entities(thread: Thread, family_id: str):
    """
    Event Processor 在处理 CREATE 事件时，调用 AI 提取 Thread 内容中
    被提及的非系统用户实体（人名），与现有 alfred_users 和 shadow_entities 比对。
    未匹配到的，写入 shadow_entities 或增加 mention_count。
    """
    mentioned_names = await ai_extract_person_names(thread.content)
    known_users = await db.get_family_display_names(family_id)

    for name in mentioned_names:
        if name in known_users:
            continue  # 已是正式成员，不创建影子
        existing = await db.find_shadow_by_name(name, family_id)
        if existing:
            await db.increment_shadow_mention(existing.shadow_id, thread.updated_at)
        else:
            await db.create_shadow_entity(family_id, display_name=name)
```

**身份对齐流程（管理员邀请时触发）：**

```
管理员："邀请 Alyssa"
  ↓
Gateway 生成邀请令牌前，查询 shadow_entities（family_id = 当前 family）
  ↓
如果存在 display_name 近似 "Alyssa" 的影子节点（模糊匹配 + mention_count > 0）：
  → Gateway 向管理员推送确认消息：
    「我记录过一个叫 Alyssa 的人，出现在 {{mention_count}} 条线索里。
     这就是你要邀请的 Alyssa 吗？回复「是」确认关联，或「不是」跳过。」
  ↓ 管理员回复「是」
  → invite_tokens.shadow_entity_id = shadow_id（写入待关联 ID）
  ↓
Alyssa 接受邀请，activate_invite() 完成用户绑定
  → db.update_shadow_entity(shadow_id, linked_user_id=alyssa.user_id, ...)
  → Brain 广播 IDENTITY_ALIGNED 事件
  → Event Processor 将所有涉及该影子节点的 shared Thread 打上 Alyssa 的 user_id 标签
  → Qdrant 中对应节点的 payload 更新
  ↓
Alyssa 的 Onboarding Step 1 后附加：
  「我在这里等你有一段时间了——
   家里有 {{mention_count}} 条线索里提到了你 🪡」
```

**数据库补充（invite_tokens 表新增字段）：**
```sql
ALTER TABLE invite_tokens ADD COLUMN shadow_entity_id TEXT REFERENCES shadow_entities(shadow_id);
```

**隐私原则：**
- 影子节点不包含任何私密推断，只记录「被提及的姓名」和「提及次数」
- `user_private` 级别的 Thread 中的人名，不提取为影子节点
- 管理员必须显式确认才触发身份对齐，系统不自动执行

### 9.9 用户模型扩展（alfred_users 表更新）

```sql
-- 在现有 alfred_users 表中新增字段
ALTER TABLE alfred_users ADD COLUMN role TEXT DEFAULT 'invited_user';
-- role: 'admin' | 'invited_user'

ALTER TABLE alfred_users ADD COLUMN invited_by TEXT REFERENCES alfred_users(user_id);
ALTER TABLE alfred_users ADD COLUMN joined_at DATETIME;
ALTER TABLE alfred_users ADD COLUMN display_name TEXT;  -- 管理员指定的姓名，用于 Onboarding 模板
```

**families 表保持不变，新增索引：**
```sql
CREATE INDEX idx_alfred_users_family_role ON alfred_users(family_id, role);
```

---

## 10. 技术架构

### 10.1 Alfred 整体拓扑

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
│   M8：邀请指令解析 / Token 识别 / 用户绑定              │
└───────────┬─────────────────┬──────────────────────────┘
            ▼                 ▼
┌───────────────────────────────────────────────────────┐
│                    【技能层】SKILLS                     │
│                                                       │
│   Thread :8002              OurCents :8001            │
│   ─────────────             ──────────────            │
│   Unified Thread CRUD       财务记账                  │
│   Trigger 解析（AI）        收据 OCR                  │
│   ACL 字段管理              跨技能事件输出            │
│   Sub-threading                                       │
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

### 10.2 三层对比

| 维度 | 大脑层 | 感官层 | 技能层 |
|------|--------|--------|--------|
| 主要职责 | 思考/编织/激活/仲裁/纠错 | 感知/路由/广播/邀请处理 | 执行 Thread CRUD / 财务 |
| 状态性 | 有状态（图谱 + Pool + 负样本 + 快照）| 无状态 | 无状态 |
| 作用域 | 家庭（Family）| 单用户通道 | 单用户 |
| 触发方式 | 事件驱动 + 定时任务 + 实时扫描 | 用户消息 | 感官层派发 |
| 延迟 | 可接受分钟级 | < 3 秒 | < 3 秒 |

### 10.3 Gateway 事件广播（三类）

```python
# ① CREATE — 技能执行成功
# ② INVALIDATE — 数据删除或大幅修改（>50% 内容变更）
# ③ USER_CORRECTION — 用户在 Web 端断开 Weaving
# + Geofence 入境事件（OS 推送到 Gateway → 转发 Brain Trigger Monitor）
# + M8 邀请指令（Gateway 本地处理，不广播到 Brain）
```

### 10.4 Qdrant 原子锁

- 写入前标记 `lock_status = "processing"`，完成后释放为 `"ready"`
- 前台查询只返回 `"ready"` 节点
- 5 秒超时自动解锁，防死锁

### 10.5 数据层

```
SQLite（技能层 + 感官层）
  ├── Gateway: contacts, conversations, messages,
  │           alfred_users（新增 role / invited_by / joined_at / display_name）,
  │           families,
  │           invite_tokens（M8 新增）
  ├── Thread:  threads（含 trigger + acl 嵌套字段）, thread_links
  │            注：v0.9 废除 reminders 表，trigger 字段替代；v0.10 新增 acl 字段
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

Qdrant :6333（单一 Collection，补丁 C）
  ├── threads_all   — 所有 Thread 统一存储
  │                   payload 含 category / trigger_type / acl_tier / lock_status
  │                   查询时按 category 动态应用相似度阈值
  └── weaving_map   — 家庭认知图谱（边 + 权值 + 纠正标记）

// 分类阈值（查询时动态应用）：
CATEGORY_THRESHOLDS = {
    "pro":     0.80,
    "life":    0.72,
    "emo":     0.65,
    "routine": 0.75
}

// 单分类搜索（精确）：
results = qdrant.search("threads_all",
    query_vector=embedding,
    query_filter={"must": [
        {"key": "category", "match": {"value": "emo"}},
        {"key": "acl_tier", "match": {"any": ["family_private", "shared"]}}
    ]},
    score_threshold=0.65)

// 跨分类搜索（Weaving 编织用）：
candidates = qdrant.search("threads_all", query_vector=embedding, limit=50,
    query_filter={"must_not": [
        {"key": "acl_tier", "match": {"value": "user_private"}}
    ]}
)
filtered = [r for r in candidates if r.score >= CATEGORY_THRESHOLDS[r.payload["category"]]]
```

### 10.6 技术选型

| 层级 | 选型 | 备注 |
|------|------|------|
| 前端图谱视图 | **React Flow** + TypeScript | v0.11 替代纯 D3.js 节点图；D3.js 保留用于热力图底层计算 |
| 前端分析图表 | D3.js / Recharts | OurCents 报表、热力图 |
| 前端部署形态 | **PWA（Progressive Web App）** | 支持 Web Push，WhatsApp 之外的第二 Nudge 通道 |
| 感官层 | Python FastAPI + Node.js（Bridge）| — |
| 技能层 | Python FastAPI（Thread :8002 / OurCents :8001）| — |
| 大脑层 | Python FastAPI（Brain :8003）| — |
| 定时任务 | APScheduler（Trigger Monitor 每分钟 / 其他工作器定时）| — |
| 关系数据库（OLTP）| SQLite | 日常事务写入：Thread / Gateway / Brain |
| 分析引擎（OLAP）| **DuckDB**（v0.11 引入，OurCents 层）| 跨月度、多维度聚合报表；直接读 SQLite 或导出的 Parquet |
| 向量数据库 | Qdrant（本地，:6333）| — |
| 内部事件通信 | HTTP Webhook（v1.0）→ **NATS JetStream**（v1.1 升级）| Payload 结构提前适配 NATS Subject 命名，见 Section 10.7 |
| Brain 推演子任务 | **LangGraph**（v1.1 引入，局部）| 仅用于 Proactive Nudge Generator + Semantic Clusterer 推演链；Trigger Monitor / Entropy Reduction 等确定性工作器不引入 |
| AI 推演 | Claude API | — |
| 意图识别 + Trigger 解析 | gpt-4o-mini | — |
| Embedding | text-embedding-3-small | — |
| 语音转录 | Whisper API | — |
| 消息推送 | WhatsApp Business API / Bridge + Web Push API（PWA）| — |
| 位置服务 | iOS/Android Geofencing 原生 API | — |
| Cron 解析 | croniter（Python）| — |
| 令牌生成 | Python secrets 模块（CSPRNG）| — |

### 10.7 NATS 预留位 — 事件 Subject 命名规范 *(v0.11 战略设计)*

> v1.0 使用 HTTP Webhook 通信，但所有事件的 Payload 结构从现在起对齐 NATS JetStream 的主题（Subject）规范。v1.1 升级时，只需将 `POST /brain/events` 的调用方替换为 `nats.publish(subject, payload)`，业务逻辑代码零改动。

**Subject 命名约定：**

```
alfred.family.{family_id}.events.create        — Thread 创建
alfred.family.{family_id}.events.invalidate    — Thread 失效
alfred.family.{family_id}.events.correction    — 用户纠正
alfred.family.{family_id}.geofence.enter       — 地理围栏入境
alfred.family.{family_id}.geofence.exit        — 地理围栏离境
alfred.family.{family_id}.identity.aligned     — Shadow User 身份对齐（v0.11 新增）
alfred.nudge.{user_id}.push                    — Brain 推送 Nudge
alfred.observer.{family_id}.traffic_spike      — 流量激增，触发 Observer Mode
```

**v1.0 Payload 当前结构（已对齐 NATS Subject）：**

```json
{
  "subject": "alfred.family.fam_001.events.create",
  "event_type": "CREATE",
  "service": "thread",
  "family_id": "fam_001",
  "timestamp": "2026-05-11T10:00:00Z",
  "entities": {
    "thread_id": "...",
    "content": "...",
    "category": "life",
    "acl_tier": "shared",
    "intent_vector": { "urgency": 0.4, "social_bond": 0.3, "goal_alignment": 0.5 }
  }
}
```

> `subject` 字段在 v1.0 中作为元数据写入，v1.1 时作为真实 NATS 主题使用。这样在过渡期间，日志和监控工具已经能按 Subject 聚合统计，无需等到 v1.1 才具备可观测性。

---

## 11. Alfred 三层架构

### 11.1 架构全景

```
Alfred = 大脑（Brain）+ 感官（Senses）+ 技能（Skills）
```

| Alfred 命名 | 智能体术语 | 核心问题 |
|------------|-----------|---------|
| 大脑（Brain）| Reasoning / Memory | Alfred 怎么思考、学习和纠错？|
| 感官（Senses）| Perception / Action | Alfred 怎么感知和表达？|
| 技能（Skills）| Tool / Capability | Alfred 能做什么？|

### 11.2 Thread-Centric 的架构意义

**新模型（大脑思维）：**
```
用户输入 → 统一成 Thread（AI 自动解析 trigger + acl）
  → 进入 Thread 服务，统一存储
Brain 的 Context Pool = 所有 Thread（按 ACL 过滤后可见的部分）
Trigger Monitor 在触发时：不只提醒，而是唤醒整条记忆线索
```

**体感差异（v0.9 引入，v0.10 延续）：**

旧模式下，「开会提醒」到点响一声，任务完成。  
新模式下，「开会提醒」到点时，Alfred 说：  
*「季度复盘会快开始了。你上次记下的「API 性能瓶颈」和这次议题有关——要带进去吗？另外，Kelly 上周说你最近工作压力有点大，开完会也许可以早点回家。」*

### 11.3 各层职责边界

**大脑层（Brain :8003）**
- 六个工作器，家庭维度，异步
- Trigger Monitor 是核心：显式激活 + 上下文注入 + 仲裁保护
- ACL 过滤：Brain 对 Qdrant 的所有查询均附加 ACL 约束
- 三类信号权重：技能事件（低）< 感官广播（中）< 用户纠正（最高）

**感官层（Gateway + Bridge）**
- 三类广播 + Geofence 事件转发
- M8：邀请指令解析 + Token 识别 + 用户绑定（Gateway 本地处理）
- 不执行业务逻辑，不主动发起 Nudge

**技能层（Thread + OurCents）**
- Thread :8002：Unified Thread 完整生命周期管理（含 ACL 字段）
- OurCents :8001：财务领域逻辑
- 标准 ASI 接口 + 双向量输出

### 11.4 扩展成本

- **新增技能**：ASI 接口 + services.yaml + 双向量输出
- **新增感官通道**：Bridge 转换 + Gateway 接收
- **新增用户**：管理员发出邀请，Gateway M8 流程处理，Brain 代码无需改动
- **Brain 代码**：前三种扩展均不需要修改

### 11.5 对现有代码的改动总结（v0.9 → v0.10）

| 文件 / 目录 | 改动内容 | 改动量 |
|-----------|---------|--------|
| `services/thread/models.py` | Thread 数据模型新增 `acl` 字段（tier / created_by / visible_to）| +20 行 |
| `services/thread/crud.py` | 录入时自动填充 `acl.created_by`；默认 `acl.tier = shared` | +15 行 |
| `services/gateway/message_handler.py` | 管理员邀请指令解析；Token 识别；`activate_invite()` 函数 | +80 行 |
| `services/gateway/onboarding.py` | 参数化 Onboarding 模板渲染（`{{user_name}}` / `{{admin_name}}`）| 重构 30 行 |
| `database/gateway.sql` | 新增 `invite_tokens` 表；`alfred_users` 表新增字段 | 迁移脚本 |
| `services/brain/qdrant_client.py` | 所有查询附加 ACL 过滤（`acl_tier` payload 字段）| +25 行 |
| `services/brain/trigger_monitor.py` | `build_contextual_nudge()` 新增 ACL 过滤参数 | +10 行 |
| **v0.10 → v0.11** | | |
| `services/brain/decision_arbiter.py` | 新增第⑥检查 Observer Mode；`gateway_client.get_recent_traffic()` 接口 | +20 行 |
| `services/gateway/shadow_entity.py` | 影子节点提取 + 身份对齐流程；`shadow_entities` 表操作 | +120 行 |
| `services/ourcents/analytics.py` | DuckDB 分析引擎接入；月度报表查询迁移 | 新建 |
| `web/src/components/Graph.tsx` | D3.js 节点图 → React Flow 重构 | 重构 |
| `web/manifest.json` + `service_worker.js` | PWA 配置 + Web Push 注册 | 新建 |
| 所有事件 Payload | 新增 `subject` 字段（NATS Subject 预留）| 全量 +1 字段 |

---

## 12. Brain 服务规格

### 12.1 服务信息

| 属性 | 值 |
|------|---|
| 端口 | :8003 |
| 技术栈 | Python / FastAPI / APScheduler |
| 数据库 | SQLite + Qdrant + 内存 Active Pool |

### 12.2 API 端点

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `GET /health` | 公开 | 健康检查 |
| `GET /alfred/capabilities` | API-Key | 声明 intent |
| `POST /alfred/execute` | API-Key | 执行 Brain intent |
| `POST /brain/events` | API-Key | 接收三类事件 |
| `POST /brain/geofence` | API-Key | 接收 Geofence 入境事件 → Trigger Monitor |
| `GET /brain/graph/{family_id}` | JWT | 图谱数据（含热度 + lock + ACL 过滤）|
| `GET /brain/graph/{family_id}/snapshot/{date}` | JWT | 历史快照 |
| `GET /brain/graph/{family_id}/forecast` | JWT | 未来推演 |
| `GET /brain/weavings/{family_id}` | JWT | Weaving 列表 |
| `POST /brain/weavings/{id}/confirm` | JWT | 显式确认 |
| `POST /brain/weavings/{id}/correct` | JWT | 用户纠正 |
| `GET /brain/active_pool/{family_id}` | JWT | 调试：Active Pool 状态 |
| `GET /brain/emotional_budget/{user_id}` | JWT | 调试：情感预算余量 |
| `GET /brain/active_geofences/{user_id}` | API-Key | Gateway 查询活跃 geofence Thread 及目标坐标 |

### 12.3 工作器总览

| 工作器 | 频率 | 核心职责 | 资源上限 |
|--------|------|---------|---------|
| ① Event Processor | 实时 | 三类事件处理，原子锁写 Qdrant | < 500ms |
| ② Semantic Clusterer | 每周 | Active Pool 扫描，双评分 Weaving（ACL 过滤）| 500 节点 |
| ③ Proactive Nudge Generator | 每日 | 隐式激活候选，情感预算过滤 | 1-2 条/日 |
| ④ Decision Arbiter | 实时（前置）| **6 项检查**（含 Observer Mode）| < 100ms |
| ⑤ Entropy Reduction | 每月 | 弱关联清理（跳过纠正边）| 50 条/次 |
| ⑥ Trigger Monitor | 实时扫描（每分钟）| 显式触发检测 + 上下文注入 + ACL 过滤 | 每次扫描 < 200ms |

---

## 13. 非功能性需求

### 13.1 隐私与安全
- 向量数据本地存储（Qdrant 自托管）
- Brain 跨用户分析仅限同一 Family
- Kill Switch + 优雅降级
- `user_private` Thread 不进入跨用户 Qdrant 查询
- USER_CORRECTION 记忆永久保留
- 邀请令牌使用 CSPRNG 生成，7 天有效期，单次使用后立即失效
- Shadow User 影子节点仅提取自 `shared` / `family_private` Thread，不推断私密内容；身份对齐需管理员显式确认
- Observer Mode 的 Gateway 流量数据不持久化，仅作实时窗口计算，不进入日志

### 13.2 性能
- 技能层响应：< 3 秒
- Brain 事件处理：CREATE < 500ms / INVALIDATE < 200ms / USER_CORRECTION < 300ms
- Decision Arbiter：< 100ms
- Trigger Monitor 轮询：每分钟一次
- 图谱查询：< 200ms
- 历史快照查询：< 500ms
- 动效帧率：≥ 60fps
- 邀请令牌验证：< 100ms

### 13.3 克制原则
- Nudge 日均上限：4 条（含显式 + 隐式）
- 情感预算：24 小时总消耗 10.0 分
- Brain 每周最多提议 3 个 Weaving
- 拒绝的 Weaving 主题，3 个月内不重提
- Trigger Monitor 生成的 Nudge 不豁免情感预算
- 时间透视未来推演最长 30 天
- Sub-threading 的子 Thread 可独立携带触发器，但不额外消耗情感预算
- 管理员一次性最多生成 5 个待用邀请令牌（防止滥发）

---

## 14. 开放问题与待讨论项

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
| Q10 | ✅ Persona 冷启动脚本（已参数化）| 已解决 |
| Q11 | Brain 提议 Weaving 时，如何让用户轻松修改标题？| 中 |
| Q12 | 跨技能关联边（金色）密度控制 | 低 |
| Q13 | Spark 状态的定义和生命周期 | 低 |
| Q14 | Active Pool 容量上限（建议 1000）及 30 天冷热边界 | 中 |
| Q15 | Intent Vector 冷启动期默认值；goal_alignment 如何在无明确长期目标时计算？| 中 |
| Q16 | 熵减弱边阈值（< 0.15 + 6 个月）是否过于激进？| 低 |
| Q17 | 情感预算初始值（10.0）和各级消耗值是否合理？不同用户是否应有不同上限？| 中 |
| Q18 | 静默确认的 30 分钟超时窗口；WhatsApp 端如何告知「不回复即同意」？| 中 |
| Q19 | Trigger Monitor 每分钟轮询是否足够实时？是否需要引入消息队列（如 Redis）优化时间精度？| 中 |
| Q20 | recurring Thread 的 cron 表达式由 AI 自动生成，误解率如何？是否需要可视化 cron 编辑器辅助确认？| 中 |
| Q21 | 受邀用户是否应该有权邀请他人？（当前默认不能，管理员可以授权）| 中 |
| Q22 | `acl.tier` 的默认值是否合理？高敏感用户（如 Kelly）是否应默认为 `user_private` 而非 `shared`？| 中 |
| Q23 | Entry Hook Weaving 的呈现时机：是在 Onboarding Step 1 之后立即推送，还是等用户发完第一条 Thread？| 低 |
| Q24 | 令牌有效期 7 天是否合理？家庭场景下是否需要更长（如 30 天）？| 低 |
| Q25 | Observer Mode 的流量阈值（5 分钟 10 条）是否合适？不同家庭的「密集对话」基线差异很大 | 中 |
| Q26 | Shadow User 的 AI 人名提取误差率？同名成员（如两个「妈妈」）如何区分？| 中 |
| Q27 | DuckDB 与 SQLite 的写入隔离：OurCents 的写入路径是否需要同步给 DuckDB，还是异步 ETL？| 中 |
| Q28 | React Flow 的图谱性能边界：当节点数接近 Full Graph 上限（20 节点）时，React Flow 的动效是否流畅？| 低 |
| Q29 | PWA Web Push 在 iOS Safari 的支持程度（iOS 16.4+ 才支持）——Kelly 的设备是否满足？| 高 |
| Q30 | LangGraph 推演链的可追溯性如何在前端呈现？是否需要「AI 思考过程」的轻量可视化？| 低 |

---

## 15. 版本路线图

### v0.1–v0.8 ✓（已完成，设计封存）

### v0.9 ✓ — Thread-Centric 架构重构（设计封存）
- [x] Unified Thread 对象模型（`trigger` 字段，废除独立 Reminder）
- [x] Nudge 技能更名为 Thread 技能，职责精确化
- [x] Brain 第⑥工作器：Trigger Monitor（显式激活 + 上下文注入）
- [x] 数据迁移方案（reminders → threads.trigger）
- [x] Qdrant 合并为单一 Collection `threads_all`（补丁 C）
- [x] APScheduler 引入（定时任务统一管理）
- [x] `firing` 原子状态（补丁 D）
- [x] Misfire Handling（补丁 A）
- [x] 自适应地理心跳（补丁 B）
- [x] `interaction_rules` in PersonaProfile（补丁 E）
- [x] `"service": "thread"` 字段统一

### v0.10 ✓ — 多用户扩展设计（设计封存）
- [x] Thread ACL（`acl` 字段：tier / created_by / visible_to）
- [x] M8 User Expansion Layer（管理员邀请流程 + invite_tokens 表 + Token 握手）
- [x] Onboarding 脚本参数化（`{{user_name}}` / `{{admin_name}}`）
- [x] Shared Weaving as Entry Hook
- [x] 用户角色模型（admin / invited_user）
- [x] Section 3 用户模型泛化

### v0.11 ✓ — 前端现代化 + 架构战略留白（当前版本，设计封存）
- [x] React Flow 取代 D3.js 节点图；D3.js 保留热力图层
- [x] PWA + Web Push：第二 Nudge 通道
- [x] DuckDB：OurCents OLAP 分析引擎（SQLite 保留 OLTP）
- [x] NATS JetStream 预留位：v1.0 Payload 提前对齐 Subject 命名规范（Section 10.7）
- [x] LangGraph 作用域明确：仅限 Proactive Nudge Generator + Semantic Clusterer 推演子任务（v1.1 引入）
- [x] Shadow User 身份对齐：影子节点提取 + 管理员确认 + 入场继承
- [x] ACL 修订：废弃私密晋升，改为共享热度关联（Section 9.6）
- [x] Decision Arbiter 第⑥检查：Observer Mode（Gateway 流量传感器）
- [x] 新增架构设计原则：基础设施先行，LLM 编排局部化，隐私边界物理化

---

### 🏁 v1.0 — MVP 最小闭环（下一个实施里程碑）

**目标：在图谱上出现第一根金色的线，并让第二个人走进这个图谱**

```
第一根金色的线：
「特斯拉最近保养费越来越贵了」
  ↓ Thread 技能保存（trigger.type = none，category = life，acl.tier = shared）
  ↓ 感官层广播 CREATE 事件
  ↓ Brain Event Processor → Qdrant → Active Pool
  ↓ Brain 发现 OurCents「特斯拉保养 ¥3200」记录
    Intent 点积 > 0.7，Fact Cosine > 0.72 ✓
  ↓ Decision Arbiter 通过，情感预算充足
  ↓ Brain 提议 Weaving：[特斯拉用车成本]
  ↓ Web 端：两个节点之间，连出一根金色的线

第二个人走进来：
Richard → Alfred："邀请 Kelly"
  ↓ Alfred 返回邀请卡（带 Token:ALFRED-XXXXXX）
  ↓ Richard 转发给 Kelly
  ↓ Kelly 点击 wa.me 链接
  ↓ Alfred 识别 Token → 绑定用户 → 参数化 Onboarding
  ↓ Kelly 看到「欢迎加入 Richard 的家庭图谱 🪡」
```

**v1.0 实施任务清单：**

*核心 Thread 功能：*
- [ ] Unified Thread CRUD（含 trigger + acl 字段）+ WhatsApp Bot 基础版
- [ ] AI trigger 解析（gpt-4o-mini，识别四种 trigger.type）
- [ ] 今日卡片视图 + 基础热力图

*Brain 基础版：*
- [ ] Event Processor + Qdrant（threads_all 单 Collection）+ Active Pool + 原子锁
- [ ] Trigger Monitor 基础版（once / recurring 两种类型，geofence 推后）
- [ ] Decision Arbiter 基础版（密度 + Kill Switch + 情感预算，三项检查）
- [ ] 最小 Weaving 闭环：Thread ↔ OurCents 跨技能金色线

*M8 用户扩展（v1.0 纳入）：*
- [ ] `invite_tokens` 表 + `alfred_users` 角色字段
- [ ] Gateway 邀请指令解析（「邀请 [姓名]」→ 生成卡片）
- [ ] Gateway Token 解析器（识别 `(Token:XXXX)` → 绑定用户）
- [ ] 参数化 Onboarding 渲染引擎（`{{user_name}}` / `{{admin_name}}`）
- [ ] Kelly Persona Profile 冷启动（Implicit Ack 开启）

*基础设施：*
- [ ] Ego-centric 图谱（含卫星节点）
- [ ] Qdrant 本地 Docker 部署

### v1.1 — AI 编织核心 + 架构异步化
- [ ] Semantic Clusterer（每周聚类 + Weaving 提议，含 ACL 过滤 + 共享热度关联）
- [ ] Decision Arbiter 完整版（语义冲突 + 纠正历史过滤）
- [ ] 静默确认完整实现
- [ ] USER_CORRECTION 逆向编织 + 负样本记忆
- [ ] Intent Vector 三维完整标注（告别冷启动默认值）
- [ ] Trigger Monitor：geofence 触发支持
- [ ] WhatsApp 语音录入
- [ ] Entry Hook Weaving（Shared Weaving as 邀请入场礼）
- [ ] **NATS JetStream 引入**：Gateway → Brain 通信从 Webhook 切换至消息总线；支持 INVALIDATE_EVENT 级联失效
- [ ] **LangGraph 推演链（局部）**：Proactive Nudge Generator + Semantic Clusterer 使用 LangGraph 状态图，推演过程可追溯
- [ ] **Weaving 版本化**：每条 Weaving 建立变更历史，与 graph_snapshots 联动，支持「这条关联是什么时候建立的」回溯

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
- [ ] ACL Web UI（Thread 权限管理界面）

### v1.4 — 完整体验
- [ ] 规律预测模型（时序 AI）
- [ ] 移动端原生 App
- [ ] 动态阈值个性化（贝叶斯）
- [ ] Health 技能接入（Apple Health）
- [ ] Health × Emo Thread 跨技能 Weaving（压力感 × 血压读数）
- [ ] 受邀用户邀请权限（可选，管理员授权后开放）

---

*本文档为活文档，随产品讨论持续迭代。*  
*v0.9 完成了从 v0.1 到今天的最后一次底层对象模型重构。核心对象只有一个：Thread。*  
*v0.10 完成了多用户扩展的完整设计。一个图谱，可以住下整个家庭。*  
*v0.11 完成了「战略性留白」：为 NATS、LangGraph、DuckDB、React Flow 留好了插槽，但一行也没有提前写。*  
*v1.0 的任务只有两个：让一根金色的线出现在图谱上，让第二个人走进这个图谱。*

---

## 🛠️ v1.0 Ubuntu 开发启动顺序

> 文档封版后的第一铲土。按此顺序开发可最快验证完整闭环，且每一步都有独立的可测试产出。

| 阶段 | 目标 | 可测试产出 | 核心风险 |
|------|------|----------|---------|
| **① 地基层** | 部署 Qdrant Docker，建立 `threads_all` Collection（含 ACL payload 字段）| `qdrant.search("threads_all", ...)` 返回正确结果 | Qdrant 版本兼容性 |
| **② 通讯层** | 调通 WhatsApp Gateway，实现 Thread Echo（发什么 Alfred 回什么）| Kelly 发一条消息，看到 Alfred 的原文回显 | WhatsApp Business API 沙箱申请周期 |
| **③ 核心层** | Thread-Centric Parser：一句话 → `Content + Trigger + ACL` 结构 | 「明天两点开会」→ 正确解析为 `trigger.type=once, fire_at=...` | LLM 解析误差率；cron 生成准确性 |
| **④ 大脑层** | Event Processor：Thread 写入 → Qdrant 向量化 → Active Pool | 发一条 Thread，Qdrant 中出现对应向量节点 | Embedding API 延迟；原子锁实现 |
| **⑤ 社交层** | M8 邀请流程：Richard 邀请 Kelly，Kelly 接受，参数化 Onboarding 触发 | Kelly 的手机收到「嘿 Kelly 👋 我是 Thread」 | Token 原子失效；Onboarding 模板渲染 |
| **⑥ 编织层** | 第一根金色的线：Thread ↔ OurCents 跨技能 Weaving，Web 端可见 | Web 图谱上出现一条金色连线 | Decision Arbiter 阈值调参；Weaving 交集可见性验证 |

**关键路径说明：** 阶段 ③ 是最高技术风险点——LLM 将自然语言准确解析为四种 trigger.type 的成功率决定了后续所有体验的质量。建议在此阶段建立一个小型 Eval 集（20-30 条典型用户输入），在进入阶段 ④ 之前将解析准确率稳定在 90% 以上。
