"""Entry point — fetch every source, detect changes, notify."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .detectors import FetchResult, content_hash, fetch, find_new_keywords, now_iso
from .notifiers import notify_all
from .sources import SOURCES, Source

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def classify(source: Source, prev: dict, result: FetchResult) -> tuple[str, list[str]]:
    """Return (severity, matched_keywords)."""
    new_kw = find_new_keywords(
        prev.get("text", ""), result.text, source.alert_keywords
    )
    if new_kw:
        return "ALERT", new_kw
    return "INFO", []


def process_source(source: Source, state: dict) -> dict | None:
    prev = state.get(source.name, {})
    result = fetch(source)

    if not result.ok:
        print(f"[{source.name}] FETCH ERROR: {result.error}", file=sys.stderr)
        return None

    new_hash = content_hash(result.text)
    if prev.get("hash") == new_hash:
        print(f"[{source.name}] no change")
        return None

    severity, matched = classify(source, prev, result)
    print(f"[{source.name}] CHANGED severity={severity} matched={matched}")

    title_prefix = "🚨 INCENTIVO" if severity == "ALERT" else "ℹ️ Mudança"
    title = f"{title_prefix} — {source.name}"
    body_lines = [
        f"Source: {source.name}",
        f"URL:    {source.url}",
        f"When:   {now_iso()}",
    ]
    if matched:
        body_lines.append(f"Keywords novas: {', '.join(matched)}")
    body_lines.append("")
    body_lines.append("Excerto:")
    body_lines.append(result.summary[:1500])
    body = "\n".join(body_lines)

    delivery = notify_all(title, body, severity)
    print(f"[{source.name}] notify -> {delivery}")

    return {
        "hash": new_hash,
        "text": result.text,
        "last_changed": now_iso(),
        "last_severity": severity,
        "last_matched": matched,
    }


def main() -> int:
    state = load_state()
    changed = False

    for source in SOURCES:
        try:
            updated = process_source(source, state)
        except Exception as exc:  # noqa: BLE001
            print(f"[{source.name}] CRASH: {exc}", file=sys.stderr)
            continue
        if updated is not None:
            state[source.name] = updated
            changed = True

    if changed:
        save_state(state)
        print("state saved")
    else:
        # Touch nothing — keeps git diffs clean.
        print("no state changes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
