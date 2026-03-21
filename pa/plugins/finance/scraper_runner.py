"""Subprocess scraper runner using AI Pilot.

Protocol: reads config from stdin, writes JSON events to stdout.
Events: {"event": "progress", "message": "..."}
        {"event": "mfa_needed", "prompt": "..."}
        {"event": "complete", "result": {...}}

MFA: reads {"event": "mfa_code", "code": "..."} from stdin when MFA is needed.
"""

import asyncio
import json
import logging
import os
import random
import sys
from typing import Any

from pa.core.tier import Tier

logger = logging.getLogger(__name__)


def _emit(event: dict) -> None:
    """Write a JSON event to stdout."""
    print(json.dumps(event), flush=True)


async def _create_pilot(data_dir: str) -> tuple:
    """Create an AIPilot with a Playwright browser. Returns (pilot, cleanup_fn)."""
    from playwright.async_api import async_playwright
    from pa.core.brain import Brain
    from pa.scrapers.pilot import AIPilot

    pw = await async_playwright().start()

    launch_args = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--js-flags=--max-old-space-size=256",
    ]

    browser = await pw.chromium.launch(headless=True, args=launch_args)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # Block heavy resources
    await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}", lambda route: route.abort())
    await context.route("**/*google*analytics*", lambda route: route.abort())
    await context.route("**/*doubleclick*", lambda route: route.abort())

    page = await context.new_page()

    brain_config = {"claude_api_key_env": "PA_CLAUDE_API_KEY", "cost_cap_monthly_usd": 20.0}
    brain = Brain(brain_config)

    pilot = AIPilot(page, brain)

    async def cleanup():
        await browser.close()
        await pw.stop()

    return pilot, cleanup


def _format_result(result) -> dict[str, Any]:
    """Convert PilotResult to serializable dict."""
    accounts = [
        {
            "account_name": a.account_name,
            "account_type": a.account_type,
            "balance": a.balance,
            "available_credit": a.available_credit,
            "minimum_payment": a.minimum_payment,
            "due_date": a.due_date,
            "statement_balance": a.statement_balance,
        }
        for a in result.accounts
    ]
    return {
        "status": result.status,
        "accounts": accounts,
        "actions": result.actions,
        "cookies": result.cookies,
        "mfa_prompt": result.mfa_prompt,
        "error": result.error,
    }


async def run_scrape(
    url: str,
    credentials: dict[str, str],
    data_dir: str,
    cookies: list[dict] | None = None,
    recipe: list[dict] | None = None,
) -> dict[str, Any]:
    """Run the AI Pilot to scrape an institution. Returns result dict.

    Cascade: cookies (session reuse) -> recipe (replay) -> AI Pilot (from scratch).
    """
    pilot, cleanup = await _create_pilot(data_dir)
    try:
        page = pilot._page

        # Phase 1: Try session reuse with saved cookies
        if cookies:
            _emit({"event": "progress", "message": "Trying saved session..."})
            context = page.context
            await context.add_cookies(cookies)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            from pa.scrapers.page_analyzer import get_cleaned_html
            html = await get_cleaned_html(page)
            try:
                check = await pilot._brain.query_json(
                    user_message="Does this page show account balances or a dashboard (not a login form)? Respond with {\"logged_in\": true/false}.",
                    system_prompt="You are checking if a browser session is still valid. Look at the HTML and determine if this is a logged-in dashboard/accounts page or a login page.",
                    tier=Tier.FAST,
                )
                if check.get("logged_in"):
                    _emit({"event": "progress", "message": "Session valid! Extracting balances..."})
                    result = await pilot.run(
                        url=page.url,
                        goal="Extract all account balances from this page. You are already logged in.",
                        credentials=credentials,
                        max_steps=5,
                    )
                    if result.status == "success":
                        return _format_result(result)
            except Exception:
                pass  # Session check failed, continue to recipe/pilot

        # Phase 2: Try recipe replay
        if recipe:
            _emit({"event": "progress", "message": "Replaying saved recipe..."})
            from pa.scrapers.recipe import RecipeEngine
            resolved = RecipeEngine.resolve_credentials(recipe, credentials)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            replay_ok = True
            for i, step in enumerate(resolved):
                try:
                    action = step.get("action")
                    if action == "fill":
                        await page.fill(step["selector"], step["value"], timeout=10000)
                    elif action == "click":
                        await page.click(step["selector"], timeout=10000)
                        await page.wait_for_load_state("domcontentloaded", timeout=30000)
                    elif action == "wait":
                        wait_for = step.get("wait_for", "selector")
                        if wait_for == "url":
                            await page.wait_for_url(step["value"], timeout=step.get("timeout_ms", 5000))
                        else:
                            await page.wait_for_selector(step["value"], timeout=step.get("timeout_ms", 5000))
                    elif action == "extract":
                        result = await pilot.run(
                            url=page.url,
                            goal="Extract all account balances from this page. You are already logged in.",
                            credentials=credentials,
                            max_steps=5,
                        )
                        return _format_result(result)
                    await asyncio.sleep(random.uniform(0.3, 1.0))
                except Exception as e:
                    logger.info("Recipe replay failed at step %d: %s", i, e)
                    replay_ok = False
                    break

            if replay_ok:
                result = await pilot.run(
                    url=page.url,
                    goal="Extract all account balances from this page.",
                    credentials=credentials,
                    max_steps=5,
                )
                return _format_result(result)
            else:
                _emit({"event": "progress", "message": f"Recipe failed, switching to AI..."})

        # Phase 3: AI Pilot from scratch
        _emit({"event": "progress", "message": "AI navigating site..."})
        result = await pilot.run(
            url=url,
            goal="Log in using the provided credentials and find all account balances. Extract every account with its name, type, and balance.",
            credentials=credentials,
        )
        return _format_result(result)

    finally:
        await cleanup()


