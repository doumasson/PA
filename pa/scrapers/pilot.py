"""AI Pilot -- Claude-driven browser navigation for any website."""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pa.core.tier import Tier
from pa.scrapers.page_analyzer import clean_html, compute_page_hash, extract_visible_text, take_screenshot

logger = logging.getLogger(__name__)

_CRED_MAP = {"$cred.username": "username", "$cred.password": "password"}

PILOT_SYSTEM_PROMPT = """You are a browser navigation assistant. You are looking at a web page and deciding what action to take next.

Goal: {goal}

You have these credentials available:
- $cred.username
- $cred.password

Actions taken so far:
{action_history}

Current page URL: {url}
Current page HTML:
{cleaned_html}

Respond with ONLY a JSON object (no other text). Available actions:
- {{"action": "fill", "selector": "css-selector", "value": "text or $cred.username or $cred.password"}}
- {{"action": "click", "selector": "css-selector"}}
- {{"action": "screenshot", "reason": "why you need to see the page visually"}}
- {{"action": "wait", "wait_for": "selector|url", "value": "css-selector or url-pattern", "timeout_ms": 5000}}
- {{"action": "extract", "balances": [{{"account_name": "...", "account_type": "checking|savings|credit_card|mortgage|loan", "balance": 1234.56, "available_credit": null, "minimum_payment": null, "due_date": null, "statement_balance": null}}]}}
- {{"action": "mfa", "prompt": "the MFA prompt shown to the user"}}
- {{"action": "fail", "reason": "why this cannot proceed"}}

Rules:
- Use the most specific CSS selector you can find
- For credential fields, use $cred.username or $cred.password as the value
- If the HTML is unclear or you cannot determine what to do, request a screenshot
- If you see account balances on the page, extract them immediately
- If you see an MFA/verification code prompt, report it with the mfa action
- If login has clearly failed (wrong password message, locked account), use the fail action"""


@dataclass
class ScrapedAccount:
    """A single account extracted from a bank website."""

    account_name: str
    account_type: str
    balance: float
    available_credit: float | None = None
    minimum_payment: float | None = None
    due_date: str | None = None
    statement_balance: float | None = None


@dataclass
class PilotResult:
    """Result of an AI Pilot navigation session."""

    status: Literal["success", "mfa_needed", "login_failed", "max_steps", "error"]
    accounts: list[ScrapedAccount] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    cookies: list[dict] = field(default_factory=list)
    mfa_prompt: str | None = None
    error: str | None = None


