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
  邀请 [姓名]  /  invite [name]   (generates invite card with token)

Token activation (any registered WhatsApp number):
  Any message containing (Token:ALFRED-XXXXXX) triggers user binding.

Called by dispatch_service before intent detection for every text message.
Returns a reply string if the message was handled, else None.
"""

import os
import re
import secrets
import string
from typing import Optional
from uuid import uuid4
from datetime import datetime, timezone

import httpx
from sqlmodel import Session

import app.repositories.account_repository as repo

import threading

# phone → {"action": str, ...}
_pending_confirmations: dict[str, dict] = {}

_TOKEN_PATTERN = re.compile(r'\(Token:([A-Z0-9\-]+)\)')
_INVITE_PATTERN = re.compile(r'^(?:邀请|invite)\s+(.+)$', re.IGNORECASE)
_MAX_PENDING_TOKENS = 5


def _generate_token_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(alphabet) for _ in range(6))
    return f"ALFRED-{suffix}"


def _init_persona(user_phone: str, family_id: str, display_name: str | None = None) -> None:
    """Fire-and-forget: initialize PersonaProfile in Brain when a user joins a family."""
    def _post():
        from app.core.config import get_settings
        settings = get_settings()
        brain_url = getattr(settings, "brain_url", None) or os.environ.get("BRAIN_URL", "")
        brain_key = getattr(settings, "alfred_internal_key", None) or os.environ.get("ALFRED_INTERNAL_KEY", "")
        if not brain_url or not brain_key:
            return
        try:
            httpx.post(
                f"{brain_url}/api/brain/personas",
                json={"user_phone": user_phone, "family_id": family_id, "display_name": display_name},
                headers={"X-Alfred-API-Key": brain_key},
                timeout=5.0,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()

def _render_invite_card(
    admin_name: str,
    token_id: str,
    bot_number: str,
    expires_at_date: str,
) -> str:
    from urllib.parse import quote
    admin_encoded = quote(admin_name)
    token_text = f"Hi Alfred, joining {admin_name}'s family. (Token:{token_id})"
    wa_link = f"https://wa.me/{bot_number.lstrip('+')}?text={quote(token_text)}"
    return (
        f"🛡️ Alfred Family Invite\n\n"
        f"{admin_name} is inviting you to join their family on Alfred.\n\n"
        f"Your personal entry link 👇\n{wa_link}\n\n"
        f"Or send Alfred this message:\n"
        f"「{token_text}」\n\n"
        f"Valid for 7 days (until {expires_at_date})\n\n"
        f"📌 Note: Alfred does not store your private information. "
        f"You can disconnect anytime — {admin_name} won't be notified."
    )


def activate_invite(session: Session, sender_phone: str, token_id: str) -> Optional[str]:
    """
    Complete user binding from a Token message. Returns a reply or None on error.
    Called from dispatch_service token parser before normal routing.
    """
    token = repo.get_invite_token(session, token_id)
    if token is None:
        return "This invite code doesn't exist. Please ask the admin to generate a new one."

    now = datetime.now(timezone.utc)
    if token.status == "used":
        return (
            "This invite code has already been used. "
            "If you already joined, just talk to me directly 😊 "
            "If not, ask the admin for a new invite."
        )
    expires_at = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=timezone.utc)
    if token.status == "expired" or expires_at < now:
        if token.status != "expired":
            token.status = "expired"
            session.add(token)
            session.commit()
        return "This invite code has expired. Please ask the admin to generate a new one."

    # Atomic CAS: mark token as used before creating the user
    existing_user = repo.get_user_by_phone(session, sender_phone)
    if existing_user and existing_user.family_id:
        return "You're already in a family. Talk to me anytime 😊"

    claimed = repo.claim_invite_token(session, token, used_by_user_id=sender_phone)
    if not claimed:
        return (
            "This invite code was just used by someone else. "
            "Please ask the admin for a new invite code."
        )

    # Create or update user record
    if existing_user:
        user = repo.update_user(
            session, existing_user,
            family_id=token.family_id,
            display_name=existing_user.display_name or token.invitee_name,
            role="invited_user",
            invited_by=token.created_by,
            joined_at=now,
        )
    else:
        user = repo.create_user(
            session,
            phone=sender_phone,
            display_name=token.invitee_name,
            family_id=token.family_id,
        )
        user = repo.update_user(
            session, user,
            role="invited_user",
            invited_by=token.created_by,
            joined_at=now,
        )

    # Notify the admin who created the invite
    admin = repo.get_user_by_id(session, token.created_by)

    # Fire-and-forget: init PersonaProfile in Brain
    _init_persona(sender_phone, token.family_id, display_name=token.invitee_name)

    # Trigger parameterized Onboarding (deferred so this function returns fast)
    admin_name = (admin.display_name if admin else None) or "Admin"
    threading.Thread(
        target=_run_onboarding_async,
        args=(sender_phone, token.invitee_name, admin_name, token.weaving_hook_id),
        daemon=True,
    ).start()

    # Notify the admin
    if admin:
        threading.Thread(
            target=_notify_admin_async,
            args=(admin.phone, token.invitee_name),
            daemon=True,
        ).start()

    return None  # Onboarding service will send the welcome message


def _run_onboarding_async(
    user_phone: str,
    user_name: str,
    admin_name: str,
    weaving_hook_id: str | None = None,
) -> None:
    try:
        from app.services.onboarding_service import run_onboarding
        run_onboarding(
            user_phone=user_phone,
            user_name=user_name,
            admin_name=admin_name,
            weaving_hook_id=weaving_hook_id,
        )
    except Exception:
        pass


def _notify_admin_async(admin_phone: str, invitee_name: str) -> None:
    """Send notification to admin that invitee accepted."""
    from app.core.config import get_settings
    from app.services.bridge_service import send_text_via_bridge
    settings = get_settings()
    try:
        if settings.whatsapp_mode == "bridge":
            send_text_via_bridge(None, admin_phone, f"✅ {invitee_name} has accepted the invite and is being onboarded.")
    except Exception:
        pass


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

_THREAD_CMD_PREFIXES = (
    "/thread get", "/thread list", "/thread delete", "/thread links",
    "/note get",   "/note list",   "/note delete",   "/note links",
    "/find",
    "/link",
    "/unlink",
)


def _call_thread_sync(phone: str, intent: str, entities: dict) -> str:
    """Synchronously POST to Thread service /alfred/execute and return the reply message."""
    from app.core.config import get_settings
    settings = get_settings()
    thread_key = getattr(settings, "thread_api_key", None) or os.environ.get("THREAD_API_KEY", "")
    thread_url = os.environ.get("THREAD_URL", "http://localhost:8002/api/thread")
    if not thread_key:
        return "Thread service not configured."
    try:
        r = httpx.post(
            f"{thread_url}/alfred/execute",
            json={
                "request_id": str(uuid4()),
                "user_id": phone,
                "whatsapp_id": phone,
                "intent": intent,
                "entities": entities,
                "session": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Alfred-API-Key": thread_key},
            timeout=12.0,
        )
        r.raise_for_status()
        return r.json().get("message", "") or "Done."
    except Exception:
        return "⚠️ Thread service error. Please try again."


def handle_bot_command(session: Session, phone: str, text: str) -> Optional[str]:
    stripped = text.strip()

    # Token activation — highest priority, checked before anything else.
    token_match = _TOKEN_PATTERN.search(stripped)
    if token_match:
        return activate_invite(session, phone, token_match.group(1))

    # Pending confirmation takes priority, but a new slash command cancels it.
    if phone in _pending_confirmations:
        # Invite command pattern is not a slash command — handle separately
        if _INVITE_PATTERN.match(stripped):
            _pending_confirmations.pop(phone)
        elif stripped.startswith("/"):
            _pending_confirmations.pop(phone)
            # Fall through to handle the new command.
        else:
            return _handle_confirmation(session, phone, stripped)

    # Invite command (natural language, no leading slash)
    invite_match = _INVITE_PATTERN.match(stripped)
    if invite_match:
        user = repo.get_user_by_phone(session, phone)
        if user and user.role == "admin":
            return _cmd_invite_user(session, user, invite_match.group(1).strip())
        return None

    if not stripped.startswith("/"):
        return None

    user = repo.get_user_by_phone(session, phone)
    if not user:
        return None  # unregistered — dispatch_service handles that

    lower = stripped.lower()

    # Thread commands — available to all registered users
    if any(lower.startswith(p) for p in _THREAD_CMD_PREFIXES):
        return _dispatch_thread_command(phone, stripped)

    if user.role != "admin":
        if any(lower.startswith(p) for p in _ADMIN_PREFIXES):
            return "❌ Admin only."
        return None

    return _dispatch_command(session, user, stripped)


# ── Thread commands (all registered users) ──────────────────────────────────────

def _dispatch_thread_command(phone: str, text: str) -> Optional[str]:
    lower = text.lower().strip()
    # /note X is a user-facing alias for /thread X
    if lower.startswith("/note"):
        text = "/thread" + text[5:]
        lower = "/thread" + lower[5:]

    if lower.startswith("/thread get"):
        m = re.search(r"#?(\d+)", text)
        if not m:
            return "Usage: /thread get #<id>"
        return _call_thread_sync(phone, "thread_get", {"short_id": int(m.group(1))})

    if lower.startswith("/thread list"):
        m = re.search(r"/thread\s+list\s+(\d+)", text, re.IGNORECASE)
        limit = int(m.group(1)) if m else 5
        return _call_thread_sync(phone, "list_threads", {"limit": limit})

    if lower.startswith("/thread delete"):
        m = re.search(r"#?(\d+)", text)
        if not m:
            return "Usage: /thread delete #<id>"
        short_id = int(m.group(1))
        _pending_confirmations[phone] = {"action": "thread_delete", "short_id": short_id}
        return f"⚠️ Delete Thread #{short_id}? Reply Y to confirm."

    if lower.startswith("/thread links"):
        m = re.search(r"#?(\d+)", text)
        short_id = int(m.group(1)) if m else None
        return _call_thread_sync(phone, "thread_links", {"short_id": short_id})

    if lower.startswith("/find"):
        query = text[5:].strip()
        if not query:
            return "Usage: /find <search term>"
        return _call_thread_sync(phone, "search_threads", {"query": query})

    if lower.startswith("/link"):
        ids = re.findall(r"#?(\d+)", text)
        if len(ids) < 2:
            return "Usage: /link #<id_A> #<id_B>"
        return _call_thread_sync(phone, "thread_link", {"thread_a": int(ids[0]), "thread_b": int(ids[1])})

    if lower.startswith("/unlink"):
        ids = re.findall(r"#?(\d+)", text)
        if len(ids) < 2:
            return "Usage: /unlink #<id_A> #<id_B>"
        return _call_thread_sync(phone, "thread_unlink", {"thread_a": int(ids[0]), "thread_b": int(ids[1])})

    return None


# ── Admin dispatch ─────────────────────────────────────────────────────────────

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
    confirmed = text.strip().upper() in ("YES", "Y")

    if pending["action"] == "remove_user":
        if not confirmed:
            return "Cancelled."
        target_phone = pending["target"]
        target = repo.get_user_by_phone(session, target_phone)
        if not target:
            return f"⚠️ User {target_phone} not found."
        if target.role == "admin" and repo.count_admins(session) <= 1:
            return "❌ Cannot remove the last admin."
        repo.delete_user(session, target)
        return f"✅ User {target_phone} removed."

    if pending["action"] == "thread_delete":
        if not confirmed:
            return "Cancelled."
        return _call_thread_sync(phone, "thread_delete", {"short_id": pending["short_id"], "confirmed": True})

    return "Unknown action."


# ── Commands ───────────────────────────────────────────────────────────────────

def _cmd_invite_user(session: Session, admin, invitee_name: str) -> str:
    """Generate an invite card for a new user. Admin only."""
    if not admin.family_id:
        return "❌ You need to be in a family to invite others. Create one first with /create family."

    if not invitee_name.strip():
        return "Usage: 邀请 [name]  or  invite [name]"

    pending_count = repo.count_pending_tokens(session, admin.family_id, admin.id)
    if pending_count >= _MAX_PENDING_TOKENS:
        return f"❌ You already have {_MAX_PENDING_TOKENS} pending invites. Wait for them to expire or be used."

    from app.core.config import get_settings
    settings = get_settings()
    bot_number = settings.bot_phone_number or ""

    token_id = _generate_token_id()
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    repo.create_invite_token(
        session,
        family_id=admin.family_id,
        created_by=admin.id,
        invitee_name=invitee_name.strip(),
        token_id=token_id,
    )

    expires_date_str = expires_at.strftime("%Y-%m-%d")
    return _render_invite_card(
        admin_name=admin.display_name or "Admin",
        token_id=token_id,
        bot_number=bot_number,
        expires_at_date=expires_date_str,
    )


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
    _init_persona(target_phone, family_id, display_name=user.display_name)
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
