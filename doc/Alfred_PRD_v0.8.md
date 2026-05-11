# Alfred — 产品需求文档（PRD）

**版本：** v0.8 Draft  
**日期：** 2026-05-04  
**作者：** Richard  
**状态：** 内部讨论稿 · **准予立项，可进入代码实施阶段**

**变更摘要（v0.7 → v0.8）：**
- **[漏洞 A] 逆向编织（USER_CORRECTION）**：用户在 Web 端手动断开或修正 Weaving 时，作为最高权重负反馈回传 Brain，调整关联权重，防止错误认知被热力图持续强化
- **[漏洞 B] 情感预算（Emotional Budget）**：Brain 维护 24 小时情感消耗计数，连续发送沉重话题后，新 Nudge 自动降级为静默提醒，保护用户（尤其 Kelly）不被轰炸
- **[漏洞 C] Qdrant 原子锁（Node Locking）**：Brain 处理期间对涉及节点标记 `processing` 状态，避免多 Collection 冷热同步延迟导致前台图谱闪烁
- **[进阶 A] Intent Vector 三维度标准**：固定 `Urgency`（紧迫感）/ `Social_Bond`（情感联结）/ `Goal_Alignment`（目标一致性）三个语义轴，让 Brain 的编织判断有明确的心理学坐标
- **[进阶 B] 时间透视（Time Perspective）**：Web 端图谱新增时间轴滑块，向左看过去的认知状态，向右看 Brain 基于当前 Weaving 推演的未来图景
- **[进阶 C] 静默确认（Implicit Ack）**：针对 Kelly 的 Persona，轻量级 Weaving 建议在无反对且对话继续后自动接受，降低交互摩擦

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

Nudge、OurCents 是它现有的**技能**，以后会不断添加；  
Gateway 和 WhatsApp 是它的**感官**——嘴巴、耳朵、眼睛；  
Brain（Weaving）是它的**大脑**——前台是家庭知识图谱，后台是 LLM 与长期记忆的对接。

> 最终目标：让你们感到即便年纪渐长、记忆衰退，生活依然在掌控之中，且充满被理解的温暖。

**产品名称：** Thread（Nudge 功能面向用户的品牌名）/ Alfred（整体平台）  
**核心服务：** Brain（大脑）/ Gateway（感官）/ Nudge + OurCents（技能）  
**核心动词：** Weave（编织）  
**核心动作：** Nudge（轻推）

---

## 2. 核心设计哲学

### 2.1 三层架构信念

**大脑负责思考，感官负责感知，技能负责执行。三者职责不能混淆。**

- **大脑是观察者，不是管理者。** Brain 从事件中学习，不干预感官和技能的正常运作。
- **感官是通道，不是决策者。** Gateway 做路由和意图识别，不承载领域逻辑。
- **技能是能力，不是全部。** 每个技能模块专注一个领域，保持独立可替换。
- **家庭是最小认知单元。** Brain 以 Family 为作用域，感官和技能按用户独立运作。
- **好的 AI 知道什么时候该沉默。** Brain 的主动 Nudge 受密度和情感预算双重约束。
- **正向叙事塑造行为。** 永远用「动能」代替「拖延」。
- **认知必须有遗忘才能保持活力。** 过期的弱关联应当被清理，而不是永远积累。
- **用户的纠正是最高权重的信号。** Brain 推演的认知可以被错，但错了必须能被改，且改正会被记住。

### 2.2 语言规范

| ❌ 禁止使用 | ✅ 使用替代 |
|-----------|-----------|
| 拖延指数 | 动能（Momentum）|
| 你在拖延 | 当前动能较低 |
| 记录任务 | 把线索缝起来 |
| 操作层 / 智能层 | 感官 / 技能 / 大脑 |

---

## 3. 目标用户

| 属性 | Richard | 太太（Kelly）|
|------|---------|------------|
| 核心输入界面 | Web 看板 | WhatsApp（首选）|
| 启动阻力 | 低 | 高（需动能积累策略）|
| 对「被管理」的感受 | 中性 | **高度敏感，易产生防御**|
| Weaving 确认方式 | 显式点击确认 | **静默确认（Implicit Ack）优先**|

---

## 4. 核心概念定义

### 4.1 三类对象的关系

```
Thread（线索）      ─── 是 ───→  Brain 的原材料（节点）
Weaving（编织）     ─── 是 ───→  Brain 建立的关系（边）
Nudge（轻推）       ─── 是 ───→  Brain 的输出行为
```

**Thread 是动态的、有时效的**（「Kelly 想买绿植」）  
**Weaving 是沉淀的、结构化的**（「阳台改造计划」——多个 Thread 的认知聚合）

### 4.2 Thread（线索）

```
Thread {
  id, content, category, person, priority, status,
  snooze_count, location_tag, source,
  created_at, updated_at,
  embedding: float[], tags: string[]
}
```

**四种分类与语义阈值：**

| 分类 | 颜色 | 阈值 |
|------|------|------|
| 职业（Pro） | 蓝色 | 0.80 |
| 生活（Life） | 琥珀色 | 0.72 |
| 规律（Routine） | 绿色 | 0.75 |
| 情感（Emo） | 粉色 | 0.65 |

### 4.3 Weaving（编织关系）

| 类型 | 视觉 | 含义 |
|------|------|------|
| 语义关联（Semantic） | 白色实线 | 内容语义相关 |
| 冲突预警（Conflict） | 红色虚线 + 呼吸动效 | 时间或资源冲突 |
| 主动编织（Proactive） | 蓝色虚线 | Brain 推演的关联 |
| 时序依赖（Sequential） | 橙色流动箭头 | A 必须先于 B |
| 空间关联（Spatial） | 紫色点线 | 物理位置接近 |
| 跨技能关联（Cross-skill） | 金色实线 | Thread ↔ OurCents / Reminder 的跨域关联 |
| 用户纠正边（Corrected） | 灰色删除线 *(新)* | 用户主动断开的错误关联，保留为历史记录 |

