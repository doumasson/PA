"""Pure-function tests for the research web layer — no network involved."""
from pa.plugins.research.web import (
    decode_ddg_url,
    extract_readable,
    parse_search_results,
)

DDG_HTML = """
<html><body>
<div class="serp__results">
  <div class="result results_links results_links_deep web-result">
    <h2 class="result__title">
      <a class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage%3Fx%3D1%26y%3D2&amp;rut=abc123">
         Example Page Title</a>
    </h2>
    <a class="result__snippet" href="#">A snippet about the <b>example</b> page.</a>
  </div>
  <div class="result result--ad">
    <h2 class="result__title">
      <a class="result__a" href="https://duckduckgo.com/y.js?ad_provider=bingv7aa&amp;u3=x">Buy Widgets Now</a>
    </h2>
  </div>
  <div class="result results_links web-result">
    <h2 class="result__title">
      <a class="result__a" href="https://direct.example.org/article">Direct Result</a>
    </h2>
    <div class="result__snippet">Second   snippet text.</div>
  </div>
  <div class="result results_links web-result">
    <h2 class="result__title">
      <a class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage%3Fx%3D1%26y%3D2&amp;rut=dupe">
         Duplicate Of First</a>
    </h2>
  </div>
</div>
</body></html>
"""

PAGE_HTML = """
<html>
<head><title>t</title><style>p { color: red; }</style><script>var tracker = 1;</script></head>
<body>
<nav><p>Home | About | Contact</p></nav>
<header><p>Site header junk</p></header>
<article>
  <h1>Big Story</h1>
  <p>First    paragraph about
     the topic.</p>
  <p>Second paragraph with a <a href="#">link</a> inside.</p>
</article>
<aside><p>Related junk you do not want</p></aside>
<footer><p>Copyright 2026</p></footer>
</body></html>
"""


# -- decode_ddg_url -------------------------------------------------------------


def test_decode_unwraps_ddg_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage%3Fx%3D1%26y%3D2&rut=abc"
    assert decode_ddg_url(href) == "https://example.com/page?x=1&y=2"


def test_decode_passes_through_plain_urls():
    assert decode_ddg_url("https://direct.example.org/a") == "https://direct.example.org/a"


def test_decode_rejects_garbage():
    assert decode_ddg_url("") == ""
    assert decode_ddg_url("javascript:void(0)") == ""
    assert decode_ddg_url("/relative/path") == ""


# -- parse_search_results ---------------------------------------------------------


def test_parse_extracts_organic_results():
    results = parse_search_results(DDG_HTML)
    urls = [r.url for r in results]
    assert urls == [
        "https://example.com/page?x=1&y=2",
        "https://direct.example.org/article",
    ]
    assert results[0].title == "Example Page Title"
    assert "snippet about the example page" in results[0].snippet
    assert results[1].snippet == "Second snippet text."


def test_parse_filters_ads():
    results = parse_search_results(DDG_HTML)
    assert all("y.js" not in r.url for r in results)
    assert all("Buy Widgets" not in r.title for r in results)


def test_parse_dedupes_and_respects_max_results():
    assert len(parse_search_results(DDG_HTML, max_results=5)) == 2  # dupe dropped
    assert len(parse_search_results(DDG_HTML, max_results=1)) == 1


def test_parse_empty_page_returns_nothing():
    assert parse_search_results("<html><body>No results.</body></html>") == []
    assert parse_search_results("") == []


# -- extract_readable -------------------------------------------------------------


def test_extract_prefers_article_and_kills_boilerplate():
    text = extract_readable(PAGE_HTML)
    assert "First paragraph about the topic." in text  # whitespace collapsed
    assert "Second paragraph with a link inside." in text
    for junk in ("Home | About", "Site header junk", "Related junk",
                 "Copyright 2026", "var tracker", "color: red"):
        assert junk not in text


def test_extract_uses_body_when_no_article():
    html = "<html><body><nav><p>menu</p></nav><p>Real  content here.</p></body></html>"
    text = extract_readable(html)
    assert text == "Real content here."


def test_extract_falls_back_to_all_text_without_paragraphs():
    html = "<html><body><div>Just a bare   div of text.</div></body></html>"
    assert extract_readable(html) == "Just a bare div of text."


def test_extract_truncates():
    text = extract_readable(PAGE_HTML, max_chars=10)
    assert len(text) <= 10


def test_extract_handles_empty_input():
    assert extract_readable("") == ""
