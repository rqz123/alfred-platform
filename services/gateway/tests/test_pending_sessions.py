"""
Tests for pending_sessions module and the multi-turn dispatch flow.

Covers:
- PendingSession expiry
- save / get / clear
- is_cancel keyword detection
- dispatch_message: INSUFFICIENT_DATA → save pending
- dispatch_message: follow-up message with missing entity → retry service
- dispatch_message: cancel keyword → clear pending, reply "Cancelled"
- dispatch_message: new intent while pending → drop old pending, handle new
- dispatch_message: max retries exceeded → give up
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app.services.pending_sessions as ps


# ──────────────────────────────────────────────────────────────────
# PendingSession / store unit tests
# ──────────────────────────────────────────────────────────────────

def setup_function():
    """Clear the in-memory store before each test."""
    ps._store.clear()


def _svc():
    return {'name': 'OurCents', 'url': 'http://localhost:8001', 'api_key': 'key'}


def test_save_and_get():
    ps.save('+861', 'add_expense', {}, _svc())
    s = ps.get('+861')
    assert s is not None
    assert s.intent == 'add_expense'


def test_get_returns_none_for_unknown_phone():
    assert ps.get('+999') is None


def test_expired_session_returns_none():
    s = ps.save('+862', 'add_expense', {}, _svc())
    # Force expiry
    s.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert ps.get('+862') is None
    # Should also be evicted from store
    assert '+862' not in ps._store


def test_clear_removes_session():
    ps.save('+863', 'get_balance', {}, _svc())
    ps.clear('+863')
    assert ps.get('+863') is None


def test_clear_on_missing_phone_is_noop():
    ps.clear('+000')   # should not raise


def test_overwrite_resets_expiry():
    ps.save('+864', 'add_expense', {}, _svc())
    ps.save('+864', 'add_income', {'amount': 100}, _svc())
    s = ps.get('+864')
    assert s.intent == 'add_income'
    assert s.entities == {'amount': 100}


# ──────────────────────────────────────────────────────────────────
# is_cancel
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', [
    '\u53d6\u6d88',           # 取消
    '\u7b97\u4e86',           # 算了
    '\u4e0d\u8981\u4e86',     # 不要了
    'cancel',
    'Cancel',
    'nevermind',
    'never mind',
    'stop',
])
def test_is_cancel_positive(text):
    assert ps.is_cancel(text) is True


@pytest.mark.parametrize('text', [
    '\u82b1\u4e865\u5143',    # 花了5元
    'remind me tomorrow',
    '\u4eca\u5929\u6709\u4ec0\u4e48',   # 今天有什么
])
def test_is_cancel_negative(text):
    assert ps.is_cancel(text) is False


# ──────────────────────────────────────────────────────────────────
# dispatch_message integration (all external I/O mocked)
# ──────────────────────────────────────────────────────────────────

def _make_msg(body='', conversation_id='conv1'):
    msg = MagicMock()
    msg.body = body
    msg.transcript = None
    msg.conversation_id = conversation_id
    return msg


def _make_session(phone='+8613800000000'):
    conv = MagicMock()
    conv.contact_id = 'c1'
    conv.connection_id = None

    contact = MagicMock()
    contact.phone_number = phone

    db = MagicMock()
    db.get.side_effect = lambda model, pk: conv if pk == 'conv1' else contact
    return db, conv, contact


def _settings(dispatch_enabled=True, whatsapp_mode='cloud'):
    s = MagicMock()
    s.dispatch_enabled = dispatch_enabled
    s.whatsapp_mode = whatsapp_mode
    s.whatsapp_access_token = ''
    s.whatsapp_phone_number_id = ''
    return s


# Helper: patch everything except the function under test
def _patches(intent_result=None, service=None, call_resp=None):
    return [
        patch('app.services.dispatch_service.detect_intent', return_value=intent_result),
        patch('app.services.dispatch_service._registry') ,
        patch('app.services.dispatch_service._call_service', return_value=call_resp),
        patch('app.services.dispatch_service._reply'),
        patch('app.services.dispatch_service.get_settings'),
    ]


def test_insufficient_data_saves_pending():
    """INSUFFICIENT_DATA response should create a pending session."""
    ps._store.clear()
    phone = '+8613800000001'
    db, conv, contact = _make_session(phone)

    intent_result = {'intent': 'add_expense', 'entities': {}}
    svc = _svc()
    call_resp = {'status': 'error', 'error_code': 'INSUFFICIENT_DATA',
                 'message': 'Please tell me the amount'}

    with patch('app.services.dispatch_service.detect_intent', return_value=intent_result), \
         patch('app.services.dispatch_service._registry') as mock_reg, \
         patch('app.services.dispatch_service._call_service', return_value=call_resp), \
         patch('app.services.dispatch_service._reply'), \
         patch('app.services.dispatch_service.get_settings', return_value=_settings()):
        mock_reg.find_service.return_value = svc

        from app.services.dispatch_service import dispatch_message
        dispatch_message(db, _make_msg('\u82b1\u4e86\u9910'))   # 花了餐

    s = ps.get(phone)
    assert s is not None
    assert s.intent == 'add_expense'


def test_followup_merges_entity_and_retries():
    """Follow-up '50元' should merge amount and call the service again."""
    ps._store.clear()
    phone = '+8613800000002'
    db, conv, contact = _make_session(phone)

    svc = _svc()
    ps.save(phone, 'add_expense', {}, svc)

    success_resp = {'status': 'success', 'message': 'Expense ¥50 recorded',
                    'quick_replies': []}

    with patch('app.services.dispatch_service.detect_intent', return_value=None), \
         patch('app.services.dispatch_service.extract_entities',
               return_value={'amount': 50.0}), \
         patch('app.services.dispatch_service._call_service',
               return_value=success_resp) as mock_call, \
         patch('app.services.dispatch_service._reply_from_resp') as mock_reply, \
         patch('app.services.dispatch_service.get_settings', return_value=_settings()):

        from app.services.dispatch_service import dispatch_message
        dispatch_message(db, _make_msg('50\u5143'))   # 50元

    mock_call.assert_called_once()
    _, _, _, intent, entities = mock_call.call_args[0]
    assert intent == 'add_expense'
    assert entities['amount'] == 50.0

    # Pending should be cleared after success
    assert ps.get(phone) is None
    mock_reply.assert_called_once()


def test_cancel_clears_pending_and_replies():
    """Cancel keyword should clear pending and send a cancellation reply."""
    ps._store.clear()
    phone = '+8613800000003'
    db, conv, contact = _make_session(phone)
    ps.save(phone, 'add_expense', {}, _svc())

    with patch('app.services.dispatch_service.get_settings', return_value=_settings()), \
         patch('app.services.dispatch_service._reply') as mock_reply:

        from app.services.dispatch_service import dispatch_message
        dispatch_message(db, _make_msg('\u53d6\u6d88'))   # 取消

    assert ps.get(phone) is None
    mock_reply.assert_called_once()
    reply_text = mock_reply.call_args[0][3]
    assert 'Cancelled' in reply_text


def test_new_intent_while_pending_drops_old():
    """A message with a new intent should drop the pending session and handle fresh."""
    ps._store.clear()
    phone = '+8613800000004'
    db, conv, contact = _make_session(phone)
    ps.save(phone, 'add_expense', {}, _svc())

    new_result = {'intent': 'get_balance', 'entities': {}}
    success_resp = {'status': 'success', 'message': 'Balance: ¥500', 'quick_replies': []}

    with patch('app.services.dispatch_service.detect_intent', return_value=new_result), \
         patch('app.services.dispatch_service._registry') as mock_reg, \
         patch('app.services.dispatch_service._call_service', return_value=success_resp), \
         patch('app.services.dispatch_service._reply_from_resp'), \
         patch('app.services.dispatch_service.get_settings', return_value=_settings()):
        mock_reg.find_service.return_value = _svc()

        from app.services.dispatch_service import dispatch_message
        dispatch_message(db, _make_msg('\u4f59\u989d'))   # 余额

    # Old pending (add_expense) should be gone; no new pending saved (get_balance succeeded)
    assert ps.get(phone) is None


def test_max_retries_gives_up():
    """After MAX_RETRIES follow-ups, clear pending and send give-up message."""
    ps._store.clear()
    phone = '+8613800000005'
    db, conv, contact = _make_session(phone)

    s = ps.save(phone, 'add_expense', {}, _svc())
    s.retries = ps.MAX_RETRIES   # already at limit

    with patch('app.services.dispatch_service.detect_intent', return_value=None), \
         patch('app.services.dispatch_service.extract_entities',
               return_value={'amount': 30.0}), \
         patch('app.services.dispatch_service._reply') as mock_reply, \
         patch('app.services.dispatch_service.get_settings', return_value=_settings()):

        from app.services.dispatch_service import dispatch_message
        dispatch_message(db, _make_msg('30\u5143'))   # 30元

    assert ps.get(phone) is None
    mock_reply.assert_called_once()
    reply_text = mock_reply.call_args[0][3]
    assert "start over" in reply_text.lower()
