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

# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Keyword fallback (v1)
# Chinese keywords encoded as Unicode escapes to keep source ASCII-clean.
# More specific intents MUST come before generic ones that share substrings:
#   monthly_report  before  add_expense  (\u6d88\u8d39\u62a5\u544a vs \u6d88\u8d39)
#   set_budget      before  add_expense  (\u82b1\u8d39\u4e0a\u9650 shares \u82b1\u8d39)
#   list_reminders  before  add_reminder (\u67e5\u770b\u63d0\u9192 vs \u63d0\u9192)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

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
    # acknowledge_reminder: quick-reply button "\u2713 OK" and unambiguous Chinese phrases
    (['\u2713 ok', '\u786e\u8ba4', '\u6536\u5230', '\u77e5\u9053\u4e86', '\u660e\u767d\u4e86',
      '\u597d\u7684', 'got it', 'confirmed', 'acknowledged'],
     'acknowledge_reminder'),
    # snooze_thread: delay/snooze a reminder
    (['\u7b49\u4e00\u4e0b', '\u7a0d\u5019', '\u518d\u8bf4', '\u8fc7\u4f1a\u5150', 'snooze', 'remind me later',
      '\u518d\u63d0\u9192', '\u5ef6\u8fdf\u63d0\u9192'],
     'snooze_thread'),
    # dismiss_thread: dismiss/cancel a pending reminder permanently
    (['\u4e0d\u7528\u4e86', '\u4e0d\u8981\u4e86', '\u7b97\u4e86', '\u5173\u6389', '\u4e0d\u9700\u8981\u4e86',
      'dismiss', '\u4e0d\u7528\u63d0\u9192\u4e86'],
     'dismiss_thread'),
    # cancel_reminder: cancel/delete/remove + reminder keyword
    (['\u53d6\u6d88\u63d0\u9192', '\u5220\u9664\u63d0\u9192', 'cancel reminder', 'delete reminder',
      'remove reminder', 'cancel alarm'],
     'cancel_reminder'),
    # thread_delete: must come before search_threads and add_thread
    (['\u5220\u9664\u7ebf\u7d22', '\u5220\u6389\u7ebf\u7d22', '\u5220\u9664\u7b2c', 'delete thread', 'remove thread', 'del thread',
     'delete note', 'remove note', 'del note'],
     'thread_delete'),
    # search_threads: must come before add_thread to avoid matching add_thread
    (['\u627e\u7b14\u8bb0', '\u641c\u7d22\u7b14\u8bb0', '\u67e5\u7b14\u8bb0', 'search note', 'find note', 'search thread', 'find thread'],
     'search_threads'),
    # list_threads: \u6211\u7684\u7b14\u8bb0=my-notes, \u7b14\u8bb0\u5217\u8868=note-list, \u67e5\u770b\u7b14\u8bb0=view-notes
    (['\u6211\u7684\u7b14\u8bb0', '\u7b14\u8bb0\u5217\u8868', '\u67e5\u770b\u7b14\u8bb0', 'list notes', 'my notes', 'list threads', 'my threads'],
     'list_threads'),
    # add_thread: \u8bb0\u4e00\u4e0b=note-this, \u7b14\u8bb0=note, \u8bb0\u5f55=record, \u8bb0\u4e2a\u7b14\u8bb0=write-a-note
    (['\u8bb0\u4e00\u4e0b', '\u7b14\u8bb0', '\u8bb0\u5f55', '\u8bb0\u4e2a\u7b14\u8bb0', 'note', 'jot', 'write down', 'thread'],
     'add_thread'),
    # add_reminder: remind/hint/don't-forget/todo/alarm/alert/set alarm
    # NOTE: \u8bb0\u5f97 (\u8bb0\u5f97) removed \u2014 too generic; "\u4e0d\u8bb0\u5f97\u4e86" would false-match
    (['\u63d0\u9192', '\u63d0\u793a', 'remind', '\u522b\u5fd8\u4e86', '\u5f85\u529e',
      'alarm', 'alert', 'set alarm', 'wake me', '\u95f9\u949f', '\u8b66\u62a5'],
     'add_reminder'),
    # get_schedule: schedule/what-today/arrangement/calendar
    (['\u65e5\u7a0b', '\u4eca\u5929\u6709\u4ec0\u4e48', '\u5b89\u6392', '\u65e5\u5386'],
     'get_schedule'),
]