### 4.4 Nudge（轻推）与情感分级

Nudge 是 Brain 的**主要输出**，受 Decision Arbiter 和情感预算双重过滤。

**情感重量分级：**

| 级别 | 类型 | 示例 | 情感消耗值 |
|------|------|------|-----------|
| L1 | 轻量提示 | 「记得今天取快递」| 0.5 |
| L2 | 任务推动 | 「上次说的报告还差结尾」| 1.0 |
| L3 | 冲突预警 | 「下周旅行和项目截止日重叠了」| 2.0 |
| L4 | 情感深度 | 「你最近动能一直不高，聊聊？」| 3.0 |

**触发优先级：**
1. 冲突预警 / 逻辑阻断（立即）
2. 时间临近
3. 空间触发（进入 Geofence）
4. 规律窗口
5. 情感回溯
6. 跨用户编织
7. 跨技能洞察

---

## 5. 功能需求（技能层）

> 技能层响应感官层的派发请求，执行具体领域逻辑，快速返回结果（< 3 秒），无需感知彼此。

### 5.1 认知图谱视图（前端展现层）

**Ego-centric 默认模式（5-7 节点）：**
- 节点评分 = `时间紧迫度(60%) × 关联强度(40%)`
- 卫星节点：Cosine Similarity > 0.85 的非紧迫节点悬停边缘

**全局模式（Full Graph）：** 上限 20 节点，四象限聚簇

**视觉动效：**

| 元素 | 动效 |
|------|------|
| 冲突节点 | 呼吸缩放 0.95 ↔ 1.05，周期 2s |
| 时序依赖边 | 橙色粒子流动 |
| Sub-thread 完成 | 能量波动至父节点，发光 0.5s |
| 卫星节点 | ±3px 浮动，周期 4s |
| 跨技能关联边 | 金色脉冲，每 5s 一次 |
| 用户纠正边 | 灰色删除线，透明度 40%，悬停显示纠正时间 |

### 5.2 Thread 操作（Nudge 技能）

- 快速录入：自然语言 → AI 解析 → 一键确认 Weaving
- 生命周期：活跃 → 休眠（7 天无更新）→ 归档
- Sub-threading：Snooze ≥ 3 次触发微粒化

### 5.3 Persona 推演引擎

```
PersonaProfile {
  user_id, communication_style, cognitive_mode,
  work_pattern, nudge_preference, personality_tags,
  momentum_score: float,      // 动能状态 0.0-1.0
  motivation_style: "logic" | "emotion" | "reward",
  implicit_ack_enabled: bool, // 是否开启静默确认（Kelly 默认 true）
  emotional_budget_24h: float // 当前 24 小时情感消耗余量（初始值 10.0）
}
```

**momentum_score 关怀信号：**

| 区间 | 行为 |
|------|------|
| 首次跌破 0.3 | 触发情感类 Nudge（不推任务） |
| 持续 < 0.3 | 激活 Sub-threading + 心愿单激励 |

### 5.4 WhatsApp 接口

- **自然语言确认**：废弃「回复 1/2」，LLM 理解「好啊」「行」「等下再说」
- **语音输入**：Whisper API 转录 → 同一解析流程
- **渐进式唤醒**：事件前 30 分钟话题引入，非闹钟式
- **静默确认（Implicit Ack）**：见第 8.4 章

### 5.5 拖延深度干预

- **Sub-threading**：微粒化任务 + 多米诺能量动效
- **关联激励**：心愿单驱动，每日最多 1 次

### 5.6 心愿单系统

- WhatsApp「我想去……」→ AI 识别 → 加入心愿单
- 激励匹配：时间 + 地理 + 情感三维匹配
- 完成后生成情感 Thread，成为记忆回溯素材

### 5.7 情感价值链

- **记忆回溯**：晨间 Nudge，朋友分享语气
- **情感总线**：跨用户情感信号 → 另一方 Nudge
- **Kill Switch**：单击断开，无弹窗，优雅降级

### 5.8 技能事件双向量标准

**标准事件结构（技能层输出）：**

```json
{
  "event_type": "add_thread",
  "service": "nudge",
  "entities": {
    "content": "特斯拉最近保养费越来越贵了",
    "category": "life",
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

**Intent Vector 三个固定维度** *(v0.8 精确化)*：

| 维度 | 含义 | 评分示例 |
|------|------|---------|
| **Urgency**（紧迫感）| 这件事有多急 | 「今天截止的报告」= 0.95；「随口一提」= 0.1 |
| **Social_Bond**（情感联结）| 这件事与关系/情感的绑定程度 | 「生日礼物」= 0.9；「加油费记账」= 0.1 |
| **Goal_Alignment**（目标一致性）| 与家庭长期目标的契合度 | 「存钱买房」= 0.85；「买零食」= 0.2 |

**Brain 的编织判断逻辑：**  
两条事件的 Intent Vector 点积 > 0.7，且 Fact Vector Cosine > 对应分类阈值时，Brain 才生成 Weaving 提议。单纯事实相似、意图相悖的事件（如「省钱计划」vs「冲动消费」）不会被编织为正向关联，而是进入冲突预警流程。

**技能层的标注策略：**
- `urgency`：从 priority 字段 + deadline 距今天数自动计算
- `social_bond`：从 category（Emo 类权重最高）+ person 字段推断
- `goal_alignment`：从家庭长期 Weaving 的主题向量相似度计算（冷启动期默认 0.5）
- 无法推断时留空，Brain 视为三维均值（0.5, 0.5, 0.5）处理

---

## 6. 用户界面设计

### 6.1 三层视图

```
层级一：今日卡片视图（默认）
  ↓ 切换
