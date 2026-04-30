"""Gemini-powered judge for distinguishing the real aviso from noise.

Called only for OFFICIAL sources that already triggered ALERT/CRITICAL via
keyword heuristics. The judge reads previous and current page excerpts and
decides whether the change actually represents the new EV incentive notice.

Returns a Verdict that can ESCALATE (keep/raise to CRITICAL with extra
context) or DOWNGRADE (push to INFO and stay silent). On any error the
caller falls back to the original heuristic decision — we never block on
Gemini availability.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
TIMEOUT = 25
MAX_INPUT_CHARS = 6000  # cap each side of the diff to keep cost bounded


@dataclass
class Verdict:
    available: bool      # False if API key missing or call failed
    is_real_aviso: bool
    confidence: float    # 0..1
    reason: str
    raw: str = ""


PROMPT = """És um classificador objetivo. A tua tarefa é decidir se uma alteração detetada numa página oficial portuguesa indica que **abriu o aviso/programa de incentivo à compra de carros elétricos** (Fundo Ambiental — Mobilidade Verde, programas conexos), ou se é apenas ruído/atualização cosmética.

Critérios para responder TRUE (`is_real_aviso=true`):
- A página passou a anunciar abertura de candidaturas, publicação de novo aviso, disponibilização de formulário, ou início de submissão de candidaturas para incentivo a veículos elétricos / mobilidade verde / Fundo Ambiental 2026.
- Aparece um link para formulário, regulamento, ou aviso publicado em DR.
- Aparece dotação orçamental nova com prazos de candidatura.

Responde FALSE quando:
- Mudança é apenas em menus, cookies, banners, contagens, datas de notícias, footer.
- Conteúdo refere o tema mas em modo informativo/histórico (relatos sobre 2025, balanços, comunicação genérica).
- Nada na alteração indica abertura concreta de aviso novo.

CONTEXTO DA FONTE:
- Nome: {source_name}
- Tier: {source_tier}
- URL: {source_url}

EXCERTO ANTERIOR (pode estar vazio):
---
{prev}
---

EXCERTO ATUAL:
---
{curr}
---

Devolve APENAS um objeto JSON válido (sem markdown, sem texto antes ou depois) com este schema:
{{
  "is_real_aviso": boolean,
  "confidence": number entre 0 e 1,
  "reason": "string curta em português, máx 200 caracteres"
}}"""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + " […] " + text[-half:]


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    # Strip code fences if model added them despite instructions.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def judge(
    prev_text: str,
    curr_text: str,
    source_name: str,
    source_tier: str,
    source_url: str,
) -> Verdict:
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return Verdict(False, False, 0.0, "GEMINI_API_KEY not set")

    prompt = PROMPT.format(
        source_name=source_name,
        source_tier=source_tier,
        source_url=source_url,
        prev=_truncate(prev_text or "(vazio)", MAX_INPUT_CHARS),
        curr=_truncate(curr_text, MAX_INPUT_CHARS),
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
        },
    }

    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            params={"key": api_key},
            json=payload,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = _extract_json(text)
        if not parsed:
            return Verdict(True, False, 0.0, "JSON parse failed", raw=text)

        is_real = bool(parsed.get("is_real_aviso", False))
        confidence = float(parsed.get("confidence", 0.0))
        reason = str(parsed.get("reason", ""))[:300]
        return Verdict(True, is_real, confidence, reason, raw=text)
    except Exception as exc:  # noqa: BLE001 — outer guard, callers fall back
        return Verdict(False, False, 0.0, f"call failed: {type(exc).__name__}: {exc}")
