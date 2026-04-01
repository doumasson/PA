"""Plugin system for PA. Plugins register commands, jobs, schema, and AI patterns."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Command:
    """A bot command registered by a plugin."""
    name: str
    description: str
    handler: Callable
    aliases: list[str] = field(default_factory=list)


@dataclass
class Job:
    """A scheduled job registered by a plugin."""
    name: str
    handler: Callable
    trigger: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppContext:
    """Typed context passed to plugins at startup."""
    store: Any
    vault: Any
    brain: Any
    bot: Any
    scheduler: Any
    config: Any


class PluginBase:
    """Base class for all PA plugins. Subclass and override what you need."""

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def schema_sql(self) -> str:
        return ""

    def commands(self) -> list[Command]:
        return []

    def jobs(self) -> list[Job]:
        return []

    def tier_patterns(self) -> dict[str, list[str]]:
        return {}

    def system_prompt_fragment(self) -> str:
        return ""

    async def on_startup(self, ctx: AppContext) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


def _validate_ddl(sql: str, plugin_name: str) -> None:
    """Validate plugin DDL: only CREATE TABLE/INDEX with plugin-prefixed names."""
    import re
    for statement in sql.split(";"):
        stmt = statement.strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if not (upper.startswith("CREATE TABLE") or upper.startswith("CREATE INDEX")):
            raise ValueError(f"Plugin '{plugin_name}' DDL contains disallowed statement: {stmt[:60]}")
        table_match = re.search(r'(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', stmt, re.IGNORECASE)
        if table_match:
            table_name = table_match.group(1)
            if not table_name.startswith(f"{plugin_name}_"):
                raise ValueError(
                    f"Plugin '{plugin_name}' table '{table_name}' must be prefixed with '{plugin_name}_'"
                )


def discover_plugins() -> list[PluginBase]:
    """Scan pa/plugins/ subdirectories for PluginBase subclasses."""
    plugins_dir = Path(__file__).parent
    found: list[PluginBase] = []

    for importer, modname, ispkg in pkgutil.iter_modules([str(plugins_dir)]):
        if not ispkg:
            continue
        try:
            module = importlib.import_module(f"pa.plugins.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase
                    and attr.name
                ):
                    found.append(attr())
        except Exception:
            continue

    return sorted(found, key=lambda p: p.name)


@dataclass
class NLHandler:
    """A natural language intent handler registered by a plugin."""
    keywords: list[str]
    handler: Callable
    description: str = ""
    priority: int = 0  # higher = checked first (used as keyword fallback tiebreak)
    intent_id: str = ""  # e.g. "finance.balance" — used by AI intent classifier
    examples: list[str] = field(default_factory=list)  # seed utterances for classifier


# Monkey-patch nl_handlers onto PluginBase so existing plugins get it free
PluginBase.nl_handlers = lambda self: []