层级二：家庭图谱视图（Ego-centric ↔ Full Graph）
  ↓ 点击节点
层级三：节点详情视图
```

### 6.2 家庭图谱视图

- **跨技能节点**：OurCents 的消费事件、Reminder 的里程碑可以显示为图谱节点（灰色，只读）
- **金色关联边**：Brain 发现 Thread 与财务事件相关时，显示跨技能 Weaving
- **家庭健康度指示**：Brain 每日计算图谱的「活跃度 / 密度 / 动能分布」，看板顶部可视化

### 6.3 自适应热力图视图

**节点热度公式：**
```
热度 = 最近 Nudge 引用 × 0.4
     + 最近 7 天浏览/编辑 × 0.3
     + 地理相关度 × 0.2
     + 时间段相关度 × 0.1
```

| 热度区间 | 节点表现 |
|---------|---------|
| 高热（> 0.7） | 全亮、较大、浮动 ±5px |
| 中热（0.3–0.7） | 正常亮度和大小 |
| 低热（0.1–0.3） | 透明度 60%，缩小 15% |
| 冷却（< 0.1）| 透明度 30%，缩小 25%，悬停才显示标签 |

冷却节点仍然存在于图谱中，不自动删除。

### 6.4 时间透视（Time Perspective）*(v0.8 新增)*

> 将知识图谱从「静态快照」变成「动态电影」。用户可以在 Web 端拖动时间轴，观察认知状态随时间的演变。

**时间轴交互设计：**

```
←────────────────── 时间轴 ──────────────────→
[过去 30 天]    [当前 / 今天]    [未来推演]
     ↑                ↑               ↑
  历史回放         默认视图       Brain 预测图景
```

**三种视图模式：**

| 模式 | 内容 | 数据来源 |
|------|------|---------|
| **历史回放**（左滑）| 过去某一天的认知图谱快照 | Brain 每日保存一次图谱状态快照 |
| **当前视图**（默认）| 实时热力图谱 | Active Pool 实时数据 |
| **未来推演**（右滑）| Brain 基于当前 Weaving 推演的可能发展 | Proactive Nudge Generator 的推演结果可视化 |

**未来推演的呈现原则：**
- 推演节点用虚线轮廓表示，与实际节点明确区分
- 悬停时显示 Brain 的推演理由（一句话）
- 推演最长看 30 天，不做长期预测（避免过度权威感）
- 推演内容不主动弹出，只在用户右滑时可见

**图谱历史快照策略：**
- 每日凌晨 2 点保存一次 Active Pool 的完整状态快照
- 保留最近 90 天，超出后自动清理
- 快照存储量估算：1000 节点 × 500 bytes × 90 天 ≈ 45MB（可接受）

### 6.5 Weaving 纠正交互 *(v0.8 新增)*

> 用户在图谱上发现 Brain 编织错误时，可以通过以下操作触发逆向编织。

**纠正入口：**
- 右键点击一条 Weaving 边 → 「断开这条关联」
- 节点详情页 → 「告诉 Alfred 这个关联不对」+ 可选填写原因

**断开操作的视觉反馈：**
1. 边立即变为灰色删除线（不消失，作为历史记录保留）
2. 显示轻提示：「已告诉 Alfred，他会记住的」
3. Brain 后台触发 USER_CORRECTION 事件（见第 7 章）

---

## 7. 功能需求（大脑层）

### 7.1 Brain 的核心职责

1. **持续观察**：接收来自所有技能的事件流
2. **建立图谱**：在 Qdrant 中维护家庭认知图谱
3. **发现洞察**：定期分析 Active Pool，发现 Weaving 机会
4. **仲裁 Nudge**：推送前执行全局兼容性校验 + 情感预算检查
5. **主动推送**：通过感官层发送通过双重过滤的 Nudge
6. **接受纠正**：将用户的 USER_CORRECTION 作为最高权重反馈更新认知
7. **维护图谱健康**：定期清理弱关联，保持图谱精干

### 7.2 Brain 的五个后台工作器

**① 事件处理器（Event Processor）— 实时**
- 触发：技能执行成功后，感官层异步广播
- 行为：解析双向量（含三维 Intent Vector），写入 Qdrant，新事件加入 Active Pool
- **节点锁机制**：写入前对涉及节点标记 `processing` 状态，写入完成后释放（见第 9.3 章）
- 延迟：< 500ms

**② 语义聚类器（Semantic Clusterer）— 每周**
- 触发：每周一次
- 行为：仅扫描 Active Pool，使用 Intent Vector 点积 + Fact Vector Cosine 双重评分
- 编织判断标准：Intent Vector 点积 > 0.7 且 Fact Cosine > 分类阈值
- 生成 Weaving 提议前，交 Decision Arbiter 审核
- 资源上限：500 节点/次

**③ 主动 Nudge 生成器（Proactive Nudge Generator）— 每日**
- 触发：每日一次，结合家庭成员的规律窗口时间
- 行为：生成候选 Nudge，标注情感重量（L1-L4）
- 经 Decision Arbiter → 情感预算双重过滤后，最终每日 1-2 条送达

**④ 决策仲裁器（Decision Arbiter）— 实时，前置于所有推送**

仲裁器依次执行五项检查：

```python
async def arbitrate(candidate_nudge: Nudge, family_id: str) -> ArbitrateResult:
    # 检查 1：时间窗口密度
    recent_nudges = await get_recent_nudges(family_id, hours=2)
    if len(recent_nudges) >= NUDGE_DENSITY_LIMIT:
        return ArbitrateResult.DEFER

    # 检查 2：情感预算（v0.8 新增）
    persona = await get_persona(candidate_nudge.user_id)
    budget_remaining = persona.emotional_budget_24h
    nudge_cost = EMOTIONAL_COST[candidate_nudge.level]   # L1=0.5 L2=1.0 L3=2.0 L4=3.0
    if budget_remaining < nudge_cost:
        if candidate_nudge.level >= L3:
            return ArbitrateResult.DEFER               # 重量级延迟到次日
        else:
            return ArbitrateResult.DOWNGRADE_TO_SILENT  # 轻量级降为静默提醒

    # 检查 3：语义冲突
    pending_nudges = await get_pending_nudges(family_id)
    for existing in pending_nudges:
        conflict_score = await semantic_conflict_check(candidate_nudge, existing)
        if conflict_score > CONFLICT_THRESHOLD:
            return resolve_conflict(candidate_nudge, existing)

    # 检查 4：情绪负载
    if persona.kill_switch_active:
        return ArbitrateResult.SUPPRESS
    if persona.momentum_score < 0.2 and candidate_nudge.nudge_type == "task":
        return ArbitrateResult.CONVERT_TO_EMOTIONAL

    # 检查 5：USER_CORRECTION 历史过滤（v0.8 新增）
    # 如果这条 Nudge 基于用户曾经纠正过的 Weaving 关联，不推送
    if await is_based_on_corrected_weaving(candidate_nudge):
        return ArbitrateResult.SUPPRESS

    # 扣除情感预算
    await deduct_emotional_budget(candidate_nudge.user_id, nudge_cost)
    return ArbitrateResult.APPROVED
