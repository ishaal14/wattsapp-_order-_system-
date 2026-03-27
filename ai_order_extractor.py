"""
OpenAI-backed grocery order extraction: raw message -> validated structured dict.

Main API:
- extract_order_with_ai(message: str) -> dict
- extract_order_as_json(message: str) -> str

This module keeps a strict JSON schema, then applies simple item rules to decide:
- is_complete
- missing_fields
- clarification_question
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import APIConnectionError, APIStatusError, OpenAI

DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You extract grocery orders from one customer message.
Return one JSON object only (no markdown, no commentary).
Use exactly these top-level keys and no others:

{
  "items": [
    {
      "name": "<English product name>",
      "quantity": <positive integer or null>,
      "brand": "<string or null>",
      "size": "<string or null>",
      "variant": "<string or null>",
      "is_complete": <boolean>,
      "missing_fields": ["<string>", ...],
      "clarification_question": "<string or null>"
    }
  ],
  "needs_clarification": <true|false>,
  "pending_clarification": <true|false>,
  "clarification_questions": [ "<string>", ... ],
  "customer_language": "<english|urdu|arabic|mixed|other>",
  "notes": "<non-product text or empty string>"
}

Rules:
- Normalize item names to English (e.g. doodh -> milk, anday -> eggs).
- Keep item names simple, singular where possible (banana, tomato, milk, bread).
- If value is unknown, use null.
- "pending_clarification" must always match "needs_clarification".
- Return strict JSON only.
"""


def _openai_error_message(exc: BaseException) -> str:
    if isinstance(exc, APIStatusError):
        code = None
        if isinstance(exc.body, dict):
            err = exc.body.get("error")
            code = err.get("code") if isinstance(err, dict) else exc.body.get("code")
        if exc.status_code == 401:
            return "OpenAI rejected the API key (401). Check OPENAI_API_KEY."
        if exc.status_code == 429 and code == "insufficient_quota":
            return (
                "OpenAI quota exceeded. Add billing at "
                "https://platform.openai.com/account/billing"
            )
        if exc.status_code == 429:
            return f"OpenAI rate limited (429): {exc.message}"
        return f"OpenAI API error ({exc.status_code}): {exc.message}"
    if isinstance(exc, APIConnectionError):
        return f"Could not reach OpenAI: {exc.message}"
    return str(exc)


def _default_item_quantities(items: list[Any]) -> None:
    for row in items:
        if isinstance(row, dict) and ("quantity" not in row or row["quantity"] is None):
            row["quantity"] = 1


_TOP_LEVEL_KEYS = (
    "items",
    "needs_clarification",
    "pending_clarification",
    "clarification_questions",
    "customer_language",
    "notes",
)


ITEM_RULES: dict[str, dict[str, list[str]]] = {
    "milk": {"required_fields": ["quantity", "size", "brand_or_any"]},
    "eggs": {"required_fields": ["quantity"]},
    "bread": {"required_fields": ["quantity", "variant"]},
    "water": {"required_fields": ["quantity", "size"]},
    "pepsi": {"required_fields": ["quantity", "size"]},
    "banana": {"required_fields": ["quantity"]},
    "bananas": {"required_fields": ["quantity"]},
    "tomato": {"required_fields": ["quantity_or_weight"]},
    "tomatoes": {"required_fields": ["quantity_or_weight"]},
    "detergent": {"required_fields": ["quantity", "brand", "size"]},
}


def _normalize_name(name: str) -> str:
    n = name.strip().lower()
    aliases = {
        "doodh": "milk",
        "anday": "eggs",
        "anda": "eggs",
        "banana": "banana",
        "bananas": "banana",
        "tomatoes": "tomatoes",
        "tomato": "tomatoes",
    }
    return aliases.get(n, n)


def _is_present_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _needs_size_for_quantity_or_weight(size: Any) -> bool:
    if not _is_present_str(size):
        return True
    token = str(size).lower()
    units = ("kg", "g", "gram", "grams", "ml", "l", "litre", "liter")
    return not any(unit in token for unit in units)


