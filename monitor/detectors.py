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


def _normalise(text: str) -> str:
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


def _fetch_html(source: Source) -> FetchResult:
    resp = requests.get(
        source.url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-PT,pt;q=0.9"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Strip noisy elements that change every request.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    region = soup.select_one(source.selector) if source.selector else soup
    if region is None:
        region = soup

    text = _normalise(region.get_text(" ", strip=True))
    summary = text[:300]
    return FetchResult(source=source.name, ok=True, text=text, summary=summary)


def _fetch_rss(source: Source) -> FetchResult:
    parsed = feedparser.parse(source.url, request_headers={"User-Agent": USER_AGENT})
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"RSS parse failed: {parsed.bozo_exception}")

    items = []
    for entry in parsed.entries[:15]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", "") or entry.get("updated", "")
        items.append(f"{published} | {title} | {link}")

    text = _normalise("\n".join(items))
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