```

**仲裁结果类型：**

| 结果 | 含义 |
|------|------|
| `APPROVED` | 立即推送 |
| `DEFER` | 延迟到下一个合适窗口 |
| `SUPPRESS` | 本次丢弃 |
| `CONVERT_TO_EMOTIONAL` | 任务语气 → 关怀语气 |
| `RESOLVE_CONFLICT` | 合并冲突 Nudge 后发送 |
| `DOWNGRADE_TO_SILENT` | 降级为静默提醒（Badge / 震动，无文字 Nudge）|

**⑤ 熵减进程（Entropy Reduction）— 每月**

```python
async def run_entropy_reduction(family_id: str):
    weak_edges = await get_weak_edges(
        family_id,
        max_weight=0.15,        # 关联权值 < 0.15
        inactive_days=180,      # 超过 6 个月未激活
        exclude_corrected=True  # 用户纠正边不参与自动清理（永久保留为历史记录）
    )
    for edge in weak_edges:
        if edge.source.is_archived and edge.target.is_archived:
            await delete_weaving_edge(edge)
        else:
            await notify_user_for_confirmation(...)
```

### 7.3 情感预算（Emotional Budget）*(v0.8 新增)*

> 防止用户在短时间内被高情感重量的 Nudge 连续轰炸，尤其保护对「被管理」高度敏感的 Kelly。

**情感预算规则：**

```
每位用户的 24 小时情感预算初始值 = 10.0 分
每条 Nudge 发送后，扣除对应情感消耗值（L1=0.5, L2=1.0, L3=2.0, L4=3.0）
每 24 小时自动重置为 10.0

预算不足时的降级策略：
  - L1/L2 Nudge：改为静默提醒（消耗值降为 0.1）
  - L3 Nudge：延迟到次日预算重置后
  - L4 Nudge：延迟到次日，且重新评估是否仍有必要

特殊情况：
  - momentum_score < 0.2 时，情感预算的 L1/L2 消耗值减半（系统保护模式）
  - 用户主动发起对话时，不计入情感预算（用户已经在场）
```

**预算可视化：** Web 看板的「家庭健康度」模块可以选择性展示今日情感预算余量（作为调试工具，上线后默认隐藏）。

### 7.4 逆向编织（USER_CORRECTION）*(v0.8 新增)*

> 用户的纠正是最高权重的信号，Brain 必须记住并持续应用。

**USER_CORRECTION 事件结构：**

```json
POST /brain/events
{
  "event_id": "uuid",
  "event_type": "correct_weaving",
  "event_action": "USER_CORRECTION",
  "entity_id": "weaving_edge_xxx",
  "correction_type": "disconnect",  // "disconnect" | "relabel" | "reverse_polarity"
  "correction_reason": "这两件事没有关系",  // 可选
  "user_id": "+8613800000000",
  "family_id": "fam_xxx",
  "timestamp": "2026-05-04T15:00:00Z"
}
```

**Brain 收到 USER_CORRECTION 后的处理：**

```python
async def handle_user_correction(event: BrainEvent):
    edge = await get_weaving_edge(event.entity_id)

    # 1. 立即将该边的权值降为 0（在 Qdrant 中更新）
    await qdrant.update_payload(
        "weaving_map",
        id=event.entity_id,
        payload={"weight": 0.0, "corrected_by_user": True, "corrected_at": now()}
    )

    # 2. 将该边的两端节点对，加入「负样本记忆」
    await add_negative_sample(
        source_id=edge.source_id,
        target_id=edge.target_id,
        family_id=event.family_id,
        reason=event.correction_reason
    )

    # 3. 更新 Qdrant 中两个节点的关联矩阵
    # 下次 Semantic Clusterer 运行时，这对节点的 Cosine 相似度结果
    # 会被负样本记忆做 penalty（乘以衰减系数 0.1）
    await register_correction_penalty(edge.source_id, edge.target_id, penalty=0.1)

    # 4. 如果 Decision Arbiter 有任何基于此边的待发 Nudge，立即撤销
    await cancel_nudges_based_on_edge(event.entity_id)
