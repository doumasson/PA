"""/ha — Home Assistant status at a glance."""
from __future__ import annotations

from collections import Counter

from pa.plugins import AppContext
from pa.plugins.homeassistant.client import HAClient, HAError

NOT_ONLINE = (
    "The brain box isn't online yet — add homeassistant.url and .token "
    "to config.local.json when it is."
)
UNREACHABLE = "I couldn't reach the smart home hub just now. I'll keep trying."


async def _record(ctx: AppContext, err: Exception, source: str) -> None:
    if getattr(ctx, "ledger", None) is not None:
        await ctx.ledger.record(err, source)


async def handle_ha(ctx: AppContext, update, context) -> str:
    client = HAClient(ctx.config)
    if not client.configured:
        return NOT_ONLINE
    try:
        await client.ping()
        states = await client.states()
    except HAError as e:
        await _record(ctx, e, "homeassistant.command")
        return UNREACHABLE
    counts = Counter(s["entity_id"].split(".", 1)[0] for s in states if "entity_id" in s)
    if not counts:
        return "Home Assistant is online, but it has no entities yet."
    by_domain = ", ".join(
        f"{domain}: {n}"
        for domain, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return f"Home Assistant is online — {sum(counts.values())} entities. {by_domain}."
