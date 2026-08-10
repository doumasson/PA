import pytest
from pa.scrapers.page_analyzer import clean_html, compute_page_hash


class TestCleanHtml:
    def test_strips_script_tags(self):
        html = '<html><body><script>alert("x")</script><p>Hello</p></body></html>'
        result = clean_html(html)
        assert "alert" not in result
        assert "Hello" in result

    def test_strips_style_tags(self):
        html = "<html><body><style>.x{color:red}</style><p>Hello</p></body></html>"
        result = clean_html(html)
        assert "color" not in result
        assert "Hello" in result

    def test_strips_noscript_svg_path(self):
        html = "<html><body><noscript>no</noscript><svg><path d='M0'/></svg><p>Hi</p></body></html>"
        result = clean_html(html)
        assert "noscript" not in result.lower()
        assert "<svg" not in result.lower()
        assert "Hi" in result

    def test_strips_html_comments(self):
        html = "<html><body><!-- secret --><p>Visible</p></body></html>"
        result = clean_html(html)
        assert "secret" not in result
        assert "Visible" in result

    def test_preserves_forms_inputs_buttons(self):
        html = '<html><body><form><input id="user" type="text"/><button>Login</button></form></body></html>'
        result = clean_html(html)
        assert "input" in result
        assert "button" in result.lower()
        assert "Login" in result

    def test_preserves_links_and_headings(self):
        html = '<html><body><h1>Welcome</h1><a href="/accounts">My Accounts</a></body></html>'
        result = clean_html(html)
        assert "Welcome" in result
        assert "My Accounts" in result

    def test_truncates_large_html(self):
        html = "<html><body>" + "<p>Line</p>" * 5000 + "</body></html>"
        result = clean_html(html, max_chars=2000)
        assert len(result) <= 2500  # some buffer for truncation message

    def test_removes_data_attributes(self):
        html = '<html><body><div data-analytics="track" data-id="123"><p>Content</p></div></body></html>'
        result = clean_html(html)
        assert "data-analytics" not in result
        assert "data-id" not in result
        assert "Content" in result


class TestComputePageHash:
    def test_same_content_same_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome to bank login")
        h2 = compute_page_hash("https://bank.com/login", "Welcome to bank login")
        assert h1 == h2

    def test_different_url_different_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome")
        h2 = compute_page_hash("https://bank.com/accounts", "Welcome")
        assert h1 != h2

    def test_different_text_different_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome")
        h2 = compute_page_hash("https://bank.com/login", "Dashboard")
        assert h1 != h2
