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
            return "❌ Admin only."
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
        return "Cancelled."

    if pending["action"] == "remove_user":
        target_phone = pending["target"]
        target = repo.get_user_by_phone(session, target_phone)
        if not target:
            return f"⚠️ User {target_phone} not found."
        if target.role == "admin" and repo.count_admins(session) <= 1:
            return "❌ Cannot remove the last admin."
        repo.delete_user(session, target)
        return f"✅ User {target_phone} removed."

    return "Unknown action."


# ── Commands ───────────────────────────────────────────────────────────────────

def _cmd_add_user(session: Session, text: str) -> str:
    # /add user +phone [display_name]
    parts = text.split(None, 3)
    if len(parts) < 3:
        return "Usage: /add user +phone [display_name]"
    phone = parts[2]
    display_name = parts[3] if len(parts) > 3 else None

    if repo.get_user_by_phone(session, phone):
        return "⚠️ That number is already registered."
    try:
        user = repo.create_user(session, phone, display_name)
    except ValueError:
        return "❌ Invalid phone number. Use E.164 format (e.g. +14081234567)."
    name_str = f" ({user.display_name})" if user.display_name else ""
    return f"✅ User {user.phone}{name_str} added."


def _cmd_remove_user(session: Session, admin, text: str) -> str:
    # /remove user +phone
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "Usage: /remove user +phone"
    target_phone = parts[2]

    target = repo.get_user_by_phone(session, target_phone)
    if not target:
        return f"❌ User {target_phone} not found."
    if admin.id == target.id:
        return "❌ Cannot remove yourself."
    if target.role == "admin" and repo.count_admins(session) <= 1:
        return "❌ Cannot remove the last admin."

    _pending_confirmations[admin.phone] = {"action": "remove_user", "target": target_phone}
    return (
        f"⚠️ Confirm removal of {target_phone}? "
        f"This cannot be undone. "
        f"Reply YES to confirm."
    )


def _cmd_list_users(session: Session) -> str:
    users = repo.list_users(session)
    if not users:
        return "👥 No users yet."

    families = {f.id: f.name for f in repo.list_families(session)}

    lines = [f"👥 Users ({len(users)}):"]
    for i, u in enumerate(users, 1):
        name = u.display_name or ""
        role_str = "[admin]" if u.role == "admin" else "[user]"
        family_str = f"— {families.get(u.family_id, u.family_id)}" if u.family_id else "— no family"
        lines.append(f"{i}. {u.phone} {name} {role_str} {family_str}")
    return "\n".join(lines)


def _cmd_set_role(session: Session, admin, text: str) -> str:
    # /set role +phone admin|user
    parts = text.split(None, 3)
    if len(parts) < 4:
        return "Usage: /set role +phone admin|user"
    target_phone, new_role = parts[2], parts[3].lower()

    if new_role not in ("admin", "user"):
        return "❌ Role must be 'admin' or 'user'."

    target = repo.get_user_by_phone(session, target_phone)
    if not target:
        return f"❌ User {target_phone} not found."
    if admin.id == target.id and new_role == "user":
        return "❌ Cannot demote yourself."
    if target.role == "admin" and new_role == "user" and repo.count_admins(session) <= 1:
        return "❌ Cannot demote the last admin."

    repo.update_user(session, target, role=new_role)
    action = "promoted to admin" if new_role == "admin" else "demoted to user"
    return f"✅ {target_phone} {action}."


def _cmd_create_family(session: Session, admin, text: str) -> str:
    # /create family "Name" or /create family Name
    m = re.match(r'/create\s+family\s+"(.+)"', text, re.IGNORECASE)
    if not m:
        m = re.match(r"/create\s+family\s+(.+)", text, re.IGNORECASE)
    if not m:
        return 'Usage: /create family "Family Name"'
    name = m.group(1).strip()
    if not name:
        return "Family name cannot be empty."

    family = repo.create_family(session, name, created_by=admin.id)
    return f"✅ Family created: {family.name} (ID: {family.id})"


def _cmd_dissolve_family(session: Session, text: str) -> str:
    # /dissolve family fam_xxx
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "Usage: /dissolve family fam_xxxx"
    family_id = parts[2]

    family = repo.get_family_by_id(session, family_id)
    if not family:
        return f"❌ Family {family_id} not found."

    repo.delete_family(session, family)
    return f"✅ Family '{family.name}' dissolved. Members' data preserved."


def _cmd_family_add(session: Session, text: str) -> str:
    # /family add +phone fam_xxx
    parts = text.split(None, 3)
    if len(parts) < 4:
        return "Usage: /family add +phone fam_xxxx"
    target_phone, family_id = parts[2], parts[3]

    user = repo.get_user_by_phone(session, target_phone)
    if not user:
        return f"❌ User {target_phone} not found."
    family = repo.get_family_by_id(session, family_id)
    if not family:
        return f"❌ Family {family_id} not found."

    repo.update_user(session, user, family_id=family_id)
    return f"✅ {target_phone} added to {family.name}."


def _cmd_family_remove(session: Session, text: str) -> str:
    # /family remove +phone
    parts = text.split(None, 2)
    if len(parts) < 3:
        return "Usage: /family remove +phone"
    target_phone = parts[2]

    user = repo.get_user_by_phone(session, target_phone)
    if not user:
        return f"❌ User {target_phone} not found."
    if not user.family_id:
        return f"⚠️ {target_phone} is not in any family."

    repo.update_user(session, user, family_id=None)
    return f"✅ {target_phone} removed from their family."


def _cmd_list_families(session: Session) -> str:
    families = repo.list_families(session)
    if not families:
        return "No families yet."

    lines = [f"👨‍👩‍👧 Families ({len(families)}):"]
    for i, f in enumerate(families, 1):
        members = repo.get_family_members(session, f.id)
        lines.append(f"{i}. {f.name} — {len(members)} member(s), ID: {f.id}")
    return "\n".join(lines)


def _cmd_status(session: Session) -> str:
    users = repo.list_users(session)
    families = repo.list_families(session)
    admins = [u for u in users if u.role == "admin"]
    admin_list = ", ".join(
        f"{a.phone} {a.display_name or ''}".strip() for a in admins
    )
    return (
        "📊 Alfred status\n"
        f"Users: {len(users)}\n"
        f"Families: {len(families)}\n"
        f"Admins: {admin_list}\n"
        "Version: v1.0"
    )
