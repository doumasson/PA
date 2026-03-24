"""Vision-guided scraper agent - figures out login flows using Claude Vision."""
from __future__ import annotations
import asyncio
import base64
import json
from pathlib import Path
from playwright.async_api import async_playwright, Page
from pa.core.tier import Tier

CHROMIUM = '/usr/bin/chromium'
BROWSER_ARGS = ['--no-sandbox', '--disable-dev-shm-usage', '--headless']

VISION_SYSTEM = """You are a web scraping agent that navigates bank/financial websites.
You will receive a screenshot and must decide what action to take next.
Respond ONLY with valid JSON, no other text.

For navigation decisions return:
{
  "action": "click" | "fill" | "wait" | "done" | "failed" | "screenshot",
  "selector": "css selector or null",
  "value": "text to type or null",
  "description": "what you see and why you chose this action",
  "found_data": null | {
    "balances": [{"name": "account name", "balance": 0.00, "type": "checking|savings|credit|loan"}],
    "transactions": []
  }
}

Rules:
- Look for username/email field first, fill it, then password, then submit
- If you see a CAPTCHA or unusual security challenge, return action=failed
- If you see account balances/data, return action=done with found_data
- If MFA is needed (code sent to phone/email), return action=wait with description explaining what's needed
- Be specific with selectors - use id, name attributes when visible
- If unsure of selector, describe what you see in description"""


async def screenshot_b64(page: Page) -> bytes:
    """Take screenshot and return as bytes."""
    return await page.screenshot(full_page=False)


async def vision_decide(page: Page, brain, context_hint: str = "") -> dict:
    """Take screenshot, ask Claude Vision what to do next."""
    img = await screenshot_b64(page)
    url = page.url
    msg = f"Current URL: {url}\n"
    if context_hint:
        msg += f"Context: {context_hint}\n"
    msg += "What should I do next to log in and find account balances?"

    try:
        result = await brain.query_json(
            msg,
            system_prompt=VISION_SYSTEM,
            tier=Tier.STANDARD,
            image=img,
        )
        return result
    except Exception as e:
        return {"action": "failed", "description": str(e)}


class ScraperAgent:
    """Vision-guided agent that learns to scrape financial institutions."""

    def __init__(self, store, vault, brain, mfa_bridge=None):
        self._store = store
        self._vault = vault
        self._brain = brain
        self._mfa_bridge = mfa_bridge
        from pa.plugins.finance.scrapers.knowledge import ScraperKnowledge
        self._knowledge = ScraperKnowledge(store)

    async def scrape(self, institution: str, notify_callback=None) -> dict:
        """
        Scrape an institution. Returns dict with balances and transactions.
        Uses learned knowledge if available, falls back to vision agent.
        """
        # Get credentials from vault
        creds = self._vault._data.get(institution)
        if not creds:
            return {"error": f"No credentials for {institution}. Use /addcred to add them."}

        url = creds.get('url', '')
        if not url:
            return {"error": f"No URL for {institution}. Use /addcred to re-add with URL."}

        # Load existing knowledge
        knowledge = await self._knowledge.get(institution) or {}

        if notify_callback:
            await notify_callback(f"Starting scrape of {institution}...")

        try:
            result = await self._run_browser(institution, url, creds, knowledge, notify_callback)
            if result.get('balances'):
                await self._knowledge.record_success(institution)
                # Save any new knowledge learned
                if result.get('learned'):
                    knowledge.update(result['learned'])
                    await self._knowledge.save(institution, knowledge)
            return result
        except Exception as e:
            await self._knowledge.record_failure(institution, str(e))
            return {"error": str(e)}

    async def _run_browser(self, institution: str, url: str, creds: dict, knowledge: dict, notify_callback) -> dict:
        """Run the browser scraping session."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=CHROMIUM,
                args=BROWSER_ARGS,
            )
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)

                result = await self._agent_loop(page, institution, creds, knowledge, notify_callback)
                return result
            finally:
                await browser.close()

    async def _agent_loop(self, page, institution: str, creds: dict, knowledge: dict, notify_callback) -> dict:
        """Main agent loop - vision guided navigation."""
        max_steps = 15
        learned = {}

        for step in range(max_steps):
            decision = await vision_decide(
                page, self._brain,
                context_hint=f"Institution: {institution}, Username: {creds.get('username', '')}"
            )

            action = decision.get('action', 'failed')
            desc = decision.get('description', '')
            selector = decision.get('selector')
            value = decision.get('value')

            if notify_callback and step % 3 == 0:
                await notify_callback(f"Step {step+1}: {desc[:80]}")

            if action == 'done':
                found_data = decision.get('found_data', {})
                found_data['learned'] = learned
                return found_data

            elif action == 'failed':
                return {"error": f"Agent failed: {desc}"}

            elif action == 'wait':
                # MFA needed
                if notify_callback:
                    await notify_callback(f"MFA needed for {institution}: {desc}")
                if self._mfa_bridge:
                    self._mfa_bridge.request(institution)
                    # Wait up to 2 minutes for MFA code
                    for _ in range(24):
                        await asyncio.sleep(5)
                        if self._mfa_bridge.has_pending(institution):
                            code = await self._mfa_bridge.get_code(institution)
                            # Try to find and fill MFA field
                            try:
                                await page.fill('input[type="tel"], input[name*="code"], input[name*="otp"]', code)
                                await page.keyboard.press('Enter')
                            except Exception:
                                pass
                            break
                else:
                    return {"error": "MFA required but no MFA bridge available"}

            elif action == 'click' and selector:
                try:
                    await page.click(selector, timeout=5000)
                    learned[f'click_{step}'] = selector
                    await asyncio.sleep(1)
                except Exception as e:
                    # Try JavaScript click as fallback
                    try:
                        await page.evaluate(f'document.querySelector("{selector}")?.click()')
                    except Exception:
                        pass

            elif action == 'fill' and selector and value:
                # Substitute credentials
                if value in ('USERNAME', 'EMAIL', '{username}'):
                    value = creds.get('username', '')
                elif value in ('PASSWORD', '{password}'):
                    value = creds.get('password', '')
                try:
                    await page.fill(selector, value, timeout=5000)
                    learned[f'fill_{step}'] = {'selector': selector, 'field': 'username' if 'user' in selector.lower() else 'other'}
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

            elif action == 'screenshot':
                await asyncio.sleep(2)

        return {"error": "Max steps reached without finding balance data"}
