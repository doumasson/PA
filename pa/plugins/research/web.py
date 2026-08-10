"""Web layer for the research plugin — DuckDuckGo search + readable extraction.

All network access for the plugin goes through here. Every entry point
degrades gracefully: on any network/parse failure `search` returns [] and
`fetch_readable` returns None — they never raise to callers.

Pure helpers (`decode_ddg_url`, `parse_search_results`, `extract_readable`)
take strings so they can be unit-tested without a network.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SEARCH_URL = "https://html.duckduckgo.com/html/"
TIMEOUT_SECONDS = 15.0

# Chrome-y boilerplate that never carries article content.
_STRIP_TAGS = (
    "script", "style", "nav", "header", "footer", "aside",
    "noscript", "form", "iframe", "svg",
)


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


# -- pure helpers (no network) -------------------------------------------------


def decode_ddg_url(href: str) -> str:
    """Unwrap DuckDuckGo redirect links.

    Organic results wrap the target as //duckduckgo.com/l/?uddg=<urlencoded>.
    Returns the real URL, or "" if no usable http(s) URL can be extracted.
    """
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    target = parse_qs(parsed.query).get("uddg", [""])[0]  # parse_qs unquotes
    if target:
        return target
    if parsed.scheme in ("http", "https"):
        return href
    return ""


def _is_ad(a) -> bool:
    href = a.get("href", "")
    if "y.js" in href or "ad_provider" in href:
        return True
    return a.find_parent(class_="result--ad") is not None


def parse_search_results(html: str, max_results: int = 5) -> list[SearchResult]:
    """Parse the DDG HTML SERP. Organic results are `a.result__a` links."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    seen: set[str] = set()
    for a in soup.find_all("a", class_="result__a"):
        if _is_ad(a):
            continue
        url = decode_ddg_url(a.get("href", ""))
        if not url or url in seen:
            continue
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        snippet = ""
        container = a.find_parent(class_="result")
        if container is not None:
            sn = container.find(class_="result__snippet")
            if sn is not None:
                snippet = re.sub(r"\s+", " ", sn.get_text(" ", strip=True))
        seen.add(url)
        out.append(SearchResult(url=url, title=title, snippet=snippet))
        if len(out) >= max_results:
            break
    return out


def extract_readable(html: str, max_chars: int = 6000) -> str:
    """Boilerplate-stripped readable text from an HTML page.

    Kills script/style/nav/header/footer/aside etc., prefers <article>/<main>,
    joins paragraph text, collapses whitespace, truncates to max_chars.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [
        re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        for p in root.find_all("p")
    ]
    text = "\n".join(p for p in paras if p)
    if not text:  # page with no <p> content — fall back to all visible text
        text = re.sub(r"\s+", " ", root.get_text(" ", strip=True))
    return text[:max_chars]


# -- network entry points --------------------------------------------------------


async def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """DuckDuckGo HTML search. Returns [] on any failure — never raises."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(SEARCH_URL, params={"q": query})
            resp.raise_for_status()
        return parse_search_results(resp.text, max_results)
    except Exception as e:
        log.warning("Web search failed for %r: %s", query, e)
        return []


async def fetch_readable(url: str, max_chars: int = 6000) -> str | None:
    """GET a page and return its readable text. None on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            if ctype and "html" not in ctype and "text" not in ctype:
                return None  # PDF/image/binary — nothing readable here
            text = extract_readable(resp.text, max_chars=max_chars)
            return text or None
    except Exception as e:
        log.warning("Fetch failed for %s: %s", url, e)
        return None
