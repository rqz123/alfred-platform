"""Parameterized Onboarding service.

Sends the 4-step cold-start script immediately (T+0), then schedules
follow-up prompts at T+1h and T+8h via threading.Timer (no extra deps).
"""
import logging
import threading
import time

from sqlmodel import Session

from app.db.session import engine

logger = logging.getLogger("alfred.onboarding")

# Seconds between consecutive onboarding steps for a natural feel
_STEP_GAP = 2

_STEP1 = """\
嘿 {user_name} 👋 我是 Thread。
{admin_name} 把我安在这里，说你是他们家的生活大导演——
但导演也有需要人帮着盯场的时候对吧？

我不是来催你干活的，就是帮你把散掉的线索缝一缝。
不管是随口一说，还是要记下来的事，都告诉我就好。

你希望我平时说话，是像个能懂你情绪的朋友，
还是干干净净说重点就好？"""

_STEP2 = """\
如果一件事你一直没动，
你更想我帮你把它拆成小步子，
还是先给你找个奖励来撑着走？"""

_STEP3 = """\
最近有什么特别想去的地方，或者想看的电影吗？
随口说一两个就好。
下次当你动能不足的时候，我好有个理由来帮你换换心情 😊"""

_STEP4 = """\
对了，还有件事先说清楚——
你看到聊天框顶部那个小心形了吗？
点一下，我就隐身了。不通知 {admin_name}，不留痕迹。

你是这里的主人，我只是那根帮你缝线索的线 🪡"""

_T1H = """\
{user_name}，试试发给我一件最近一直搁着的事——
随便什么都行，哪怕只是一句话。
我马上帮你把它挂到图谱上 🗺️"""

_T8H = """\
我刚才悄悄做了一件事 🪡
你发给我的几条线索，我发现它们之间有些微妙的联系。
下次你来的时候，我来给你讲讲。"""


def _send_proactive(user_phone: str, body: str) -> None:
    """Send a proactive message to a user, finding an active bridge session."""
    from app.core.config import get_settings
    from app.services.bridge_service import list_bridge_sessions, send_text_via_bridge
    from app.repositories.chat_repository import create_or_get_contact, get_or_create_conversation
    from app.repositories.connection_repository import list_connections
    from app.models.chat import WhatsAppConnection, Message
    from datetime import datetime, timezone

    settings = get_settings()

    try:
        with Session(engine) as session:
            contact = create_or_get_contact(session, user_phone, display_name=None)
            conv = get_or_create_conversation(session, contact)

            provider_message_id: str | None = None

            if settings.whatsapp_mode == "bridge":
                conn_record = session.get(WhatsAppConnection, conv.connection_id) if conv.connection_id else None
                if conn_record is None:
                    live = {s["id"]: s for s in list_bridge_sessions()}
                    conn_record = next(
                        (
                            session.get(WhatsAppConnection, c.id)
                            for c in list_connections(session)
                            if live.get(c.bridge_session_id, {}).get("status") == "connected"
                        ),
                        None,
                    )
                if conn_record:
                    provider_message_id = send_text_via_bridge(
                        conn_record.bridge_session_id, contact.phone_number, body
                    )
                else:
                    logger.warning("Onboarding send skipped — no active bridge connection for %s", user_phone)
                    return
            else:
                from app.services.dispatch_service import _send_cloud_reply
                _send_cloud_reply(contact.phone_number, body, settings)

            msg = Message(
                conversation_id=conv.id,
                provider_message_id=provider_message_id,
                direction="outbound",
                message_type="text",
                body=body,
                delivery_status="sent" if provider_message_id else "queued",
            )
            session.add(msg)
            conv.updated_at = datetime.now(timezone.utc)
            session.add(conv)
            session.commit()

    except Exception as exc:
        logger.error("Onboarding proactive send failed for %s: %s", user_phone, exc)


def _send_steps(
    user_phone: str,
    user_name: str,
    admin_name: str,
    weaving_hook_id: str | None,
) -> None:
    """Send the 4 cold-start steps synchronously with small gaps.

    Entry Hook (if present) is appended immediately after Step 1 per PRD 8.2 T+0 尾部.
    """
    steps = [
        _STEP1.format(user_name=user_name, admin_name=admin_name),
        _STEP2,
        _STEP3,
        _STEP4.format(admin_name=admin_name),
    ]
    for i, step in enumerate(steps):
        _send_proactive(user_phone, step)
        time.sleep(_STEP_GAP)
        if i == 0 and weaving_hook_id:
            _send_entry_hook(user_phone, admin_name, weaving_hook_id)
            time.sleep(_STEP_GAP)


def _send_entry_hook(user_phone: str, admin_name: str, weaving_hook_id: str) -> None:
    """Fetch the Entry Hook Weaving from Brain and deliver it after Step 1."""
    try:
        from app.core.config import get_settings
        import httpx

        settings = get_settings()
        resp = httpx.get(
            f"{settings.brain_url}/api/brain/weavings/by_id/{weaving_hook_id}",
            headers={"X-API-Key": settings.brain_api_key},
            timeout=10.0,
        )
        if resp.is_error:
            logger.warning("Entry hook fetch failed: %s", resp.text)
            return
        weaving = resp.json()
        summary = weaving.get("summary") or weaving.get("content") or ""
        if summary:
            hook_msg = f"{admin_name} 想让你第一眼看到这个…\n\n{summary} 🪡"
            _send_proactive(user_phone, hook_msg)
    except Exception as exc:
        logger.error("Entry hook send failed for %s: %s", user_phone, exc)


def _schedule(delay_seconds: float, fn, *args) -> None:
    t = threading.Timer(delay_seconds, fn, args=args)
    t.daemon = True
    t.start()


def run_onboarding(
    user_phone: str,
    user_name: str,
    admin_name: str,
    weaving_hook_id: str | None = None,
) -> None:
    """Entry point called from a background thread after invite acceptance.

    Sends Steps 1–4 immediately, then schedules T+1h and T+8h follow-ups.
    """
    logger.info("Starting onboarding for %s (%s)", user_name, user_phone)

    # T+0: cold-start script
    _send_steps(user_phone, user_name, admin_name, weaving_hook_id)

    t1h_msg = _T1H.format(user_name=user_name)
    t8h_msg = _T8H

    _schedule(3600, _send_proactive, user_phone, t1h_msg)   # T+1h
    _schedule(28800, _send_proactive, user_phone, t8h_msg)  # T+8h

    logger.info("Onboarding steps sent for %s; T+1h and T+8h scheduled", user_name)
