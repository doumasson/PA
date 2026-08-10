"""Weekly self-report — Albus accounts for himself.

Sunday evening digest from the stats, learning store, ledger, and repair
queue: reflex rate trend, what got learned, what broke and what got fixed.
Pure SQL + one formatted message; zero LLM cost.
"""
from __future__ import annotations


async def weekly_self_report(ctx) -> None:
    parts = [await ctx.stats.reflex_report()]

    counts = await ctx.learning.counts()
    if counts:
        pretty = ", ".join(f"{v} {k}s" for k, v in sorted(counts.items()))
        parts.append(f"Memory: {pretty}.")

    new_learnings = await ctx.store.fetchall(
        "SELECT kind, key FROM core_learnings "
        "WHERE created_at >= datetime('now', '-7 days') "
        "ORDER BY id DESC LIMIT 5"
    )
    if new_learnings:
        lines = "\n".join(f"  • [{r['kind']}] {r['key'][:70]}" for r in new_learnings)
        parts.append(f"Newest learnings:\n{lines}")

    gaps = await ctx.store.fetchall(
        "SELECT key, value, hits FROM core_learnings WHERE kind = 'gap' "
        "ORDER BY hits DESC, id DESC LIMIT 5"
    )
    if gaps:
        import json
        lines = []
        for g in gaps:
            missing = json.loads(g["value"]).get("missing", g["key"])[:90]
            lines.append(f"  • {missing}" + (f" (asked {g['hits'] + 1}x)" if g["hits"] else ""))
        parts.append("Things you asked for that I can't do yet:\n" + "\n".join(lines))

    errors = await ctx.store.fetchone(
        "SELECT COUNT(*) AS n, COALESCE(SUM(count), 0) AS total FROM core_ledger "
        "WHERE last_seen >= datetime('now', '-7 days')"
    )
    repairs = await ctx.store.fetchall(
        "SELECT status, COUNT(*) AS n FROM repair_queue "
        "WHERE updated_at >= datetime('now', '-7 days') GROUP BY status"
    )
    repair_bits = ", ".join(f"{r['n']} {r['status']}" for r in repairs) or "none"
    parts.append(
        f"Health: {errors['n']} distinct failure signatures this week "
        f"({errors['total']} occurrences). Repairs: {repair_bits}."
    )

    await ctx.bot.send_message(
        "🦉 **Albus — Weekly Self-Report**\n\n" + "\n\n".join(parts)
    )
