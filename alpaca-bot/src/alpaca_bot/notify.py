from __future__ import annotations

import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from urllib import request as urlrequest

from alpaca_bot.config import Settings
from alpaca_bot.recap import DailyRecap

log = logging.getLogger(__name__)


def send_recap(settings: Settings, recap: DailyRecap) -> dict[str, Any]:
    """Deliver recap via configured channel (email or webhook)."""
    if settings.recap_webhook_url:
        return _send_webhook(settings.recap_webhook_url, recap)
    if settings.recap_email_to and settings.smtp_host and settings.smtp_user:
        return _send_smtp(settings, recap)
    if settings.resend_api_key and settings.recap_email_to:
        return _send_resend(settings, recap)
    # Always log locally even without delivery config
    log.info("Daily recap (no delivery configured):\n%s", recap.to_text())
    return {
        "ok": False,
        "error": "Set RECAP_EMAIL_TO + SMTP_* or RESEND_API_KEY, or RECAP_WEBHOOK_URL",
        "channel": "log_only",
    }


def _send_smtp(settings: Settings, recap: DailyRecap) -> dict[str, Any]:
    msg = EmailMessage()
    msg["Subject"] = recap.subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = settings.recap_email_to
    msg.set_content(recap.to_text())
    msg.add_alternative(recap.to_html(), subtype="html")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.ehlo()
            if settings.smtp_use_tls:
                server.starttls(context=ctx)
            if settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        log.info("Recap emailed to %s", settings.recap_email_to)
        return {"ok": True, "channel": "smtp", "to": settings.recap_email_to}
    except Exception as exc:  # noqa: BLE001
        log.exception("SMTP recap failed")
        return {"ok": False, "error": str(exc), "channel": "smtp"}


def _send_resend(settings: Settings, recap: DailyRecap) -> dict[str, Any]:
    from_addr = settings.smtp_from or "Alpaca Bot <onboarding@resend.dev>"
    payload = {
        "from": from_addr,
        "to": [settings.recap_email_to],
        "subject": recap.subject,
        "text": recap.to_text(),
        "html": recap.to_html(),
    }
    req = urlrequest.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        log.info("Recap sent via Resend to %s", settings.recap_email_to)
        return {"ok": True, "channel": "resend", "to": settings.recap_email_to, "id": body.get("id")}
    except Exception as exc:  # noqa: BLE001
        log.exception("Resend recap failed")
        return {"ok": False, "error": str(exc), "channel": "resend"}


def _send_webhook(url: str, recap: DailyRecap) -> dict[str, Any]:
    payload = {
        "content": recap.subject,
        "embeds": [
            {
                "title": f"Daily Recap {recap.trading_day}",
                "description": recap.to_text()[:4000],
                "color": 5025616 if recap.day_pl_dollars >= 0 else 15158332,
            }
        ],
    }
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            resp.read()
        log.info("Recap sent to webhook")
        return {"ok": True, "channel": "webhook"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Webhook recap failed")
        return {"ok": False, "error": str(exc), "channel": "webhook"}
