"""Simple in-memory conversation engine for grocery ordering."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from ai_order_extractor import apply_item_rules, extract_order_with_ai, validate_order_response


OrderExtractor = Callable[[str], dict[str, Any]]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


class ConversationEngine:
    def __init__(self, extractor: OrderExtractor | None = None) -> None:
        self.extractor: OrderExtractor = extractor or extract_order_with_ai
        self.sessions: dict[str, dict[str, Any]] = {}

    def _empty_order(self) -> dict[str, Any]:
        # Must match the validated order response schema.
        return {
            "items": [],
            "needs_clarification": False,
            "clarification_questions": [],
            "customer_language": "english",
            "notes": "",
            
        }

    def _session(self, customer_id: str) -> dict[str, Any]:
        if customer_id not in self.sessions:
            self.sessions[customer_id] = {
                "messages": [],
                "current_order": None,
                "pending_clarification": False,
            }
        return self.sessions[customer_id]

    def _merge_item(self, base_item: dict[str, Any], incoming_item: dict[str, Any], raw_message: str) -> None:
        for key in ("quantity", "brand", "size", "variant"):
            if _is_missing(base_item.get(key)) and not _is_missing(incoming_item.get(key)):
                base_item[key] = incoming_item.get(key)

        # Simple fallback for brand-only follow-ups (e.g. "almarai").
        # Guarded so unrelated one-word messages (e.g. "bread") do not fill another item's brand.
        token = raw_message.strip()
        same_item_name = incoming_item.get("name") == base_item.get("name")
        if " " not in token and _is_missing(base_item.get("brand")) and token and same_item_name:
            base_item["brand"] = token.lower()

    def _merge_followup(self, current_order: dict[str, Any], followup_order: dict[str, Any], raw_message: str) -> dict[str, Any]:
        current_items = current_order["items"]
        incoming_items = followup_order["items"]
        used_incoming: set[int] = set()

        incomplete_indexes = [i for i, it in enumerate(current_items) if not it.get("is_complete", False)]
        for idx in incomplete_indexes:
            base_item = current_items[idx]
            match_index = None

            for j, incoming in enumerate(incoming_items):
                if j in used_incoming:
                    continue
                if incoming.get("name") == base_item.get("name"):
                    match_index = j
                    break

            if match_index is None and len(incomplete_indexes) == 1 and len(incoming_items) == 1:
                match_index = 0

            if match_index is not None:
                used_incoming.add(match_index)
                self._merge_item(base_item, incoming_items[match_index], raw_message)

        for j, incoming in enumerate(incoming_items):
            if j not in used_incoming:
                current_items.append(incoming)

        apply_item_rules(current_order)
        validate_order_response(current_order)
        return current_order

    def process_customer_message(self, customer_id: str, message: str) -> dict[str, Any]:
        session = self._session(customer_id)
        session["messages"].append(message)

        raw = "" if message is None else str(message)
        if not raw.strip():
            session["current_order"] = deepcopy(self._empty_order())
            session["pending_clarification"] = False
            return {customer_id: deepcopy(session)}

        extracted = self.extractor(raw)
        validate_order_response(extracted)
        apply_item_rules(extracted)
        validate_order_response(extracted)

        if session["pending_clarification"] and session["current_order"] is not None:
            merged = self._merge_followup(session["current_order"], extracted, raw)
            session["current_order"] = merged
        else:
            session["current_order"] = deepcopy(extracted)

        # Keep session flag in sync with the order.
        session["pending_clarification"] = bool(session["current_order"]["needs_clarification"])
        session["current_order"]["pending_clarification"] = session["pending_clarification"]

        return {customer_id: deepcopy(session)}

_DEFAULT_ENGINE = ConversationEngine()


def process_customer_message(customer_id: str, message: str) -> dict[str, Any]:
    """Module-level helper using a default in-memory engine."""
    return _DEFAULT_ENGINE.process_customer_message(customer_id, message)

