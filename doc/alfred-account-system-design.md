# Alfred 统一账号体系 — 技术设计文档

> **版本**: v1.0  
> **用途**: 供 Claude programming tool 实现  
> **范围**: 账号管理、权限、Family 组、Bot 命令、API、数据库 Schema

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| WA 号码即身份 | 每个 Alfred 用户以 WhatsApp 号码（E.164 格式）作为唯一主键身份 |
| Bot 号码与用户解耦 | Alfred Bot 号码只是消息通道，与用户账号无关，换号不影响数据 |
| Admin 集中管理 | 账号增删改、Family 管理全部由 Admin 控制，用户不能自助注册 |
| Bot 即管理界面 | Admin 通过 Bot 命令完成所有管理操作，Web Settings 是辅助界面 |
| 无 Web 登录 | **不保留** username/password 登录体系，无 OurCents/Reminder 独立账号 |
| 删除即彻底 | 删除用户级联删除所有应用数据（账单、提醒、笔记等） |
| Family 是组合层 | 用户可单独存在或加入 Family，Family 功能 v2 实现共享视图 |

---

## 2. 角色与权限

### 2.1 角色定义

| 角色 | 说明 |
|------|------|
| `admin` | 管理员，可增删改用户、管理 Family、查看系统状态 |
| `user` | 普通用户，只能操作自己的应用数据 |

### 2.2 权限矩阵

| 操作 | admin | user |
|------|:-----:|:----:|
| 添加用户 | ✅ | ❌ |
| 删除用户 | ✅ | ❌ |
| 提升/降级角色 | ✅ | ❌ |
| 创建/解散 Family | ✅ | ❌ |
| 管理 Family 成员 | ✅ | ❌ |
| 查看系统用户列表 | ✅ | ❌ |
| 操作自己的应用数据 | ✅ | ✅ |

### 2.3 Admin 约束

- 系统至少保留 **1 个 Admin**
- Admin 可以提升其他 user 为 admin
- Admin **不能降级自己**（防止 admin 清空）
- Admin 同时也是普通 user，可以正常使用 Alfred 记账等功能

---

## 3. 系统启动（Bootstrap）

首次部署时，通过唯一一次 HTTP 请求完成初始化：

### 3.1 Bootstrap API

```
POST /api/alfred/bootstrap
```

**Request Body**:

```json
{
  "family_name": "Zhang Family",
  "admin_phone": "+14081234567",
  "admin_display_name": "Richard"
}
```

**行为**:

1. 检查系统是否已有用户（有则返回 `409 Conflict`，拒绝重复执行）
2. 创建第一个 Family
3. 创建第一个 Admin 用户，关联到该 Family
4. 返回成功

**Response**:

```json
{
  "success": true,
  "user_id": "usr_xxxx",
  "family_id": "fam_xxxx",
  "message": "Bootstrap complete. Admin created: +14081234567"
}
```

**约束**: Bootstrap 接口在系统已有用户后永久失效（幂等保护）。

---

## 4. 数据库 Schema

### 4.1 `alfred_users` — 用户主表

```sql
CREATE TABLE alfred_users (
  id            TEXT PRIMARY KEY,          -- usr_<ulid>
  phone         TEXT NOT NULL UNIQUE,      -- E.164 格式，如 +14081234567
  display_name  TEXT,
  role          TEXT NOT NULL DEFAULT 'user', -- 'user' | 'admin'
  family_id     TEXT REFERENCES alfred_families(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alfred_users_phone ON alfred_users(phone);
CREATE INDEX idx_alfred_users_family_id ON alfred_users(family_id);
```

### 4.2 `alfred_families` — Family 表

```sql
CREATE TABLE alfred_families (
  id            TEXT PRIMARY KEY,          -- fam_<ulid>
  name          TEXT NOT NULL,
  created_by    TEXT REFERENCES alfred_users(id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.3 外键关系说明

- `alfred_users.family_id → alfred_families.id`（可为 NULL，表示无 Family）
- `alfred_families.created_by → alfred_users.id`（创建者，允许 NULL 防止循环依赖）
- 删除用户时，级联删除所有应用数据（OurCents、Reminder、Notes 各自通过 `user_id` 外键级联）

### 4.4 应用数据表（外键约束示例）

各应用数据表须包含：

```sql
user_id TEXT NOT NULL REFERENCES alfred_users(id) ON DELETE CASCADE
```

这确保删除用户时，所有相关数据自动清除。

---

## 5. 用户身份解析

每条 WhatsApp 消息到达时，系统通过以下步骤解析用户身份：

```
收到 WA 消息
  → 提取 whatsapp_id（发消息的 WA 号码，E.164 格式）
  → SELECT * FROM alfred_users WHERE phone = whatsapp_id
  → 找到 → 得到 user_id, role, family_id → 继续处理
  → 未找到 → 返回 "您的号码尚未注册，请联系管理员"
