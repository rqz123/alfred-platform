"""
Tests for intent_service.py — keyword fallback path only.
(LLM path requires INTENT_OPENAI_API_KEY and a live OpenAI call, so it is not
tested here; the fallback logic ensures the service works without a key.)

Chinese input strings are written as Unicode escape sequences so the test file
remains ASCII-clean, but they are functionally identical to the Chinese text
that a real user would type.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.intent_service import _keyword_detect, _extract_entities, VALID_INTENTS


class TestKeywordDetect:
    # \u82b1\u4e86=spent, \u5757=chunk(colloquial unit), \u5403\u996d=eating
    def test_add_expense_chinese(self):
        r = _keyword_detect('\u82b1\u4e8650\u5757\u5403\u996d')
        assert r is not None
        assert r['intent'] == 'add_expense'

    # \u6d88\u8d39\u4e86=consumed
    def test_add_expense_amount_extracted(self):
        r = _keyword_detect('\u6d88\u8d39\u4e86128.5\u5143')
        assert r is not None
        assert r['entities']['amount'] == 128.5

    # \u6536\u5230\u5de5\u8d44=received salary
    def test_add_income(self):
        r = _keyword_detect('\u6536\u5230\u5de5\u8d448000\u5143')
        assert r is not None
        assert r['intent'] == 'add_income'

    # \u8d26\u6237\u4f59\u989d\u8fd8\u5269\u591a\u5c11=account balance how much left
    def test_get_balance(self):
        r = _keyword_detect('\u8d26\u6237\u4f59\u989d\u8fd8\u5269\u591a\u5c11')
        assert r is not None
        assert r['intent'] == 'get_balance'

    # \u672c\u6708\u6d88\u8d39\u62a5\u544a=monthly expense report
    def test_monthly_report(self):
        r = _keyword_detect('\u672c\u6708\u6d88\u8d39\u62a5\u544a')
        assert r is not None
        assert r['intent'] == 'monthly_report'

    # \u63d0\u9192\u6211\u660e\u5929\u5f00\u4f1a=remind me meeting tomorrow
    def test_add_reminder(self):
        r = _keyword_detect('\u63d0\u9192\u6211\u660e\u5929\u5f00\u4f1a')
        assert r is not None
        assert r['intent'] == 'add_reminder'

    # \u67e5\u770b\u63d0\u9192=view reminders
    def test_list_reminders(self):
        r = _keyword_detect('\u67e5\u770b\u63d0\u9192')
        assert r is not None
        assert r['intent'] == 'list_reminders'

    # \u4eca\u5929\u6709\u4ec0\u4e48\u5b89\u6392=what schedule today
    def test_get_schedule(self):
        r = _keyword_detect('\u4eca\u5929\u6709\u4ec0\u4e48\u5b89\u6392')
        assert r is not None
        assert r['intent'] == 'get_schedule'

    # \u4f60\u597d=hello, \u4eca\u5929\u5929\u6c14\u4e0d\u9519=nice weather today
    def test_no_match_returns_none(self):
        assert _keyword_detect('\u4f60\u597d') is None
        assert _keyword_detect('\u4eca\u5929\u5929\u6c14\u4e0d\u9519') is None
        assert _keyword_detect('') is None

    def test_all_intents_in_valid_set(self):
        samples = [
            '\u82b1\u4e86100\u5143',          # spent 100
            '\u6536\u51655000',                # income 5000
            '\u8fd8\u5269\u591a\u5c11\u94b1',  # how much left
            '\u672c\u6708\u6708\u62a5',         # monthly report
            '\u522b\u5fd8\u4e86\u5f00\u4f1a',  # don't forget meeting
            '\u6211\u7684\u63d0\u9192\u5217\u8868',  # my reminder list
            '\u4eca\u5929\u65e5\u5386\u5b89\u6392',  # today calendar schedule
        ]
        for s in samples:
            r = _keyword_detect(s)
            if r:
                assert r['intent'] in VALID_INTENTS, \
                    f"unexpected intent {r['intent']!r} for input {s!r}"


class TestExtractEntities:
    # \u82b1\u4e86=spent, \u5143=yuan, \u5403\u996d=eating
    def test_amount_integer(self):
        e = _extract_entities('\u82b1\u4e8650\u5143\u5403\u996d', 'add_expense')
        assert e['amount'] == 50.0

    # \u652f\u51fa=expense
    def test_amount_decimal(self):
        e = _extract_entities('\u652f\u51fa39.9\u5143', 'add_expense')
        assert e['amount'] == 39.9

    # \u4e70\u8863\u670d=buy clothes
    def test_amount_yen_sign(self):
        e = _extract_entities('\xa5200\u4e70\u8863\u670d', 'add_expense')
        assert e['amount'] == 200.0

    # \u4eca\u5929=today
    def test_date_today(self):
        e = _extract_entities('\u4eca\u5929\u82b1\u4e8630\u5143', 'add_expense')
        assert e.get('date') == 'today'

    # \u6628\u5929=yesterday
    def test_date_yesterday(self):
        e = _extract_entities('\u6628\u5929\u5403\u996d\u6d88\u8d3980', 'add_expense')
        assert e.get('date') == 'yesterday'

    # \u660e\u5929=tomorrow
    def test_date_tomorrow(self):
        e = _extract_entities('\u660e\u5929\u8981\u82b1\u4e8650\u5143', 'add_expense')
        assert e.get('date') == 'tomorrow'

    # \u5403\u996d=eating (food category)
    def test_category_food(self):
        e = _extract_entities('\u5403\u996d\u82b1\u4e8630\u5143', 'add_expense')
        assert e.get('category') == 'food'

    # \u6253\u8f66=taxi (transport category)
    def test_category_transport(self):
        e = _extract_entities('\u6253\u8f66\u82b1\u4e8625\u5143', 'add_expense')
        assert e.get('category') == 'transport'

    # \u63d0\u9192\u6211\u660e\u5929\u5f00\u4f1a=remind me meeting tomorrow
    def test_reminder_title_extracted(self):
        e = _extract_entities('\u63d0\u9192\u6211\u660e\u5929\u5f00\u4f1a', 'add_reminder')
        assert 'title' in e
        # \u5f00\u4f1a=meeting should be in the extracted title
        assert '\u5f00\u4f1a' in e['title']

    # \u67e5\u770b\u4f59\u989d=check balance
    def test_no_amount_when_absent(self):
        e = _extract_entities('\u67e5\u770b\u4f59\u989d', 'get_balance')
        assert 'amount' not in e


class TestDetectIntentFallback:
    """detect_intent() with no API key should fall through to keyword."""

    def test_falls_back_to_keyword_without_api_key(self, monkeypatch):
        monkeypatch.setenv('INTENT_OPENAI_API_KEY', '')
        from app.core.config import get_settings
        get_settings.cache_clear()

        from app.services.intent_service import detect_intent
        # \u82b1\u4e86100\u5143\u5403\u996d=spent 100 yuan eating
        r = detect_intent('\u82b1\u4e86100\u5143\u5403\u996d')
        assert r is not None
        assert r['intent'] == 'add_expense'
        assert r['entities']['amount'] == 100.0

        get_settings.cache_clear()
