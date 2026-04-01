"""Gmail plugin commands."""
from __future__ import annotations
import re
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_email_block(ctx: AppContext, text: str, update: Update) -> str:
    """Handle requests to block email senders/topics. Zero API calls."""
    tl = text.lower()

    # Extract what they don't want
    # Patterns: "stop sending me X emails", "I don't care about X", "block X emails"
    patterns = [
        r"(?:stop|quit|don't|dont)\s+(?:sending|showing|telling)\s+(?:me\s+)?(?:about\s+)?(.+?)(?:\s+emails?)?$",
        r"(?:i\s+)?(?:don't|dont)\s+care\s+about\s+(.+?)(?:\s+emails?)?$",
        r"block\s+(.+?)(?:\s+emails?)?$",
        r"(?:i'm\s+)?not\s+interested\s+in\s+(.+?)(?:\s+emails?)?$",
        r"(?:mute|ignore|filter out|hide)\s+(.+?)(?:\s+emails?)?$",
    ]

    topic = None
    for pat in patterns:
        m = re.search(pat, tl)
        if m:
            topic = m.group(1).strip().rstrip('.')
            break

    if not topic:
        # Fallback: grab the key noun after complaint keywords
        for kw in ["about ", "from "]:
            idx = tl.find(kw)
            if idx != -1:
                topic = tl[idx + len(kw):].strip().rstrip('.')
                break

    if not topic or len(topic) < 2:
        return "What emails should I stop showing you? Try: 'stop sending me LinkedIn emails' or 'I don't care about First Tee'"

    # Determine if it's a sender or topic keyword
    block_type = "sender" if any(x in topic for x in ["@", ".com", ".org", ".net"]) else "keyword"

    await ctx.store.execute(
        "INSERT OR IGNORE INTO google_email_blocks (block_type, pattern, reason) VALUES (?, ?, ?)",
        (block_type, topic.lower(), text.strip()[:200]),
    )

    # Also save as preference for the triage prompt
    await ctx.brain.learn_preference(f"Do NOT notify about {topic} emails", learned_from="email_block")

    return f"Got it — I'll filter out {topic} emails from now on. Use /email_blocks to see what's blocked."


async def handle_email_blocks(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Show blocked email senders/topics."""
    rows = await ctx.store.fetchall(
        "SELECT block_type, pattern, created_at FROM google_email_blocks ORDER BY created_at DESC"
    )
    if not rows:
        return "No email blocks set. Tell me 'stop sending me X emails' to add one."
    lines = ["**Blocked Email Topics/Senders**\n"]
    for r in rows:
        lines.append(f"  [{r['block_type']}] {r['pattern']}")
    lines.append("\nUse /email_unblock <pattern> to remove one.")
    return "\n".join(lines)


async def handle_email_unblock(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Remove an email block."""
    args = context.args or []
    if not args:
        return "Usage: /email_unblock <pattern>"
    pattern = " ".join(args).lower()
    rows = await ctx.store.execute_rowcount(
        "DELETE FROM google_email_blocks WHERE LOWER(pattern) = ?", (pattern,)
    )
    if rows == 0:
        return f"No block found for '{pattern}'. Use /email_blocks to see all."
    return f"Unblocked: {pattern}"


async def handle_kid_sport(ctx: AppContext, text: str, update: Update) -> str:
    """Update what sport a kid plays. Stored in google_state, used by email triage.

    Handles corrections like:
    - "Asher is the soccer player, not Maddox"
    - "Maddox plays basketball, Asher plays soccer"
    - "Asher is soccer, Maddox is basketball"
    """
    tl = text.lower()

    sports = ["basketball", "football", "soccer", "baseball", "hockey", "lacrosse",
              "swimming", "tennis", "golf", "volleyball", "wrestling", "track",
              "cross country", "gymnastics"]

    # Detect if both kids are mentioned (correction scenario)
    has_maddox = "maddox" in tl
    has_asher = "asher" in tl

    found_sports = [s for s in sports if s in tl]

    updates = []

    if has_maddox and has_asher and found_sports:
        # Both kids mentioned — use Claude to parse the correction
        result = await ctx.brain.query(
            text,
            system_prompt=(
                'Extract kid-sport assignments from this message. Kids are Maddox (12) and Asher (10). '
                'Return ONLY JSON array: [{"kid": "maddox", "sport": "..."}, {"kid": "asher", "sport": "..."}]. '
                'Raw JSON only.'
            ),
            tier=Tier.FAST,
            use_conversation=False,
        )
        try:
            import json
            start = result.find('[')
            end = result.rfind(']')
            if start != -1:
                pairs = json.loads(result[start:end + 1])
                for p in pairs:
                    if p.get('kid') and p.get('sport'):
                        updates.append((p['kid'].lower(), p['sport'].lower()))
        except Exception:
            pass

    if not updates:
        # Single kid or fallback — original logic
        kid = None
        sport = None
        if has_maddox:
            kid = "maddox"
        elif has_asher:
            kid = "asher"

        for s in sports:
            if s in tl:
                sport = s
                break

        if not kid:
            return "Which kid? Try: 'Maddox is now playing football'"
        if not sport:
            return f"What sport? Try: '{kid.capitalize()} is now playing football'"
        updates.append((kid, sport))

    confirmations = []
    for kid, sport in updates:
        await ctx.store.execute(
            "INSERT INTO google_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"kid_{kid}_sport", sport),
        )
        await ctx.brain.learn_preference(
            f"{kid.capitalize()} plays {sport.upper()} (not other sports)",
            learned_from="kid_sport_update"
        )
        confirmations.append(f"{kid.capitalize()} plays {sport}")

    return f"Got it — {', '.join(confirmations)}. I'll update the email triage."


async def handle_gmail_check(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Manually trigger a Gmail check."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    await update.message.reply_text("Checking Gmail...")

    from pa.plugins.google.jobs import check_gmail
    await check_gmail(ctx)
    return "Done. I'll message you if anything needs attention."


async def handle_gmail_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language Gmail/calendar queries."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    tl = text.lower()

    if any(w in tl for w in ["check", "any emails", "what's in", "inbox", "new email", "unread"]):
        await update.message.reply_text("Checking Gmail now...")
        from pa.plugins.google.jobs import check_gmail
        from pa.plugins.google.client import gmail_service
        from pa.plugins.google.gmail import get_unread_since
        try:
            gmail = gmail_service(ctx.vault)
            emails = get_unread_since(gmail, max_results=5)
            count = len(emails)
            if count == 0:
                return "No unread emails."
            return f"You have {count} unread emails. Triaging now..."
        except Exception as e:
            return f"Gmail error: {e}"

    return await ctx.brain.query(
        f"User asked about email/calendar: '{text}'. "
        f"Tell them they can use /gmail to check email, or ask me to check for them.",
        tier=Tier.FAST
    )
