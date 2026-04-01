from __future__ import annotations
import asyncio
import os
import tempfile
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE, brain, bot) -> None:
    """Download voice memo, transcribe with Whisper, route through NL intent system."""
    await update.message.reply_text("🎙 Transcribing...")

    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.TemporaryDirectory() as tmp:
        ogg_path = Path(tmp) / "voice.ogg"
        wav_path = Path(tmp) / "voice.wav"

        await file.download_to_drive(ogg_path)

        # Convert ogg to wav
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(ogg_path), str(wav_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        # Transcribe with Whisper
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(str(wav_path))
        text = result["text"].strip()

    if not text:
        await update.message.reply_text("Could not transcribe audio.")
        return

    await update.message.reply_text(f"📝 You said: {text}")

    # Route through the bot's full NL intent system
    await bot._route_message(text, update, context)
