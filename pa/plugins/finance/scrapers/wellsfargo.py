import asyncio
import random
from typing import Any

from playwright.async_api import BrowserContext

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData
from pa.scrapers.mfa_bridge import MFABridge


class WellsFargoScraper(BaseScraper):
    institution = "wellsfargo"

    LOGIN_URL = "https://connect.secure.wellsfargo.com/auth/login/present"

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL)
        await self._human_delay()

        await self._page.fill('input[name="j_username"]', credentials["username"])
        await self._human_delay()

        await self._page.fill('input[name="j_password"]', credentials["password"])
        await self._human_delay()

        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

        if await self._check_mfa():
            code = await self._mfa_bridge.request_mfa(
                self.institution,
                "Wells Fargo is requesting an MFA code. Reply with the code.",
            )
            await self._submit_mfa(code)

    async def get_balances(self) -> list[BalanceData]:
        await self._page.goto("https://connect.secure.wellsfargo.com/accounts/start")
        await self._page.wait_for_load_state("networkidle")
        await self._human_delay()

        balances: list[BalanceData] = []
        return balances

    async def get_transactions(self, since_date: str) -> list[TransactionData]:
        transactions: list[TransactionData] = []
        return transactions

    async def logout(self) -> None:
        try:
            await self._page.goto("https://connect.secure.wellsfargo.com/auth/logout")
            await self._human_delay()
        except Exception:
            pass

    async def _check_mfa(self) -> bool:
        mfa_indicators = [
            "text me a temporary code",
            "enter your code",
            "verify your identity",
        ]
        content = await self._page.content()
        return any(indicator in content.lower() for indicator in mfa_indicators)

    async def _submit_mfa(self, code: str) -> None:
        await self._page.fill('input[type="text"]', code)
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
