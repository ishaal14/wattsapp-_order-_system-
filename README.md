# WhatsApp order system

Turn messy grocery-style messages into structured data: a **rule-based parser** for fast local parsing, and an **OpenAI-backed extractor** for richer understanding (language, notes, clarification).

## Layout

```
whatsapp-order-system/
├── order_parser.py
├── test_order_parser.py
├── ai_order_extractor.py
├── test_ai_order_extractor.py
├── conversation_engine.py
├── test_conversation_engine.py
├── README.md
├── requirements.txt
└── Makefile
```

Also included: `order_response.schema.json` (JSON shape for AI output), `pytest.ini` (optional `@pytest.mark.integration`).

## Rich item schema

The AI extractor now returns item-level fields needed for realistic grocery fulfillment:

- `name`
- `quantity`
- `brand`
- `size`
- `variant`
- `is_complete`
- `missing_fields`
- `clarification_question`

Top-level keys remain:

- `items`
- `needs_clarification`
- `clarification_questions`
- `customer_language`
- `notes`

## How completeness is decided

`ai_order_extractor.py` includes a simple `ITEM_RULES` config:

- `milk`: `quantity + size + brand_or_any`
- `eggs`: `quantity`
- `bread`: `quantity + variant`
- `water`: `quantity + size`
- `pepsi`: `quantity + size`
- `banana`: `quantity`
- `tomatoes`: `quantity_or_weight`
- `detergent`: `quantity + brand + size`

After AI JSON is parsed and validated, these rules are applied to:

- mark each item complete/incomplete
- compute `missing_fields`
- generate one clarification question per incomplete item
- set top-level clarification fields

## Conversation engine

`conversation_engine.py` is a local in-memory state engine with:

- session storage by `customer_id`
- `messages` history
- `current_order`
- `pending_clarification` flag

Main API:

```python
from conversation_engine import process_customer_message

result = process_customer_message("customer_1", "bread")
session = result["customer_1"]
current_order = session["current_order"]
```

Follow-up behavior:

- if there are pending incomplete items, a new message is treated as clarification
- follow-up fields are merged into existing incomplete items
- then rules are re-applied to recompute completion/clarification
- if still incomplete, clarification remains active

## Setup

```bash
cd whatsapp-order-system
pip install -r requirements.txt
# Set your OpenAI API key (AI extraction only)

# PowerShell:
$env:OPENAI_API_KEY="sk-..."

# Or (Git Bash / bash):
export OPENAI_API_KEY="sk-..."

# Optional: choose a model (default is gpt-4o-mini)
$env:OPENAI_ORDER_MODEL="gpt-4o-mini"
```

## Tests

```bash
# Unit tests (default: integration tests are opt-in)
python -m pytest -q

# Same as above
make test
```

## Integration Test (Optional, Live OpenAI)

This test calls the real OpenAI API and may fail if you have no quota / rate limits.

```bash
# PowerShell:
$env:RUN_INTEGRATION="1"
python -m pytest -q -m integration -o addopts=

# Or via make (should work cross-platform on Windows):
make test-integration
```

## Test Manually

### Rule-based parser (local, no API key)

```bash
python order_parser.py "2 milk and eggs"
```

### AI extractor (needs `OPENAI_API_KEY`)

From the folder:

```bash
python ai_order_extractor.py "2 doodh aur anday bhej do"
```

Or in Python:

```python
from ai_order_extractor import extract_order_with_ai

result = extract_order_with_ai("2 doodh aur anday bhej do")
print(result)  # should match the required JSON shape
```

## Parser behaviour

- Separators: commas, `and`, and `aur` (word boundaries, any casing).
- Missing quantity means 1.
- Repeated items are merged; quantities are summed.
