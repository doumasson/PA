"""Robinhood Chain scanner + trader bridge for Albus — BONKbot-style UX.

Read (rh-scanner subprocess, sandbox-safe):
  /check /hot /bags — cards with holdings-aware Buy/Sell buttons
  /alert /alerts /tp /sl /limit — price alerts & orders (notify + action button)
Trade (rh-trader on 127.0.0.1:8484, quote -> tap ✅ Confirm):
  /buy /sell /confirm, and /wallet (new/import/use/list)

Alerts flow: rh-scanner writes JSON to the spool dir; the rh_spool job here
delivers each through Albus with its buttons attached. Buttons route back via
Callback prefixes: rhtr (confirm/cancel), rhbuy, rhsell.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.request
from typing import Any

from pa.plugins import PluginBase, Command, NLHandler, Callback, Job, AppContext

SCANNER = "/home/admin/rh-scanner/scanner.py"
TRADER = "http://127.0.0.1:8484"
TRADER_ENV = "/home/admin/rh-trader/.env"
SPOOL = "/mnt/tokendata/albus/data/rh-spool"
_TICKER_RE = re.compile(r"^[A-Za-z0-9$._\-]{1,20}$")
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_CA_RE = re.compile(r"CA: (0x[0-9a-fA-F]{40})")
_INT_RE = re.compile(r"^\d+[smh]$", re.I)

_PENDING: dict[int, dict] = {}  # user id -> last quote (textual /confirm path)


def _pre(text: str) -> str:
    return "<pre>" + html.escape(text) + "</pre>"


def _buy_row(token: str):
    return [["Buy 0.005Ξ", f"rhbuy:0.005:{token}"], ["0.01Ξ", f"rhbuy:0.01:{token}"]]


# ------------------------------------------------------------- scanner bridge

async def _run_scanner(args: list[str], timeout: int = 120) -> str:
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/python3", SCANNER, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd="/home/admin/rh-scanner",
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return "Scanner timed out — probably API rate-limit backoff. Try again in a minute."
    text = (out or b"").decode(errors="replace").strip()
    if proc.returncode != 0:
        return "Scanner hit an error:\n" + "\n".join(text.splitlines()[-3:])
    return text[-3500:] if text else "Scanner returned nothing."


async def _add_trigger(spec: dict) -> str:
    out = await _run_scanner(["--add-trigger", json.dumps(spec)], timeout=40)
    return html.escape(out.strip())


def _parse_interval(s: str, default: int = 60) -> int:
    m = re.match(r"^(\d+)([smh])$", s, re.I)
    if not m:
        return default
    return max(15, int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2).lower()])


# ------------------------------------------------------------- trader bridge

def _trader_secret() -> str:
    try:
        for line in open(TRADER_ENV):
            if line.startswith("TRADER_SECRET="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _trader_post_sync(path: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        TRADER + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Trader-Auth": _trader_secret()},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": f"trader unreachable: {e}"}


def _trader_get_sync(path: str, timeout: int) -> dict:
    req = urllib.request.Request(TRADER + path,
                                 headers={"X-Trader-Auth": _trader_secret()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": f"trader unreachable: {e}"}


async def _trader_post(path: str, payload: dict, timeout: int = 30) -> dict:
    return await asyncio.to_thread(_trader_post_sync, path, payload, timeout)


async def _trader_get(path: str, timeout: int = 15) -> dict:
    return await asyncio.to_thread(_trader_get_sync, path, timeout)


def _uid(update: Any) -> int:
    try:
        return update.effective_user.id
    except Exception:
        return 0


def _quote_html(q: dict) -> str:
    h = q.get("human") or {}
    fee_pct = q.get("fee", 0) / 10000
    ico = "🟢" if q["side"] == "buy" else "🔴"
    return (
        f"{ico} <b>{q['side'].upper()} QUOTE — {html.escape(q['sym'])}</b>\n"
        f"spend: <b>{html.escape(str(h.get('spend')))}</b>\n"
        f"est. receive: <b>{html.escape(str(h.get('est_out')))}</b>\n"
        f"slippage ≤{q.get('slippage_pct')}% · pool fee {fee_pct:g}% "
        f"· ~${q.get('trade_usd'):,}\n⏱ expires in 2 min"
    )


async def _quote_and_offer(ctx: AppContext, update: Any, side: str,
                           token: str, eth=None, pct=None) -> str | None:
    payload = {"side": side, "token": token}
    if eth is not None:
        payload["eth_amount"] = eth
    if pct is not None:
        payload["pct"] = pct
    q = await _trader_post("/quote", payload)
    if q.get("error"):
        return f"❌ {html.escape(str(q['error']))}"
    _PENDING[_uid(update)] = q
    await ctx.bot.send_buttons(_quote_html(q), [[
        ("✅ Confirm", f"rhtr:c:{q['qid']}"),
        ("❌ Cancel", f"rhtr:x:{q['qid']}"),
    ]])
    return None


def _fill_text(sym, r: dict) -> str:
    if r.get("error"):
        return f"❌ trade failed: {html.escape(str(r['error']))}"
    ok = r.get("status") == "ok"
    head = "✅ <b>FILLED</b>" if ok else f"⚠️ <b>{html.escape(str(r.get('status')))}</b>"
    return (f"{head} — {html.escape(str(sym))}: "
            f"<b>{html.escape(str(r.get('filled')))}</b>\n"
            f"https://robinhoodchain.blockscout.com/tx/{r.get('tx', '')}")


# ------------------------------------------------------------- read handlers

async def handle_check(ctx: AppContext, update: Any, context: Any) -> str | None:
    args = context.args if context.args else []
    if not args:
        return "Usage: /check <ticker>\nExample: /check DIH"
    ticker = args[0].lstrip("$").strip()
    if not _TICKER_RE.match(ticker):
        return f"That does not look like a ticker: {ticker!r}"
    out = await _run_scanner(["--check", ticker])
    m = _CA_RE.search(out)
    if m:
        await ctx.bot.send_buttons(_pre(out), [[(l, c) for l, c in _buy_row(m.group(1))]])
        return None
    return _pre(out)


async def handle_hot(ctx: AppContext, update: Any, context: Any) -> str | None:
    out = await _run_scanner(["--hot"], timeout=150)
    pairs, cur = [], None
    for line in out.splitlines():
        m = re.match(r"🟢 +\d+/100 (\S+)", line)
        if m:
            cur = m.group(1)
        m2 = _CA_RE.search(line)
        if m2 and cur:
            pairs.append((cur, m2.group(1)))
            cur = None
    rows = [[(f"Buy {s} 0.005Ξ", f"rhbuy:0.005:{a}")] for s, a in pairs[:4]]
    if rows:
        await ctx.bot.send_buttons(_pre(out), rows)
        return None
    return _pre(out)


async def handle_bags(ctx: AppContext, update: Any, context: Any) -> str | None:
    args = context.args if context.args else []
    addr = args[0].strip() if args else ""
    if addr and not _ADDR_RE.match(addr):
        return "That does not look like a wallet address (0x + 40 hex)."
    out = await _run_scanner(["--bags"] + ([addr] if addr else []), timeout=90)
    toks, lines = [], []
    for line in out.splitlines():
        if line.startswith("#tokens "):
            for pair in line[len("#tokens "):].split(","):
                s, _, a = pair.partition("=")
                if s and _ADDR_RE.match(a or ""):
                    toks.append((s, a))
        else:
            lines.append(line)
    display = _pre("\n".join(lines))
    rows = [[(f"Sell {s} 50%", f"rhsell:50:{a}"), (f"{s} 100%", f"rhsell:100:{a}")]
            for s, a in toks[:6]]
    if rows:
        await ctx.bot.send_buttons(display, rows)
        return None
    return display


async def handle_check_nl(ctx: AppContext, text: str, update: Any) -> str | None:
    class _A:
        args: list = []
    fake = _A()
    if re.search(r"\b(my bags|bags|portfolio|my coins|holdings)\b", text, re.I):
        m = re.search(r"(0x[0-9a-fA-F]{40})", text)
        fake.args = [m.group(1)] if m else []
        return await handle_bags(ctx, update, fake)
    if re.search(r"\b(hot|anything good|what.?s good|worth buying)\b", text, re.I):
        return await handle_hot(ctx, update, fake)
    m = re.search(
        r"(?:check|score|look\s*at)\s+(?:ticker\s+|coin\s+|token\s+)?\$?([A-Za-z0-9._\-]{1,20})",
        text, re.I)
    if not m:
        m = re.search(r"how(?:\x27s| is| does)\s+\$?([A-Za-z0-9._\-]{1,20})", text, re.I)
    if not m or m.group(1).lower() in {"ticker", "coin", "token", "the", "my", "on", "out"}:
        return ("Which ticker? e.g. 'check DIH' — or say 'whats hot' for the "
                "current board.")
    fake.args = [m.group(1)]
    return await handle_check(ctx, update, fake)


# ------------------------------------------------------------- alerts & orders

async def handle_alert(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args if context.args else []
    if not args:
        return ("Price alerts:\n/alert DIH > 0.005   (or &lt;)\n"
                "/alert DIH 15m   (repeat every 15m/1h/…)\n"
                "/alerts   list all · /alert del &lt;id&gt;")
    if args[0].lower() == "del" and len(args) > 1:
        return html.escape(await _run_scanner(["--del-trigger", args[1]]))
    sym = args[0].lstrip("$")
    if len(args) >= 3 and args[1] in (">", "<", ">=", "<=", "above", "below"):
        op = "above" if args[1] in (">", ">=", "above") else "below"
        try:
            price = float(args[2])
        except ValueError:
            return f"Bad price: {args[2]!r}"
        interval = _parse_interval(args[3]) if len(args) > 3 else 30
        return await _add_trigger({"type": "alert", "sym": sym, "op": op,
                                   "price": price, "interval_s": interval})
    if len(args) == 2 and _INT_RE.match(args[1]):
        return await _add_trigger({"type": "periodic", "sym": sym,
                                   "interval_s": _parse_interval(args[1])})
    return "Usage: /alert DIH > 0.005  |  /alert DIH 15m  |  /alert del <id>"


async def handle_alerts(ctx: AppContext, update: Any, context: Any) -> str:
    return _pre(await _run_scanner(["--list-triggers"], timeout=30))


async def handle_tp(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args if context.args else []
    if len(args) < 2:
        return "Usage: /tp DIH 100 [sellpct]\n(alerts you + Sell button at +100%)"
    try:
        spec = {"type": "tp", "sym": args[0].lstrip("$"), "pct": float(args[1])}
    except ValueError:
        return f"Bad percent: {args[1]!r}"
    if len(args) > 2:
        try:
            spec["sell_pct"] = float(args[2])
        except ValueError:
            return f"Bad sell percent: {args[2]!r}"
    return await _add_trigger(spec)


async def handle_sl(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args if context.args else []
    if len(args) < 2:
        return "Usage: /sl DIH 30 [sellpct]\n(alerts you + Sell button at -30%)"
    try:
        spec = {"type": "sl", "sym": args[0].lstrip("$"), "pct": float(args[1])}
    except ValueError:
        return f"Bad percent: {args[1]!r}"
    if len(args) > 2:
        try:
            spec["sell_pct"] = float(args[2])
        except ValueError:
            return f"Bad sell percent: {args[2]!r}"
    return await _add_trigger(spec)


async def handle_limit(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args if context.args else []
    if len(args) < 4 or args[0].lower() not in ("buy", "sell"):
        return ("Usage:\n/limit buy DIH <price> <eth>\n"
                "/limit sell DIH <price> <pct>")
    side, sym = args[0].lower(), args[1].lstrip("$")
    try:
        price = float(args[2])
        spec = {"type": "limit", "side": side, "sym": sym, "price": price}
        spec["eth" if side == "buy" else "pct"] = float(args[3])
    except ValueError:
        return "Bad number in that limit order."
    return await _add_trigger(spec)


# ------------------------------------------------------------- wallet

async def handle_wallet(ctx: AppContext, update: Any, context: Any) -> str:
    args = context.args if context.args else []
    if not args:
        h = await _trader_get("/health")
        if h.get("error"):
            return f"❌ {html.escape(h['error'])}"
        if not h.get("wallet"):
            return "No wallet loaded.\n/wallet new  ·  /wallet import <key/phrase>"
        return (f"👛 <b>Active wallet</b>\n<code>{h['wallet']}</code>\n"
                f"{h.get('eth')} ETH\n\n/wallet list · new · use &lt;addr&gt; · import &lt;key&gt;")
    sub = args[0].lower()
    if sub == "list":
        r = await _trader_post("/wallet/list", {})
        ws = r.get("wallets") or []
        if not ws:
            return "No wallets yet. /wallet new"
        return "<b>Wallets</b>\n" + "\n".join(
            ("➡️ " if w["active"] else "   ") + f"<code>{w['address']}</code>" for w in ws)
    if sub == "new":
        r = await _trader_post("/wallet/new", {})
        if r.get("error"):
            return f"❌ {html.escape(str(r['error']))}"
        return ("🆕 <b>New wallet created &amp; now active</b>\n"
                f"<code>{r['address']}</code>\n\n"
                "⚠️ <b>SAVE THIS SEED PHRASE</b> — shown once. Back it up, then "
                "delete this message:\n"
                f"<code>{html.escape(r.get('mnemonic', ''))}</code>\n\n"
                "Fund the address, then /bags.")
    if sub == "use" and len(args) > 1:
        r = await _trader_post("/wallet/use", {"address": args[1]})
        if r.get("error"):
            return f"❌ {html.escape(str(r['error']))}"
        return f"✅ Active wallet: <code>{r['address']}</code>"
    if sub == "import" and len(args) > 1:
        secret = " ".join(args[1:]).strip()
        try:
            await update.message.delete()   # scrub the key from chat immediately
        except Exception:
            pass
        r = await _trader_post("/wallet/import", {"secret": secret})
        if r.get("error"):
            return f"❌ {html.escape(str(r['error']))}"
        return (f"✅ Imported &amp; active: <code>{r['address']}</code>\n"
                "(your message with the key was deleted)")
    return "Usage: /wallet [list | new | use <addr> | import <key/phrase>]"


# ------------------------------------------------------------- trade handlers

async def handle_buy(ctx: AppContext, update: Any, context: Any) -> str | None:
    args = context.args if context.args else []
    if len(args) < 2:
        return "Usage: /buy <ticker|0xCA> <eth>\nExample: /buy DIH 0.01"
    try:
        eth = float(args[1])
    except ValueError:
        return f"Bad ETH amount: {args[1]!r}"
    return await _quote_and_offer(ctx, update, "buy", args[0].strip(), eth=eth)


async def handle_sell(ctx: AppContext, update: Any, context: Any) -> str | None:
    args = context.args if context.args else []
    if not args:
        return "Usage: /sell <ticker|0xCA> [pct]\nExamples: /sell DIH 50 · /sell DIH all"
    pct = 100.0
    if len(args) > 1:
        raw = args[1].strip().rstrip("%")
        if raw.lower() != "all":
            try:
                pct = float(raw)
            except ValueError:
                return f"Bad percent: {args[1]!r}"
    return await _quote_and_offer(ctx, update, "sell", args[0].strip(), pct=pct)


async def handle_confirm(ctx: AppContext, update: Any, context: Any) -> str:
    q = _PENDING.pop(_uid(update), None)
    if not q:
        return "Nothing pending. Quote first with /buy or /sell."
    if q.get("expires", 0) < time.time():
        return "That quote expired — quote again."
    return _fill_text(q.get("sym"), await _trader_post("/trade", {"qid": q["qid"]}, timeout=240))


# ------------------------------------------------------------- callbacks

async def cb_trade(ctx: AppContext, update: Any, payload: str) -> str | None:
    action, _, qid = payload.partition(":")
    if action == "x":
        return "🚫 Cancelled — quote discarded."
    if action != "c" or not qid:
        return "Unknown trade action."
    sym = next((q.get("sym") for q in _PENDING.values() if q.get("qid") == qid), "trade")
    return _fill_text(sym, await _trader_post("/trade", {"qid": qid}, timeout=240))


async def cb_buy(ctx: AppContext, update: Any, payload: str) -> str | None:
    eth_s, _, token = payload.partition(":")
    try:
        eth = float(eth_s)
    except ValueError:
        return "Bad amount in button."
    if not _ADDR_RE.match(token or ""):
        return "Bad token in button."
    return await _quote_and_offer(ctx, update, "buy", token, eth=eth)


async def cb_sell(ctx: AppContext, update: Any, payload: str) -> str | None:
    pct_s, _, token = payload.partition(":")
    try:
        pct = float(pct_s)
    except ValueError:
        return "Bad percent in button."
    if not _ADDR_RE.match(token or ""):
        return "Bad token in button."
    return await _quote_and_offer(ctx, update, "sell", token, pct=pct)


# ------------------------------------------------------------- spool delivery

async def job_rh_spool(ctx: AppContext) -> None:
    """Deliver scanner alerts/warnings/triggers through Albus with buttons."""
    try:
        names = sorted(os.listdir(SPOOL))[:12]
    except OSError:
        return
    for n in names:
        path = os.path.join(SPOOL, n)
        try:
            d = json.load(open(path))
        except Exception:
            d = None
        if d:
            text = d.get("html") or d.get("body") or ""
            rows = []
            for row in (d.get("buttons") or []):
                rows.append([(lbl, cb) for lbl, cb in row])
            try:
                if rows:
                    await ctx.bot.send_buttons(text, rows)
                elif text:
                    await ctx.bot.send_message(text)
            except Exception:
                pass
        try:
            os.remove(path)
        except OSError:
            pass


class RhScanPlugin(PluginBase):
    name = "rhscan"
    description = "Robinhood Chain scanner + Telegram trading (buttons, alerts, wallets)"
    version = "0.6.0"

    def commands(self) -> list[Command]:
        return [
            Command(name="check", description="Score a token + buy buttons (/check DIH)",
                    handler=handle_check),
            Command(name="hot", description="Live alert-window board + one-tap buys",
                    handler=handle_hot),
            Command(name="bags", description="Portfolio with PnL + sell buttons",
                    handler=handle_bags),
            Command(name="buy", description="Buy: /buy DIH 0.01 → ✅ Confirm",
                    handler=handle_buy),
            Command(name="sell", description="Sell: /sell DIH 50 → ✅ Confirm",
                    handler=handle_sell),
            Command(name="confirm", description="Textual fallback for the Confirm button",
                    handler=handle_confirm),
            Command(name="wallet", description="Wallets: /wallet [new|import|use|list]",
                    handler=handle_wallet),
            Command(name="alert", description="Price alert: /alert DIH > 0.005 (or 15m)",
                    handler=handle_alert),
            Command(name="alerts", description="List active price alerts & orders",
                    handler=handle_alerts),
            Command(name="tp", description="Take-profit alert: /tp DIH 100",
                    handler=handle_tp),
            Command(name="sl", description="Stop-loss alert: /sl DIH 30",
                    handler=handle_sl),
            Command(name="limit", description="Limit order: /limit buy DIH 0.003 0.01",
                    handler=handle_limit),
        ]

    def callbacks(self) -> list[Callback]:
        return [
            Callback(prefix="rhtr", handler=cb_trade,
                     description="Confirm/cancel a quoted Robinhood Chain trade"),
            Callback(prefix="rhbuy", handler=cb_buy, description="One-tap buy button"),
            Callback(prefix="rhsell", handler=cb_sell, description="One-tap sell button"),
        ]

    def jobs(self) -> list[Job]:
        return [Job(name="rh_spool", handler=job_rh_spool,
                    trigger="interval", kwargs={"minutes": 1})]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=["check ticker", "check coin", "check token", "ticker check",
                          "score ticker", "how does ticker", "whats hot",
                          "anything good", "my bags", "portfolio"],
                handler=handle_check_nl,
                description="Scorecard for a Robinhood Chain token, the live hot list, or the wallet portfolio",
                priority=10,
                intent_id="rhscan.check",
                examples=["check DIH", "check ticker CASHCAT", "how does BIH look",
                          "whats hot right now", "hows my bags"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Robinhood Chain tools: /check /hot /bags (cards with holdings-aware "
            "Buy/Sell buttons); /alert /tp /sl /limit (price alerts & orders that "
            "notify with an action button); /buy /sell (quote → tap Confirm); "
            "/wallet new|import|use|list. Alerts arrive with buttons via rh_spool. "
            "All trades are human-confirmed — never initiate trades from natural "
            "language."
        )
