"""
Bridge WhatsApp customer ids (phone / wa_id) to OrderManager + ConversationEngine.

One active order per customer until the order is ACCEPTED or REJECTED; then the next
message starts a new order.
"""

from __future__ import annotations

from typing import Any

from order_manager import OrderManager, OrderStatus

_manager: OrderManager | None = None
_customer_order_id: dict[str, str] = {}


def get_order_manager() -> OrderManager:
    global _manager
    if _manager is None:
        _manager = OrderManager()
    return _manager


def set_order_manager(manager: OrderManager | None) -> None:
    """For tests: inject a manager with a stub extractor. Pass None to clear."""
    global _manager
    _manager = manager
    _customer_order_id.clear()


def reset_whatsapp_flow_state() -> None:
    """Clear in-memory session mapping (e.g. between tests)."""
    global _manager
    _manager = None
    _customer_order_id.clear()


def _reply_text(order: dict[str, Any]) -> str:
    status = order.get("status")
    questions = order.get("clarification_questions") or []
    if status == OrderStatus.PENDING_CLARIFICATION and questions:
        return str(questions[0])
    if status == OrderStatus.READY:
        return order.get("last_system_message") or "Your order looks complete."
    if status == OrderStatus.SENT_TO_SHOP:
        return order.get("last_system_message") or "Your order was sent to the shop."
    if status == OrderStatus.ACCEPTED:
        return order.get("last_system_message") or "Thanks — your order is confirmed."
    if status == OrderStatus.REJECTED:
        return order.get("last_system_message") or "Sorry, something went wrong with your order."
    return order.get("last_system_message") or "Thanks, we received your message."


def process_incoming_customer_message(customer_id: str, message: str) -> str:
    """
    Run the message through OrderManager (which uses ConversationEngine).

    customer_id should be stable per WhatsApp user (we use the sender wa_id).
    """
    mgr = get_order_manager()
    oid = _customer_order_id.get(customer_id)

    if oid and oid in mgr.orders:
        order = mgr.orders[oid]
        if order["status"] in (OrderStatus.ACCEPTED, OrderStatus.REJECTED):
            _customer_order_id.pop(customer_id, None)
        else:
            updated = mgr.receive_customer_message(oid, message)
            return _reply_text(updated)
    elif oid:
        _customer_order_id.pop(customer_id, None)

    created = mgr.create_order(customer_id, message)
    _customer_order_id[customer_id] = created["id"]
    return _reply_text(created)
