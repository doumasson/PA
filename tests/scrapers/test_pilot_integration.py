"""Integration test: Pilot navigates a mock login page flow."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from pa.scrapers.pilot import AIPilot, ScrapedAccount


@pytest.fixture
def mock_brain_sequence():
    """Brain that returns a realistic 4-step login sequence."""
    brain = AsyncMock()
    brain.query_json = AsyncMock(side_effect=[
        {"action": "fill", "selector": "#username", "value": "$cred.username"},
        {"action": "fill", "selector": "#password", "value": "$cred.password"},
        {"action": "click", "selector": "#login-btn"},
        {
            "action": "extract",
            "balances": [
                {"account_name": "Checking ****1234", "account_type": "checking", "balance": 2500.00},
                {"account_name": "Savings ****5678", "account_type": "savings", "balance": 10000.00},
            ],
        },
    ])
    return brain


@pytest.fixture
def mock_page_login_flow():
    """Page that simulates login form -> accounts page transition."""
    page = AsyncMock()

    # Track call count for changing page state
    state = {"calls": 0}

    pages = [
        '<html><body><form><input id="username"/><input id="password"/><button id="login-btn">Sign In</button></form></body></html>',
        '<html><body><form><input id="username"/><input id="password"/><button id="login-btn">Sign In</button></form></body></html>',
        '<html><body><form><input id="username"/><input id="password"/><button id="login-btn">Sign In</button></form></body></html>',
        '<html><body><h1>Your Accounts</h1><div>Checking ****1234: $2,500.00</div><div>Savings ****5678: $10,000.00</div></body></html>',
    ]
    texts = ["Sign In form", "Sign In form", "Sign In form", "Your Accounts Checking Savings"]
    urls = [
        "https://bank.com/login", "https://bank.com/login",
        "https://bank.com/login", "https://bank.com/accounts",
    ]

    async def get_content():
        idx = min(state["calls"], len(pages) - 1)
        state["calls"] += 1
        return pages[idx]

    async def get_text(script):
        idx = min(state["calls"] - 1, len(texts) - 1)
        return texts[max(0, idx)]

    page.content = get_content
    page.evaluate = get_text
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG")

    # Start URL on login page
    page.url = urls[0]

    # click updates the URL to the accounts page (simulating navigation)
    async def click_and_navigate(selector, **kwargs):
        page.url = urls[3]

    page.click = AsyncMock(side_effect=click_and_navigate)

    return page


class TestPilotIntegration:
    @pytest.mark.asyncio
    async def test_full_login_and_extract(self, mock_page_login_flow, mock_brain_sequence):
        pilot = AIPilot(mock_page_login_flow, mock_brain_sequence)
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Log in and get balances",
            credentials={"username": "testuser", "password": "testpass"},
        )

        assert result.status == "success"
        assert len(result.accounts) == 2
        assert result.accounts[0].account_name == "Checking ****1234"
        assert result.accounts[0].balance == 2500.00
        assert result.accounts[1].account_type == "savings"

        # Verify credentials were filled correctly
        mock_page_login_flow.fill.assert_any_call("#username", "testuser")
        mock_page_login_flow.fill.assert_any_call("#password", "testpass")

        # Verify actions were recorded with placeholders, not real creds
        actions_json = json.dumps(result.actions)
        assert "testuser" not in actions_json
        assert "testpass" not in actions_json
        assert "$cred.username" in actions_json
        assert len(result.actions) == 4
