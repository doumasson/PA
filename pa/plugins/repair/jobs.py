"""Repair plugin jobs — queue recurring failures, relay daemon results.

The Albus process never patches itself; it only queues work, asks for
approval, and reports outcomes. The actual diagnosis (Claude Code) and
application (merge, test, restart) happen in the repair daemon, which runs
outside this process via a systemd timer — so a crashed Albus can still be
repaired.
"""
from __future__ import annotations

BURST_THRESHOLD = 3      # ledger count before a signature is queued
LOOKBACK_DAYS = 7
DIFF_PREVIEW_CHARS = 2800


async def job_repair_scan(ctx) -> None:
    """Every 15 min — queue recurring ledger failures for diagnosis."""
    rows = await ctx.store.fetchall(
        """SELECT l.signature, l.source, l.error_type, l.message, l.trace, l.count
           FROM core_ledger l
           WHERE l.count >= ?
             AND l.last_seen >= datetime('now', ?)
             AND l.source NOT LIKE 'repair%'
             AND NOT EXISTS (
                 SELECT 1 FROM repair_queue q WHERE q.signature = l.signature
                   AND (q.status NOT IN ('failed', 'closed')
                        OR q.updated_at > datetime('now', '-14 days'))
             )
           ORDER BY l.count DESC LIMIT 3""",
        (BURST_THRESHOLD, f"-{LOOKBACK_DAYS} days"),
    )
    for r in rows:
        detail = (
            f"source: {r['source']}\n"
            f"error: {r['error_type']}: {r['message']}\n"
            f"occurrences: {r['count']}\n\n"
            f"traceback:\n{r['trace'] or '(none captured)'}"
        )
        await ctx.store.execute(
            "INSERT INTO repair_queue (signature, source, detail) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(signature) DO UPDATE SET "
            "status = 'queued', detail = excluded.detail, notified = 0, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE repair_queue.status IN ('failed', 'closed')",
            (r["signature"], r["source"], detail[:8000]),
        )
        await ctx.bot.send_message(
            f"🔧 {r['source']} has failed {r['count']}x "
            f"({r['error_type']}). I've queued a diagnosis — "
            f"I'll propose a fix for your approval."
        )


async def job_repair_notify(ctx) -> None:
    """Every 2 min — send approval requests and final outcomes from the daemon."""
    # Approval requests
    pending = await ctx.store.fetchall(
        "SELECT * FROM repair_queue WHERE status = 'awaiting_approval' AND notified = 0"
    )
    for row in pending:
        diff = row["diff"] or "(no diff captured)"
        if len(diff) > DIFF_PREVIEW_CHARS:
            hidden = len(diff) - DIFF_PREVIEW_CHARS
            diff = (
                diff[:DIFF_PREVIEW_CHARS]
                + f"\n... ⚠️ TRUNCATED — {hidden:,} more chars not shown. "
                "Don't approve blind: reject and ask me to show the full diff."
            )
        text = (
            f"🔧 Proposed fix #{row['id']} for {row['source']}\n\n"
            f"{row['summary'] or '(no summary)'}\n\n"
            f"```\n{diff}\n```\n"
            "Approve to apply, test, and restart."
        )
        await ctx.bot.send_approval(
            text,
            approve_data=f"repair:approve:{row['id']}",
            reject_data=f"repair:reject:{row['id']}",
        )
        await ctx.store.execute(
            "UPDATE repair_queue SET notified = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )

    # Final outcomes
    finished = await ctx.store.fetchall(
        "SELECT * FROM repair_queue "
        "WHERE status IN ('applied', 'failed') AND notified < 2"
    )
    for row in finished:
        icon = "✅" if row["status"] == "applied" else "⚠️"
        outcome = (
            "applied, tested, and Albus restarted"
            if row["status"] == "applied"
            else f"failed: {(row['result'] or 'unknown')[:400]}"
        )
        await ctx.bot.send_message(
            f"{icon} Repair #{row['id']} ({row['source']}): {outcome}"
        )
        await ctx.store.execute(
            "UPDATE repair_queue SET notified = 2, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
