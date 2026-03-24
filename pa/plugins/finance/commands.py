import asyncio
import json
import sys
import time
from typing import Any

from pa.plugins import AppContext
from pa.plugins.finance.repository import FinanceRepository
from pa.plugins.finance.formatters import (
    format_balance_summary, format_debt_summary, format_due_summary,
    format_spending_summary, format_trend_summary,
)

_scrape_lock = asyncio.Lock()
_login_failures: dict[str, dict] = {}  # {institution: {"count": int, "blocked_until": float}}
_COOLDOWN_SECONDS = 3600
_MAX_FAILURES_BEFORE_COOLDOWN = 2


def _check_cooldown(institution: str) -> str | None:
    """Check if institution is in login failure cooldown."""
    info = _login_failures.get(institution)
    if info and info["count"] >= _MAX_FAILURES_BEFORE_COOLDOWN:
        if time.time() < info["blocked_until"]:
            remaining = int(info["blocked_until"] - time.time()) // 60
            return f"Scraping {institution} is blocked for ~{remaining} min after repeated login failures. Check your credentials with /creds."
        else:
            _login_failures.pop(institution, None)
    return None


def _record_login_failure(institution: str) -> None:
    """Record a login failure. After 2, block for 1 hour."""
    info = _login_failures.get(institution, {"count": 0, "blocked_until": 0})
    info["count"] = info.get("count", 0) + 1
    if info["count"] >= _MAX_FAILURES_BEFORE_COOLDOWN:
        info["blocked_until"] = time.time() + _COOLDOWN_SECONDS
    _login_failures[institution] = info


def _repo(ctx: AppContext) -> FinanceRepository:
    return FinanceRepository(ctx.store)


