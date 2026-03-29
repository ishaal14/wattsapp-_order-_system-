"""Send outbound WhatsApp text messages via Meta WhatsApp Cloud API."""

from __future__ import annotations

import os
from typing import Any

import requests

# Graph API version (see Meta "Send messages" docs).
_DEFAULT_GRAPH_VERSION = "v21.0"


def _graph_base() -> str:
    version = os.getenv("WHATSAPP_GRAPH_API_VERSION", _DEFAULT_GRAPH_VERSION).strip() or _DEFAULT_GRAPH_VERSION
    return f"https://graph.facebook.com/{version}"


def send_whatsapp_text(to_number: str, text: str) -> dict[str, Any]:
    """
    Send a plain text message to a WhatsApp user.

    to_number: E.164 without + (e.g. 966501234567) as returned by webhooks in ``from``.

    Returns a dict with at least ``ok`` (bool). On success, includes ``data`` (JSON body).
    On failure, includes ``error`` and optionally ``status_code``.
    """
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not token or not phone_id:
        return {
            "ok": False,
            "error": "Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID",
        }

    url = f"{_graph_base()}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}

    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.ok:
        return {"ok": True, "status_code": resp.status_code, "data": data}

    err_msg = data.get("error", data) if isinstance(data, dict) else str(data)
    return {
        "ok": False,
        "status_code": resp.status_code,
        "error": err_msg,
        "data": data,
    }