```

**负样本记忆的持久化：**

```
SQLite（brain.db）新增表：
correction_memory {
  id, family_id,
  source_node_id, target_node_id,
  correction_type, reason,
  penalty_coefficient: float,  // 默认 0.1
  created_at
}
```

**重要原则：** 负样本记忆**永不自动过期**。只有用户主动「恢复这条关联」时才解除 penalty。

### 7.5 激活池（Active Pool）设计

**纳入标准（满足任意一条）：**

| 条件 | 说明 |
|------|------|
| 最近 30 天内有任意更新 | 被编辑、关联、浏览均计入 |
| 最近 30 天内被 Nudge 引用 | Brain 曾以此节点生成 Nudge |
| 与当前 Geofence 相关 | 节点有 `location_tag` 且用户最近进入该区域 |
| 用户手动「置顶」| 用户在前台标记为常驻活跃 |

**退出机制：** 连续 30 天无激活 → 移入 Archive Pool（热力图冷却显示）

**容量上限：** 1000 节点/Family（待 Q14 确认）

### 7.6 Weaving 生命周期（完整版）

```
技能层事件 → 感官层广播（CREATE / INVALIDATE / USER_CORRECTION）
  → Brain Event Processor
     ├── CREATE：双向量解析 → Qdrant 写入（原子锁）→ Active Pool
     ├── INVALIDATE：标记 needs_reweave → 下周重新验证
     └── USER_CORRECTION：权值归零 → 负样本记忆 → 撤销关联 Nudge

  → 每周 Semantic Clusterer（仅 Active Pool）
     → Intent Vector 点积 + Fact Cosine 双重评分
     → 生成 Weaving 提议

  → Decision Arbiter 审核 + 情感预算过滤
     → 通过 → 推送给用户确认
        ├── 显式确认（Richard 风格）：点击「确认」
        └── 静默确认（Kelly 风格）：无反对 + 继续对话 → 自动接受

  → confirmed Weaving
     → 可挂载 Reminder / 关联外部链接 / 被其他 Weaving 引用
     → 连续 30 天无激活 → Archive Pool（热力图冷却）

  → 每月熵减进程
     → 弱关联被清理（边）
     → 用户纠正边：永久保留，不参与熵减
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

你希望我平时说话，是像个能懂你情绪的朋友，
还是干干净净说重点就好？」
```

**Step 2：探索动能（等 Step 1 回应后）**
```
「如果一件事你一直没动，
你更想我帮你把它拆成小步子，
还是先给你找个奖励来撑着走？」
```

**Step 3：心愿单初始化（等 Step 2 回应后）**
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

### 8.2 24 小时 Onboarding 旅程

| 时间点 | 动作 |
|--------|------|
| T+0 | 冷启动脚本（四步，呼吸节奏）|
| T+1h | 引导发送第一条 Thread，立即图谱反馈 |
| T+8h | 第一次「隐形编织」（Aha! 时刻）|
| T+24h | 动能复盘，正向收尾 |

### 8.3 成功指标

| 指标 | 目标 |
|------|------|
| 冷启动完成率 | > 80% |
| T+1h 首条录入率 | > 70% |
| T+8h Aha! 体验率 | > 60% |
| D7 留存率 | > 50% |

### 8.4 静默确认（Implicit Ack）*(v0.8 新增)*

> 专为 Kelly 的 Persona 设计。高摩擦的「请点击确认」会破坏对话的自然感。

**触发条件（同时满足）：**
1. 用户 `implicit_ack_enabled = true`（Kelly 默认开启，Richard 默认关闭）
2. Weaving 提议为轻量级（L1 或 L2 情感重量）
3. Brain 发出提议后，用户在 30 分钟内：
   - 没有点击「不对」或「取消」
   - 在 WhatsApp 上发送了任意新消息（表明用户仍在活跃）

**静默确认后的处理：**
- Weaving 状态从 `proposed` 升级为 `confirmed`
- 热度自动设置为中热（0.5），进入 Active Pool
- 不发送任何通知（静默即是接受）
- 保留 24 小时撤销窗口：用户可以说「刚才那个编织取消」→ Brain 理解并执行 USER_CORRECTION

**静默确认不适用的场景：**
- L3 / L4 情感重量的 Weaving（重要决策必须显式确认）
- 涉及删除、修改已有 Weaving 的操作
- 跨技能 Weaving 首次创建（首次的重要关联需要显式确认）

---

## 9. 技术架构

### 9.1 Alfred 整体拓扑

```
┌─────────────────────────────────────────────────────┐
│                  【大脑层】BRAIN  :8003               │
│                                                     │
│  后台工作器：                                        │
│  ① Event Processor（实时，含原子锁）                  │
│  ② Semantic Clusterer（每周，Intent+Fact 双评分）     │
│  ③ Proactive Nudge Generator（每日）                 │
│  ④ Decision Arbiter（实时，含情感预算）               │
│  ⑤ Entropy Reduction（每月，跳过用户纠正边）          │
│                                                     │
│  存储：SQLite（weavings + nudge_log + correction_memory）│
│        Qdrant :6333                                 │
│        Active Pool（内存，1000 节点上限）             │
│        图谱历史快照（每日，保留 90 天）               │
└──────────────────────┬──────────────────────────────┘
                       │  CREATE / INVALIDATE / USER_CORRECTION
                       │  主动推送 /api/internal/push
                       ▼
┌─────────────────────────────────────────────────────┐
│                 【感官层】SENSES                      │
│   WhatsApp → Bridge :3001 → GATEWAY :8000            │
│   广播：CREATE / INVALIDATE / USER_CORRECTION        │
└───────────┬──────────────┬──────────────────────────┘
            ▼              ▼
┌───────────────────────────────────────────────────┐
│                   【技能层】SKILLS                  │
│   Nudge :8002 │ OurCents :8001 │ ～～ 未来技能      │
│   事件输出：Fact Vector + Intent Vector（三维）      │
└───────────────────────────────────────────────────┘
                            │
                      ┌─────▼───────────┐
                      │    Web 前端     │
                      │  ・今日卡片     │
                      │  ・家庭图谱     │
                      │    - 热力图     │
                      │    - 时间透视   │
                      │    - 纠正交互   │
                      │  ・知识库       │
                      └─────────────────┘