class AIPilot:
    """Navigates any website using Claude to analyze pages and decide actions."""

    def __init__(self, page: Any, brain: Any) -> None:
        self._page = page
        self._brain = brain
        self._screenshot_count = 0
        self._max_screenshots = 3

    async def run(
        self,
        url: str,
        goal: str,
        credentials: dict[str, str],
        resume_from: list[dict] | None = None,
        max_steps: int = 20,
        session_timeout: float = 300.0,
    ) -> PilotResult:
        """Navigate the website to achieve the goal, returning structured results."""
        actions: list[dict[str, Any]] = list(resume_from or [])
        session_start = time.monotonic()

        try:
            if not resume_from:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            return PilotResult(status="error", error=f"Failed to load {url}: {e}")

        prev_hash = ""

        for step in range(max_steps):
            if time.monotonic() - session_start > session_timeout:
                return PilotResult(status="error", actions=actions, error=f"Session timeout ({session_timeout}s)")

            try:
                html = await self._page.content()
                cleaned = clean_html(html)
                visible_text = await extract_visible_text(self._page)
                current_url = self._page.url
            except Exception as e:
                return PilotResult(status="error", actions=actions, error=f"Page read failed: {e}")

            current_hash = compute_page_hash(current_url, visible_text)
            page_changed = current_hash != prev_hash
            prev_hash = current_hash

            action_history = json.dumps(actions[-10:], indent=2) if actions else "None yet"
            prompt = PILOT_SYSTEM_PROMPT.format(
                goal=goal,
                action_history=action_history,
                url=current_url,
                cleaned_html=cleaned,
            )

            if not page_changed and actions:
                prompt += "\n\nWARNING: The page did not change after your last action. Try a different approach."

            try:
                action = await self._brain.query_json(
                    user_message="What is the next action?",
                    system_prompt=prompt,
                    tier=Tier.STANDARD,
                )
            except Exception as e:
                return PilotResult(status="error", actions=actions, error=f"Claude API error: {e}")

            action_type = action.get("action")
            logger.info("Pilot step %d: %s", step + 1, action_type)

            actions.append(action)

            result = await self._execute_action(action, credentials, current_url, visible_text)
            if result is not None:
                result.actions = actions
                return result

            await asyncio.sleep(random.uniform(0.5, 2.0))

        return PilotResult(status="max_steps", actions=actions, error=f"Exceeded {max_steps} navigation steps")

    async def _execute_action(
        self,
        action: dict[str, Any],
        credentials: dict[str, str],
        current_url: str,
        visible_text: str,
    ) -> PilotResult | None:
        """Execute a single action returned by Claude. Returns PilotResult if terminal, None to continue."""
        action_type = action.get("action")

        try:
            if action_type == "fill":
                value = self._resolve_credential(action.get("value", ""), credentials)
                await self._page.fill(action["selector"], value)
                action["checkpoint"] = compute_page_hash(current_url, visible_text)
                return None

            elif action_type == "click":
                await self._page.click(action["selector"], timeout=15000)
                await self._page.wait_for_load_state("domcontentloaded", timeout=30000)
                action["checkpoint"] = compute_page_hash(current_url, visible_text)
                return None

            elif action_type == "screenshot":
                if self._screenshot_count >= self._max_screenshots:
                    logger.warning("Screenshot limit reached, continuing without")
                    return None
                self._screenshot_count += 1
                image = await take_screenshot(self._page)
                try:
                    visual_action = await self._brain.query_json(
                        user_message="Here is a screenshot of the page. What action should I take?",
                        system_prompt=PILOT_SYSTEM_PROMPT.format(
                            goal="(see prior context)",
                            action_history="(see prior context)",
                            url=self._page.url,
                            cleaned_html="(screenshot provided instead)",
                        ),
                        tier=Tier.STANDARD,
                        image=image,
                    )
                    return await self._execute_action(visual_action, credentials, current_url, visible_text)
                except Exception as e:
                    logger.warning("Vision call failed: %s", e)
                    return None

            elif action_type == "wait":
                wait_for = action.get("wait_for", "selector")
                value = action.get("value", "")
                timeout = action.get("timeout_ms", 5000)
                if wait_for == "url":
                    await self._page.wait_for_url(f"**{value}**", timeout=timeout)
                else:
                    await self._page.wait_for_selector(value, timeout=timeout)
                return None

            elif action_type == "extract":
                accounts = []
                for b in action.get("balances", []):
                    accounts.append(ScrapedAccount(
                        account_name=b.get("account_name", "Unknown"),
                        account_type=b.get("account_type", "checking"),
                        balance=float(b.get("balance", 0)),
                        available_credit=b.get("available_credit"),
                        minimum_payment=b.get("minimum_payment"),
                        due_date=b.get("due_date"),
                        statement_balance=b.get("statement_balance"),
                    ))
                return PilotResult(status="success", accounts=accounts)

            elif action_type == "mfa":
                return PilotResult(
                    status="mfa_needed",
                    mfa_prompt=action.get("prompt", "MFA code required"),
                )

            elif action_type == "fail":
                return PilotResult(
                    status="login_failed",
                    error=action.get("reason", "Unknown failure"),
                )

            else:
                logger.warning("Unknown action type: %s", action_type)
                return None

        except Exception as e:
            logger.warning("Action %s failed: %s", action_type, e)
            return None

    @staticmethod
    def _resolve_credential(value: str, credentials: dict[str, str]) -> str:
        """Replace $cred.username/$cred.password with actual values."""
        if value in _CRED_MAP:
            return credentials.get(_CRED_MAP[value], value)
        return value
