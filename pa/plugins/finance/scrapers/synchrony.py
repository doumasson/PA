import asyncio
import random
from typing import Any

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData


class SynchronyScraper(BaseScraper):
    institution = "synchrony"

    LOGIN_URL = "https://consumercenter.mysynchrony.com/consumercenter/login"

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL)
        await self._human_delay()
        await self._page.fill('input[id="username"]', credentials["username"])
        await self._human_delay()
        await self._page.fill('input[id="password"]', credentials["password"])
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

    async def get_balances(self) -> list[BalanceData]:
        return []

    async def get_transactions(self, since_date: str) -> list[TransactionData]:
        return []

    async def logout(self) -> None:
        try:
            await self._page.goto("https://consumercenter.mysynchrony.com/consumercenter/logout")
        except Exception:
            pass

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