```

### 9.2 三层对比

| 维度 | 大脑层（Brain）| 感官层（Gateway）| 技能层（Nudge/OurCents）|
|------|--------------|----------------|----------------------|
| 主要职责 | 思考、学习、仲裁、关心、接受纠正 | 感知、路由、广播 | 执行领域逻辑 |
| 触发方式 | 事件驱动 + 定时任务 | 用户消息触发 | 感官层派发触发 |
| 状态性 | 有状态（图谱 + Pool + 负样本记忆）| 无状态 | 无状态 |
| 作用域 | 家庭（Family）| 单用户通道 | 单用户 |
| 延迟 | 可接受分钟级 | < 3 秒 | < 3 秒 |

### 9.3 Gateway 事件广播机制

**三类事件广播：**

```python
# dispatch_service.py

# ① CREATE（技能执行成功）
async def _on_skill_success(self, intent, entities, user_id, family_id):
    asyncio.create_task(brain_client.publish_event({
        "event_action": "CREATE",
        "event_type": intent,
        "entities": entities,   # 含 fact_context + intent_context + intent_vector
        "user_id": user_id, "family_id": family_id, "timestamp": now()
    }))

# ② INVALIDATE（数据删除或大幅修改）
async def _on_data_mutation(self, entity_id, mutation_type, user_id, family_id):
    if mutation_type in ("DELETE", "MAJOR_EDIT"):
        asyncio.create_task(brain_client.publish_event({
            "event_action": "INVALIDATE",
            "entity_id": entity_id,
            "user_id": user_id, "family_id": family_id, "timestamp": now()
        }))

# ③ USER_CORRECTION（用户在 Web 端纠正 Weaving）
async def _on_user_correction(self, edge_id, correction_type, reason, user_id, family_id):
    asyncio.create_task(brain_client.publish_event({
        "event_action": "USER_CORRECTION",
        "entity_id": edge_id,
        "correction_type": correction_type,
        "correction_reason": reason,
        "user_id": user_id, "family_id": family_id, "timestamp": now()
    }))
```

### 9.4 Qdrant 原子锁（Node Locking）*(v0.8 新增)*

> 防止 Event Processor 处理新事件期间，Semantic Clusterer 或前台图谱查询读取到不一致的中间状态，导致图谱「闪烁」。

**锁机制设计：**

```python
async def process_event_with_lock(event: BrainEvent):
    affected_nodes = extract_node_ids(event)

    # 1. 在 Qdrant payload 中标记节点为 "processing"
    for node_id in affected_nodes:
        await qdrant.set_payload("weaving_map", node_id, {"lock_status": "processing"})

    try:
        # 2. 执行实际的 Embedding 生成和图谱更新
        await do_weaving_update(event)

    finally:
        # 3. 无论成功或失败，释放锁
        for node_id in affected_nodes:
            await qdrant.set_payload("weaving_map", node_id, {"lock_status": "ready"})

# 前台图谱查询时，过滤掉 lock_status = "processing" 的节点
async def get_graph(family_id: str):
    return await qdrant.search(
        "weaving_map",
        filter={"lock_status": "ready"},  # 只返回 ready 状态的节点
        family_id=family_id
    )
```

**锁超时保护：** 若节点处于 `processing` 状态超过 5 秒（网络超时或崩溃），后台定时任务自动重置为 `ready`，避免死锁。

### 9.5 数据层

```
SQLite（技能层，各服务独立）
  ├── Gateway: contacts, conversations, messages, alfred_users, families
  ├── Nudge:   threads, reminders, thread_links
  └── OurCents: expenses, incomes, budgets

SQLite（大脑层专属）
  ├── brain_events:       接收的事件队列（含 event_action）
  ├── weavings:           id, family_id, title, core_knowledge,
  │                       source_thread_ids, source_skill_events,
  │                       edge_weights, last_activated_at, status, timestamps
  ├── nudge_log:          所有推送记录（含情感重量，供预算计算）
  ├── correction_memory:  用户纠正记录（永不过期）
  │                       id, family_id, source_node_id, target_node_id,
  │                       correction_type, reason, penalty_coefficient
  └── graph_snapshots:    每日图谱快照（供时间透视功能，保留 90 天）

内存缓存（Brain 进程内）
  └── active_pool:   热节点集合（LRU，1000 上限）

Qdrant（本地 :6333）
  ├── threads_pro / threads_life / threads_emo / threads_routine
  └── weaving_map   // 新增字段：lock_status, intent_vector(3D), corrected_by_user
