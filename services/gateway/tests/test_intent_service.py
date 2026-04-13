"""
Tests for intent_service.py — keyword fallback path only
(LLM path requires INTENT_OPENAI_API_KEY and a live OpenAI call, so it is not
tested here; the fallback logic ensures service works without a key.)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.intent_service import _keyword_detect, _extract_entities, VALID_INTENTS


class TestKeywordDetect:
    def test_add_expense_chinese(self):
        r = _keyword_detect("花了50块吃饭")
        assert r is not None
        assert r["intent"] == "add_expense"

    def test_add_expense_amount_extracted(self):
        r = _keyword_detect("消费了128.5元")
        assert r["entities"]["amount"] == 128.5

    def test_add_income(self):
        r = _keyword_detect("收到工资8000元")
        assert r is not None
        assert r["intent"] == "add_income"

    def test_get_balance(self):
        r = _keyword_detect("账户余额还剩多少")
        assert r is not None
        assert r["intent"] == "get_balance"

    def test_monthly_report(self):
        r = _keyword_detect("本月消费报告")
        assert r is not None
        assert r["intent"] == "monthly_report"

    def test_add_reminder(self):
        r = _keyword_detect("提醒我明天开会")
        assert r is not None
        assert r["intent"] == "add_reminder"

    def test_list_reminders(self):
        r = _keyword_detect("查看提醒")
        assert r is not None
        assert r["intent"] == "list_reminders"

    def test_get_schedule(self):
        r = _keyword_detect("今天有什么安排")
        assert r is not None
        assert r["intent"] == "get_schedule"

    def test_no_match_returns_none(self):
        assert _keyword_detect("你好") is None
        assert _keyword_detect("今天天气不错") is None
        assert _keyword_detect("") is None

    def test_all_intents_in_valid_set(self):
        # Every keyword that matches should map to a VALID_INTENTS member
        samples = [
            "花了100元",
            "收入5000",
            "还剩多少钱",
            "本月月报",
            "别忘了开会",
            "我的提醒列表",
            "今天日历安排",
        ]
        for s in samples:
            r = _keyword_detect(s)
            if r:
                assert r["intent"] in VALID_INTENTS, f"{s!r} → unknown intent {r['intent']!r}"


class TestExtractEntities:
    def test_amount_integer(self):
        e = _extract_entities("花了50元吃饭", "add_expense")
        assert e["amount"] == 50.0

    def test_amount_decimal(self):
        e = _extract_entities("支出39.9元", "add_expense")
        assert e["amount"] == 39.9

    def test_amount_yen_sign(self):
        e = _extract_entities("¥200买衣服", "add_expense")
        assert e["amount"] == 200.0

    def test_date_today(self):
        e = _extract_entities("今天花了30元", "add_expense")
        assert e.get("date") == "today"

    def test_date_yesterday(self):
        e = _extract_entities("昨天吃饭消费80", "add_expense")
        assert e.get("date") == "yesterday"

    def test_date_tomorrow(self):
        e = _extract_entities("明天要花50元", "add_expense")
        assert e.get("date") == "tomorrow"

    def test_category_food(self):
        e = _extract_entities("吃饭花了30元", "add_expense")
        assert e.get("category") == "food"

    def test_category_transport(self):
        e = _extract_entities("打车花了25元", "add_expense")
        assert e.get("category") == "transport"

    def test_reminder_title_extracted(self):
        e = _extract_entities("提醒我明天开会", "add_reminder")
        assert "title" in e
        assert "开会" in e["title"]

    def test_no_amount_when_absent(self):
        e = _extract_entities("查看余额", "get_balance")
        assert "amount" not in e


class TestDetectIntentFallback:
    """detect_intent() with no API key should fall through to keyword."""

    def test_falls_back_to_keyword_without_api_key(self, monkeypatch):
        # Ensure no LLM key is configured
        monkeypatch.setenv("INTENT_OPENAI_API_KEY", "")
        # Clear the lru_cache so settings reload picks up the monkeypatch
        from app.core.config import get_settings
        get_settings.cache_clear()

        from app.services.intent_service import detect_intent
        r = detect_intent("花了100元吃饭")
        assert r is not None
        assert r["intent"] == "add_expense"
        assert r["entities"]["amount"] == 100.0

        # Restore
        get_settings.cache_clear()
