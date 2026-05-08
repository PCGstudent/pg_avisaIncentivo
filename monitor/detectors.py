"""Fetching, normalisation and change detection."""

from __future__ import annotations

import calendar
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

# Janela de relevância para entradas RSS. Notícias mais antigas que isto
# são contexto histórico — não queremos disparar ALERTs a falar duma
# coisa que aconteceu há semanas. 10 dias dá folga para fim-de-semana,
# atrasos do GitHub Actions, e feeds que indexam notícias com delay.
RSS_RECENT_DAYS = 10


@dataclass
class FetchResult:
    source: str
    ok: bool
    text: str  # normalised text used for hashing/keyword scan
    summary: str  # short human-readable summary for notifications
    # Lista de unidades atómicas para detecção de "novidade":
    # - RSS: títulos de notícia (string normalizada por título)
    # - HTML: parágrafos / linhas relevantes do conteúdo principal
    # O detector compara este conjunto contra o conjunto guardado
    # do fetch anterior para identificar items genuinamente novos.
    items: list[str] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = []


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

    # Lista de "blocos" — parágrafos, items de lista, headings — para detecção
    # de novidade. Filtra blocos curtos (<30 chars) que são tipicamente
    # entradas de menu/navegação sem informação útil.
    blocks: list[str] = []
    for el in region.find_all(["p", "li", "h1", "h2", "h3", "h4", "td"]):
        snippet = _normalise(el.get_text(" ", strip=True))
        if len(snippet) >= 30:
            blocks.append(snippet.lower())
    # Dedup preservando ordem.
    seen = set()
    unique_blocks: list[str] = []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            unique_blocks.append(b)

    summary = text[:300]
    return FetchResult(
        source=source.name,
        ok=True,
        text=text,
        summary=summary,
        items=unique_blocks,
    )


def _entry_age_days(entry: dict) -> float | None:
    """Return age in days for an RSS entry, or None if no parseable date."""
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            try:
                ts = calendar.timegm(struct)
                age_seconds = time.time() - ts
                return age_seconds / 86400.0
            except (TypeError, ValueError):
                continue
    return None


def _fetch_rss(source: Source) -> FetchResult:
    parsed = feedparser.parse(source.url, request_headers={"User-Agent": USER_AGENT})
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"RSS parse failed: {parsed.bozo_exception}")

    # `text` é usado para hash + keyword scan. Tem de ser estável e relevante:
    # - só títulos normalizados, ordenados, sem datas nem links (Google News
    #   mete tokens voláteis nos URLs e reordena);
    # - só entradas dos últimos RSS_RECENT_DAYS dias — notícias antigas a
    #   entrar/sair do feed mexiam o hash sem informação útil, e ALERTs com
    #   keywords que só apareciam em notícias velhas são confusos.
    # Entradas sem data parseável são incluídas (não punir falta de metadata).
    recent_titles: list[str] = []
    recent_items: list[str] = []
    skipped_old = 0
    for entry in parsed.entries[:30]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        age = _entry_age_days(entry)
        if age is not None and age > RSS_RECENT_DAYS:
            skipped_old += 1
            continue
        link = entry.get("link", "")
        published = entry.get("published", "") or entry.get("updated", "")
        recent_titles.append(_normalise(title.lower()))
        recent_items.append(f"{published} | {title} | {link}")

    if skipped_old:
        print(
            f"[{source.name}] RSS: {len(recent_titles)} recentes, "
            f"{skipped_old} antigas ignoradas (>{RSS_RECENT_DAYS}d)"
        )

    text = _normalise(" || ".join(sorted(set(recent_titles))))
    summary = "\n".join(recent_items[:3]) if recent_items else "(sem entradas recentes)"
    # `items` = títulos normalizados, sem duplicados. Cada um é uma unidade
    # atómica de "novidade" no feed.
    return FetchResult(
        source=source.name,
        ok=True,
        text=text,
        summary=summary,
        items=sorted(set(recent_titles)),
    )


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