async def handle_balance(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_balance_summary(balances)


async def handle_debt(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_debt_summary(balances)


async def handle_due(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_due_summary(balances)


async def handle_spending(ctx: AppContext, update: Any, context: Any) -> str:
    period = "this month"
    if context.args:
        period = " ".join(context.args)
    txns = await _repo(ctx).get_transactions(limit=500)
    return format_spending_summary(txns, period)


async def handle_trend(ctx: AppContext, update: Any, context: Any) -> str:
    repo = _repo(ctx)
    monthly = await repo.get_monthly_spending(months=6)
    # Optionally show category breakdown for a specific month
    detail_month = context.args[0] if context.args else None
    categories = None
    if detail_month:
        categories = await repo.get_monthly_by_category(detail_month)
    elif monthly:
        # Default: show breakdown for most recent month
        detail_month = monthly[-1]["month"]
        categories = await repo.get_monthly_by_category(detail_month)
    return format_trend_summary(monthly, detail_month, categories)


async def handle_plan(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."
    from pa.core.tier import Tier
    response = await ctx.brain.query(
        "Create a debt payoff plan based on my current balances. Compare snowball vs avalanche strategies.",
        tier=Tier.DEEP,
    )
    return response


async def handle_scrape(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    institution = context.args[0] if context.args else None
    if not institution:
        return "Usage: /scrape <institution>"

    creds = ctx.vault.get(institution)
    if not creds:
        return f"No credentials for '{institution}'. Use /addcred first."

    url = creds.get("url")
    if not url:
        return f"No login URL stored for '{institution}'. Use /addcred to re-add with URL."

    cooldown_msg = _check_cooldown(institution)
    if cooldown_msg:
        return cooldown_msg

    if _scrape_lock.locked():
        return "A scrape is already in progress. Please wait."

    async with _scrape_lock:
        repo = _repo(ctx)
        start_time = time.time()

        await update.message.reply_text(f"Scraping {institution}...")

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pa.plugins.finance.scraper_runner",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Load saved cookies and recipe for cascade
            from pa.scrapers.session_store import SessionStore
            session_store = SessionStore(ctx.vault)
            saved_cookies = await session_store.load_cookies(institution)

            from pa.scrapers.recipe import RecipeEngine
            recipe_engine = RecipeEngine(ctx.store)
            recipe = await recipe_engine.get_recipe(f"scrape_{institution}")
            saved_recipe = json.loads(recipe["steps"]) if recipe else None

            config = json.dumps({
                "url": url,
                "credentials": {"username": creds["username"], "password": creds["password"]},
                "data_dir": str(ctx.config.get("data_dir", ".")),
                "cookies": saved_cookies,
                "recipe": saved_recipe,
            })
            proc.stdin.write(config.encode() + b"\n")
            await proc.stdin.drain()

            result = None
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    await repo.log_scrape(institution, "failure", error_message="Timeout after 300s", duration_seconds=time.time() - start_time)
                    return f"Scrape of {institution} timed out after 5 minutes."

                if not line:
                    break

                try:
                    event = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue

                if event.get("event") == "progress":
                    pass

                elif event.get("event") == "mfa_needed":
                    prompt = event.get("prompt", "MFA code required")
                    await update.message.reply_text(f"MFA required: {prompt}\nReply with your code within 5 minutes.")
                    ctx.bot._mfa_subprocess = proc
                    ctx.bot._mfa_institution = institution
                    continue

                elif event.get("event") == "complete":
                    result = event.get("result", {})
                    break

            if hasattr(ctx.bot, '_mfa_subprocess'):
                del ctx.bot._mfa_subprocess
                if hasattr(ctx.bot, '_mfa_institution'):
                    del ctx.bot._mfa_institution

            await proc.wait()
            duration = time.time() - start_time

            if result is None:
                await repo.log_scrape(institution, "failure", error_message="No result from subprocess", duration_seconds=duration)
                return f"Scrape of {institution} failed — no result received."

            if result.get("status") == "login_failed":
                _record_login_failure(institution)
                error = result.get("error", "Unknown error")
                await repo.log_scrape(institution, "failure", error_message=error, duration_seconds=duration)
                failures = _login_failures.get(institution, {}).get("count", 0)
                if failures >= _MAX_FAILURES_BEFORE_COOLDOWN:
                    return f"Scrape of {institution} failed: {error}\nBlocked for 1 hour after {failures} consecutive failures."
                return f"Scrape of {institution} failed: {error}"

            if result.get("status") != "success":
                error = result.get("error", "Unknown error")
                await repo.log_scrape(institution, "failure", error_message=error, duration_seconds=duration)
                return f"Scrape of {institution} failed: {error}"

            # Success — clear any login failure tracking
            _login_failures.pop(institution, None)

            accounts = result.get("accounts", [])
            if not accounts:
                await repo.log_scrape(institution, "failure", error_message="No accounts found", duration_seconds=duration)
                return f"Scrape of {institution} succeeded but found no accounts."

            existing = await repo.get_accounts()
            existing_map = {(a["institution"], a["name"]): a["id"] for a in existing}

            stored_count = 0
            for acct in accounts:
                key = (institution, acct["account_name"])
                if key in existing_map:
                    account_id = existing_map[key]
                else:
                    account_id = await repo.add_account(
                        institution=institution,
                        name=acct["account_name"],
                        account_type=acct.get("account_type", "checking"),
                    )

                await repo.add_balance(
                    account_id=account_id,
                    balance=acct["balance"],
                    statement_balance=acct.get("statement_balance"),
                    available_credit=acct.get("available_credit"),
                    minimum_payment=acct.get("minimum_payment"),
                    due_date=acct.get("due_date"),
                )
                stored_count += 1

            cookies = result.get("cookies", [])
            if cookies:
                await session_store.save_cookies(institution, cookies)

            actions = result.get("actions", [])
            if actions:
                await recipe_engine.record(f"scrape_{institution}", "finance", actions)

            await repo.log_scrape(institution, "success", duration_seconds=duration)

            lines = [f"Scraped {institution} ({duration:.1f}s) — {stored_count} accounts:"]
            for acct in accounts:
                balance_str = f"${acct['balance']:,.2f}"
                lines.append(f"  {acct['account_name']}: {balance_str}")
            return "\n".join(lines)

        except Exception as e:
            duration = time.time() - start_time
            await repo.log_scrape(institution, "failure", error_message=str(e), duration_seconds=duration)
            return f"Scrape of {institution} failed: {e}"


async def handle_schedule(ctx: AppContext, update: Any, context: Any) -> str:
    schedule = ctx.config.get("schedule", {})
    lines = ["**Current Schedule**\n"]
    for key, val in schedule.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


async def handle_backup(ctx: AppContext, update: Any, context: Any) -> str:
    backup_path = ctx.config.get("backup_path", "")
    if not backup_path:
        return "Backup path not configured. Set backup_path in config."
    return f"Backup saved to {backup_path}"
