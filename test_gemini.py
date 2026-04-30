"""Smoke-test the Gemini judge with two synthetic scenarios.

Run this on GitHub Actions (where GEMINI_API_KEY is in env) via:
  python test_gemini.py
"""

import json
import os

import requests

from monitor.gemini_judge import judge


def _diag_call() -> None:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        print("DIAG: no GEMINI_API_KEY in env")
        return
    print(f"DIAG: key length={len(key)} prefix={key[:4]}*** suffix=***{key[-4:]}")
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": "Reply with just OK"}]}]},
            timeout=20,
        )
        print(f"DIAG: HTTP {r.status_code}")
        try:
            print("DIAG body:", json.dumps(r.json(), indent=2)[:1500])
        except Exception:
            print("DIAG body (raw):", r.text[:1500])
    except Exception as exc:  # noqa: BLE001
        print(f"DIAG: exception {type(exc).__name__}: {exc}")


CASE_A_PREV = (
    "Fundo Ambiental — apoios 2025. Esta página tem informação sobre o "
    "programa Mobilidade Verde Passageiros 2025/2026. As candidaturas "
    "decorreram entre 29 de dezembro de 2025 e 12 de fevereiro de 2026."
)

CASE_A_CURR_REAL = (
    "AVISO N.º 17/2026 — Mobilidade Verde Passageiros. CANDIDATURAS ABERTAS "
    "a partir de 15 de maio de 2026. Dotação total: 20 milhões de euros. "
    "Submeta a sua candidatura através do formulário disponível abaixo. "
    "Prazo até 31 de julho de 2026 ou até esgotar a dotação. Beneficiários: "
    "particulares, empresas, IPSS, autarquias. Apoio até 4.000 € por veículo."
)

CASE_B_CURR_NOISE = (
    "Fundo Ambiental — apoios 2025. Esta página tem informação sobre o "
    "programa Mobilidade Verde Passageiros 2025/2026. As candidaturas "
    "decorreram entre 29 de dezembro de 2025 e 12 de fevereiro de 2026. "
    "Aviso de cookies atualizado. Menu de navegação reformulado. "
    "Footer com novos contactos institucionais."
)


def run(label: str, prev: str, curr: str) -> None:
    v = judge(
        prev_text=prev,
        curr_text=curr,
        source_name="FundoAmbiental_TEST",
        source_tier="OFFICIAL",
        source_url="https://www.fundoambiental.pt/test",
    )
    print(
        f"[{label}] available={v.available} is_real={v.is_real_aviso} "
        f"conf={v.confidence:.2f} reason={v.reason!r}"
    )


if __name__ == "__main__":
    print("=== Direct API diagnostic ===")
    _diag_call()
    print()
    print("CASE A — should detect REAL aviso")
    run("REAL", CASE_A_PREV, CASE_A_CURR_REAL)
    print()
    print("CASE B — should detect NOISE")
    run("NOISE", CASE_A_PREV, CASE_B_CURR_NOISE)
