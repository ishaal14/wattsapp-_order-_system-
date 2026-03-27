from __future__ import annotations

from typing import Any

import pytest

from conversation_engine import ConversationEngine
from order_manager import OrderManager, OrderStatus


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


def test_happy_path_ready_sent_accepted():
    mapping = {
        "2 almarai 1l milk": _order(
            [{"name": "milk", "quantity": 2, "brand": "almarai", "size": "1L", "variant": None}],
            needs=False,
        )
    }
    manager = OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m]))

    order = manager.create_order("cust_1", "2 almarai 1l milk")
    assert order["status"] == OrderStatus.READY

    shop_payload = manager.send_to_shop(order["id"])
    assert manager.orders[order["id"]]["status"] == OrderStatus.SENT_TO_SHOP
    assert "Order order_1" in shop_payload
    assert "milk" in shop_payload

    customer_msg = manager.accept_order(order["id"])
    assert manager.orders[order["id"]]["status"] == OrderStatus.ACCEPTED
    assert "confirmed" in customer_msg
    assert "20 mins" in customer_msg


def test_clarification_flow_incomplete_then_complete_then_accepted():
    mapping = {
        "milk": _order(
            [{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}],
            needs=True,
            qs=["Which brand and size of milk do you want"],
        ),
        "almarai 1l": _order(
            [{"name": "milk", "quantity": 1, "brand": "almarai", "size": "1L", "variant": None}],
            needs=False,
        ),
    }
    manager = OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m]))

    order = manager.create_order("cust_2", "milk")
    assert order["status"] == OrderStatus.PENDING_CLARIFICATION
    assert "shop is asking:" in order["last_system_message"]
    assert "Which brand and size" in order["last_system_message"]

    updated = manager.receive_customer_message(order["id"], "almarai 1l")
    assert updated["status"] == OrderStatus.READY

    manager.send_to_shop(order["id"])
    msg = manager.accept_order(order["id"])
    assert manager.orders[order["id"]]["status"] == OrderStatus.ACCEPTED
    assert "confirmed" in msg


def test_rejection_flow_sent_then_rejected():
    mapping = {
        "12 eggs": _order([{"name": "eggs", "quantity": 12, "brand": None, "size": None, "variant": None}]),
    }
    manager = OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m]))

    order = manager.create_order("cust_3", "12 eggs")
    assert order["status"] == OrderStatus.READY

    manager.send_to_shop(order["id"])
    msg = manager.reject_order(order["id"])
    assert manager.orders[order["id"]]["status"] == OrderStatus.REJECTED
    assert "sorry" in msg.lower()


def test_shop_can_ask_customer_question():
    mapping = {
        "12 eggs": _order([{"name": "eggs", "quantity": 12, "brand": None, "size": None, "variant": None}]),
    }
    manager = OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m]))
    order = manager.create_order("cust_4", "12 eggs")
    manager.send_to_shop(order["id"])

    msg = manager.ask_customer(order["id"], "Do you want brown or white eggs")
    assert manager.orders[order["id"]]["status"] == OrderStatus.PENDING_CLARIFICATION
    assert "shop is asking:" in msg


def test_cannot_send_to_shop_unless_ready():
    mapping = {
        "milk": _order(
            [{"name": "milk", "quantity": 1, "brand": None, "size": None, "variant": None}],
            needs=True,
            qs=["Which brand and size of milk do you want"],
        )
    }
    manager = OrderManager(engine=ConversationEngine(extractor=lambda m: mapping[m]))
    order = manager.create_order("cust_5", "milk")

    with pytest.raises(ValueError, match="must be READY"):
        manager.send_to_shop(order["id"])