```

无需 token、session 或 cookie，号码即身份。

---

## 6. Admin Bot 命令

Admin 通过给 Alfred Bot 发以下命令管理账号（命令大小写不敏感）。

### 6.1 用户管理

#### 添加用户

```
/add user +14081234567 [display_name]
```

- 成功：`✅ 用户 +14081234567 (Richard) 已添加`
- 已存在：`⚠️ 该号码已注册`
- 权限不足：`❌ 仅 Admin 可执行此操作`

#### 删除用户

```
/remove user +14081234567
```

- 要求二次确认：`⚠️ 确认删除 +14081234567？此操作不可逆，所有数据将清除。回复 YES 确认。`
- 确认后执行级联删除
- 不能删除自己（返回错误）
- 不能删除最后一个 Admin

#### 列出用户

```
/list users
```

返回格式：

```
👥 当前用户列表（共 3 人）：
1. +14081234567 Richard [admin] — Zhang Family
2. +14089876543 Alice [user] — Zhang Family
3. +14085551234 Bob [user] — 无 Family
```

#### 提升/降级角色

```
/set role +14089876543 admin
/set role +14089876543 user
```

- 不能降级自己
- 不能删除最后一个 admin

### 6.2 Family 管理（v1 基础功能）

#### 创建 Family

```
/create family "Zhang Family"
```

#### 解散 Family

```
/dissolve family fam_xxxx
```

- 解散后成员的 `family_id` 置为 NULL，数据保留

#### 添加成员到 Family

```
/family add +14089876543 fam_xxxx
```

#### 从 Family 移除成员

```
/family remove +14089876543
```

#### 查看 Family

```
/list families
```

### 6.3 系统状态

```
/status
```

返回：

```
📊 Alfred 系统状态
用户总数：3
Family 总数：1
Admin：+14081234567 Richard
版本：v1.0
```

---

## 7. REST API 设计

所有 API 以 `/api/alfred/` 为前缀。  
**认证方式**：服务端通过请求中携带的 `X-Alfred-Phone` header（内部服务间调用）或从 WA 消息上下文中注入，不使用 JWT/session。

> ⚠️ 以下 API 供内部服务和 Web Settings 页面调用，不对外公开。

### 7.1 Bootstrap

```
POST /api/alfred/bootstrap
```

见 §3.1。

### 7.2 用户 CRUD

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/alfred/users` | 列出所有用户 | admin |
| `POST` | `/api/alfred/users` | 添加用户 | admin |
| `GET` | `/api/alfred/users/:phone` | 查询单个用户 | admin |
| `PATCH` | `/api/alfred/users/:phone` | 更新用户信息/角色 | admin |
| `DELETE` | `/api/alfred/users/:phone` | 删除用户（级联） | admin |

**POST /api/alfred/users** Request Body:

```json
{
  "phone": "+14089876543",
  "display_name": "Alice",
  "family_id": "fam_xxxx"   // 可选
}
```

**PATCH /api/alfred/users/:phone** Request Body（只传需要改的字段）:

```json
{
  "display_name": "Alice Chen",
  "role": "admin",
  "family_id": "fam_xxxx"
}
```

