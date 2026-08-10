"""Natural-language smart-home control.

One states fetch + ONE PARSE-tier brain call per request: the brain sees the
user's words next to a compact entity list and picks an action. Replies are
read aloud to the kids through HA eventually, so everything stays short and
speakable.
"""
from __future__ import annotations

import logging

from pa.core.brain import Tier
from pa.plugins import AppContext
from pa.plugins.homeassistant.client import HAClient, HAError
from pa.plugins.homeassistant.commands import NOT_ONLINE, UNREACHABLE, _record

logger = logging.getLogger(__name__)

# Domains worth showing the brain; everything else (zone, sun, update,
# automation internals...) is noise for a spoken assistant.
INTERESTING_DOMAINS = frozenset({
    "light", "switch", "cover", "climate", "sensor", "person",
    "media_player", "lock", "binary_sensor",
})
_MAX_ENTITIES = 150  # keep the PARSE prompt compact on entity-heavy homes

CONFUSED = "I couldn't work out what to do with the smart home there — try naming the device."


def _compact_entities(states: list[dict]) -> list[dict]:
    picked = []
    for s in states:
        entity_id = s.get("entity_id", "")
        if entity_id.split(".", 1)[0] not in INTERESTING_DOMAINS:
            continue
        picked.append({
            "entity_id": entity_id,
            "name": (s.get("attributes") or {}).get("friendly_name", entity_id),
            "state": s.get("state", "unknown"),
        })
    return picked[:_MAX_ENTITIES]


def _prompt(text: str, entities: list[dict]) -> str:
    listing = "\n".join(
        f"{e['entity_id']} | {e['name']} | {e['state']}" for e in entities
    )
    return (
        f"User request: {text}\n\n"
        f"Smart home entities (entity_id | name | state):\n{listing}\n\n"
        'Decide what to do. Respond with JSON: {"action": "get" or "set" or '
        '"none", "entity_id": "the single best entity_id or null", '
        '"service": "HA service like light.turn_on / lock.lock, or null", '
        '"reply": "short spoken answer for get/none, else null"}.\n'
        "Use 'set' only when the user asks to change something. For 'get', "
        "answer from the states shown. Replies are read aloud to children — "
        "one short friendly sentence, no entity_ids or jargon."
    )


async def handle_ha_nl(ctx: AppContext, text: str, update) -> str:
    client = HAClient(ctx.config)
    if not client.configured:
        return NOT_ONLINE

    try:
        states = await client.states()
    except HAError as e:
        await _record(ctx, e, "homeassistant.nl")
        return UNREACHABLE

    entities = _compact_entities(states)
    if not entities:
        return "The smart home hub is up, but nothing's connected to it yet."
    names = {e["entity_id"]: e["name"] for e in entities}

    try:
        decision = await ctx.brain.query_json(_prompt(text, entities), tier=Tier.PARSE)
    except Exception as e:
        await _record(ctx, e, "homeassistant.nl")
        return "I couldn't think that one through just now — try again in a moment."

    action = decision.get("action")
    entity_id = decision.get("entity_id")

    def _has_confirmation(t: str) -> bool:
        return "confirm" in t.lower()

    if action == "set" and decision.get("service") and entity_id:
        domain, _, service = str(decision["service"]).partition(".")
        if not service:
            return CONFUSED
        # Never act on an entity the hub didn't actually report — a PARSE
        # misfire must not invent a device to operate.
        if entity_id not in names:
            return CONFUSED
        # Security domains (locks, garage/covers, alarms) don't get flipped on
        # a single-shot Haiku parse — one misread of "is the door locked?" must
        # not unlock the house. Require an explicit confirmation word.
        SECURITY_DOMAINS = {"lock", "cover", "alarm_control_panel"}
        if domain in SECURITY_DOMAINS and not _has_confirmation(text):
            verb = service.replace("_", " ")
            return (
                f"That would {verb} {names.get(entity_id, entity_id)}. "
                "For safety I won't touch locks or doors unless you add the word "
                "'confirm' — e.g. 'confirm, unlock the front door'."
            )
        try:
            await client.call_service(domain, service, entity_id)
        except HAError as e:
            await _record(ctx, e, "homeassistant.nl")
            return f"I couldn't reach {names.get(entity_id, 'that device')} — the hub didn't answer."
        return f"Done — {service.replace('_', ' ')}, {names.get(entity_id, entity_id)}."

    if action in ("get", "none"):
        reply = decision.get("reply")
        if reply:
            return str(reply)
        if entity_id in names:  # brain picked an entity but forgot the words
            state = next(e["state"] for e in entities if e["entity_id"] == entity_id)
            return f"{names[entity_id]} is {state}."

    logger.debug("HA NL got an unusable decision: %r", decision)
    return CONFUSED
