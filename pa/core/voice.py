"""Voice-note transcription — Telegram voice memos become routed messages.

Whisper (local, free) transcribes; the text then flows through the normal
reflex ladder exactly as if typed. The model is cached after first load
(~10s on a Pi), and transcription runs off the event loop.
"""
from __future__ import annotations

import asyncio
import importlib.util
import tempfile
from pathlib import Path

_whisper_model = None


def available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def _transcribe(wav_path: str) -> str:
    global _whisper_model
    import whisper
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model.transcribe(wav_path)["text"]


async def handle_voice(update, context, bot) -> None:
    """Download a Telegram voice memo, transcribe, route through the bot."""
    await update.message.reply_text("🎙 Transcribing...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.TemporaryDirectory() as tmp:
        ogg_path = Path(tmp) / "voice.ogg"
        wav_path = Path(tmp) / "voice.wav"
        await file.download_to_drive(ogg_path)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(ogg_path), str(wav_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        text = (await asyncio.to_thread(_transcribe, str(wav_path))).strip()

    if not text:
        await update.message.reply_text("Could not transcribe audio.")
        return

    await update.message.reply_text(f"📝 You said: {text}")
    await bot._route_message(text, update)