### 7.3 Family CRUD

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/alfred/families` | 列出所有 Family | admin |
| `POST` | `/api/alfred/families` | 创建 Family | admin |
| `GET` | `/api/alfred/families/:id` | 查询 Family 详情及成员 | admin |
| `PATCH` | `/api/alfred/families/:id` | 更新 Family 名称 | admin |
| `DELETE` | `/api/alfred/families/:id` | 解散 Family | admin |

### 7.4 身份解析（内部调用）

```
GET /api/alfred/resolve?phone=+14081234567
```

Response:

```json
{
  "user_id": "usr_xxxx",
  "phone": "+14081234567",
  "display_name": "Richard",
  "role": "admin",
  "family_id": "fam_xxxx"
}
```

用于各应用模块（OurCents、Reminder 等）在处理 WA 消息时快速查询用户身份。

---

## 8. Web Settings 页面

Web Settings 是辅助管理界面，功能与 Bot 命令等价。无登录体系，访问方式待定（可通过 magic link 或限制内网访问）。

**Settings 页面模块**:

- **My Account**: 查看自己的 phone、display_name，修改 display_name
- **Family**: 查看自己所属 Family 及成员列表（只读，Admin 才能修改）
- **Admin Panel**（仅 admin 可见）:
  - 用户列表，添加/删除/角色管理
  - Family 列表，创建/解散/成员管理

---

## 9. 删除策略

### 默认行为：硬删除

执行 `DELETE /api/alfred/users/:phone` 或 `/remove user` 命令时：

1. 删除所有应用数据（通过各表 `ON DELETE CASCADE` 自动执行）
2. 删除 `alfred_users` 记录
3. 如该用户是 Family 中唯一 admin，需先转移或解散 Family（系统提示）

### 可选：30 天冷冻期（v2 扩展）

若需要 30 天恢复窗口，可在 `alfred_users` 加字段：

```sql
deleted_at TIMESTAMPTZ  -- NULL 表示正常，非 NULL 表示冻结中
```

v1 不实现此功能，默认硬删除。

---

## 10. 错误处理规范

所有 API 统一返回格式：

```json
{
  "success": false,
  "error": {
    "code": "USER_NOT_FOUND",
    "message": "No user found with phone +14089876543"
  }
}
```

常用错误码：

| Code | 说明 |
|------|------|
| `BOOTSTRAP_ALREADY_DONE` | 系统已初始化，Bootstrap 被拒绝 |
| `USER_NOT_FOUND` | 用户不存在 |
| `USER_ALREADY_EXISTS` | 号码已注册 |
| `LAST_ADMIN_PROTECTED` | 不能删除/降级最后一个 Admin |
| `SELF_DELETE_FORBIDDEN` | 不能删除自己 |
| `SELF_DEMOTE_FORBIDDEN` | 不能降级自己 |
| `PERMISSION_DENIED` | 权限不足（非 admin） |
| `PHONE_INVALID` | 手机号格式不合法（需 E.164） |
| `FAMILY_NOT_FOUND` | Family 不存在 |

---

## 11. Family v2 功能预留（不在 v1 实现）

v2 将支持 Family 共享视图：

- Family 总账单视图（所有成员的 OurCents 数据汇总）
- Family 共享提醒
- Family 共享笔记

Schema 已在 v1 中预留 `family_id` 字段，v2 只需添加查询逻辑，不需要 schema 变更。

---

## 12. 实现检查清单

### Phase 1 — 核心账号体系

- [ ] 创建 `alfred_families` 和 `alfred_users` 表（含索引）
- [ ] 实现 Bootstrap API（幂等保护）
- [ ] 实现用户 CRUD API
- [ ] 实现 Family CRUD API
- [ ] 实现身份解析 `/api/alfred/resolve`
- [ ] WA 消息处理层：每条消息先走 resolve，找不到则回复提示
- [ ] Admin 权限中间件（所有 admin API 校验 role）

### Phase 2 — Bot 命令

- [ ] 实现 `/add user`
- [ ] 实现 `/remove user`（含二次确认）
- [ ] 实现 `/list users`
- [ ] 实现 `/set role`
- [ ] 实现 `/create family`、`/dissolve family`
- [ ] 实现 `/family add`、`/family remove`、`/list families`
- [ ] 实现 `/status`

### Phase 3 — Web Settings

- [ ] My Account 页面
- [ ] Family 查看页面
- [ ] Admin Panel（用户管理 + Family 管理）

---

## 13. 技术栈假设

> 实现时按实际项目栈调整，本文档不限定具体框架。

- 数据库：PostgreSQL（推荐）或 SQLite（轻量部署）
- ID 生成：ULID（`usr_` 前缀 + ulid，`fam_` 前缀 + ulid）
- 手机号格式：E.164，存入前需校验和标准化
- Bot 框架：与现有 Alfred WA bridge 集成

---

*文档结束 — Alfred Account System Design v1.0*
