"""
Bot command handler for Alfred account management.

Commands (admin only):
  /add user +phone [name]
  /remove user +phone          (two-step: asks YES confirmation)
  /list users
  /set role +phone admin|user
  /create family "Name"
  /dissolve family fam_xxx
  /family add +phone fam_xxx
  /family remove +phone
  /list families
  /status

Called by dispatch_service before intent detection for every text message.
Returns a reply string if the message was handled, else None.
"""

import re
from typing import Optional

from sqlmodel import Session

import app.repositories.account_repository as repo

# phone → {"action": str, "target": str}
_pending_confirmations: dict[str, dict] = {}

_ADMIN_PREFIXES = (
    "/add user",
    "/remove user",
    "/list users",
    "/list families",
    "/set role",
    "/create family",
    "/dissolve family",
    "/family",
    "/status",
)


def handle_bot_command(session: Session, phone: str, text: str) -> Optional[str]:
    stripped = text.strip()

    # Pending confirmation takes priority, but a new slash command cancels it.
    if phone in _pending_confirmations:
        if stripped.startswith("/"):
            _pending_confirmations.pop(phone)
            # Fall through to handle the new command.
        else:
            return _handle_confirmation(session, phone, stripped)

    if not stripped.startswith("/"):
        return None

    user = repo.get_user_by_phone(session, phone)
    if not user:
        return None  # unregistered — dispatch_service handles that

    lower = stripped.lower()
    if user.role != "admin":
        if any(lower.startswith(p) for p in _ADMIN_PREFIXES):
            return "❌ 仅 Admin 可执行此操作"
        return None

    return _dispatch_command(session, user, stripped)


# ── Dispatch ───────────────────────────────────────────────────────────────────

def _dispatch_command(session: Session, admin, text: str) -> Optional[str]:
    lower = text.lower()
    if lower.startswith("/add user"):
        return _cmd_add_user(session, text)
    if lower.startswith("/remove user"):
        return _cmd_remove_user(session, admin, text)
    if lower.startswith("/list users"):
        return _cmd_list_users(session)
    if lower.startswith("/set role"):
        return _cmd_set_role(session, admin, text)
    if lower.startswith("/create family"):
        return _cmd_create_family(session, admin, text)
    if lower.startswith("/dissolve family"):
        return _cmd_dissolve_family(session, text)
    if lower.startswith("/family add"):
        return _cmd_family_add(session, text)
    if lower.startswith("/family remove"):
        return _cmd_family_remove(session, text)
    if lower.startswith("/list families"):
        return _cmd_list_families(session)
    if lower.startswith("/status"):
        return _cmd_status(session)
    return None


# ── Confirmation ───────────────────────────────────────────────────────────────

def _handle_confirmation(session: Session, phone: str, text: str) -> str:
    pending = _pending_confirmations.pop(phone)
    if text.strip().upper() != "YES":
        return "取消操作。"

    if pending["action"] == "remove_user":
        target_phone = pending["target"]
        admin = repo.get_user_by_phone(session, phone)
        target = repo.get_user_by_phone(session, target_phone)
        if not target:
            return f"⚠️ 用户 {target_phone} 不存在。"
        if target.role == "admin" and repo.count_admins(session) <= 1:
            return "❌ 不能删除最后一个 Admin。"
        repo.delete_user(session, target)
        return f"✅ 用户 {target_phone} 已删除，所有数据已清除。"

    return "未知操作。"


# ── Commands ───────────────────────────────────────────────────────────────────

def _cmd_add_user(session: Session, text: str) -> str:
    # /add user +phone [display_name]
    parts = text.split(None, 3)
    if len(parts) < 3:
        return "用法: /add user +phone [display_name]"
    phone = parts[2]
    display_name = parts[3] if len(parts) > 3 else None

    if repo.get_user_by_phone(session, phone):
        return "⚠️ 该号码已注册"
    try:
        user = repo.create_user(session, phone, display_name)
    except ValueError:
        return "❌ 手机号格式不合法，请使用 E.164 格式（如 +14081234567）"
    name_str = f" ({user.display_name})" if user.display_name else ""
    return f"✅ 用户 {user.phone}{name_str} 已添加"


def _cmd_remove_user(session: Session, admin, text: str) -> str:
    # /remove user +phone
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "用法: /remove user +phone"
    target_phone = parts[2]

    target = repo.get_user_by_phone(session, target_phone)
    if not target:
        return f"❌ 用户 {target_phone} 不存在"
    if admin.id == target.id:
        return "❌ 不能删除自己"
    if target.role == "admin" and repo.count_admins(session) <= 1:
        return "❌ 不能删除最后一个 Admin"

    _pending_confirmations[admin.phone] = {"action": "remove_user", "target": target_phone}
    return (
        f"⚠️ 确认删除 {target_phone}？"
        f"此操作不可逆，所有数据将清除。"
        f"回复 YES 确认。"
    )


