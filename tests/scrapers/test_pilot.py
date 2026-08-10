import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pa.scrapers.pilot import AIPilot, PilotResult, ScrapedAccount, PILOT_SYSTEM_PROMPT


class TestScrapedAccount:
    def test_create_minimal(self):
        a = ScrapedAccount(account_name="Checking", account_type="checking", balance=1500.0)
        assert a.balance == 1500.0
        assert a.available_credit is None

    def test_create_full(self):
        a = ScrapedAccount(
            account_name="Visa ****1234",
            account_type="credit_card",
            balance=500.0,
            available_credit=4500.0,
            minimum_payment=25.0,
            due_date="2026-04-15",
        )
        assert a.minimum_payment == 25.0


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://bank.com/login"
    page.content = AsyncMock(return_value="<html><body><form><input id='user'/></form></body></html>")
    page.evaluate = AsyncMock(return_value="Login page")
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG")
    page.goto = AsyncMock()
    return page


@pytest.fixture
def mock_brain():
    brain = AsyncMock()
    return brain


@pytest.fixture
def pilot(mock_page, mock_brain):
    return AIPilot(mock_page, mock_brain)


class TestPilotActionExecution:
    @pytest.mark.asyncio
    async def test_fill_action_substitutes_credentials(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(side_effect=[
            {"action": "fill", "selector": "#user", "value": "$cred.username"},
            {"action": "extract", "balances": [{"account_name": "Checking", "account_type": "checking", "balance": 1000.0}]},
        ])
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "john", "password": "secret"},
        )
        mock_page.fill.assert_called_with("#user", "john")

    @pytest.mark.asyncio
    async def test_extract_action_returns_balances(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "extract",
            "balances": [
                {"account_name": "Checking", "account_type": "checking", "balance": 1500.0},
                {"account_name": "Visa", "account_type": "credit_card", "balance": 500.0, "available_credit": 4500.0},
            ],
        })
        result = await pilot.run(
            url="https://bank.com/accounts",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "success"
        assert len(result.accounts) == 2
        assert result.accounts[0].balance == 1500.0

    @pytest.mark.asyncio
    async def test_mfa_action_returns_mfa_needed(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "mfa",
            "prompt": "Enter code sent to ***-1234",
        })
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "mfa_needed"
        assert "1234" in result.mfa_prompt

    @pytest.mark.asyncio
    async def test_fail_action_returns_error(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "fail",
            "reason": "Invalid password",
        })
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "login_failed"

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={"action": "click", "selector": "#btn"})
        call_count = 0
        async def changing_content():
            nonlocal call_count
            call_count += 1
            return f"<html><body><button id='btn'>Click {call_count}</button></body></html>"
        mock_page.content = changing_content
        mock_page.evaluate = AsyncMock(side_effect=lambda _: f"Page {call_count}")

        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
            max_steps=5,
        )
        assert result.status == "max_steps"

    @pytest.mark.asyncio
    async def test_credentials_never_in_actions_log(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(side_effect=[
            {"action": "fill", "selector": "#user", "value": "$cred.username"},
            {"action": "fill", "selector": "#pass", "value": "$cred.password"},
            {"action": "extract", "balances": [{"account_name": "Checking", "account_type": "checking", "balance": 100.0}]},
        ])
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "realuser", "password": "realpass"},
        )
        actions_json = json.dumps(result.actions)
        assert "realuser" not in actions_json
        assert "realpass" not in actions_json
        assert "$cred.username" in actions_json
