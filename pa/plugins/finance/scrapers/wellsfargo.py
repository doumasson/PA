import asyncio
import re
import random
from dataclasses import dataclass
from typing import Any

from playwright.async_api import BrowserContext

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData
from pa.scrapers.mfa_bridge import MFABridge


@dataclass
class WFBalanceData(BalanceData):
    """Extended BalanceData with account metadata for storage."""
    account_name: str = ""
    account_type: str = "checking"
    interest_rate: float | None = None


class WellsFargoScraper(BaseScraper):
    institution = "wellsfargo"

    LOGIN_URL = "https://connect.secure.wellsfargo.com/auth/login/present"
    ACCOUNTS_URL = "https://connect.secure.wellsfargo.com/accounts/start"

    async def _dump_page(self, label: str) -> None:
        """Save page HTML to /tmp for debugging on headless Pi."""
        try:
            html = await self._page.content()
            path = f"/tmp/wf_{label}.html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL, timeout=60000)
        await self._human_delay()
        await self._dump_page("login")

        # Try multiple selector strategies for username field
        username_selectors = [
            'input[name="j_username"]',
            'input[id="j_username"]',
            'input[type="text"]',
            'input[autocomplete="username"]',
            '#userid',
            'input[name="userid"]',
        ]
        username_el = await self._find_element(username_selectors)
        if not username_el:
            raise RuntimeError("Could not find username field. Check /tmp/wf_login.html")
        await username_el.fill(credentials["username"])
        await self._human_delay()

        # Try multiple selector strategies for password field
        password_selectors = [
            'input[name="j_password"]',
            'input[id="j_password"]',
            'input[type="password"]',
            'input[autocomplete="current-password"]',
            '#password',
            'input[name="password"]',
        ]
        password_el = await self._find_element(password_selectors)
        if not password_el:
            raise RuntimeError("Could not find password field. Check /tmp/wf_login.html")
        await password_el.fill(credentials["password"])
        await self._human_delay()

        # Try multiple submit button selectors
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button[id*="sign"]',
            'a[id*="sign"]',
            'button:has-text("Sign On")',
        ]
        submit_el = await self._find_element(submit_selectors)
        if not submit_el:
            raise RuntimeError("Could not find submit button. Check /tmp/wf_login.html")
        await submit_el.click()
        await self._page.wait_for_load_state("domcontentloaded", timeout=60000)
        await self._dump_page("post_login")

        if await self._check_mfa():
            code = await self._mfa_bridge.request_mfa(
                self.institution,
                "Wells Fargo is requesting an MFA code. Reply with the code.",
            )
            await self._submit_mfa(code)

    async def get_balances(self) -> list[BalanceData]:
        await self._page.goto(self.ACCOUNTS_URL, wait_until="domcontentloaded", timeout=60000)
        await self._human_delay()

        # Take a screenshot for debugging if needed
        await self._page.screenshot(path="/tmp/wf_accounts.png")

        balances: list[BalanceData] = []

        # WF account summary page has account groups (checking, savings, credit cards, etc.)
        # Each account row shows account name and balance
        # Try multiple selector strategies since WF updates their DOM frequently

        # Strategy 1: Look for account rows by common WF patterns
        account_rows = await self._page.query_selector_all(
            '[class*="account"], [data-testid*="account"], [class*="Account"]'
        )

        if not account_rows:
            # Strategy 2: Get the full page text and parse it
            return await self._parse_balances_from_text()

        for row in account_rows:
            try:
                bal = await self._parse_account_row(row)
                if bal:
                    balances.append(bal)
            except Exception:
                continue

        # If structured parsing found nothing, fall back to text parsing
        if not balances:
            balances = await self._parse_balances_from_text()

        return balances

    async def _parse_account_row(self, row: Any) -> WFBalanceData | None:
        text = await row.inner_text()
        if not text.strip():
            return None

        # Try to extract account name and balance from the row text
        amount = self._extract_amount(text)
        if amount is None:
            return None

        # First line is usually the account name
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        if not lines:
            return None

        name = lines[0]
        account_type = self._infer_type(name, text)

        bal = WFBalanceData(balance=amount)
        bal.account_name = name
        bal.account_type = account_type
        return bal

    async def _parse_balances_from_text(self) -> list[WFBalanceData]:
        """Fallback: parse the full page text for account info."""
        content = await self._page.inner_text("body")
        balances: list[WFBalanceData] = []

        # Split into lines, look for patterns like:
        # "ACCOUNT NAME"
        # "$1,234.56"
        lines = [l.strip() for l in content.split("\n") if l.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            amount = self._extract_amount(line)

            if amount is not None and i > 0:
                # Look back for account name
                name = lines[i - 1]
                # Skip if the "name" is also just a number
                if not self._extract_amount(name) and len(name) > 2:
                    account_type = self._infer_type(name, "")
                    bal = WFBalanceData(balance=amount)
                    bal.account_name = name
                    bal.account_type = account_type
                    balances.append(bal)
            i += 1

        return balances

    @staticmethod
    def _extract_amount(text: str) -> float | None:
        """Extract a dollar amount from text like '$1,234.56' or '-$50.00'."""
        match = re.search(r'-?\$[\d,]+\.\d{2}', text)
        if not match:
            return None
        raw = match.group().replace("$", "").replace(",", "")
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _infer_type(name: str, context: str) -> str:
        """Guess account type from name/context."""
        combined = (name + " " + context).lower()
        if any(w in combined for w in ["credit card", "visa", "mastercard", "credit"]):
            return "credit_card"
        if any(w in combined for w in ["savings", "way2save"]):
            return "savings"
        if any(w in combined for w in ["mortgage", "home loan"]):
            return "mortgage"
        if any(w in combined for w in ["loan", "auto"]):
            return "loan"
        return "checking"

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
            "we need to verify",
            "security challenge",
            "one-time access code",
        ]
        content = await self._page.content()
        return any(indicator in content.lower() for indicator in mfa_indicators)

    async def _submit_mfa(self, code: str) -> None:
        # Try multiple input selectors
        for selector in ['input[type="text"]', 'input[type="tel"]', 'input[name*="code"]']:
            try:
                el = await self._page.query_selector(selector)
                if el:
                    await el.fill(code)
                    break
            except Exception:
                continue
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("domcontentloaded", timeout=60000)

    async def _find_element(self, selectors: list[str]) -> Any:
        """Try multiple selectors, return the first visible element found."""
        for selector in selectors:
            try:
                el = await self._page.query_selector(selector)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