async def run_scrape_resume_mfa(
    url: str,
    credentials: dict[str, str],
    data_dir: str,
    mfa_code: str,
    prior_actions: list[dict],
) -> dict[str, Any]:
    """Resume a scrape after MFA code is provided."""
    pilot, cleanup = await _create_pilot(data_dir)
    try:
        page = pilot._page
        from pa.scrapers.recipe import RecipeEngine
        resolved = RecipeEngine.resolve_credentials(prior_actions, credentials)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for step in resolved:
            action = step.get("action")
            try:
                if action == "fill":
                    await page.fill(step["selector"], step["value"], timeout=10000)
                elif action == "click":
                    await page.click(step["selector"], timeout=10000)
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                elif action in ("mfa", "extract", "fail", "screenshot"):
                    break
            except Exception:
                break
            await asyncio.sleep(random.uniform(0.3, 1.0))

        result = await pilot.run(
            url=page.url,
            goal=f"Enter the MFA verification code '{mfa_code}' and then find all account balances.",
            credentials=credentials,
            max_steps=15,
        )
        return _format_result(result)
    finally:
        await cleanup()


async def _main() -> None:
    """Subprocess entry point. Reads config from stdin, runs scrape, writes results to stdout."""
    input_line = sys.stdin.readline().strip()
    config = json.loads(input_line)

    url = config["url"]
    credentials = config["credentials"]
    data_dir = config.get("data_dir", ".")
    saved_cookies = config.get("cookies")
    saved_recipe = config.get("recipe")

    _emit({"event": "progress", "message": f"Starting scrape of {url}"})

    try:
        result = await run_scrape(url, credentials, data_dir,
                                   cookies=saved_cookies, recipe=saved_recipe)

        if result["status"] == "mfa_needed":
            _emit({"event": "mfa_needed", "prompt": result["mfa_prompt"]})
            mfa_line = sys.stdin.readline().strip()
            if not mfa_line:
                _emit({"event": "complete", "result": {"status": "error", "error": "MFA timeout", "accounts": []}})
                return
            mfa_msg = json.loads(mfa_line)
            if mfa_msg.get("event") == "mfa_code":
                code = mfa_msg["code"]
                _emit({"event": "progress", "message": "MFA code received, resuming..."})
                result = await run_scrape_resume_mfa(url, credentials, data_dir, code, result.get("actions", []))

        _emit({"event": "complete", "result": result})

    except Exception as e:
        _emit({"event": "complete", "result": {"status": "error", "error": str(e), "accounts": []}})


if __name__ == "__main__":
    asyncio.run(_main())
