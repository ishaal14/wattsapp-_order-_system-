"""
Order lifecycle manager (in-memory).

This module sits above `conversation_engine.py` and simulates:
customer -> system -> shop -> customer.

No DB, no UI, no WhatsApp: just Python objects and simple messages.
"""

from __future__ import annotations

from typing import Any

from conversation_engine import ConversationEngine


class OrderStatus:
    CREATED = "CREATED"
    PENDING_CLARIFICATION = "PENDING_CLARIFICATION"
    READY = "READY"
    SENT_TO_SHOP = "SENT_TO_SHOP"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OrderManager:
    def __init__(self, *, engine: ConversationEngine | None = None) -> None:
        self.engine = engine or ConversationEngine()
        self.orders: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"order_{self._counter}"

    def _require_order(self, order_id: str) -> dict[str, Any]:
        if order_id not in self.orders:
            raise KeyError(f"Unknown order_id: {order_id}")
        return self.orders[order_id]

    def _status_from_order(self, current_order: dict[str, Any]) -> str:
        return (
            OrderStatus.PENDING_CLARIFICATION
            if current_order.get("needs_clarification", False)
            else OrderStatus.READY
        )

    def create_order(self, customer_id: str, message: str) -> dict[str, Any]:
        """
        Create a new order and immediately process the first customer message
        through the conversation engine.
        """
        order_id = self._next_id()
        order = {
            "id": order_id,
            "customer_id": customer_id,
            "status": OrderStatus.CREATED,
            "items": [],
            "clarification_questions": [],
            "notes": "",
            "last_customer_message": message,
            "last_shop_message": "",
            "last_system_message": "",
        }
        self.orders[order_id] = order

        convo = self.engine.process_customer_message(customer_id, message)
        current_order = convo[customer_id]["current_order"]
        self.update_order_from_conversation(order_id, current_order)
        return self.orders[order_id]

    def update_order_from_conversation(self, order_id: str, conversation_output: dict[str, Any]) -> dict[str, Any]:
        """
        Update items + state based on conversation engine "current_order" output.
        """
        order = self._require_order(order_id)
        order["items"] = conversation_output.get("items", [])
        order["clarification_questions"] = conversation_output.get("clarification_questions", [])
        order["notes"] = conversation_output.get("notes", "")
        order["status"] = self._status_from_order(conversation_output)

        if order["status"] == OrderStatus.PENDING_CLARIFICATION and order["clarification_questions"]:
            order["last_system_message"] = f"shop is asking: {order['clarification_questions'][0]}"
        elif order["status"] == OrderStatus.READY:
            order["last_system_message"] = "order ready to send to shop"

        return order

    def send_to_shop(self, order_id: str) -> str:
        order = self._require_order(order_id)
        if order["status"] != OrderStatus.READY:
            raise ValueError(f"Order {order_id} must be READY to send to shop (got {order['status']})")

        order["status"] = OrderStatus.SENT_TO_SHOP
        order["last_shop_message"] = self._format_shop_payload(order)
        order["last_system_message"] = "order sent to shop"
        return order["last_shop_message"]

    def accept_order(self, order_id: str) -> str:
        order = self._require_order(order_id)
        if order["status"] != OrderStatus.SENT_TO_SHOP:
            raise ValueError(
                f"Order {order_id} must be SENT_TO_SHOP to accept (got {order['status']})"
            )
        order["status"] = OrderStatus.ACCEPTED
        msg = "order confirmed delivery in 20 mins"
        order["last_system_message"] = msg
        return msg

    def reject_order(self, order_id: str, reason: str | None = None) -> str:
        order = self._require_order(order_id)
        if order["status"] != OrderStatus.SENT_TO_SHOP:
            raise ValueError(
                f"Order {order_id} must be SENT_TO_SHOP to reject (got {order['status']})"
            )
        order["status"] = OrderStatus.REJECTED
        base = "sorry items not available"
        msg = f"{base} ({reason})" if reason else base
        order["last_system_message"] = msg
        return msg

    def ask_customer(self, order_id: str, question: str) -> str:
        """
        Simulate shop asking a question to the customer.
        """
        order = self._require_order(order_id)
        order["status"] = OrderStatus.PENDING_CLARIFICATION
        order["last_system_message"] = f"shop is asking: {question}"
        return order["last_system_message"]

    def receive_customer_message(self, order_id: str, message: str) -> dict[str, Any]:
        """
        Continue the conversation for an existing order using the same customer_id.
        """
        order = self._require_order(order_id)
        order["last_customer_message"] = message
        convo = self.engine.process_customer_message(order["customer_id"], message)
        current_order = convo[order["customer_id"]]["current_order"]
        return self.update_order_from_conversation(order_id, current_order)

    def _format_shop_payload(self, order: dict[str, Any]) -> str:
        lines: list[str] = [f"Order {order['id']} from {order['customer_id']}:"]
        items = order.get("items") or []
        if not items:
            lines.append("- (no items)")
            return "\n".join(lines)

        for it in items:
            name = it.get("name", "item")
            qty = it.get("quantity", 1)
            brand = it.get("brand")
            size = it.get("size")
            variant = it.get("variant")

            extra = " ".join(x for x in [brand, size, variant] if x)
            if extra:
                lines.append(f"- {qty} x {name} ({extra})")
            else:
                lines.append(f"- {qty} x {name}")
        return "\n".join(lines)


def demo() -> None:
    """
    Optional tiny demo using a stub extractor (no OpenAI).
    """
    from typing import Callable

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

    extractor: Callable[[str], dict[str, Any]] = lambda m: mapping[m]  # type: ignore[assignment]
    manager = OrderManager(engine=ConversationEngine(extractor=extractor))

    o = manager.create_order("cust_1", "milk")
    print("1)", o["status"], "-", o["last_system_message"])
    o = manager.receive_customer_message(o["id"], "almarai 1l")
    print("2)", o["status"], "-", o["last_system_message"])
    print("3) sending to shop:\n", manager.send_to_shop(o["id"]))
    print("4)", manager.accept_order(o["id"]))

if __name__ == "__main__":
    import sys

    manager = OrderManager()

    message = sys.argv[1] if len(sys.argv) > 1 else ""

    order = manager.create_order("cust_cli", message)

    print("\n=== ORDER CREATED ===")
    print("ID:", order["id"])
    print("STATUS:", order["status"])
    print("SYSTEM:", order["last_system_message"])
    print("ITEMS:", order["items"])