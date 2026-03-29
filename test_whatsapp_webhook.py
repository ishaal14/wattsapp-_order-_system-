from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from conversation_engine import ConversationEngine
from order_manager import OrderManager
from whatsapp_client import send_whatsapp_text
from whatsapp_flow import reset_whatsapp_flow_state, set_order_manager
from whatsapp_webhook import create_app, parse_incoming_text_messages


def _order(items: list[dict[str, Any]], needs: bool = False, qs: list[str] | None = None) -> dict[str, Any]:
    cooked = []
    for item in items:
        cooked.append(
            {
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "brand": item.get("brand"),
                "size": item.get("size"),
                "variant": item.get("variant"),
                "is_complete": item.get("is_complete", not needs),
                "missing_fields": item.get("missing_fields", []),
                "clarification_question": item.get("clarification_question"),
            }
        )
    return {
        "items": cooked,
        "needs_clarification": needs,
        "pending_clarification": needs,
        "clarification_questions": qs or [],
        "customer_language": "english",
        "notes": "",
    }


@pytest.fixture
def app():
    reset_whatsapp_flow_state()
    yield create_app()
    reset_whatsapp_flow_state()


@pytest.fixture
def client(app):
    return app.test_client()


def test_webhook_verification_success(monkeypatch, client):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "mysecret")
    r = client.get(
        "/webhook?hub.mode=subscribe&hub.verify_token=mysecret&hub.challenge=CHALLENGE123"
    )
    assert r.status_code == 200
    assert r.data.decode("utf-8") == "CHALLENGE123"
    assert "text/plain" in r.headers.get("Content-Type", "")


def test_webhook_verification_failure(monkeypatch, client):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "mysecret")
    r = client.get(
        "/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=CHALLENGE123"
    )
    assert r.status_code == 403


def _text_payload(body: str, wa_from: str = "15551234567") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "123"},
                            "contacts": [{"wa_id": wa_from, "profile": {"name": "Test"}}],
                            "messages": [
                                {
                                    "from": wa_from,
                                    "id": "wamid.test",
                                    "timestamp": "1234567890",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_parse_incoming_text_message():
    p = _text_payload("hello milk")
    msgs = parse_incoming_text_messages(p)
    assert len(msgs) == 1
    assert msgs[0]["from"] == "15551234567"
    assert msgs[0]["text"] == "hello milk"


def test_parse_ignores_unsupported_object():
    assert parse_incoming_text_messages({"object": "not_whatsapp"}) == []


def test_parse_ignores_status_updates():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [{"id": "x", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ]
            }
        ],
    }
    assert parse_incoming_text_messages(payload) == []


@patch("whatsapp_webhook.send_whatsapp_text")
def test_webhook_post_text_message(mock_send, monkeypatch, client):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "pid")
    mock_send.return_value = {"ok": True, "status_code": 200, "data": {}}

    mapping = {
        "milk": _order(
            [{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}],
            needs=True,
            qs=["Which brand of milk?"],
        ),
    }
    set_order_manager(OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m])))

    r = client.post(
        "/webhook",
        data=json.dumps(_text_payload("milk")),
        content_type="application/json",
    )
    assert r.status_code == 200
    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    assert args[0] == "15551234567"
    assert "Which brand" in args[1]


@patch("whatsapp_webhook.send_whatsapp_text")
def test_webhook_post_ignored_payload_still_200(mock_send, monkeypatch, client):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "pid")
    r = client.post(
        "/webhook",
        data=json.dumps({"object": "whatsapp_business_account", "entry": []}),
        content_type="application/json",
    )
    assert r.status_code == 200
    mock_send.assert_not_called()


@patch("whatsapp_client.requests.post")
def test_send_whatsapp_text_builds_payload(mock_post, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONE_ID_1")
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"messages": [{"id": "mid"}]}
    mock_post.return_value = mock_resp

    out = send_whatsapp_text("966501112233", "Hello")

    assert out["ok"] is True
    mock_post.assert_called_once()
    call_kw = mock_post.call_args
    assert "graph.facebook.com" in call_kw[0][0]
    assert "PHONE_ID_1" in call_kw[0][0]
    body = call_kw[1]["json"]
    assert body["to"] == "966501112233"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Hello"
    assert call_kw[1]["headers"]["Authorization"] == "Bearer test-token"


@patch("whatsapp_client.requests.post")
def test_send_whatsapp_text_http_error(mock_post, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "t")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "p")
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": {"message": "Invalid"}}
    mock_post.return_value = mock_resp

    out = send_whatsapp_text("1", "x")
    assert out["ok"] is False
    assert out["status_code"] == 400


@patch("whatsapp_webhook.send_whatsapp_text")
def test_end_to_end_incoming_triggers_reply(mock_send, monkeypatch, client):
    """Incoming text -> conversation/order flow -> send_whatsapp_text called with reply."""
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "pid")
    mock_send.return_value = {"ok": True, "status_code": 200, "data": {}}

    mapping = {
        "milk": _order(
            [{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}],
            needs=True,
            qs=["Which brand of 1L milk do you want"],
        ),
        "almarai 1l": _order(
            [{"name": "milk", "quantity": 1, "brand": "almarai", "size": "1L", "variant": None}],
            needs=False,
        ),
    }

    set_order_manager(
        OrderManager(
            engine=ConversationEngine(extractor=lambda m: mapping[m.strip().lower()])
        )
    )

    client.post(
        "/webhook",
        data=json.dumps(_text_payload("milk")),
        content_type="application/json",
    )
    first_reply = mock_send.call_args[0][1]
    assert "Which brand" in first_reply

    mock_send.reset_mock()
    client.post(
        "/webhook",
        data=json.dumps(_text_payload("almarai 1l")),
        content_type="application/json",
    )
    assert mock_send.called
    second_reply = mock_send.call_args[0][1]
    assert len(second_reply) > 0
