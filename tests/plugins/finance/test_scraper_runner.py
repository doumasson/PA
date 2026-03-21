import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pa.plugins.finance.scraper_runner import run_scrape, _format_result


class TestFormatResult:
    def test_formats_success_result(self):
        result = MagicMock()
        result.status = "success"
        result.accounts = [
            MagicMock(account_name="Checking", account_type="checking", balance=1500.0,
                      available_credit=None, minimum_payment=None, due_date=None, statement_balance=None)
        ]
        result.actions = [{"action": "click", "selector": "#btn"}]
        result.cookies = [{"name": "s", "value": "v"}]
        result.mfa_prompt = None
        result.error = None

        formatted = _format_result(result)
        assert formatted["status"] == "success"
        assert len(formatted["accounts"]) == 1
        assert formatted["accounts"][0]["account_name"] == "Checking"
        assert formatted["accounts"][0]["balance"] == 1500.0

    def test_formats_error_result(self):
        result = MagicMock()
        result.status = "error"
        result.accounts = []
        result.actions = []
        result.cookies = []
        result.mfa_prompt = None
        result.error = "Something failed"

        formatted = _format_result(result)
        assert formatted["status"] == "error"
        assert formatted["error"] == "Something failed"


class TestRunScrape:
    @pytest.mark.asyncio
    async def test_returns_success_from_pilot(self):
        mock_pilot_result = MagicMock()
        mock_pilot_result.status = "success"
        mock_pilot_result.accounts = [
            MagicMock(account_name="Checking", account_type="checking", balance=1500.0,
                      available_credit=None, minimum_payment=None, due_date=None, statement_balance=None)
        ]
        mock_pilot_result.actions = [{"action": "click"}]
        mock_pilot_result.cookies = []
        mock_pilot_result.mfa_prompt = None
        mock_pilot_result.error = None

        with patch("pa.plugins.finance.scraper_runner._create_pilot") as mock_create:
            mock_pilot = AsyncMock()
            mock_pilot.run = AsyncMock(return_value=mock_pilot_result)
            mock_pilot._page = MagicMock()
            mock_create.return_value = (mock_pilot, AsyncMock())

            result = await run_scrape(
                url="https://bank.com/login",
                credentials={"username": "u", "password": "p"},
                data_dir="/tmp",
            )
        assert result["status"] == "success"
        assert len(result["accounts"]) == 1
