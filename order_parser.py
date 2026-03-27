"""
Grocery-style order parsing — all parsing logic is in this module.

``parse_order(text: str) -> dict[str, int]``
    Maps each normalized item name to its total quantity.
    Key order is first-seen (Python 3.7+ ``dict`` preserves insertion order).

Example: ``parse_order("2 milk and eggs")`` → ``{"milk": 2, "eggs": 1}``.
"""

import re

__all__ = ["parse_order", "format_order"]


def _normalize_item_name(name: str) -> str:
    return " ".join(name.strip().split())


def parse_order(text: str) -> dict[str, int]:
    """
    Turn free-form grocery text into ``{item_name: quantity, ...}`` (insertion order kept).

    Example: ``parse_order("2 milk and eggs")`` → ``{"milk": 2, "eggs": 1}``.

    - Separators: ``,``, ``and``, ``aur`` (word boundaries, any casing).
    - Quantity defaults to 1 when omitted.
    - Same item appears once with summed quantity (first-seen order preserved).
    - With no separators and no numbers, each word is one item (e.g. ``milk milk eggs``).
    """
    if not text or not text.strip():
        return {}

    cleaned = re.sub(r"\s+", " ", text.lower()).strip()
    has_explicit_separator = bool(re.search(r"(?:,|\band\b|\baur\b)", cleaned))
    parts = re.split(r"\s*(?:,|\band\b|\baur\b)\s*", cleaned)

    combined: dict[str, int] = {}
    order: list[str] = []

    def add_item(name: str, qty: int) -> None:
        item_name = _normalize_item_name(name)
        if not item_name:
            return
        if item_name not in combined:
            combined[item_name] = qty
            order.append(item_name)
        else:
            combined[item_name] += qty

    for raw_part in parts:
        part = raw_part.strip()
        if not part:
            continue

        tokens = part.split()
        has_number = any(t.isdigit() for t in tokens)

        if not has_explicit_separator and not has_number:
            for token in tokens:
                add_item(token, 1)
            continue

        i = 0
        while i < len(tokens):
            if tokens[i].isdigit():
                qty = int(tokens[i])
                i += 1
            else:
                qty = 1

            start = i
            while i < len(tokens) and not tokens[i].isdigit():
                i += 1

            name = " ".join(tokens[start:i]).strip()
            if name:
                add_item(name, qty)

    return {item: combined[item] for item in order}


def format_order(parsed: dict[str, int]) -> list[str]:
    return [f"{item} x{qty}" for item, qty in parsed.items()]


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "2 apples and milk aur 3 apples"

    parsed = parse_order(text)
    print(format_order(parsed))
