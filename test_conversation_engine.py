from __future__ import annotations

from typing import Any

from conversation_engine import ConversationEngine


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
                "is_complete": item.get("is_complete", False),
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


def test_complete_cases():
    mapping = {
        "12 eggs": _order([{"name": "eggs", "quantity": 12, "brand": None, "size": None, "variant": None}]),
        "2 almarai 1l milk": _order([{"name": "milk", "quantity": 2, "brand": "almarai", "size": "1L", "variant": None}]),
        "1 big white bread": _order([{"name": "bread", "quantity": 1, "brand": None, "size": "big", "variant": "white"}]),
        "2 pepsi 330ml": _order([{"name": "pepsi", "quantity": 2, "brand": None, "size": "330ml", "variant": None}]),
        "1kg tomatoes": _order([{"name": "tomatoes", "quantity": 1, "brand": None, "size": "1kg", "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])

    for msg in mapping:
        result = engine.process_customer_message("c1", msg)["c1"]["current_order"]
        assert result["needs_clarification"] is False
        assert all(it["is_complete"] for it in result["items"])


def test_incomplete_cases():
    mapping = {
        "milk": _order([{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}]),
        "1l milk": _order([{"name": "milk", "quantity": 1, "brand": None, "size": "1L", "variant": None}]),
        "bread": _order([{"name": "bread", "quantity": None, "brand": None, "size": None, "variant": None}]),
        "2 pepsi": _order([{"name": "pepsi", "quantity": 2, "brand": None, "size": None, "variant": None}]),
        "water": _order([{"name": "water", "quantity": None, "brand": None, "size": None, "variant": None}]),
        "detergent": _order([{"name": "detergent", "quantity": 1, "brand": None, "size": None, "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])

    for msg in mapping:
        result = engine.process_customer_message("c2", msg)["c2"]["current_order"]
        assert result["needs_clarification"] is True
        assert any(not it["is_complete"] for it in result["items"])


def test_followup_bread_completion():
    mapping = {
        "bread": _order([{"name": "bread", "quantity": None, "brand": None, "size": None, "variant": None}]),
        "1 big white bread": _order([{"name": "bread", "quantity": 1, "brand": None, "size": "big", "variant": "white"}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])

    first = engine.process_customer_message("c3", "bread")["c3"]["current_order"]
    assert first["needs_clarification"] is True

    final = engine.process_customer_message("c3", "1 big white bread")["c3"]["current_order"]
    assert final["needs_clarification"] is False
    assert final["items"][0]["is_complete"] is True


def test_followup_milk_brand_completion():
    mapping = {
        "1l milk": _order([{"name": "milk", "quantity": 1, "brand": None, "size": "1L", "variant": None}]),
        "almarai": _order([{"name": "milk", "quantity": None, "brand": "almarai", "size": None, "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])
    engine.process_customer_message("c4", "1l milk")
    final = engine.process_customer_message("c4", "almarai")["c4"]["current_order"]
    assert final["needs_clarification"] is False
    milk = final["items"][0]
    assert milk["brand"] == "almarai"
    assert milk["is_complete"] is True


def test_followup_two_items_completion():
    mapping = {
        "milk and bread": _order(
            [
                {"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None},
                {"name": "bread", "quantity": None, "brand": None, "size": None, "variant": None},
            ]
        ),
        "almarai and 1 big white bread": _order(
            [
                {"name": "milk", "quantity": None, "brand": "almarai", "size": "1L", "variant": None},
                {"name": "bread", "quantity": 1, "brand": None, "size": "big", "variant": "white"},
            ]
        ),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])
    engine.process_customer_message("c5", "milk and bread")
    final = engine.process_customer_message("c5", "almarai and 1 big white bread")["c5"]["current_order"]
    assert final["needs_clarification"] is False
    assert all(x["is_complete"] for x in final["items"])


def test_followup_pepsi_size_completion():
    mapping = {
        "2 pepsi": _order([{"name": "pepsi", "quantity": 2, "brand": None, "size": None, "variant": None}]),
        "330ml": _order([{"name": "pepsi", "quantity": None, "brand": None, "size": "330ml", "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])
    engine.process_customer_message("c6", "2 pepsi")
    final = engine.process_customer_message("c6", "330ml")["c6"]["current_order"]
    assert final["needs_clarification"] is False
    assert final["items"][0]["size"] == "330ml"


def test_still_incomplete_after_followup():
    mapping = {
        "milk": _order([{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}]),
        "almarai": _order([{"name": "milk", "quantity": None, "brand": "almarai", "size": None, "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])
    engine.process_customer_message("c7", "milk")
    follow = engine.process_customer_message("c7", "almarai")["c7"]["current_order"]
    assert follow["needs_clarification"] is True
    assert "size" in follow["items"][0]["missing_fields"]


def test_unknown_item_supported():
    mapping = {
        "something special": _order([{"name": "mystery-item", "quantity": None, "brand": None, "size": None, "variant": None}]),
    }
    engine = ConversationEngine(extractor=lambda m: mapping[m])
    result = engine.process_customer_message("c8", "something special")["c8"]["current_order"]
    assert result["items"][0]["name"] == "mystery-item"
    assert result["needs_clarification"] is True

