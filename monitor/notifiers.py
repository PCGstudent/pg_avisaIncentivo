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

    Severity:
      - CRITICAL: ntfy max priority + email + all channels.
      - ALERT:    ntfy default priority + email + all channels.
      - INFO:     no notifications. Logged in GitHub Actions output and
                  in state.json (committed) — full audit trail without spam.

    Returns a dict {channel: status} for logging.
    """
    results: dict[str, str] = {}
    push_allowed = severity in ("CRITICAL", "ALERT")

    # ntfy.sh — push only on ALERT/CRITICAL.
    topic = _env("NTFY_TOPIC")
    if topic and push_allowed:
        server = _env("NTFY_SERVER") or "https://ntfy.sh"
        results["ntfy"] = _safe(_send_ntfy, server, topic, title, body, severity)
    elif not push_allowed:
        results["ntfy"] = "skipped (INFO — push muted)"
    else:
        results["ntfy"] = "skipped (NTFY_TOPIC unset)"

    # Email — only on ALERT/CRITICAL. INFO ficaria a inundar a inbox e o
    # efeito é o oposto do desejado (deixamos de abrir os emails reais).
    if _env("EMAIL_USER") and _env("EMAIL_TO") and push_allowed:
        results["email"] = _safe(_send_email, title, body)
    elif not push_allowed:
        results["email"] = "skipped (INFO — email muted)"
    else:
        results["email"] = "skipped (email not configured)"

    # Telegram — only on ALERT/CRITICAL.
    if _env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID") and push_allowed:
        results["telegram"] = _safe(_send_telegram, title, body)
    else:
        results["telegram"] = "skipped"

    # Discord — only on ALERT/CRITICAL.
    if _env("DISCORD_WEBHOOK_URL") and push_allowed:
        results["discord"] = _safe(_send_discord, title, body, severity)
    else:
        results["discord"] = "skipped"

    return results


def _safe(fn, *args, **kwargs) -> str:
    try:
        fn(*args, **kwargs)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


def _send_ntfy(server: str, topic: str, title: str, body: str, severity: str) -> None:
    if severity == "CRITICAL":
        priority = "max"
        tags = "rotating_light,red_circle"
    elif severity == "ALERT":
        priority = "default"
        tags = "yellow_circle"
    else:
        priority = "low"
        tags = "information_source"
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
