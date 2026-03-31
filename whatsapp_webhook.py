"""
Flask app: Meta WhatsApp Cloud API webhook (verify + receive) and reply sender.

Text messages only. Set WHATSAPP_VERIFY_TOKEN, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
OPENAI_API_KEY (for the AI extractor used by the order flow).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from flask import Flask, Response, abort, jsonify, request

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from whatsapp_client import send_whatsapp_text
from whatsapp_flow import process_incoming_customer_message

logger = logging.getLogger(__name__)


def _load_env() -> None:
    if load_dotenv:
        load_dotenv()


def parse_incoming_text_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract inbound text messages from a WhatsApp webhook payload.

    Returns a list of dicts: ``from`` (wa_id string), ``text``, optional ``message_id``.
    Ignores non-text types and malformed entries safely.
    """
    if not isinstance(payload, dict):
        return []
    if payload.get("object") != "whatsapp_business_account":
        return []

    out: list[dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") != "text":
                    continue
                text_obj = msg.get("text")
                if not isinstance(text_obj, dict):
                    continue
                body = text_obj.get("body")
                if body is None:
                    continue
                from_id = msg.get("from")
                if not from_id:
                    continue
                out.append(
                    {
                        "from": str(from_id),
                        "text": str(body),
                        "message_id": msg.get("id"),
                    }
                )
    return out


def create_app() -> Flask:
    _load_env()
    app = Flask(__name__)

    @app.get("/webhook")
    def verify_webhook():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        verify = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

        if mode == "subscribe" and token == verify and challenge is not None and challenge != "":
            return Response(str(challenge), status=200, mimetype="text/plain; charset=utf-8")

        abort(403)

    @app.post("/webhook")
    def receive_webhook():
        try:
            payload = request.get_json(silent=True)
        except Exception:  # noqa: BLE001 — malformed body
            payload = None
        if not isinstance(payload, dict):
            return jsonify({"ok": True, "ignored": "invalid_json"}), 200

        messages = parse_incoming_text_messages(payload)
        for item in messages:
            customer_id = item["from"]
            text = item["text"]
            logger.info("Inbound WhatsApp text from=%s len=%s", customer_id, len(text))
            try:
                reply = process_incoming_customer_message(customer_id, text)
            except Exception:
                logger.exception("process_incoming_customer_message failed for %s", customer_id)
                reply = "Sorry, something went wrong. Please try again in a moment."

            result = send_whatsapp_text(customer_id, reply)
            if not result.get("ok"):
                logger.error("send_whatsapp_text failed: %s", result)

        return jsonify({"ok": True}), 200

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    _load_env()
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
else:
    # For gunicorn on Railway
    app = create_app()