VALID_INTENTS = {
    'add_expense', 'add_income', 'get_balance', 'monthly_report',
    'set_budget', 'add_reminder', 'list_reminders', 'get_schedule',
    'cancel_reminder', 'acknowledge_reminder',
    'snooze_thread', 'dismiss_thread',
    'add_thread', 'list_threads', 'search_threads', 'thread_delete',
}


_FUTURE_MARKERS = ['明天', '下周', '下个月', 'tomorrow', 'next week', 'next month', '以后', '将来', '要交', '需要付', 'need to pay', 'will pay', 'remind me to pay']


def _keyword_detect(text: str) -> Optional[dict]:
    t = text.lower()
    for keywords, intent in KEYWORD_MAP:
        if any(k in t for k in keywords):
            # Guard: expense/income keywords paired with future markers → add_thread instead
            if intent in ('add_expense', 'add_income') and any(m in t for m in _FUTURE_MARKERS):
                return {'intent': 'add_thread', 'entities': _extract_entities(t, 'add_thread')}
            return {'intent': intent, 'entities': _extract_entities(t, intent)}
    return None


def _extract_entities(text: str, intent: str) -> dict:
    entities: dict = {}

    # Currency symbol (check before stripping it from the amount regex)
    _sym_map = {'$': 'USD', '\xa5': 'CNY', '\uff65': 'CNY', '\uff04': 'USD',
                '\u20ac': 'EUR', '\u00a3': 'GBP'}
    for sym, code in _sym_map.items():
        if sym in text:
            entities['currency'] = code
            break

    # Amount: e.g. 50, \xa550, $50, 50.5
    m = re.search(r'[\xa5$\uff65]?\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    if m:
        entities['amount'] = float(m.group(1))

    # Date keywords (English and Chinese)
    if 'today' in text or '\u4eca\u5929' in text:
        entities['date'] = 'today'
    elif 'tomorrow' in text or '\u660e\u5929' in text:
        entities['date'] = 'tomorrow'
    elif 'yesterday' in text or '\u6628\u5929' in text:
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

    # Thread content: everything after the trigger word is the thread.
    # If the text IS only a trigger word (no content follows), leave content empty
    # so the handler can ask the user for the actual content.
    if intent == 'add_thread':
        _thread_trigger_words = {
            '\u8bb0\u4e00\u4e0b', '\u7b14\u8bb0', '\u8bb0\u5f55', '\u8bb0\u4e2a\u7b14\u8bb0',
            'note', 'jot', 'write down', 'thread',
        }
        m2 = re.search(
            r'(?:\u8bb0\u4e00\u4e0b|\u7b14\u8bb0|\u8bb0\u5f55|\u8bb0\u4e2a\u7b14\u8bb0|note[:\uff1a ]?|thread[:\uff1a ]?|jot|write down)[\uff1a:\s]*(.+)',
            text, re.IGNORECASE,
        )
        if m2:
            entities['content'] = m2.group(1).strip()
        elif text.strip().lower().rstrip(':\uff1a').strip() in _thread_trigger_words:
            entities['content'] = ''  # bare trigger word \u2014 handler will ask for content
        else:
            entities['content'] = text  # natural-language statement (no trigger word)

    # Scope + period for balance/report queries
    if intent in ('get_balance', 'monthly_report'):
        # scope: personal = \u6211/\u6211\u81ea\u5df1, family = \u6211\u4eec\u5bb6/\u6211\u4eec/\u5bb6\u91cc
        family_kw = ['\u6211\u4eec\u5bb6', '\u6211\u5bb6', '\u5bb6\u91cc', '\u6211\u4eec', 'our family', 'we ']
        personal_kw = ['\u6211\u81ea\u5df1', '\u6211\u82b1', '\u6211\u8fd9\u6708', '\u6211\u4e0a\u6708', 'my ', 'i spend', 'i spent']
        if any(k in text for k in family_kw):
            entities['scope'] = 'family'
        elif any(k in text for k in personal_kw):
            entities['scope'] = 'personal'
        # period: last_month = \u4e0a\u4e2a\u6708/\u4e0a\u6708, current_month = default
        if '\u4e0a\u4e2a\u6708' in text or '\u4e0a\u6708' in text or 'last month' in text:
            entities['period'] = 'last_month'
        else:
            entities['period'] = 'current_month'

    # Search query: extract search term, stripping note/\u7b14\u8bb0 trigger if present
    if intent == 'search_threads':
        m2 = re.search(
            r'(?:\u627e|\u641c|\u67e5|search|find)\s*(?:\u7b14\u8bb0\s*|note\s*|thread\s*)?(.+)',
            text, re.IGNORECASE,
        )
        if m2:
            entities['query'] = m2.group(1).strip()

    # Thread ID and confirmation for delete
    if intent == 'thread_delete':
        m2 = re.search(r'#(\d+)|thread\s+(\d+)|\u7b2c\s*(\d+)|\u7ebf\u7d22\s*(\d+)', text, re.IGNORECASE)
        if m2:
            entities['short_id'] = int(next(g for g in m2.groups() if g is not None))
        else:
            m3 = re.search(
                r'(?:delete|remove|del)\s+(?:thread|note|\u7ebf\u7d22|\u7b14\u8bb0)\s+([^\s#\d].{0,60})',
                text, re.IGNORECASE,
            )
            if m3:
                entities['title'] = m3.group(1).strip()
        # Confirmation check only when no thread reference was found in this message.
        # Prevents false-positives: "delete thread smoke_test" contains "ok" inside "smoke"
        # which would otherwise match and skip the confirmation step.
        if not entities.get('short_id') and not entities.get('title'):
            _affirm_kw = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'confirm', 'delete it',
                          '\u786e\u8ba4', '\u662f\u7684', '\u597d\u7684', '\u597d', '\u662f',
                          '\u884c', '\u53ef\u4ee5', '\u5220\u5427']
            if any(k in text for k in _affirm_kw):
                entities['confirmed'] = True

    # Cancel reminder: extract number — handles "取消提醒1", "cancel reminder 2", "#3"
    if intent == 'cancel_reminder':
        # Try #N or trailing digit patterns first
        m2 = re.search(r'#(\d+)', text)
        if not m2:
            m2 = re.search(r'(?:取消|删除)\s*(?:提醒|提示)?\s*#?(\d+)', text)
        if not m2:
            m2 = re.search(r'(?:cancel|delete|remove)\s*(?:reminder|alarm)?\s*#?(\d+)', text, re.IGNORECASE)
        if not m2:
            # "提醒1" pattern: trigger word directly followed by digit(s)
            m2 = re.search(r'提醒(\d+)', text)
        if m2:
            entities['title'] = m2.group(1)

    # snooze delay: extract minutes
    if intent == 'snooze_thread':
        m2 = re.search(r'(\d+)\s*(?:min|minute|\u5206\u949f|\u5206)', text, re.IGNORECASE)
        if m2:
            entities['delay_minutes'] = int(m2.group(1))
        m3 = re.search(r'(\d+)\s*(?:hour|\u5c0f\u65f6|hr)', text, re.IGNORECASE)
        if m3:
            entities['delay_minutes'] = int(m3.group(1)) * 60
        m4 = re.search(r'#(\d+)', text)
        if m4:
            entities['short_id'] = int(m4.group(1))

    # dismiss short_id: extract thread number
    if intent == 'dismiss_thread':
        m2 = re.search(r'#(\d+)|thread\s+(\d+)', text, re.IGNORECASE)
        if m2:
            entities['short_id'] = int(next(g for g in m2.groups() if g is not None))

    # Reminder title: extract content after trigger word
    # trigger words: \u63d0\u9192=remind, \u522b\u5fd8\u4e86=don't-forget, \u8bb0\u5f97=remember
    if intent == 'add_reminder':
        # Chinese: \u63d0\u9192/\u522b\u5fd8\u4e86 + content
        m2 = re.search(r'(?:\u63d0\u9192|\u522b\u5fd8\u4e86)[\u6211]?\s*(.{2,40})', text)
        if not m2:
            # English: "remind me to/about X", "remember to X", "don't forget to X"
            m2 = re.search(
                r'(?:remind\s+me\s+(?:to|about)\s+|remember\s+to\s+|don\'t\s+forget\s+to?\s+)'
                r'(.{2,60}?)(?:\s+(?:tomorrow|tonight|today|at\s+\d|every\s+|next\s+)|$)',
                text, re.IGNORECASE,
            )
        if m2:
            entities['title'] = m2.group(1).strip()

    return entities


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# LLM path (primary)
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

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
                    "cancel_reminder", "acknowledge_reminder",
                    "snooze_thread", "dismiss_thread",
                    "add_thread", "list_threads", "search_threads", "thread_delete", "none",
                ],
            },
            "confidence": {"type": "number"},
            "entities": {
                "type": "object",
                "properties": {
                    "amount":   {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "currency": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "date":     {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "category": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "title":    {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "content":  {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "scope":    {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "period":   {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "short_id":      {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "delay_minutes": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "query":         {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["amount", "currency", "date", "category", "title", "content", "scope", "period", "short_id", "delay_minutes", "query"],
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
    "- acknowledge_reminder: user confirms or acknowledges a reminder (OK, got it, confirmed, \u597d\u7684, \u6536\u5230, \u77e5\u9053\u4e86)\n"
    "- snooze_thread: user wants to delay a reminder (e.g. 'remind me later', 'in 30 minutes', '\u7b49\u4e00\u4e0b', '\u7a0d\u5019', 'snooze')\n"
    "- dismiss_thread: user explicitly cancels a pending reminder permanently (e.g. '\u4e0d\u7528\u4e86', '\u4e0d\u8981\u4e86', '\u7b97\u4e86', 'dismiss', 'never mind')\n"
    "- add_thread: user wants to record or save a thread or memory\n"
    "- list_threads: user wants to see their recent threads\n"
    "- search_threads: user wants to find or search their threads by topic\n"
    "- thread_delete: user wants to delete a specific thread by number or name (e.g. 'delete thread 3', 'delete thread dentist', '\u5220\u9664\u7b2c3\u6761\u7ebf\u7d22', '\u5220\u9664\u7ebf\u7d22 \u670d\u836f')\n"
    "- none: message does not match any of the above, or the message is incomplete/ambiguous\n"
    "NOTE: 'note' and 'thread' are synonyms in this system \u2014 'note: dentist' is the same as 'thread: dentist', 'delete note 3' is the same as 'delete thread 3', etc.\n\n"
    "IMPORTANT \u2014 completeness rules (return 'none' if not met):\n"
    "- add_reminder: classify if there is ANY time/date reference (e.g. '9am', 'tomorrow', "
    "'every Monday', '11:15pm', 'in 30 minutes') OR alarm/reminder language. "
    "The 'what' can be implicit \u2014 'set 11pm alarm', 'wake me at 7', 'alert at noon' all qualify. "
    "Only return 'none' if there is NO time and NO alarm/reminder intent at all (e.g. a random word).\n"
    "- add_expense: ONLY classify if (1) an amount is explicitly stated AND "
    "(2) the event has already happened (past tense \u2014 \u82b1\u4e86, spent, bought, paid, \u4e70\u4e86, \u4ed8\u4e86, etc.). "
    "If the amount is stated but the action is future or hypothetical "
    "('\u660e\u5929\u8981\u4ea4', 'need to pay', 'will spend', 'remind me to pay') \u2192 use add_thread instead.\n"
    "- add_income: ONLY classify if (1) an amount is explicitly stated AND "
    "(2) income has already been received (\u6536\u5230, \u6536\u5165, earned, received). No amount \u2192 'none'.\n"
    "- add_thread: classify if the user wants to save a piece of information. Two sub-cases:\n"
    "  (a) Message has a clear note trigger (\u8bb0\u4e00\u4e0b, \u7b14\u8bb0, note, jot, write down) with real content to save.\n"
    "  (b) Message is a first-person past-event statement the user is recording as a memory \u2014 "
    "e.g. '\u4eca\u5929\u548c\u738b\u533b\u751f\u590d\u8bca' / 'met the architect today about the renovation' / 'ran into John at the cafe'. "
    "These have no explicit trigger word but are clearly personal records, not requests.\n"
    "  Distinguish from add_reminder: reminder = user wants to be alerted at a future time. "
    "Do NOT classify as add_thread if the message is purely future/request ('remind me', 'set alarm').\n"
    "- search_threads: ONLY classify if a search topic or keyword is present.\n"
    "- cancel_reminder: ONLY classify if a specific reminder is identified (number or name).\n"
    "- snooze_thread: classify if user clearly wants to delay a reminder; extract delay_minutes if mentioned (default 30).\n"
    "- dismiss_thread: classify if user clearly wants to stop a reminder permanently.\n"
    "- thread_delete: ONLY classify if a thread number OR thread name is identified (e.g. '#3', 'thread 3', '\u7b2c3\u6761', 'delete thread dentist', '\u5220\u9664\u7ebf\u7d22 \u670d\u836f').\n"
    "- Gibberish or messages with no actionable meaning \u2192 'none'.\n\n"
    "Extract entities when present:\n"
    "- amount: numeric value (e.g. 50.0)\n"
    "- currency: ISO currency code inferred from the symbol: $ \u2192 USD, \xa5 or \uffe5 \u2192 CNY, \u20ac \u2192 EUR, \xa3 \u2192 GBP, "
    "HK$ \u2192 HKD. Use null if no currency symbol is present (caller will apply a default).\n"
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
    "- title: for add_reminder, capture the COMPLETE reminder request including any time/date "
    "(e.g. 'alarm at 1:10 pm', 'call John tomorrow at 9am', 'wake me at 7:30', 'meeting every Monday at 8am'); "
    "for cancel_reminder, the reference number or name; "
    "for thread_delete by name, the thread name to delete (e.g. 'dentist' from 'delete thread dentist')\n"
    "- content: the full text the user wants to save for add_thread intents \u2014 "
    "capture everything after the trigger word (e.g. 'Thread', 'note', '\u8bb0\u4e00\u4e0b', '\u7b14\u8bb0') as content; "
    "use null for all other intents\n"
    "- scope: for get_balance / monthly_report only \u2014 "
    "'personal' when the user refers to their own spending (\u6211, \u6211\u81ea\u5df1, I, my, me); "
    "'family' when referring to the whole household (\u6211\u4eec\u5bb6, \u5bb6\u91cc, \u6211\u4eec, our family, we); "
    "use null for all other intents\n"
    "- period: for get_balance / monthly_report only \u2014 "
    "'last_month' when the user asks about last month (\u4e0a\u4e2a\u6708, \u4e0a\u6708, last month); "
    "'current_month' when asking about this month (\u8fd9\u4e2a\u6708, \u672c\u6708, this month) or no period mentioned; "
    "use null for all other intents\n"
    "- short_id: for thread_delete only \u2014 the integer thread number when a number is given (e.g. 3 from 'thread #3' or '\u7b2c3\u6761'); use null when deleting by name or for all other intents\n"
    "- query: for search_threads only \u2014 the search keyword or phrase after the trigger word "
    "(e.g. '\u836f\u623f' from '\u627e\u7b14\u8bb0 \u836f\u623f', 'milk' from 'find note milk'); use null for all other intents\n"
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


# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Public API
# \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

_ADD_THREAD_PREFIXES = (
    '记一下', '笔记', '记录', '记个笔记',
    'note:', 'note：', 'jot', 'thread:', 'thread：', 'write down',
)

# Delete-thread prefixes: bypass LLM so "delete thread <name>" always routes to
# thread_delete, not cancel_reminder (which shares "delete" + a name).
_DELETE_THREAD_PREFIXES = (
    'delete thread', 'remove thread', 'del thread',
    'delete note', 'remove note', 'del note',
    '删除线索', '删掉线索', '删除第',
)


def detect_intent(text: str) -> Optional[dict]:
    """
    Detect intent from message text.

    Tries LLM first (if INTENT_OPENAI_API_KEY is configured), then falls back
    to keyword matching.

    Returns {'intent': str, 'entities': dict} or None.
    """
    # Explicit add_thread trigger words at the start of the message bypass the LLM.
    # "记一下：明天要交水电费" must always be add_thread — the user stated it explicitly.
    # LLM would see the amount/category and misclassify it as add_expense.
    t_lower = text.strip().lower()
    if any(t_lower.startswith(p) for p in _ADD_THREAD_PREFIXES):
        return _keyword_detect(text)
    if any(t_lower.startswith(p) for p in _DELETE_THREAD_PREFIXES):
        return _keyword_detect(text)

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


def is_affirmative(text: str) -> bool:
    """
    Ask the LLM whether the message is a positive / confirming response.

    Used when detect_intent returns None for a short message \u2014 to catch things
    like 'Ok', 'okay', '\u597d', 'yes', 'yep', '\u662f', '\u55ef', 'sure', 'alright', etc.
    Falls back to a small hard-coded set when the LLM key is not configured.
    """
    from app.core.config import get_settings
    settings = get_settings()

    if settings.intent_openai_api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.intent_openai_api_key)
            response = client.chat.completions.create(
                model=settings.intent_openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Answer only 'yes' or 'no'. "
                            "Is the following message an affirmative, positive, or confirming response? "
                            "Examples that should return 'yes': OK, okay, ok, yes, yeah, yep, sure, done, "
                            "got it, alright, good, fine, confirmed, \u597d, \u662f, \u597d\u7684, \u597d\u554a, \u55ef, \u884c, \u53ef\u4ee5, \u6536\u5230, "
                            "\u77e5\u9053\u4e86, \u660e\u767d\u4e86, \u6ca1\u95ee\u9898. "
                            "Return 'no' for anything else."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=3,
                timeout=5.0,
            )
            return response.choices[0].message.content.strip().lower().startswith("yes")
        except Exception as exc:
            logger.warning("is_affirmative LLM call failed: %s", exc)

    # Keyword fallback
    t = text.strip().lower()
    _affirmative = {
        'ok', 'okay', 'yes', 'yeah', 'yep', 'yup', 'sure', 'done', 'good',
        'got it', 'alright', 'fine', 'confirmed', 'acknowledged',
        '\u597d', '\u662f', '\u597d\u7684', '\u597d\u554a', '\u5d4c', '\u884c',
        '\u53ef\u4ee5', '\u6536\u5230', '\u77e5\u9053\u4e86', '\u660e\u767d\u4e86',
        '\u6ca1\u95ee\u9898',
    }
    return t in _affirmative
