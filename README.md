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
├── order_manager.py
├── test_order_manager.py
├── whatsapp_flow.py          # customer_id -> OrderManager / reply text
├── whatsapp_client.py          # Meta send message API
├── whatsapp_webhook.py         # Flask: GET verify + POST webhook
├── test_whatsapp_webhook.py
├── .env.example
├── README.md
├── requirements.txt
└── Makefile
```

Also included: `order_response.schema.json` (JSON shape for AI output), `pytest.ini` (optional `@pytest.mark.integration`).

Official Meta references (follow these for setup and behavior):

- [Get started](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started)
- [Webhooks overview](https://developers.facebook.com/docs/graph-api/webhooks)
- [Creating webhook endpoints](https://developers.facebook.com/docs/graph-api/webhooks/getting-started)
- [Send messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages)
- [Access tokens](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started#access-tokens)

For production, plan to move from temporary dashboard tokens to a **System User** access token as described in Meta’s documentation.

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

### Environment variables (WhatsApp + order flow)

Copy `.env.example` to `.env` and fill in values (the app loads `.env` automatically when `python-dotenv` is installed).

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for the AI order extractor used by the conversation engine. |
| `WHATSAPP_ACCESS_TOKEN` | Meta **permanent** or **temporary** token with `whatsapp_business_messaging` (see Meta docs). |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp **Phone number ID** from the WhatsApp product in the Meta app dashboard. |
| `WHATSAPP_VERIFY_TOKEN` | Any secret string you choose; must match the **Verify token** in the webhook configuration. |
| `WHATSAPP_GRAPH_API_VERSION` | Optional. Default is `v21.0`. |
| `PORT`, `HOST` | Optional. Defaults: `5000`, `0.0.0.0`. |

PowerShell example:

```powershell
Copy-Item .env.example .env
# Edit .env with your keys, then:
$env:OPENAI_API_KEY="sk-..."
$env:WHATSAPP_ACCESS_TOKEN="..."
$env:WHATSAPP_PHONE_NUMBER_ID="..."
$env:WHATSAPP_VERIFY_TOKEN="my-secret-verify-token"
```

### Run the webhook server locally

```bash
make run
# or
python whatsapp_webhook.py
```

The server exposes:

- `GET /webhook` — Meta **webhook verification** (`hub.mode`, `hub.verify_token`, `hub.challenge`).
- `POST /webhook` — incoming WhatsApp events (text messages are processed; others are ignored safely).
- `GET /health` — simple health check.

### Expose the server with ngrok (or similar)

Meta must reach your machine over HTTPS. Install [ngrok](https://ngrok.com/), run your server on `PORT` (default `5000`), then:

```bash
ngrok http 5000
```

Use the **HTTPS** forwarding URL (for example `https://abc123.ngrok-free.app`) as the base **Callback URL** in the Meta app:

- **Callback URL:** `https://YOUR-URL/webhook`
- **Verify token:** same value as `WHATSAPP_VERIFY_TOKEN`

Click **Verify and save** in the dashboard. Meta will call `GET /webhook` with the verify parameters.

### Configure the webhook in Meta

In the Meta Developer App → WhatsApp → **Configuration**:

1. Subscribe to the **messages** field for your webhook.
2. Set **Callback URL** to `https://YOUR_PUBLIC_HOST/webhook` and **Verify token** to match `WHATSAPP_VERIFY_TOKEN`.

### Manual end-to-end test on WhatsApp

1. Start the server and ngrok; confirm Meta webhook verification passes.
2. From the WhatsApp test number or linked phone, send a text message (for example `1l milk`).
3. Watch the terminal: you should see a log line like `Inbound WhatsApp text from=...`.
4. You should receive a reply on WhatsApp (for example a clarification question), then you can answer (for example `almarai`) and the flow continues.

### How the pieces fit together

- **Webhook verification (GET):** Meta sends `hub.mode=subscribe`, `hub.verify_token`, and `hub.challenge`. If the token matches `WHATSAPP_VERIFY_TOKEN`, the server returns `hub.challenge` as plain text so Meta marks the subscription as verified.
- **Incoming messages (POST):** Meta posts JSON. Only payloads with `object: whatsapp_business_account` and `messages.type: text` are handled. The sender’s `from` field is used as `customer_id` (WhatsApp `wa_id`).
- **Reply path:** `whatsapp_flow.process_incoming_customer_message` runs `OrderManager` (which uses `ConversationEngine` and the AI extractor). The reply string is sent with `whatsapp_client.send_whatsapp_text` to the Graph API `/{phone-number-id}/messages` endpoint.

## Tests

```bash
# Unit tests (default: integration tests are opt-in)
python -m pytest -q

# Same as above
make test

# Run WhatsApp webhook server (after env vars are set)
make run
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
