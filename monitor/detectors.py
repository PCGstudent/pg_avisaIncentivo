"""Fetching, normalisation and change detection."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

import feedparser
import requests
from bs4 import BeautifulSoup

from .sources import Source

USER_AGENT = (
    "Mozilla/5.0 (compatible; pg-avisaIncentivo/1.0; +https://github.com/)"
)
TIMEOUT = 20


@dataclass
class FetchResult:
    source: str
    ok: bool
    text: str  # normalised text used for hashing/keyword scan
    summary: str  # short human-readable summary for notifications
    error: str | None = None


_DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_NOISE_PHRASES = (
    # Linhas de pagamentos quinzenais publicadas todos os meses pelo FA;
    # mudam constantemente de valor e data sem qualquer ligação ao aviso EV.
    # Apanha do início do título até à elipse "..." que termina o snippet.
    # `Ag.ncia` tolera Agência/Agencia (com ou sem acento, encoding glitches).
    re.compile(
        r"Pagamentos da Ag.ncia para o Clima.*?\.\.\.",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"Pagamentos do Fundo Ambiental.*?\.\.\.",
        re.IGNORECASE | re.DOTALL,
    ),
)


def _normalise(text: str) -> str:
    # Remove blocos de pagamentos antes de colapsar espaços — são puro ruído
    # que mexe a cada poll e não tem informação sobre a abertura do aviso.
    for pat in _NOISE_PHRASES:
        text = pat.sub(" ", text)
    # Datas DD/MM/YYYY são datas de notícias; mudam todos os dias e não
    # adicionam sinal. Mantemos anos isolados (ex: "2026") porque são
    # keywords de contexto.
    text = _DATE_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch(source: Source) -> FetchResult:
    try:
        if source.kind == "rss":
            return _fetch_rss(source)
        return _fetch_html(source)
    except Exception as exc:  # noqa: BLE001 — top-level guard
        return FetchResult(
            source=source.name,
            ok=False,
            text="",
            summary="",
            error=f"{type(exc).__name__}: {exc}",
        )


ERROR_PAGE_MARKERS = (
    "ocorreu um erro inesperado",
    "the resource cannot be found",
    "service unavailable",
)


def _is_error_page(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in ERROR_PAGE_MARKERS)


def _fetch_html(source: Source) -> FetchResult:
    resp = requests.get(
        source.url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-PT,pt;q=0.9",
        },
        timeout=TIMEOUT,
    )
    # Tolerar 404 / 410 — usado para URLs preventivas (ainda não publicadas).
    # O texto normalizado capta o status code, por isso quando passar a 200
    # com conteúdo, o hash muda e o detector dispara ALERT.
    if resp.status_code in (404, 410, 503):
        text = f"HTTP_STATUS_{resp.status_code}"
        return FetchResult(source=source.name, ok=True, text=text, summary=text)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Strip noisy elements that change every request.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    region = soup.select_one(source.selector) if source.selector else soup
    if region is None:
        region = soup

    text = _normalise(region.get_text(" ", strip=True))

    # Páginas oficiais do FA oscilam para "Ocorreu um erro inesperado".
    # Colapsamos para um marcador estável para o hash não andar a mexer
    # entre variantes de erro. Tratado como equivalente a 503.
    if _is_error_page(text):
        text = "HTTP_STATUS_503"
        return FetchResult(source=source.name, ok=True, text=text, summary=text)

    summary = text[:300]
    return FetchResult(source=source.name, ok=True, text=text, summary=summary)


def _fetch_rss(source: Source) -> FetchResult:
    parsed = feedparser.parse(source.url, request_headers={"User-Agent": USER_AGENT})
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"RSS parse failed: {parsed.bozo_exception}")

    # `text` é usado para hash + keyword scan. Tem de ser estável: só títulos
    # normalizados, ordenados, sem datas nem links (Google News mete tokens
    # voláteis nos URLs e reordena, o que disparava notificações INFO sem
    # mudança real de conteúdo).
    titles: list[str] = []
    items: list[str] = []  # versão rica para mostrar na notificação
    for entry in parsed.entries[:15]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link", "")
        published = entry.get("published", "") or entry.get("updated", "")
        if title:
            titles.append(_normalise(title.lower()))
        items.append(f"{published} | {title} | {link}")

    text = _normalise(" || ".join(sorted(set(titles))))
    summary = "\n".join(items[:3])
    return FetchResult(source=source.name, ok=True, text=text, summary=summary)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_new_keywords(
    old_text: str, new_text: str, keywords: list[str]
) -> list[str]:
    """Return keywords that appear in the new text but not the old one."""
    old_lower = old_text.lower()
    new_lower = new_text.lower()
    hits = []
    for kw in keywords:
        kw_l = kw.lower()
        if kw_l in new_lower and kw_l not in old_lower:
            hits.append(kw)
    return hits


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
