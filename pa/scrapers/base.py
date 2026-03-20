from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from playwright.async_api import BrowserContext

from pa.scrapers.mfa_bridge import MFABridge


@dataclass
class BalanceData:
    balance: float
    statement_balance: float | None = None
    available_credit: float | None = None
    minimum_payment: float | None = None
    due_date: str | None = None


@dataclass
class TransactionData:
    date: str
    description: str
    amount: float
    posted_date: str | None = None
    is_pending: bool = False


class BaseScraper(ABC):
    institution: str = ""

    def __init__(self, context: BrowserContext, mfa_bridge: MFABridge):
        self._context = context
        self._mfa_bridge = mfa_bridge
        self._page = None

    async def open(self) -> None:
        self._page = await self._context.new_page()

    async def close(self) -> None:
        if self._page:
            await self._page.close()
            self._page = None

    @abstractmethod
    async def login(self, credentials: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_balances(self) -> list[BalanceData]: ...

    @abstractmethod
    async def get_transactions(self, since_date: str) -> list[TransactionData]: ...

    @abstractmethod
    async def logout(self) -> None: ...