```

### 9.6 技术选型

| 层级 | 选型 |
|------|------|
| 前端 | React + D3.js + TypeScript |
| 感官层 | Python FastAPI（Gateway）+ Node.js（Bridge）|
| 技能层 | Python FastAPI（各技能独立进程）|
| 大脑层 | Python FastAPI（Brain）|
| 关系数据库 | SQLite |
| 向量数据库 | **Qdrant（本地，:6333）**|
| AI 推演 | Claude API |
| 意图识别 | gpt-4o-mini |
| Embedding | text-embedding-3-small |
| 语音转录 | Whisper API |
| 消息推送 | WhatsApp Business API / Bridge |
| 位置服务 | iOS/Android Geofencing |

---

## 10. Alfred 三层架构

### 10.1 架构全景

```
Alfred = 大脑（Brain）+ 感官（Senses）+ 技能（Skills）
```

| Alfred 命名 | 智能体术语 | 核心问题 |
|------------|-----------|---------|
| 大脑（Brain）| Reasoning / Memory | Alfred 怎么思考、学习和纠错？ |
| 感官（Senses）| Perception / Action | Alfred 怎么感知和表达？ |
| 技能（Skills）| Tool / Capability | Alfred 能做什么？ |

### 10.2 各层职责边界

**大脑层（Brain :8003）**
- 家庭维度，异步，不响应即时请求
- 五个工作器：观察 / 聚类 / 推送 / 仲裁 / 清理
- 三类记忆：向量图谱（Qdrant）+ 元数据（SQLite）+ 负样本记忆（永久）
- 三类信号权重：技能事件（低）< 感官广播（中）< 用户纠正（最高）

**感官层（Gateway :8000 + Bridge :3001）**
- 用户维度，同步，唯一对外通信层
- 三类广播：CREATE / INVALIDATE / USER_CORRECTION
- 不执行业务逻辑，不主动发起 Nudge

**技能层（Nudge :8002 / OurCents :8001 / 未来）**
- 用户维度，同步，互不感知
- 标准接口（ASI）+ 双向量输出（Fact + Intent 三维）
- 不主动与用户通信

### 10.3 扩展成本

**新增技能：** 实现 ASI 接口 + 注册 `services.yaml` + 双向量输出  
**新增感官通道：** 实现 Bridge，将输入转为统一格式 POST 到 Gateway  
**Brain 代码：** 两种扩展均不需要修改 Brain

### 10.4 对现有代码的最小侵入

| 文件 | 改动内容 | 改动量 |
|------|---------|--------|
| `dispatch_service.py` | 三类广播（CREATE / INVALIDATE / USER_CORRECTION）| +26 行 |
| `services.yaml` | Brain 服务注册 | +5 行 |
| `services/brain/` | 全新服务（5 个工作器）| 新建 |
| `web/src/` | 图谱页（热力图 + 时间透视 + 纠正交互）| 新建 |

---

## 11. Brain 服务规格

### 11.1 服务信息

| 属性 | 值 |
|------|---|
| 目录 | `services/brain/` |
| 端口 | :8003 |
| 技术栈 | Python / FastAPI |
| 数据库 | SQLite + Qdrant + 内存 Active Pool |

### 11.2 API 端点

| 端点 | 鉴权 | 用途 |
|------|------|------|
| `GET /health` | 公开 | 健康检查 |
| `GET /alfred/capabilities` | API-Key | 声明 intent |
| `POST /alfred/execute` | API-Key | 执行 Brain intent |
| `POST /brain/events` | API-Key | 接收三类事件 |
| `GET /brain/graph/{family_id}` | JWT | 图谱数据（含热度 + lock 过滤）|
| `GET /brain/graph/{family_id}/snapshot/{date}` | JWT | 历史快照（时间透视）|
| `GET /brain/graph/{family_id}/forecast` | JWT | 未来推演（时间透视右滑）|
| `GET /brain/weavings/{family_id}` | JWT | Weaving 列表 |
| `POST /brain/weavings/{id}/confirm` | JWT | 显式确认 |
| `POST /brain/weavings/{id}/correct` | JWT | 用户纠正 |
| `GET /brain/active_pool/{family_id}` | JWT | 调试：Active Pool 状态 |
| `GET /brain/emotional_budget/{user_id}` | JWT | 调试：情感预算余量 |

**Brain 专属 Intent：**

| Intent | 功能 |
|--------|------|
| `show_graph` | 当前图谱摘要（含热力分布）|
| `list_weavings` | 已确认 Weaving 列表 |
| `get_weaving` | Weaving 详情 |
| `confirm_weaving` | 显式确认 |

### 11.3 后台工作器总览

| 工作器 | 频率 | 核心职责 | 资源上限 |
|--------|------|---------|---------|
| ① Event Processor | 实时 | 双向量解析，Qdrant 写入（原子锁）| < 500ms |
| ② Semantic Clusterer | 每周 | Active Pool 扫描，Intent+Fact 双评分 | 500 节点 |
| ③ Proactive Nudge Generator | 每日 | 生成候选 Nudge，交仲裁+预算过滤 | 1-2 条/日 |
| ④ Decision Arbiter | 实时（前置）| 5 项检查：密度/预算/冲突/情绪/纠正历史 | < 100ms |
| ⑤ Entropy Reduction | 每月 | 清理弱关联边（跳过用户纠正边）| 50 条/次 |

---

## 12. 非功能性需求

### 12.1 隐私与安全
- 向量数据本地存储（Qdrant 自托管）
- Brain 跨用户分析仅限同一 Family
- 情感总线：双向同意 + Kill Switch
- 私密 Thread 不进入 Qdrant
- 用户纠正记忆永久保留，不受熵减影响

### 12.2 性能
- 技能层响应：< 3 秒
- Brain CREATE 事件处理：< 500ms
- Brain INVALIDATE 事件处理：< 200ms
- Brain USER_CORRECTION 处理：< 300ms（含 Qdrant 权值更新）
- Decision Arbiter：< 100ms
- 图谱查询（含热度 + lock 过滤）：< 200ms
- 历史快照查询：< 500ms
- 动效帧率：≥ 60fps

### 12.3 克制原则
- Nudge 日均上限：4 条（Decision Arbiter 统一计数）
- 情感预算：24 小时总消耗上限 10.0 分
- Brain 每周最多提议 3 个 Weaving
- 用户拒绝的 Weaving 主题，3 个月内不重复提议
- 熵减只删「边」，不删「节点」
- 时间透视的未来推演最长 30 天，不做长期预言
- 静默确认只适用于 L1/L2 轻量级 Weaving

---

## 13. 开放问题与待讨论项

| # | 问题 | 优先级 |
|---|------|-------|
| Q1 | Thread 休眠阈值（建议 7 天，可配置）| 高 |
| Q2 | Ego-centric 节点评分权重（建议 6:4）| 高 |
| Q3 | Kill Switch 断开时 UI 细节 | 高 |
| Q4 | 卫星节点阈值（0.85 待 A/B 测试）| 高 |
| Q5 | ✅ WhatsApp Onboarding | 已解决（第 8 章）|
| Q6 | Geofence 半径（建议 500m，可配置）| 中 |
| Q7 | Sub-thread 拆解主导权（AI 提议，用户逐步确认）| 中 |
| Q8 | Brain 每周 Weaving 提议上限（建议 3 个）| 中 |
| Q9 | Brain 的 Qdrant：与 Nudge 共用实例还是独立实例？| 中 |
| Q10 | ✅ Persona 冷启动脚本 | 已解决（第 8 章）|
| Q11 | Brain 提议 Weaving 时，如何让用户轻松修改 AI 生成标题？| 中 |
| Q12 | 跨技能关联边（金色）在图谱上是否可能过于密集？| 低 |
| Q13 | Spark 状态的定义和生命周期 | 低 |
| Q14 | Active Pool 容量上限（建议 1000）及 30 天冷热边界是否合适？| 中 |
| Q15 | Intent Vector 三维度的冷启动期默认值（0.5, 0.5, 0.5）是否合理？goal_alignment 如何在家庭没有明确长期目标时计算？| 中 |
| Q16 | 熵减弱边阈值（权值 < 0.15 + 6 个月未激活）是否过于激进？| 低 |
| Q17 | 情感预算初始值（10.0）和各级消耗值是否合理？Kelly 和 Richard 是否应有不同的预算上限？| 中 |
| Q18 | 静默确认的 30 分钟超时窗口是否合适？如何在 WhatsApp 端明确告知用户「不回复即视为同意」？| 中 |

---

## 14. 版本路线图

### v0.1–v0.6 ✓（已完成）

### v0.7 ✓ — 架构漏洞封堵 + 生物逻辑补全
- [x] Decision Arbiter / INVALIDATE_EVENT / Active Pool
- [x] Entropy Reduction / 热力图 / 双向量标准

### v0.8 ✓ — MVP 就绪版（当前）
- [x] 逆向编织（USER_CORRECTION）+ 负样本记忆
- [x] 情感预算（Emotional Budget）
- [x] Qdrant 原子锁（Node Locking）
- [x] Intent Vector 三维度标准（Urgency / Social_Bond / Goal_Alignment）
- [x] 时间透视（Time Perspective）
- [x] 静默确认（Implicit Ack）for Kelly

---

### 🏁 v0.9 — MVP 最小闭环（下一个里程碑）

**目标：打通一条完整的金色线**

```
你在 WhatsApp 发一句「特斯拉最近保养费越来越贵了」
  ↓
