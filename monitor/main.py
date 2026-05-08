"""Entry point — fetch every source, detect changes, notify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .detectors import FetchResult, content_hash, fetch, now_iso
from .gemini_judge import Verdict, judge
from .notifiers import notify_all
from .sources import (
    CONTEXT_KEYWORDS,
    DEFINITIVE_PHRASES,
    SOURCES,
    STRONG_KEYWORDS,
    Source,
)

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"
FAIL_THRESHOLD = 5


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


def _new_phrases(prev_text: str, new_text: str, phrases: list[str]) -> list[str]:
    prev_l = prev_text.lower()
    new_l = new_text.lower()
    return [p for p in phrases if p.lower() in new_l and p.lower() not in prev_l]


def classify(
    source: Source, prev: dict, result: FetchResult
) -> tuple[str, list[str], str]:
    """Return (severity, evidence, reason).

    Severity levels:
      - CRITICAL: very likely the actual aviso. Push with max priority.
      - ALERT:    plausible signal worth reading. Push with default priority.
      - INFO:     mere change. Email only, no push. (Skipped in notifier.)
    """
    prev_text = prev.get("text", "")

    # Sinal de ouro: URL preventiva passou de 404/410 (não existia) a conteúdo
    # real. Excluímos 503 porque é erro transitório do servidor — passar de
    # 503 a conteúdo é apenas o servidor a recuperar, não publicação nova.
    was_missing = prev_text in ("HTTP_STATUS_404", "HTTP_STATUS_410")
    is_present = not result.text.startswith("HTTP_STATUS_")
    if was_missing and is_present and source.tier == "OFFICIAL":
        return "CRITICAL", ["URL_PASSOU_A_EXISTIR"], "URL preventiva oficial publicada"

    # Frases inequívocas (independente da fonte).
    new_definitive = _new_phrases(prev_text, result.text, DEFINITIVE_PHRASES)
    if new_definitive:
        return "CRITICAL", new_definitive, "frase inequívoca de abertura"

    # Combinação forte + contexto numa fonte oficial.
    new_strong = _new_phrases(prev_text, result.text, STRONG_KEYWORDS)
    new_context = _new_phrases(prev_text, result.text, CONTEXT_KEYWORDS)

    if source.tier == "OFFICIAL" and new_strong and new_context:
        return (
            "CRITICAL",
            new_strong + new_context,
            "fonte oficial com keyword forte + contexto",
        )

    if new_strong and new_context:
        return "ALERT", new_strong + new_context, "keyword forte + contexto"

    if new_strong or len(new_context) >= 2:
        return "ALERT", new_strong + new_context, "sinais parciais"

    return "INFO", new_context, "mudança sem sinal forte"


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
                "ALERT",
            )
        merged = dict(prev)
        merged["consecutive_failures"] = fails
        return merged

    new_hash = content_hash(result.text)
    if prev.get("hash") == new_hash:
        print(f"[{source.name}] no change")
        return None

    # Página acabou de cair em erro (404/410/503/error page). Atualizamos o
    # estado em silêncio — não notificamos perda de conteúdo. O sinal
    # interessante é o oposto: erro -> conteúdo (tratado em classify).
    became_error = result.text.startswith("HTTP_STATUS_") and not prev.get(
        "text", ""
    ).startswith("HTTP_STATUS_")
    if became_error:
        print(f"[{source.name}] became error page ({result.text}) — silent update")
        return {
            "hash": new_hash,
            "text": result.text,
            "last_changed": now_iso(),
            "last_severity": "INFO",
            "last_evidence": [],
            "last_reason": "página passou a estado de erro (silenciado)",
            "consecutive_failures": 0,
        }

    severity, evidence, reason = classify(source, prev, result)
    print(
        f"[{source.name}] CHANGED severity={severity} reason={reason} "
        f"evidence={evidence[:5]}"
    )

    # AI second opinion. Aplica-se em dois casos:
    # 1. Fontes OFFICIAL com ALERT/CRITICAL — validação habitual.
    # 2. Fontes NEWS com CRITICAL — porque RSS do Google News é propenso a
    #    falsos positivos (ex: "Aviso n.º 5656/2024/2" totalmente não-EV
    #    apareceu no feed e disparou CRITICAL pela frase "aviso n.º").
    #    Notícias relevantes verdadeiras serão validadas pelo Gemini com
    #    confidence alta; ruído é rebaixado para INFO antes de notificar.
    verdict: Verdict | None = None
    needs_judge = (
        source.tier == "OFFICIAL" and severity in ("CRITICAL", "ALERT")
    ) or (source.tier == "NEWS" and severity == "CRITICAL")
    if needs_judge:
        verdict = judge(
            prev_text=prev.get("text", ""),
            curr_text=result.text,
            source_name=source.name,
            source_tier=source.tier,
            source_url=source.url,
        )
        print(
            f"[{source.name}] gemini available={verdict.available} "
            f"is_real={verdict.is_real_aviso} conf={verdict.confidence:.2f} "
            f"reason={verdict.reason!r}"
        )
        if verdict.available:
            if verdict.is_real_aviso and verdict.confidence >= 0.7:
                # AI confirms — keep/raise to CRITICAL with its reasoning.
                severity = "CRITICAL"
                reason = f"{reason} | Gemini: {verdict.reason}"
            elif (not verdict.is_real_aviso) and verdict.confidence >= 0.6:
                # AI rebuts — downgrade to INFO so the phone stays quiet.
                severity = "INFO"
                reason = f"rebaixado por Gemini: {verdict.reason}"
            # else: AI unsure, keep heuristic decision unchanged.

    if severity == "CRITICAL":
        title = f"🔴 AVISO INCENTIVO EV — {source.name}"
        prefix = "⚡ AÇÃO POSSÍVEL"
    elif severity == "ALERT":
        title = f"🟡 Sinal possível — {source.name}"
        prefix = "Provável notícia / mexida relacionada"
    else:
        title = f"ℹ️ Mudança — {source.name}"
        prefix = "Mudança sem sinal forte"

    body_lines = [
        prefix,
        "",
        f"Razão:    {reason}",
        f"Fonte:    {source.name} ({source.tier})",
        f"URL:      {source.url}",
        f"Quando:   {now_iso()}",
    ]
    if evidence:
        body_lines.append(f"Sinais:   {', '.join(evidence[:8])}")
    if verdict and verdict.available:
        body_lines.append(
            f"Gemini:   is_real={verdict.is_real_aviso} "
            f"(conf {verdict.confidence:.2f}) — {verdict.reason}"
        )
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
        "last_evidence": evidence,
        "last_reason": reason,
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
        print("no state changes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