def _compute_missing_fields(item: dict[str, Any]) -> list[str]:
    name = _normalize_name(str(item["name"]))
    required = ITEM_RULES.get(name, {}).get("required_fields", ["quantity"])
    missing: list[str] = []

    for req in required:
        if req == "quantity":
            if not isinstance(item.get("quantity"), int) or isinstance(item.get("quantity"), bool):
                missing.append("quantity")
        elif req == "brand":
            if not _is_present_str(item.get("brand")):
                missing.append("brand")
        elif req == "size":
            if not _is_present_str(item.get("size")):
                missing.append("size")
        elif req == "variant":
            if not _is_present_str(item.get("variant")):
                missing.append("variant")
        elif req == "brand_or_any":
    # brand is required unless explicitly handled later
             if not _is_present_str(item.get("brand")):
              missing.append("brand")
        
        
        elif req == "quantity_or_weight":
            has_quantity = isinstance(item.get("quantity"), int) and not isinstance(item.get("quantity"), bool)
            has_weight = not _needs_size_for_quantity_or_weight(item.get("size"))
            if not (has_quantity or has_weight):
                missing.append("quantity_or_weight")

    return missing


def _clarification_question_for_item(item: dict[str, Any], missing_fields: list[str]) -> str | None:
    if not missing_fields:
        return None

    name = _normalize_name(str(item["name"]))
    quantity = item.get("quantity")
    brand = item.get("brand")
    size = item.get("size")

    if name == "bread" and {"quantity", "variant"}.issubset(set(missing_fields)):
        return "How many and what type of bread do you want"
    if name == "water" and {"quantity", "size"}.issubset(set(missing_fields)):
        return "How many and what size of water do you want"
    if name == "milk":
        if "brand" in missing_fields and _is_present_str(size):
            return f"Which brand of {size} milk do you want"
        if "size" in missing_fields and _is_present_str(brand):
            return f"Which size of {brand} milk do you want"
        if {"brand", "size"}.issubset(set(missing_fields)):
            return "Which brand and size of milk do you want"
    if name == "pepsi" and "size" in missing_fields and isinstance(quantity, int):
        return f"Which size of pepsi do you want for {quantity}"
    if name == "detergent" and set(missing_fields) == {"brand", "size"}:
        return "Which brand and size of detergent do you want"
    if name == "tomatoes" and "quantity_or_weight" in missing_fields:
        return "How many tomatoes or what weight do you want"

    if len(missing_fields) == 1:
        return f"Please provide {missing_fields[0]} for {name}"
    joined = ", ".join(missing_fields)
    return f"Please provide {joined} for {name}"


def apply_item_rules(order: dict[str, Any]) -> dict[str, Any]:
    questions: list[str] = []

    for item in order["items"]:
        item["name"] = _normalize_name(str(item["name"]))
        missing_fields = _compute_missing_fields(item)
        item["missing_fields"] = missing_fields
        item["is_complete"] = len(missing_fields) == 0
        item["clarification_question"] = _clarification_question_for_item(item, missing_fields)
        if item["clarification_question"]:
            questions.append(item["clarification_question"])

    deduped_questions = list(dict.fromkeys(questions))
    order["clarification_questions"] = deduped_questions
    order["needs_clarification"] = len(deduped_questions) > 0
    order["pending_clarification"] = order["needs_clarification"]
    return order


