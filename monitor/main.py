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
    prev_text = prev.get("text", "")

    # Caso especial: URL preventiva passou de 404/410/503 → conteúdo real.
    # Isto é o sinal de ouro — uma página de aviso nova a aparecer.
    was_missing = prev_text.startswith("HTTP_STATUS_")
    is_present = not result.text.startswith("HTTP_STATUS_")
    if was_missing and is_present:
        return "ALERT", ["URL_AGORA_EXISTE"]

    new_kw = find_new_keywords(prev_text, result.text, source.alert_keywords)
    if new_kw:
        return "ALERT", new_kw
    return "INFO", []


FAIL_THRESHOLD = 5  # consecutive failures before raising a self-alert


def process_source(source: Source, state: dict) -> dict | None:
    prev = state.get(source.name, {})
    result = fetch(source)

    if not result.ok:
        fails = int(prev.get("consecutive_failures", 0)) + 1
        print(
            f"[{source.name}] FETCH ERROR ({fails}x): {result.error}",
            file=sys.stderr,
        )
        if fails == FAIL_THRESHOLD:
            notify_all(
                f"⚠️ Monitor: fonte com falhas — {source.name}",
                f"A fonte {source.name} ({source.url}) falhou {fails} runs "
                f"consecutivos.\nÚltimo erro: {result.error}\n\n"
                "Pode ser bloqueio, mudança de URL, ou indisponibilidade. "
                "Verifica manualmente.",
                "INFO",
            )
        # Persistir contagem mesmo em erro (não conta como mudança real).
        merged = dict(prev)
        merged["consecutive_failures"] = fails
        return merged

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
        "consecutive_failures": 0,
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
