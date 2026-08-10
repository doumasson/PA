"""Photo intake — snap a bill, receipt, flyer, or note and Albus reads it.

The vision model (REASON tier, via the subscription proxy) extracts what the
photo is and what's in it. If it implies an action, the extraction is turned
into a plain-language instruction and routed through the normal reflex
ladder — so a photographed bill flows into the same handler as a typed
"add bill ...", and the route gets learned like any other.
"""
from __future__ import annotations

import logging

from pa.core.brain import Tier

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """You are the vision intake for a personal assistant. Look at the image (a photo the owner sent, possibly a bill, receipt, letter, school flyer, schedule, product, or handwritten note) and extract:

{
  "type": "bill|receipt|letter|flyer|schedule|handwriting|product|other",
  "summary": "one-sentence description of what this is",
  "details": "the key facts: merchant/sender, amounts, dates, items — terse lines",
  "route_text": "an imperative instruction for the assistant IF action is implied (e.g. 'add bill Xcel Energy $64.12 due 2026-07-29', 'add soccer practice Tuesday 5pm to the calendar', 'add milk and eggs to the grocery list'), else null"
}

Rules: amounts/dates exactly as printed; if the owner's caption gives instructions, they override your guess for route_text; never invent data not visible."""


async def handle_photo(update, context, bot) -> None:
    await update.message.reply_text("👁 Taking a look...")
    try:
        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        image = bytes(await file.download_as_bytearray())
        caption = (update.message.caption or "").strip()

        prompt = "Extract the contents of this photo."
        if caption:
            prompt += f'\nOwner\'s caption: "{caption}"'
        extraction = await bot._brain.query_json(
            prompt, tier=Tier.REASON, system=_EXTRACT_SYSTEM,
            image=image, max_tokens=800,
        )
    except Exception as e:
        if bot._ledger is not None:
            await bot._ledger.record(e, source="photo_intake")
        await update.message.reply_text(
            "I couldn't make sense of that photo — recorded the failure."
        )
        return

    summary = extraction.get("summary") or "a photo"
    details = extraction.get("details") or ""
    reply = f"📎 {summary}"
    if details:
        reply += f"\n{details}"
    await update.message.reply_text(reply)

    route_text = extraction.get("route_text")
    if route_text and isinstance(route_text, str):
        await bot._route_message(route_text, update)