def _ordered_response(data: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with keys in the expected output order."""
    return {key: data[key] for key in _TOP_LEVEL_KEYS}


def validate_order_response(data: dict[str, Any]) -> None:
    """Strict validation for top-level and item-level schema."""
    if not isinstance(data, dict):
        raise ValueError("Invalid order: root must be a JSON object")

    allowed = set(_TOP_LEVEL_KEYS)
    unknown = set(data.keys()) - allowed
    if unknown:
        raise ValueError(
            f"Invalid AI response: unknown keys {sorted(unknown)} (schema allows only {sorted(allowed)})"
        )

    for key in _TOP_LEVEL_KEYS:
        if key not in data:
            raise ValueError(f"Invalid AI response: missing {key}")

    if not isinstance(data["items"], list):
        raise ValueError("Invalid AI response: 'items' must be a list")
    if not isinstance(data["needs_clarification"], bool):
        raise ValueError("Invalid AI response: 'needs_clarification' must be a boolean")
    if not isinstance(data["pending_clarification"], bool):
        raise ValueError("Invalid AI response: 'pending_clarification' must be a boolean")
    if not isinstance(data["clarification_questions"], list):
        raise ValueError("Invalid AI response: 'clarification_questions' must be a list")
    if not isinstance(data["customer_language"], str):
        raise ValueError("Invalid AI response: 'customer_language' must be a string")
    if not isinstance(data["notes"], str):
        raise ValueError("Invalid AI response: 'notes' must be a string")

    for i, q in enumerate(data["clarification_questions"]):
        if not isinstance(q, str):
            raise ValueError(
                f"Invalid AI response: clarification_questions[{i}] must be a string"
            )

    item_allowed = {
        "name",
        "quantity",
        "brand",
        "size",
        "variant",
        "is_complete",
        "missing_fields",
        "clarification_question",
    }
    for idx, item in enumerate(data["items"]):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid AI response: items[{idx}] must be an object")

        extra = set(item.keys()) - item_allowed
        if extra:
            raise ValueError(
                f"Invalid AI response: items[{idx}] unknown keys {sorted(extra)}"
            )

        if "name" not in item:
            raise ValueError(f"Invalid AI response: items[{idx}] missing 'name' (must be a string)")
        if not isinstance(item["name"], str):
            raise ValueError(
                f"Invalid AI response: items[{idx}] 'name' must be a string, not {type(item['name']).__name__}"
            )
        name = item["name"].strip()
        if not name:
            raise ValueError(
                f"Invalid AI response: items[{idx}] 'name' must be a non-empty string"
            )
        item["name"] = name

        if "quantity" not in item:
            raise ValueError(f"Invalid AI response: items[{idx}] missing 'quantity'")
        qty = item["quantity"]
        if qty is not None:
            if isinstance(qty, bool) or not isinstance(qty, int):
                raise ValueError(
                    f"Invalid AI response: items[{idx}] ({name!r}) 'quantity' must be an integer > 0 if present"
                )
            if qty < 1:
                raise ValueError(
                    f"Invalid AI response: quantity for item at index {idx} ({name!r}) must be positive, got {qty}"
                )

        for key in ("brand", "size", "variant"):
            if key not in item:
                raise ValueError(f"Invalid AI response: items[{idx}] missing '{key}'")
            value = item[key]
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"Invalid AI response: items[{idx}] '{key}' must be a string or null"
                )
            if isinstance(value, str):
                item[key] = value.strip() or None

        if "is_complete" not in item or not isinstance(item["is_complete"], bool):
            raise ValueError(f"Invalid AI response: items[{idx}] 'is_complete' must be a boolean")

        if "missing_fields" not in item or not isinstance(item["missing_fields"], list):
            raise ValueError(f"Invalid AI response: items[{idx}] 'missing_fields' must be a list")
        for j, field in enumerate(item["missing_fields"]):
            if not isinstance(field, str):
                raise ValueError(
                    f"Invalid AI response: items[{idx}] missing_fields[{j}] must be a string"
                )

        if "clarification_question" not in item:
            raise ValueError(f"Invalid AI response: items[{idx}] missing 'clarification_question'")
        cq = item["clarification_question"]
        if cq is not None and not isinstance(cq, str):
            raise ValueError(
                f"Invalid AI response: items[{idx}] 'clarification_question' must be a string or null"
            )


def extract_order_with_ai(message: str) -> dict:
    """
    Parse ``message`` with OpenAI and return a validated order dict.

    Environment: ``OPENAI_API_KEY`` (required). Optional ``OPENAI_ORDER_MODEL`` (default ``gpt-4o-mini``).

    Raises ``ValueError`` for missing key, empty message, bad JSON, or invalid structure.
    Propagates OpenAI SDK errors (auth, quota, network, etc.).
    """
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is not set or is empty")
    text = str(message).strip()
    if not text:
        raise ValueError("message must be a non-empty string")

    model = os.environ.get("OPENAI_ORDER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    raw = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = raw.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("Invalid AI response: empty content")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from AI: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Invalid AI response: root must be a JSON object")

    if isinstance(data.get("items"), list):
        _default_item_quantities(data["items"])

    validate_order_response(data)
    apply_item_rules(data)
    # Ensure stable key order for the UI / integrations that expect this format.
    return _ordered_response(data)


def extract_order_as_json(message: str, *, indent: int | None = 2) -> str:
    """Same as extract_order_with_ai, as a JSON string (UTF-8, non-ASCII preserved)."""
    return json.dumps(extract_order_with_ai(message), indent=indent, ensure_ascii=False)


if __name__ == "__main__":
    import sys

    demo = "I need 2 apples, doodh, and some bread"
    user_text = " ".join(sys.argv[1:]).strip()
    text = user_text or demo
    try:
        result = extract_order_with_ai(text)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except ValueError as e:
        print(f"Error: {e}")
    except (APIStatusError, APIConnectionError) as e:
        print(_openai_error_message(e))
        
