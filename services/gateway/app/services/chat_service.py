"""
LLM-powered conversational fallback for Alfred.

Called by dispatch_service when intent detection returns None — replaces the
hardcoded "Sorry I didn't understand" message with a real GPT conversation that
is context-aware and knows Alfred's built-in capabilities.
"""

import logging

logger = logging.getLogger("alfred.chat")

_ALFRED_SYSTEM_PROMPT = """\
You are Alfred, a personal AI assistant accessible via WhatsApp.
You are helpful, friendly, and concise (keep replies under ~150 words unless a \
longer answer is genuinely needed).

You have three built-in capabilities that you can route users to:
1. Expense & receipt tracking — users say things like "I spent $20 on lunch" or \
send a photo of a receipt.
2. Reminders & alarms — users say things like "Remind me to take medicine at 9pm" \
or "Set an alarm for 7am tomorrow".
3. Personal notes — users say things like "Note: dentist appointment is next Tuesday" \
or "记一下 明天买降压药".

For general questions, small talk, stories, advice, or anything outside those three \
areas, respond naturally as a helpful assistant.

When a user seems to want one of your built-in features but hasn't phrased it clearly, \
gently guide them with a short example. Do NOT say you "can't" do general conversation.

Respond in the same language the user writes in (Chinese or English).\
"""

_FALLBACK = (
    "Sorry, I didn't understand that. I can help with expenses, reminders, or notes — "
    'try saying something like "Spent $20 on lunch" or "Remind me at 9am".'
)


def llm_chat_reply(session, msg, settings) -> str:
    """
    Generate a natural language reply via OpenAI, with conversation history as context.

    Returns the reply text. Falls back to the hardcoded sorry message if the API key
    is not configured or the call fails.
    """
    if not settings.intent_openai_api_key:
        return _FALLBACK

    try:
        from sqlmodel import select
        from app.models.chat import Message

        # Fetch the last 10 messages for this conversation, oldest first,
        # to give the LLM enough context for follow-up questions.
        recent = session.exec(
            select(Message)
            .where(Message.conversation_id == msg.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(10)
        ).all()
        recent = list(reversed(recent))

        openai_messages = [{"role": "system", "content": _ALFRED_SYSTEM_PROMPT}]
        for m in recent:
            role = "user" if m.direction == "inbound" else "assistant"
            content = m.transcript or m.body or ""
            if content:
                openai_messages.append({"role": role, "content": content})

        from openai import OpenAI
        client = OpenAI(api_key=settings.intent_openai_api_key)
        resp = client.chat.completions.create(
            model=settings.intent_openai_model,
            messages=openai_messages,
            max_tokens=300,
            timeout=15.0,
        )
        reply = resp.choices[0].message.content.strip()
        logger.info("LLM chat reply for conversation=%s: %r", msg.conversation_id, reply[:80])
        return reply

    except Exception as exc:
        logger.warning("LLM chat reply failed, using fallback: %s", exc)
        return _FALLBACK