Nudge 技能保存 Thread，含 Intent Vector（焦虑感，Goal_Alignment=0.5）
  ↓
感官层广播 CREATE 事件
  ↓
Brain Event Processor 写入 Qdrant，加入 Active Pool
  ↓
Brain 发现 OurCents 里有「特斯拉保养 ¥3200」的财务记录
Intent Vector 点积 > 0.7，Fact Cosine > 0.72（生活类阈值）
  ↓
Decision Arbiter 审核通过，情感预算充足
  ↓
Brain 提议 Weaving：「[特斯拉用车成本] Thread ↔ OurCents」
  ↓
Web 端图谱：两个节点之间，连出一根金色的线
```

**v0.9 实施任务清单：**
- [ ] Thread CRUD + WhatsApp Bot 基础版
- [ ] 今日卡片视图（静态 Nudge）
- [ ] Persona Profile 冷启动流程（Kelly Implicit Ack 开启）
- [ ] Ego-centric 图谱（含卫星节点 + 基础热力图）
- [ ] **Brain 基础版**：Event Processor + Qdrant 写入 + Active Pool + 原子锁
- [ ] **Decision Arbiter 基础版**：时间密度 + Kill Switch + 情感预算（三项）
- [ ] **最小 Weaving 闭环**：跨技能金色线（Thread ↔ OurCents）
- [ ] Qdrant 本地部署（Docker）

### v1.0 — AI 编织核心
- [ ] Semantic Clusterer（每周聚类 + Weaving 提议）
- [ ] Decision Arbiter 完整版（语义冲突 + 纠正历史过滤）
- [ ] 静默确认完整实现
- [ ] USER_CORRECTION 逆向编织 + 负样本记忆
- [ ] Intent Vector 三维度完整标注（告别冷启动默认值）
- [ ] WhatsApp 语音录入

### v1.1 — 情感与干预层
- [ ] 情感总线 + Kill Switch + 优雅降级
- [ ] 记忆回溯
- [ ] Sub-threading + 多米诺动效
- [ ] 心愿单 + 关联激励
- [ ] Proactive Nudge Generator（每日主动推送）
- [ ] INVALIDATE_EVENT 级联失效完整实现
- [ ] Entropy Reduction 熵减进程
- [ ] 时间透视（历史回放 + 未来推演）

### v1.2 — 空间与跨技能层
- [ ] Geofencing 空间触发
- [ ] 跨技能 Weaving 完整版（三技能交叉洞察）
- [ ] 家庭知识库 Web UI（含热力图完整版）
- [ ] 规律统计学习

### v1.3 — 完整体验
- [ ] 规律预测模型（时序 AI）
- [ ] 移动端原生 App
- [ ] 动态阈值个性化（贝叶斯）
- [ ] 多技能扩展（Health / Calendar / ...）
- [ ] Health × Emo Thread 跨技能 Weaving

---

*本文档为活文档，随产品讨论持续迭代。*  
*v0.8 是设计阶段的封存版本，架构已在逻辑层面完全闭环。*  
*v0.9 的唯一目标：让一根金色的线出现在图谱上。其余的都是后话。*
