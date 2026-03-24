from __future__ import annotations
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext
from pa.plugins.agent.memory import AgentMemory

AGENT_SCRIPT = Path.home() / "agent/run.py"
SHOT_DIR     = Path.home() / "agent-screenshots"


def _get_latest_screenshot() -> Path | None:
    dirs = sorted(SHOT_DIR.glob("iter-*"), reverse=True)
    for d in dirs:
        shots = sorted(d.glob("*.png"), reverse=True)
        if shots:
            return shots[0]
    return None


def _agent_running() -> bool:
    result = subprocess.run(["pgrep", "-f", "agent/run.py"], capture_output=True)
    return result.returncode == 0


def _start_agent() -> str:
    if _agent_running():
        return "The build agent is already running."
    subprocess.Popen(
        ["bash", "-c",
         "export PATH=/home/admin/.local/bin:/home/admin/.npm-global/bin:$PATH && source ~/pa/.venv/bin/activate && "
         "set -a && source ~/pa/.env && set +a && "
         "python3 " + str(AGENT_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "DungeonMind build agent started. Updates coming each iteration."


def _stop_agent() -> str:
    result = subprocess.run(["pkill", "-f", "agent/run.py"], capture_output=True)
    return "Build agent stopped." if result.returncode == 0 else "Build agent wasn't running."


async def cmd_agent(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = context.args or []
    subcmd = args[0].lower() if args else "status"
    memory = AgentMemory(ctx.store)

    if subcmd == "status":
        running = "RUNNING" if _agent_running() else "IDLE"
        summary = await memory.get_status_summary()
        return f"**Build Agent: {running}**\n\n{summary}"

    if subcmd in ("start", "go", "run", "kick"):
        return _start_agent()

    if subcmd == "stop":
        return _stop_agent()

    if subcmd == "history":
        rows = await memory.get_last_iterations(10)
        if not rows:
            return "No build history yet."
        lines = ["**Last 10 iterations:**"]
        for r in rows:
            status = "pass" if r["succeeded"] else "FAIL"
            lines.append(f"[{status}] iter {r['iteration']} -- {r['what_happened'][:80]}")
        return "\n".join(lines)

    if subcmd == "screenshot":
        shot = _get_latest_screenshot()
        if not shot:
            return "No screenshots yet."
        await update.message.reply_photo(photo=open(shot, "rb"))
        return f"Latest: {shot.name}"

    if subcmd == "lesson":
        lesson = " ".join(args[1:])
        if not lesson:
            return "Usage: /agent lesson <what you learned>"
        await memory.add_lesson(lesson, source="human")
        return f"Lesson saved: {lesson}"

    return (
        "Build agent commands:\n"
        "/agent status -- current state\n"
        "/agent start -- kick off a build run\n"
        "/agent stop -- stop the build agent\n"
        "/agent history -- last 10 iterations\n"
        "/agent screenshot -- latest screenshot\n"
        "/agent lesson <text> -- teach it something"
    )


async def handle_agent_query(ctx: AppContext, text: str, update: Update) -> str | None:
    """NL handler for build agent. Triggers must reference 'dungeonmind', 'build agent',
    or 'the game' to avoid clashing with other Albus features."""
    t = text.lower()
    memory = AgentMemory(ctx.store)

    # Start triggers — must mention the game/agent/build specifically
    start_phrases = [
        "start the build", "start build agent", "start the agent",
        "run the build", "run build agent", "run the agent",
        "build dungeonmind", "start dungeonmind", "run dungeonmind",
        "build the game", "start building the game",
        "fire up the build", "fire up the agent",
        "kick off the build", "kick off the agent",
        "kick off dungeonmind", "let the agent rip",
    ]
    if any(phrase in t for phrase in start_phrases):
        return _start_agent()

    # Stop triggers
    stop_phrases = [
        "stop the build", "stop build agent", "stop the agent",
        "stop dungeonmind", "stop building the game",
        "kill the agent", "kill build agent",
        "pause the build", "pause the agent",
    ]
    if any(phrase in t for phrase in stop_phrases):
        return _stop_agent()

    # Status triggers
    status_phrases = [
        "build status", "agent status", "build agent status",
        "how is dungeonmind", "how is the build", "how is the agent",
        "how's dungeonmind", "how's the build", "how's the agent",
        "what did the agent build", "what's the agent doing",
        "is the agent running", "is the build running",
        "dungeonmind status",
    ]
    if any(phrase in t for phrase in status_phrases):
        running = "RUNNING" if _agent_running() else "IDLE"
        summary = await memory.get_status_summary()
        return f"Build Agent: {running}\n\n{summary}"

    # Screenshot triggers
    if any(phrase in t for phrase in [
        "build screenshot", "agent screenshot", "game screenshot",
        "show me the game", "show me dungeonmind", "what does the game look like",
    ]):
        shot = _get_latest_screenshot()
        if shot and update.message:
            await update.message.reply_photo(photo=open(shot, "rb"))
            return f"Latest screenshot: {shot.name}"
        return "No screenshots yet."

    # History triggers
    if any(phrase in t for phrase in [
        "build history", "agent history", "what did it build",
        "last build run", "build iterations",
    ]):
        rows = await memory.get_last_iterations(5)
        if not rows:
            return "No build history yet."
        lines = []
        for r in rows:
            lines.append(f"Iter {r['iteration']}: {r['what_happened'][:100]}")
        return "\n".join(lines)

    return None
