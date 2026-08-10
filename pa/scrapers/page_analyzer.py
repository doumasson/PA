"""HTML cleaning and page analysis utilities for AI Pilot."""

import hashlib
import re


_STRIP_TAGS = re.compile(
    r"<(script|style|noscript|svg|path)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_DATA_ATTRS = re.compile(r'\s(?:data-|aria-)\w+(?:=(?:"[^"]*"|\'[^\']*\'|\S+))?', re.IGNORECASE)
_SELF_CLOSING_STRIP = re.compile(r"<(?:svg|path)\b[^/>]*/?>", re.IGNORECASE)


def clean_html(html: str, max_chars: int = 12000) -> str:
    """Strip noise from HTML, keeping forms/inputs/buttons/links/text."""
    result = _STRIP_TAGS.sub("", html)
    result = _SELF_CLOSING_STRIP.sub("", result)
    result = _COMMENTS.sub("", result)
    result = _DATA_ATTRS.sub("", result)
    result = re.sub(r"\n\s*\n", "\n", result)
    result = result.strip()
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[...truncated...]"
    return result


def compute_page_hash(url: str, visible_text: str) -> str:
    """Hash URL + visible text for checkpoint comparison."""
    content = f"{url}|{visible_text}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def extract_visible_text(page) -> str:
    """Extract visible text content from a Playwright page."""
    return await page.evaluate("() => document.body.innerText || ''")


async def take_screenshot(page) -> bytes:
    """Take a PNG screenshot of the current page."""
    return await page.screenshot(type="png", full_page=False)


async def get_cleaned_html(page) -> str:
    """Get the page HTML and clean it for Claude analysis."""
    html = await page.content()
    return clean_html(html)
