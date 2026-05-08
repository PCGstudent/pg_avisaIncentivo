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

# Limite de items "vistos" guardados por fonte. Garbage collect — depois
# disto descartam-se os mais antigos. 200 acomoda mais de uma semana de
# notícias mesmo num feed activo, sem o state.json crescer sem fim.
SEEN_ITEMS_LIMIT = 200


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


def _scan_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return keywords that appear in `text` (case-insensitive)."""
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def _new_items(seen: list[str], current: list[str]) -> list[str]:
    """Items present in `current` but not in `seen`."""
    seen_set = set(seen)
    return [item for item in current if item not in seen_set]


def classify(
    source: Source, prev: dict, result: FetchResult
) -> tuple[str, list[str], str]:
    """Return (severity, evidence, reason).

    Decisão baseada em ITEMS NOVOS (títulos RSS / parágrafos HTML), não em
    keywords novas no texto agregado. Razão: o objectivo é apanhar uma
    notícia/alteração genuinamente nova, não keywords novas no texto. Uma
    notícia velha a saltar para o topo do feed não é novidade; uma notícia
    nova com keywords que já apareciam noutras notícias antigas É novidade.

    Severity levels:
      - CRITICAL: very likely the actual aviso. Push with max priority.
      - ALERT:    plausible signal worth reading. Push with default priority.
      - INFO:     mere change. No push, no email.
    """
    prev_text = prev.get("text", "")

    # Sinal de ouro: URL preventiva passou de 404/410 (não existia) a conteúdo
    # real. Excluímos 503 porque é erro transitório do servidor.
    was_missing = prev_text in ("HTTP_STATUS_404", "HTTP_STATUS_410")
    is_present = not result.text.startswith("HTTP_STATUS_")
    if was_missing and is_present and source.tier == "OFFICIAL":
        return "CRITICAL", ["URL_PASSOU_A_EXISTIR"], "URL preventiva oficial publicada"

    # Items genuinamente novos vs tudo o que já vimos antes nesta fonte.
    seen_items: list[str] = prev.get("seen_items", [])
    new_items = _new_items(seen_items, result.items)

    if not new_items:
        # Hash mudou (chegámos aqui), mas nenhum item de bloco novo —
        # foi reordenação, mudança cosmética, ou pequeno ajuste em texto
        # que não constituiu parágrafo novo. Nada a alertar.
        return "INFO", [], "mudança sem item novo (reordenação/cosmético)"

    # Análise de sinal feita SÓ sobre os items novos — assim keywords que já
    # existiam noutros items antigos não disparam falsos alertas, e
    # keywords só num item novo apanham sempre o sinal.
    delta_text = " || ".join(new_items)

    new_definitive = _scan_keywords(delta_text, DEFINITIVE_PHRASES)
    if new_definitive:
        return (
            "CRITICAL",
            new_definitive + [f"({len(new_items)} items novos)"],
            "frase inequívoca de abertura em item novo",
        )

    new_strong = _scan_keywords(delta_text, STRONG_KEYWORDS)
    new_context = _scan_keywords(delta_text, CONTEXT_KEYWORDS)

    if source.tier == "OFFICIAL" and new_strong and new_context:
        return (
            "CRITICAL",
            new_strong + new_context + [f"({len(new_items)} items novos)"],
            "fonte oficial com keyword forte + contexto em item novo",
        )

    if new_strong and new_context:
        return (
            "ALERT",
            new_strong + new_context + [f"({len(new_items)} items novos)"],
            "keyword forte + contexto em item novo",
        )

    if new_strong or len(new_context) >= 2:
        return (
            "ALERT",
            new_strong + new_context + [f"({len(new_items)} items novos)"],
            "sinais parciais em item novo",
        )

    return (
        "INFO",
        new_context + [f"({len(new_items)} items novos)"],
        "item novo mas sem sinal forte",
    )


def process_source(source: Source, state: dict) -> dict | None:
    prev = state.get(source.name, {})
    result = fetch(source)
    meta = state.setdefault("_meta", {})

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

    # Bootstrap: ou primeira vez que vemos esta fonte, ou migração (state
    # antigo sem `seen_items`). Em qualquer caso, todos os items pareceriam
    # "novos" mas não há sinal — registamos em silêncio para detecção futura.
    is_bootstrap = "seen_items" not in prev
    if is_bootstrap:
        print(f"[{source.name}] BOOTSTRAP — {len(result.items)} items registados em silêncio")
        return {
            "hash": new_hash,
            "text": result.text,
            "seen_items": result.items[:SEEN_ITEMS_LIMIT],
            "last_changed": now_iso(),
            "last_severity": "INFO",
            "last_evidence": [],
            "last_reason": "bootstrap (estado inicial registado)",
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
        # Contadores agregados — usados pelo heartbeat para detectar
        # "Gemini está sempre a rebaixar" ou "Gemini não está disponível".
        meta["gemini_calls"] = int(meta.get("gemini_calls", 0)) + 1
        if not verdict.available:
            meta["gemini_unavailable"] = int(meta.get("gemini_unavailable", 0)) + 1
        if verdict.available:
            if verdict.is_real_aviso and verdict.confidence >= 0.7:
                # AI confirms — keep/raise to CRITICAL with its reasoning.
                severity = "CRITICAL"
                reason = f"{reason} | Gemini: {verdict.reason}"
                meta["gemini_confirms"] = int(meta.get("gemini_confirms", 0)) + 1
            elif (not verdict.is_real_aviso) and verdict.confidence >= 0.6:
                # AI rebuts — downgrade to INFO so the phone stays quiet.
                severity = "INFO"
                reason = f"rebaixado por Gemini: {verdict.reason}"
                meta["gemini_rebuts"] = int(meta.get("gemini_rebuts", 0)) + 1
            else:
                meta["gemini_unsure"] = int(meta.get("gemini_unsure", 0)) + 1

    if severity == "CRITICAL":
        title = f"🔴 AVISO INCENTIVO EV — {source.name}"
        prefix = "⚡ AÇÃO POSSÍVEL"
    elif severity == "ALERT":
        title = f"🟡 Sinal possível — {source.name}"
        prefix = "Provável notícia / mexida relacionada"
    else:
        title = f"ℹ️ Mudança — {source.name}"
        prefix = "Mudança sem sinal forte"

    # Items genuinamente novos para mostrar no email — é o que interessa.
    seen_items_prev: list[str] = prev.get("seen_items", [])
    new_items_for_body = _new_items(seen_items_prev, result.items)

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
    if new_items_for_body:
        body_lines.append("")
        body_lines.append(f"Items novos ({len(new_items_for_body)}):")
        for item in new_items_for_body[:10]:
            body_lines.append(f"  • {item[:200]}")
    body_lines.append("")
    body_lines.append("Excerto:")
    body_lines.append(result.summary[:1500])
    body = "\n".join(body_lines)

    delivery = notify_all(title, body, severity)
    print(f"[{source.name}] notify -> {delivery}")

    # Contar entregas de email para o heartbeat detectar canal partido.
    email_status = delivery.get("email", "")
    if email_status == "ok":
        meta["email_ok"] = int(meta.get("email_ok", 0)) + 1
    elif email_status.startswith("error:"):
        meta["email_errors"] = int(meta.get("email_errors", 0)) + 1
        meta["last_email_error"] = email_status

    # Atualizar set de items vistos: items prévios + items deste fetch.
    # Trim aos mais recentes (current items + tail dos antigos) — assim
    # os items que ainda aparecem no fetch ficam, e os outros expiram.
    merged_seen = list(result.items)
    for item in seen_items_prev:
        if item not in merged_seen:
            merged_seen.append(item)
    merged_seen = merged_seen[:SEEN_ITEMS_LIMIT]

    return {
        "hash": new_hash,
        "text": result.text,
        "seen_items": merged_seen,
        "last_changed": now_iso(),
        "last_severity": severity,
        "last_evidence": evidence,
        "last_reason": reason,
        "consecutive_failures": 0,
    }


def _bump_meta_counter(state: dict, key: str) -> None:
    """Increment a named counter in state["_meta"]. Used by heartbeat."""
    meta = state.setdefault("_meta", {})
    meta[key] = int(meta.get(key, 0)) + 1
    meta["last_run"] = now_iso()


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

    # Sempre atualizar timestamp do último run, mesmo sem mudanças, para
    # o heartbeat poder dizer que o monitor está vivo.
    state.setdefault("_meta", {})["last_run"] = now_iso()
    save_state(state)
    if changed:
        print("state saved")
    else:
        print("only meta updated")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
