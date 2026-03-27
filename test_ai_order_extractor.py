import json
import os
from unittest.mock import MagicMock

import pytest
from openai import OpenAIError

from ai_order_extractor import (
    apply_item_rules,
    extract_order_as_json,
    extract_order_with_ai,
    validate_order_response,
)


def _fake_completion(content: str):
    class Msg:
        def __init__(self, c):
            self.content = c

    class Choice:
        def __init__(self, c):
            self.message = Msg(c)

    class Resp:
        def __init__(self, c):
            self.choices = [Choice(c)]

    return Resp(content)


def _patch_openai_client(monkeypatch, completion_content: str):
    mock_inst = MagicMock()
    mock_inst.chat.completions.create.return_value = _fake_completion(completion_content)
    monkeypatch.setattr("ai_order_extractor.OpenAI", MagicMock(return_value=mock_inst))


def test_valid_response(monkeypatch):
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 2,
                "brand": "almarai",
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }

    _patch_openai_client(monkeypatch, json.dumps(payload))

    result = extract_order_with_ai("2 milk")
    assert result["items"][0]["name"] == "milk"
    assert result["items"][0]["quantity"] == 2
    assert result["items"][0]["is_complete"] is True


def test_missing_keys(monkeypatch):
    _patch_openai_client(monkeypatch, "{}")

    with pytest.raises(ValueError, match=r"Invalid AI response: missing items"):
        extract_order_with_ai("anything")


def test_unknown_top_level_key_rejected(monkeypatch):
    payload = {
        "items": [],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
        "extra": 1,
    }
    _patch_openai_client(monkeypatch, json.dumps(payload))
    with pytest.raises(ValueError, match=r"unknown keys"):
        extract_order_with_ai("milk")


def test_validate_order_response_requires_item_name_and_quantity():
    with pytest.raises(ValueError, match=r"missing 'name'"):
        validate_order_response(
            {
                "items": [{"quantity": 1}],
                "needs_clarification": False,
                "pending_clarification": False,
                "clarification_questions": [],
                "customer_language": "english",
                "notes": "",
            }
        )

    with pytest.raises(ValueError, match=r"'name' must be a string"):
        validate_order_response(
            {
                "items": [{"name": 99, "quantity": 1}],
                "needs_clarification": False,
                "pending_clarification": False,
                "clarification_questions": [],
                "customer_language": "english",
                "notes": "",
            }
        )

    with pytest.raises(ValueError, match=r"missing 'quantity'"):
        validate_order_response(
            {
                "items": [
                    {
                        "name": "milk",
                        "brand": None,
                        "size": None,
                        "variant": None,
                        "is_complete": False,
                        "missing_fields": [],
                        "clarification_question": None,
                    }
                ],
                "needs_clarification": False,
                "pending_clarification": False,
                "clarification_questions": [],
                "customer_language": "english",
                "notes": "",
            }
        )


def test_unknown_item_key_rejected(monkeypatch):
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 1,
                "brand": None,
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
                "sku": "x",
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }
    _patch_openai_client(monkeypatch, json.dumps(payload))
    with pytest.raises(ValueError, match=r"items\[0\] unknown keys"):
        extract_order_with_ai("milk")


def test_invalid_quantity(monkeypatch):
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 0,
                "brand": None,
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }

    _patch_openai_client(monkeypatch, json.dumps(payload))

    with pytest.raises(ValueError, match=r"milk.*must be positive"):
        extract_order_with_ai("invalid quantity")


def test_empty_item_name(monkeypatch):
    payload = {
        "items": [
            {
                "name": "   ",
                "quantity": 1,
                "brand": None,
                "size": None,
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }
    _patch_openai_client(monkeypatch, json.dumps(payload))

    with pytest.raises(ValueError, match=r"non-empty string"):
        extract_order_with_ai("something")


def test_invalid_json(monkeypatch):
    _patch_openai_client(monkeypatch, "not valid json {")

    with pytest.raises(ValueError, match=r"Invalid JSON from AI"):
        extract_order_with_ai("order text")


def test_default_quantity_when_omitted(monkeypatch):
    payload = {
        "items": [
            {
                "name": "bread",
                "brand": None,
                "size": "big",
                "variant": "white",
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }

    _patch_openai_client(monkeypatch, json.dumps(payload))

    result = extract_order_with_ai("bread please")
    assert result["items"][0]["quantity"] == 1


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        extract_order_with_ai("milk")


def test_roman_urdu_mixed_order_shape(monkeypatch):
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 2,
                "brand": "olpers",
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            },
            {
                "name": "eggs",
                "quantity": 1,
                "brand": None,
                "size": None,
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            },
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "urdu",
        "notes": "bhej do",
    }
    _patch_openai_client(monkeypatch, json.dumps(payload))

    result = extract_order_with_ai("2 doodh aur anday bhej do")
    assert result["customer_language"] == "urdu"
    assert {x["name"] for x in result["items"]} == {"milk", "eggs"}


def test_extract_order_as_json_roundtrip(monkeypatch):
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 2,
                "brand": "almarai",
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "pending_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }
    _patch_openai_client(monkeypatch, json.dumps(payload))

    out = extract_order_as_json("2 milk", indent=None)
    assert json.loads(out)["items"][0]["name"] == "milk"


@pytest.mark.parametrize(
    ("item", "is_complete", "missing"),
    [
        ({"name": "eggs", "quantity": 12, "brand": None, "size": None, "variant": None}, True, []),
        ({"name": "milk", "quantity": 1, "brand": None, "size": "1L", "variant": None}, False, ["brand"]),
        ({"name": "bread", "quantity": None, "brand": None, "size": None, "variant": None}, False, ["quantity", "variant"]),
        ({"name": "pepsi", "quantity": 2, "brand": None, "size": None, "variant": None}, False, ["size"]),
        ({"name": "water", "quantity": None, "brand": None, "size": None, "variant": None}, False, ["quantity", "size"]),
        ({"name": "tomatoes", "quantity": 1, "brand": None, "size": None, "variant": None}, True, []),
    ],
)
def test_apply_item_rules_completeness(item, is_complete, missing):
    order = {
        "items": [
            {
                **item,
                "is_complete": False,
                "missing_fields": [],
                "clarification_question": None,
            }
        ],
        "needs_clarification": False,
        "clarification_questions": [],
        "customer_language": "english",
        "notes": "",
    }
    apply_item_rules(order)
    assert order["items"][0]["is_complete"] is is_complete
    assert order["items"][0]["missing_fields"] == missing


def test_validate_order_response_rejects_invalid_missing_fields_type():
    payload = {
        "items": [
            {
                "name": "milk",
                "quantity": 1,
                "brand": None,
                "size": "1L",
                "variant": None,
                "is_complete": False,
                "missing_fields": "brand",
                "clarification_question": "Which brand?",
            }
        ],
        "needs_clarification": True,
        "pending_clarification": True,
        "clarification_questions": ["Which brand?"],
        "customer_language": "english",
        "notes": "",
    }
    with pytest.raises(ValueError, match=r"missing_fields"):
        validate_order_response(payload)


@pytest.mark.integration
def test_integration_live_openai():
    """Optional: real API call. Run with RUN_INTEGRATION=1 and OPENAI_API_KEY set."""
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to run integration tests (requires OPENAI_API_KEY)")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY is not set")

    try:
        result = extract_order_with_ai("2 doodh aur anday bhej do")
    except OpenAIError as e:
        pytest.skip(f"OpenAI unavailable for optional integration test: {e}")

    validate_order_response(result)
    assert isinstance(result["items"], list)
    assert len(result["items"]) >= 1
