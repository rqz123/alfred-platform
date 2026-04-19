"""
Intent detection for inbound WhatsApp messages.

Primary path: LLM-based (gpt-4o-mini) with structured JSON output.
Fallback: keyword matching (used when INTENT_OPENAI_API_KEY is absent or LLM call fails).

Returns {'intent': str, 'entities': dict} or None if no intent matched.

Note: Chinese keyword patterns are stored as Unicode escape sequences so the
source file remains ASCII-safe, but the strings are functionally identical to
the corresponding Chinese characters at runtime.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger('alfred.intent')

# ──────────────────────────────────────────────────────────────────
# Keyword fallback (v1)
# Chinese keywords encoded as Unicode escapes to keep source ASCII-clean.
# More specific intents MUST come before generic ones that share substrings:
#   monthly_report  before  add_expense  (\u6d88\u8d39\u62a5\u544a vs \u6d88\u8d39)
#   set_budget      before  add_expense  (\u82b1\u8d39\u4e0a\u9650 shares \u82b1\u8d39)
#   list_reminders  before  add_reminder (\u67e5\u770b\u63d0\u9192 vs \u63d0\u9192)
# ──────────────────────────────────────────────────────────────────

KEYWORD_MAP = [
    # monthly_report: \u6708\u62a5=monthly-report, \u6708\u5ea6=monthly,
    #   \u6d88\u8d39\u62a5\u544a=expense-report, \u6708\u8d26\u5355=bill, \u672c\u6708=this-month
    (['\u6708\u62a5', '\u6708\u5ea6', '\u6d88\u8d39\u62a5\u544a', '\u6708\u8d26\u5355', '\u672c\u6708'],
     'monthly_report'),
    # set_budget: \u9884\u7b97=budget, \u9650\u989d=limit,
    #   \u82b1\u8d39\u4e0a\u9650=spending-cap, \u6bcf\u6708\u9884\u7b97=monthly-budget
    (['\u9884\u7b97', '\u9650\u989d', '\u82b1\u8d39\u4e0a\u9650', '\u6bcf\u6708\u9884\u7b97'],
     'set_budget'),
    # list_reminders: \u63d0\u9192\u5217\u8868=reminder-list, \u6211\u7684\u63d0\u9192=my-reminders,
    #   \u67e5\u770b\u63d0\u9192=view-reminders, \u6709\u4ec0\u4e48\u63d0\u9192=what-reminders
    (['\u63d0\u9192\u5217\u8868', '\u6211\u7684\u63d0\u9192', '\u67e5\u770b\u63d0\u9192',
      '\u6709\u4ec0\u4e48\u63d0\u9192'],
     'list_reminders'),
    # add_expense: spent/consumed/bought/paid/expense/bookkeeping/cost
    (['\u82b1\u4e86', '\u6d88\u8d39', '\u4e70\u4e86', '\u4ed8\u4e86', '\u652f\u51fa',
      '\u8bb0\u8d26', '\u82b1\u8d39'],
     'add_expense'),
    # add_income: income/salary/received/credited/earned
    (['\u6536\u5165', '\u5de5\u8d44', '\u6536\u5230', '\u5165\u8d26', '\u8d5a\u4e86'],
     'add_income'),
    # get_balance: balance/remaining/account/surplus/how-much
    (['\u4f59\u989d', '\u8fd8\u5269', '\u8d26\u6237', '\u7ed3\u4f59', '\u591a\u5c11\u94b1'],
     'get_balance'),
    # cancel_reminder: cancel/delete/remove + reminder keyword
    (['\u53d6\u6d88\u63d0\u9192', '\u5220\u9664\u63d0\u9192', 'cancel reminder', 'delete reminder',
      'remove reminder', 'cancel alarm'],
     'cancel_reminder'),
    # add_reminder: remind/hint/remind/don't-forget/remember/todo + english 'remind'
    (['\u63d0\u9192', '\u63d0\u793a', 'remind', '\u522b\u5fd8\u4e86', '\u8bb0\u5f97', '\u5f85\u529e'],
     'add_reminder'),
    # get_schedule: schedule/what-today/arrangement/calendar
    (['\u65e5\u7a0b', '\u4eca\u5929\u6709\u4ec0\u4e48', '\u5b89\u6392', '\u65e5\u5386'],
     'get_schedule'),
]

VALID_INTENTS = {
    'add_expense', 'add_income', 'get_balance', 'monthly_report',
    'set_budget', 'add_reminder', 'list_reminders', 'get_schedule',
    'cancel_reminder',
}


def _keyword_detect(text: str) -> Optional[dict]:
    t = text.lower()
    for keywords, intent in KEYWORD_MAP:
        if any(k in t for k in keywords):
            return {'intent': intent, 'entities': _extract_entities(t, intent)}
    return None


def _extract_entities(text: str, intent: str) -> dict:
    entities: dict = {}

    # Amount: e.g. 50, ¥50, $50, 50.5
    m = re.search(r'[\xa5$\uff65]?\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    if m:
        entities['amount'] = float(m.group(1))

    # Date keywords
    if '\u4eca\u5929' in text:       # today
        entities['date'] = 'today'
    elif '\u660e\u5929' in text:     # tomorrow
        entities['date'] = 'tomorrow'
    elif '\u6628\u5929' in text:     # yesterday
        entities['date'] = 'yesterday'

    # Category hints for expense/income/budget
    if intent in ('add_expense', 'add_income', 'set_budget'):
        # food: eat/meal/dish/takeaway/coffee/bubble-tea
        food_kw = ['\u5403', '\u996d', '\u9910', '\u5916\u5356', '\u5496\u5561', '\u5976\u8336']
        # transport: taxi/didi/subway/bus/gas
        transport_kw = ['\u6253\u8f66', '\u6ef4\u6ef4', '\u5730\u94c1', '\u516c\u4ea4', '\u52a0\u6cb9']
        # shopping: buy/shop/online-shop/taobao/jd
        shopping_kw = ['\u4e70', '\u8d2d\u7269', '\u7f51\u8d2d', '\u6dd8\u5b9d', '\u4eac\u4e1c']
        # medical: hospital/medicine/see-doctor/clinic
        medical_kw = ['\u533b\u9662', '\u836f', '\u770b\u75c5', '\u8bca\u6240']
        for category, kw_list in [
            ('food', food_kw),
            ('transport', transport_kw),
            ('shopping', shopping_kw),
            ('medical', medical_kw),
        ]:
            if any(k in text for k in kw_list):
                entities['category'] = category
                break

    # Reminder title: extract content after trigger word
    # trigger words: \u63d0\u9192=remind, \u522b\u5fd8\u4e86=don't-forget, \u8bb0\u5f97=remember
    if intent == 'add_reminder':
        m2 = re.search(
            r'(?:\u63d0\u9192|\u522b\u5fd8\u4e86|\u8bb0\u5f97)[\u6211]?\s*(.{2,20})',
            text,
        )
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
                    "set_budget", "add_reminder", "list_reminders", "get_schedule",
                    "cancel_reminder", "none",
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
    "- set_budget: user wants to set a spending budget for a category\n"
    "- add_reminder: user wants to set a reminder or to-do\n"
    "- list_reminders: user wants to see their active reminders\n"
    "- get_schedule: user asks about today's schedule or calendar\n"
    "- cancel_reminder: user wants to cancel, delete, or remove a reminder (by number or name)\n"
    "- none: message does not match any of the above\n\n"
    "Extract entities when present:\n"
    "- amount: numeric value (e.g. 50.0)\n"
    "- date: 'today', 'yesterday', or 'tomorrow' if mentioned\n"
    "- category: pick the best match from this list for expense/income/budget:\n"
    "    'food' (restaurants, groceries, coffee, drinks, meals)\n"
    "    'transportation' (taxi, gas, subway, bus, flight, parking)\n"
    "    'shopping' (clothing, retail, online purchases, electronics, gifts)\n"
    "    'healthcare' (hospital, pharmacy, doctor, medicine, dental)\n"
    "    'entertainment' (movies, games, sports, concerts, subscriptions)\n"
    "    'utilities' (electricity, water, internet, phone bill, rent)\n"
    "    'other' (anything that does not fit the above)\n"
    "  Use null only if no category can be inferred at all.\n"
    "- title: reminder content text for add_reminder; or the reference (number or name) for cancel_reminder — put it in title\n"
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


def extract_entities(text: str, intent: str) -> dict:
    """
    Extract entities from text given a known intent.

    Used by the multi-turn follow-up path: when we already know the intent
    from a previous turn, we call this to pull entities from the user's
    supplementary message (e.g. "50 yuan" after "spent money" was already routed).
    """
    return _extract_entities(text.lower(), intent)
