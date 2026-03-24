import asyncio
import json
import sys
import time
from typing import Any

from pa.plugins import AppContext
from pa.plugins.finance.repository import FinanceRepository
from pa.plugins.finance.formatters import (
    format_balance_summary, format_bills_summary, format_debt_summary,
    format_due_summary, format_spending_summary, format_trend_summary,
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


async def handle_forecast(ctx: AppContext, update: Any, context: Any) -> str:
    """Cash flow forecast for the next 14 days."""
    import datetime

    repo = _repo(ctx)

    # Get checking balance
    balances = await repo.get_latest_balances()
    checking = [b for b in balances if b['type'] in ('checking', 'depository')]
    if not checking:
        return "No checking account data. Use /sync first."
    checking_balance = sum(b['balance'] for b in checking)

    # Get unpaid bills due in the next 14 days
    today = datetime.date.today()
    cutoff = (today + datetime.timedelta(days=14)).isoformat()
    upcoming_bills = await ctx.store.fetchall(
        "SELECT name, amount, due_date FROM finance_bills "
        "WHERE paid_this_cycle = 0 AND due_date IS NOT NULL AND due_date <= ? "
        "ORDER BY due_date",
        (cutoff,),
    )
    total_bills = sum(b['amount'] or 0 for b in upcoming_bills)

    # Average daily spending from last 30 days
    since_30 = (today - datetime.timedelta(days=30)).isoformat()
    txns = await repo.get_transactions(since_date=since_30, limit=1000)
    debits = [t for t in txns if t['amount'] > 0]
    total_spent_30 = sum(t['amount'] for t in debits)
    avg_daily = total_spent_30 / 30 if debits else 0

    projected_spending = avg_daily * 14
    remaining = checking_balance - total_bills - projected_spending

    lines = [
        f"Cash Flow Forecast (14 days)",
        f"",
        f"Checking balance: ${checking_balance:,.2f}",
        f"Upcoming bills: ${total_bills:,.2f} ({len(upcoming_bills)} bills)",
    ]
    if upcoming_bills:
        for b in upcoming_bills:
            lines.append(f"  - {b['name']}: ${b['amount'] or 0:,.2f} (due {b['due_date']})")
    lines.append(f"Avg daily spending: ${avg_daily:,.2f}/day (~${projected_spending:,.2f} over 14 days)")
    lines.append(f"")
    lines.append(f"Projected balance in 14 days: ${remaining:,.2f}")

    if remaining < 0:
        # Estimate when you'll run short
        daily_drain = avg_daily + (total_bills / 14 if total_bills else 0)
        if daily_drain > 0:
            days_until_zero = int(checking_balance / daily_drain)
            run_short_date = today + datetime.timedelta(days=days_until_zero)
            lines.append(f"")
            lines.append(f"Warning: You may run short around {run_short_date.isoformat()}.")
        else:
            lines.append(f"")
            lines.append(f"Warning: You may run short before the 14 days are up.")

    return "\n".join(lines)


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


async def handle_bills(ctx: AppContext, update: Any, context: Any) -> str:
    rows = await ctx.store.fetchall(
        "SELECT * FROM finance_bills ORDER BY paid_this_cycle ASC, due_date ASC"
    )
    return format_bills_summary(rows)


async def handle_bill_add(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args or []
    if len(args) < 2:
        return "Usage: /bill_add <name> <amount> [due_date] [frequency]\nExample: /bill_add Electric 150 2026-04-05 monthly"
    name = args[0]
    try:
        amount = float(args[1])
    except ValueError:
        return "Amount must be a number. Example: /bill_add Electric 150"
    due_date = args[2] if len(args) > 2 else None
    frequency = args[3] if len(args) > 3 else "monthly"
    valid_frequencies = {"weekly", "biweekly", "monthly", "quarterly", "annual"}
    if frequency not in valid_frequencies:
        return f"Invalid frequency. Choose from: {', '.join(sorted(valid_frequencies))}"
    await ctx.store.execute(
        "INSERT INTO finance_bills (name, amount, due_date, frequency, source) "
        "VALUES (?, ?, ?, ?, 'manual') "
        "ON CONFLICT(name) DO UPDATE SET amount=excluded.amount, due_date=excluded.due_date, "
        "frequency=excluded.frequency, updated_at=CURRENT_TIMESTAMP",
        (name, amount, due_date, frequency),
    )
    due_str = f" due {due_date}" if due_date else ""
    return f"Bill added: {name} ${amount:,.2f} {frequency}{due_str}"


async def handle_bill_paid(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args or []
    if not args:
        return "Usage: /bill_paid <name>\nExample: /bill_paid Electric"
    name = " ".join(args)
    import datetime
    today = datetime.date.today().isoformat()
    rows_changed = await ctx.store.execute_rowcount(
        "UPDATE finance_bills SET paid_this_cycle = 1, last_paid = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE LOWER(name) = LOWER(?)",
        (today, name),
    )
    if rows_changed == 0:
        return f"No bill found with name '{name}'. Use /bills to see tracked bills."
    return f"Marked {name} as paid."
