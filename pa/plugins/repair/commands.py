"""Repair plugin commands and approval callbacks."""
from __future__ import annotations

from pa.plugins import AppContext

_STATUS_ICONS = {
    "queued": "⏳", "diagnosing": "🔍", "awaiting_approval": "🙋",
    "approved": "👍", "applying": "🔧", "applied": "✅",
    "failed": "⚠️", "rejected": "🚫", "closed": "📁",
}


async def handle_repairs(ctx: AppContext, update, context) -> str:
    """List recent repair-queue entries."""
    rows = await ctx.store.fetchall(
        "SELECT id, signature, source, status, summary, updated_at "
        "FROM repair_queue ORDER BY updated_at DESC LIMIT 10"
    )
    if not rows:
        return "Repair queue is empty. Nothing has needed fixing — splendid."
    lines = ["**Repair Queue**\n"]
    for r in rows:
        icon = _STATUS_ICONS.get(r["status"], "•")
        summary = f" — {r['summary'][:80]}" if r["summary"] else ""
        lines.append(
            f"{icon} #{r['id']} [{r['signature']}] {r['source']} "
            f"({r['status']}){summary}"
        )
    return "\n".join(lines)


async def handle_repair_callback(ctx: AppContext, update, payload: str) -> str:
    """Handle repair:approve:<id> / repair:reject:<id> button presses."""
    action, _, repair_id = payload.partition(":")
    if action not in ("approve", "reject") or not repair_id.isdigit():
        return "That repair action made no sense to me."
    row = await ctx.store.fetchone(
        "SELECT id, status, source FROM repair_queue WHERE id = ?", (int(repair_id),)
    )
    if row is None:
        return f"Repair #{repair_id} no longer exists."
    if row["status"] != "awaiting_approval":
        return f"Repair #{repair_id} is already {row['status']} — nothing to do."
    new_status = "approved" if action == "approve" else "rejected"
    await ctx.store.execute(
        "UPDATE repair_queue SET status = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (new_status, row["id"]),
    )
    if action == "approve":
        return (
            f"👍 Repair #{repair_id} approved — the daemon will apply it, "
            "run the tests, and restart me within ~2 minutes."
        )
    return f"🚫 Repair #{repair_id} rejected. The proposed patch will be discarded."
