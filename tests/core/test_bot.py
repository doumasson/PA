from pa.core.bot import PABot
from pa.plugins import Command
import pytest


def test_register_command():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    bot.register_command(Command(name="balance", description="Show balance", handler=lambda: None))
    assert "balance" in bot._command_registry


def test_cannot_override_builtin():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    with pytest.raises(ValueError, match="builtin"):
        bot.register_command(Command(name="unlock", description="Bad", handler=lambda: None))


def test_help_text_includes_registered():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    bot._plugin_names = []
    bot.register_command(Command(name="balance", description="Show balance", handler=lambda: None))
    text = bot.build_help_text()
    assert "/balance" in text
    assert "/unlock" in text
