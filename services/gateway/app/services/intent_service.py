"""
Keyword-based intent detection for inbound WhatsApp messages.

Returns {intent, entities} or None if no intent matched.
"""

import re
from typing import Optional

KEYWORD_MAP = [
    (['花了', '消费', '买了', '付了', '支出', '记账', '花费'], 'add_expense'),
    (['收入', '工资', '收到', '入账', '赚了'],                 'add_income'),
    (['余额', '还剩', '账户', '结余', '多少钱'],               'get_balance'),
    (['本月', '月报', '月度', '消费报告', '月账单'],            'monthly_report'),
    (['提醒', '提示', 'remind', '别忘了', '记得', '待办'],     'add_reminder'),
    (['提醒列表', '我的提醒', '查看提醒', '有什么提醒'],        'list_reminders'),
    (['日程', '今天有什么', '安排', '日历'],                    'get_schedule'),
]


def detect_intent(text: str) -> Optional[dict]:
    """
    Detect intent from message text using keyword matching.

    Returns {'intent': str, 'entities': dict} or None.
    """
    t = text.lower()
    for keywords, intent in KEYWORD_MAP:
        if any(k in t for k in keywords):
            return {'intent': intent, 'entities': _extract_entities(t, intent)}
    return None


def _extract_entities(text: str, intent: str) -> dict:
    entities: dict = {}

    # Amount: e.g. 50, ¥50, $50, 50.5
    m = re.search(r'[¥$￥]?\s*([0-9]+(?:\.[0-9]{1,2})?)', text)
    if m:
        entities['amount'] = float(m.group(1))

    # Date keywords
    if '今天' in text:
        entities['date'] = 'today'
    elif '明天' in text:
        entities['date'] = 'tomorrow'
    elif '昨天' in text:
        entities['date'] = 'yesterday'

    # Category hints for expenses
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

    # Reminder title: try to extract content after trigger word
    if intent == 'add_reminder':
        m2 = re.search(r'(?:提醒|别忘了|记得)[我]?\s*(.{2,20})', text)
        if m2:
            entities['title'] = m2.group(1).strip()

    return entities
