"""
Intent detection for inbound WhatsApp messages.

Primary path: LLM-based (gpt-4o-mini) with structured JSON output.
Fallback: keyword matching (used when INTENT_OPENAI_API_KEY is absent or LLM call fails).

Returns {'intent': str, 'entities': dict} or None if no intent matched.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger('alfred.intent')

# ──────────────────────────────────────────────────────────────────
# Keyword fallback (v1)
# ──────────────────────────────────────────────────────────────────

KEYWORD_MAP = [
    # More specific intents MUST come before generic ones that share substrings.
    # '消费报告' must match monthly_report before add_expense's '消费'.
    # '查看提醒' must match list_reminders before add_reminder's '提醒'.
    (['月报', '月度', '消费报告', '月账单', '本月'],            'monthly_report'),
    (['提醒列表', '我的提醒', '查看提醒', '有什么提醒'],        'list_reminders'),
    (['花了', '消费', '买了', '付了', '支出', '记账', '花费'], 'add_expense'),
    (['收入', '工资', '收到', '入账', '赚了'],                 'add_income'),
    (['余额', '还剩', '账户', '结余', '多少钱'],               'get_balance'),
    (['提醒', '提示', 'remind', '别忘了', '记得', '待办'],     'add_reminder'),
    (['日程', '今天有什么', '安排', '日历'],                    'get_schedule'),
]

VALID_INTENTS = {
    'add_expense', 'add_income', 'get_balance', 'monthly_report',
    'add_reminder', 'list_reminders', 'get_schedule',
}


def _keyword_detect(text: str) -> Optional[dict]:
    t = text.lower()
    for keywords, intent in KEYWORD_MAP:
        if any(k in t for k in keywords):
            return {'intent': intent, 'entities': _extract_entities(t, intent)}
    return None


def _extract_entities(text: str, intent: str) -> dict:
    entities: dict = {}

    m = re.search(r'[¥$￥]?\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    if m:
        entities['amount'] = float(m.group(1))

    if '今天' in text:
        entities['date'] = 'today'
    elif '明天' in text:
        entities['date'] = 'tomorrow'
    elif '昨天' in text:
        entities['date'] = 'yesterday'

    if intent in ('add_expense', 'add_income'):
        for category, keywords in [
            ('food', ['吃', '饭', '餐', '外卖', '咖啡', '奶茶']),
            ('transport', ['打车', '滴滴', '地铁', '公交', '加油']),
            ('shopping', ['买', '购物', '网购', '淘宝', '京东']),
            ('medical', ['医院', '药', '看病', '诊所']),
        ]:
            if any(k in text for k in keywords):
                entities['category'] = category
                break

    if intent == 'add_reminder':
        m2 = re.search(r'(?:提醒|别忘了|记得)[我]?\s*(.{2,20})', text)
        if m2:
            entities['title'] = m2.group(1).strip()

    return entities


# ──────────────────────────────────────────────────────────────────
# LLM path (primary)
# ──────────────────────────────────────────────────────────────────

_INTENT_SCHEMA = {
    "name": "detect_intent",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "add_expense", "add_income", "get_balance", "monthly_report",
                    "add_reminder", "list_reminders", "get_schedule", "none",
                ],
            },
            "confidence": {"type": "number"},
            "entities": {
                "type": "object",
                "properties": {
                    "amount":   {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "date":     {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "category": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "title":    {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["amount", "date", "category", "title"],
                "additionalProperties": False,
            },
        },
        "required": ["intent", "confidence", "entities"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = (
    "You are an intent classifier for a Chinese personal finance and reminder assistant "
    "called Alfred. Classify the user's message into one of these intents:\n"
    "- add_expense: user recorded a spending/purchase\n"
    "- add_income: user recorded receiving money\n"
    "- get_balance: user asks about account balance or remaining money\n"
    "- monthly_report: user wants a monthly spending summary\n"
    "- add_reminder: user wants to set a reminder or to-do\n"
    "- list_reminders: user wants to see their active reminders\n"
    "- get_schedule: user asks about today's schedule or calendar\n"
    "- none: message does not match any of the above\n\n"
    "Extract entities when present:\n"
    "- amount: numeric value (e.g. 50.0)\n"
    "- date: 'today', 'yesterday', or 'tomorrow' if mentioned\n"
    "- category: 'food', 'transport', 'shopping', or 'medical' for expense/income\n"
    "- title: reminder content text for add_reminder\n"
    "Set confidence between 0 and 1. Use null for entities that are not present."
)


def _llm_detect(text: str, api_key: str, model: str) -> Optional[dict]:
    """Call OpenAI for intent classification. Returns None on any failure."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": _INTENT_SCHEMA,
            },
            timeout=10.0,
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.warning('LLM intent detection failed, falling back to keywords: %s', exc)
        return None

    intent = result.get('intent', 'none')
    confidence = result.get('confidence', 0.0)

    if intent == 'none' or confidence < 0.5:
        return None
    if intent not in VALID_INTENTS:
        return None

    raw_entities = result.get('entities', {})
    entities = {k: v for k, v in raw_entities.items() if v is not None}

    logger.debug('LLM intent=%s confidence=%.2f entities=%s', intent, confidence, entities)
    return {'intent': intent, 'entities': entities}


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def detect_intent(text: str) -> Optional[dict]:
    """
    Detect intent from message text.

    Tries LLM first (if INTENT_OPENAI_API_KEY is configured), then falls back
    to keyword matching.

    Returns {'intent': str, 'entities': dict} or None.
    """
    from app.core.config import get_settings
    settings = get_settings()

    if settings.intent_openai_api_key:
        result = _llm_detect(text, settings.intent_openai_api_key, settings.intent_openai_model)
        if result is not None:
            return result
        # Fall through to keyword on LLM failure

    return _keyword_detect(text)