def _cmd_list_users(session: Session) -> str:
    users = repo.list_users(session)
    if not users:
        return "👥 当前没有用户。"

    # Pre-fetch all families for name lookup
    families = {f.id: f.name for f in repo.list_families(session)}

    lines = [f"👥 当前用户列表（共 {len(users)} 人）："]
    for i, u in enumerate(users, 1):
        name = u.display_name or ""
        role_str = "[admin]" if u.role == "admin" else "[user]"
        if u.family_id:
            fam_name = families.get(u.family_id, u.family_id)
            family_str = f"— {fam_name}"
        else:
            family_str = "— 无 Family"
        lines.append(f"{i}. {u.phone} {name} {role_str} {family_str}")
    return "\n".join(lines)


def _cmd_set_role(session: Session, admin, text: str) -> str:
    # /set role +phone admin|user
    parts = text.split(None, 3)
    if len(parts) < 4:
        return "用法: /set role +phone admin|user"
    target_phone, new_role = parts[2], parts[3].lower()

    if new_role not in ("admin", "user"):
        return "❌ 角色必须是 admin 或 user"

    target = repo.get_user_by_phone(session, target_phone)
    if not target:
        return f"❌ 用户 {target_phone} 不存在"
    if admin.id == target.id and new_role == "user":
        return "❌ 不能降级自己"
    if target.role == "admin" and new_role == "user" and repo.count_admins(session) <= 1:
        return "❌ 不能降级最后一个 Admin"

    repo.update_user(session, target, role=new_role)
    action = "提升为 Admin" if new_role == "admin" else "降级为普通用户"
    return f"✅ {target_phone} 已{action}"


def _cmd_create_family(session: Session, admin, text: str) -> str:
    # /create family "Name" or /create family Name
    m = re.match(r'/create\s+family\s+"(.+)"', text, re.IGNORECASE)
    if not m:
        m = re.match(r"/create\s+family\s+(.+)", text, re.IGNORECASE)
    if not m:
        return '用法: /create family "Family Name"'
    name = m.group(1).strip()
    if not name:
        return "Family 名称不能为空"

    family = repo.create_family(session, name, created_by=admin.id)
    return f"✅ Family 已创建：{family.name}（ID: {family.id}）"


def _cmd_dissolve_family(session: Session, text: str) -> str:
    # /dissolve family fam_xxx
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "用法: /dissolve family fam_xxxx"
    family_id = parts[2]

    family = repo.get_family_by_id(session, family_id)
    if not family:
        return f"❌ Family {family_id} 不存在"

    repo.delete_family(session, family)
    return f"✅ Family {family.name} 已解散，成员数据已保留"


def _cmd_family_add(session: Session, text: str) -> str:
    # /family add +phone fam_xxx
    parts = text.split(None, 3)
    if len(parts) < 4:
        return "用法: /family add +phone fam_xxxx"
    target_phone, family_id = parts[2], parts[3]

    user = repo.get_user_by_phone(session, target_phone)
    if not user:
        return f"❌ 用户 {target_phone} 不存在"
    family = repo.get_family_by_id(session, family_id)
    if not family:
        return f"❌ Family {family_id} 不存在"

    repo.update_user(session, user, family_id=family_id)
    return f"✅ {target_phone} 已加入 {family.name}"


def _cmd_family_remove(session: Session, text: str) -> str:
    # /family remove +phone
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "用法: /family remove +phone"
    target_phone = parts[2]

    user = repo.get_user_by_phone(session, target_phone)
    if not user:
        return f"❌ 用户 {target_phone} 不存在"
    if not user.family_id:
        return f"⚠️ {target_phone} 不在任何 Family 中"

    repo.update_user(session, user, family_id=None)
    return f"✅ {target_phone} 已从 Family 中移出"


def _cmd_list_families(session: Session) -> str:
    families = repo.list_families(session)
    if not families:
        return "没有 Family。"

    lines = [f"👨‍👩‍👧 Family 列表（共 {len(families)} 个）："]
    for i, f in enumerate(families, 1):
        members = repo.get_family_members(session, f.id)
        lines.append(f"{i}. {f.name}（{len(members)} 人，ID: {f.id}）")
    return "\n".join(lines)


def _cmd_status(session: Session) -> str:
    users = repo.list_users(session)
    families = repo.list_families(session)
    admins = [u for u in users if u.role == "admin"]
    admin_list = ", ".join(
        f"{a.phone} {a.display_name or ''}".strip() for a in admins
    )
    return (
        "📊 Alfred 系统状态\n"
        f"用户总数：{len(users)}\n"
        f"Family 总数：{len(families)}\n"
        f"Admin：{admin_list}\n"
        "版本：v1.0"
    )
