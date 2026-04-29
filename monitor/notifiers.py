"""Multi-channel notification dispatch."""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import requests

TIMEOUT = 15


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def notify_all(title: str, body: str, severity: str) -> dict[str, str]:
    """Send notification through all configured channels.

    Returns a dict {channel: status} for logging.
    """
    results: dict[str, str] = {}

    # ntfy.sh — primary push channel.
    topic = _env("NTFY_TOPIC")
    if topic:
        server = _env("NTFY_SERVER") or "https://ntfy.sh"
        results["ntfy"] = _safe(_send_ntfy, server, topic, title, body, severity)
    else:
        results["ntfy"] = "skipped (NTFY_TOPIC unset)"

    # Email
    if _env("EMAIL_USER") and _env("EMAIL_TO"):
        results["email"] = _safe(_send_email, title, body)
    else:
        results["email"] = "skipped (email not configured)"

    # Telegram
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"):
        results["telegram"] = _safe(_send_telegram, title, body)
    else:
        results["telegram"] = "skipped (telegram not configured)"

    # Discord
    if _env("DISCORD_WEBHOOK_URL"):
        results["discord"] = _safe(_send_discord, title, body, severity)
    else:
        results["discord"] = "skipped (discord not configured)"

    return results


def _safe(fn, *args, **kwargs) -> str:
    try:
        fn(*args, **kwargs)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


def _send_ntfy(server: str, topic: str, title: str, body: str, severity: str) -> None:
    priority = "urgent" if severity == "ALERT" else "default"
    tags = "rotating_light" if severity == "ALERT" else "information_source"
    requests.post(
        f"{server.rstrip('/')}/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": tags,
        },
        timeout=TIMEOUT,
    ).raise_for_status()


def _send_email(title: str, body: str) -> None:
    host = _env("EMAIL_SMTP_HOST") or "smtp.gmail.com"
    port = int(_env("EMAIL_SMTP_PORT") or "587")
    user = _env("EMAIL_USER")
    pwd = _env("EMAIL_PASSWORD")
    to = _env("EMAIL_TO")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = user
    msg["To"] = to

    with smtplib.SMTP(host, port, timeout=TIMEOUT) as smtp:
        smtp.starttls()
        smtp.login(user, pwd)
        smtp.send_message(msg)


def _send_telegram(title: str, body: str) -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_CHAT_ID")
    text = f"*{title}*\n\n{body}"
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
        timeout=TIMEOUT,
    ).raise_for_status()


def _send_discord(title: str, body: str, severity: str) -> None:
    url = _env("DISCORD_WEBHOOK_URL")
    color = 0xE53935 if severity == "ALERT" else 0x1E88E5
    requests.post(
        url,
        json={
            "embeds": [
                {
                    "title": title,
                    "description": body[:3500],
                    "color": color,
                }
            ]
        },
        timeout=TIMEOUT,
    ).raise_for_status()
