"""Plugin contract v2.

Plugins are validated at the door: api_version must be 2, and every handler
signature is checked with inspect at discovery time. A broken plugin is a
loud boot error, never a silent no-show (config `plugins.ignore_broken`
softens that to a logged skip in emergencies).

Handler conventions (enforced):
  command handler: async (ctx, update, context) -> str
  NL handler:      async (ctx, text, update) -> str
  job handler:     async (ctx) -> None
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PluginError(ValueError):
    """A plugin failed validation at discovery/registration time."""


@dataclass
class Command:
    """A bot command registered by a plugin."""
    name: str
    description: str
    handler: Callable          # async (ctx, update, context) -> str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Job:
    """A scheduled job registered by a plugin."""
    name: str
    handler: Callable          # async (ctx) -> None
    trigger: str               # "interval" | "cron"
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class NLHandler:
    """A natural language intent handler registered by a plugin."""
    keywords: list[str]
    handler: Callable          # async (ctx, text, update) -> str
    description: str = ""
    priority: int = 0
    intent_id: str = ""        # e.g. "finance.balance"
    examples: list[str] = field(default_factory=list)


@dataclass
class Callback:
    """An inline-button callback handler registered by a plugin.

    Matches callback_query data of the form "<prefix>:<payload>"."""
    prefix: str                # e.g. "repair" matches "repair:approve:42"
    handler: Callable          # async (ctx, update, payload) -> str | None
    description: str = ""


@dataclass
class AppContext:
    """Typed context passed to plugins. Access services ONLY through this."""
    store: Any
    vault: Any
    brain: Any
    bot: Any
    scheduler: Any
    config: Any
    profile: Any = None
    learning: Any = None
    ledger: Any = None
    stats: Any = None


class PluginBase:
    """Base class for all Albus plugins. Subclass and override what you need."""

    api_version: int = 2
    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def schema_sql(self) -> str:
        return ""

    def commands(self) -> list[Command]:
        return []

    def jobs(self) -> list[Job]:
        return []

    def nl_handlers(self) -> list[NLHandler]:
        return []

    def callbacks(self) -> list[Callback]:
        return []

    def system_prompt_fragment(self) -> str:
        return ""

    async def on_startup(self, ctx: AppContext) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


# -- validation ---------------------------------------------------------------


def _validate_ddl(sql: str, plugin_name: str) -> None:
    """Only CREATE TABLE/INDEX, all names prefixed with '{plugin}_'."""
    for statement in sql.split(";"):
        stmt = statement.strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if not (
            upper.startswith("CREATE TABLE")
            or upper.startswith("CREATE INDEX")
            or upper.startswith("CREATE VIRTUAL TABLE")  # FTS5 search tables
        ):
            raise PluginError(
                f"Plugin '{plugin_name}' DDL contains disallowed statement: {stmt[:60]}"
            )
        m = re.search(r"(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", stmt, re.IGNORECASE)
        if m and not m.group(1).startswith(f"{plugin_name}_"):
            raise PluginError(
                f"Plugin '{plugin_name}' table '{m.group(1)}' must be prefixed "
                f"with '{plugin_name}_'"
            )


def _check_handler(fn: Callable, expected_params: int, what: str, plugin: str) -> None:
    if not inspect.iscoroutinefunction(fn):
        raise PluginError(f"Plugin '{plugin}': {what} must be an async function")
    params = [
        p for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if len(params) != expected_params:
        names = ", ".join(p.name for p in params)
        raise PluginError(
            f"Plugin '{plugin}': {what} has signature ({names}) — "
            f"expected exactly {expected_params} positional params "
            f"(commands: ctx, update, context / NL: ctx, text, update / jobs: ctx)"
        )


def validate_plugin(plugin: PluginBase) -> None:
    """Raise PluginError if the plugin violates the v2 contract."""
    if getattr(plugin, "api_version", 1) != 2:
        raise PluginError(
            f"Plugin '{plugin.name}' declares api_version="
            f"{getattr(plugin, 'api_version', 1)}; v2 required. "
            "See docs/superpowers/specs/2026-07-02-v2-core-design.md for migration."
        )
    _validate_ddl(plugin.schema_sql(), plugin.name)
    for cmd in plugin.commands():
        _check_handler(cmd.handler, 3, f"command /{cmd.name}", plugin.name)
    for nl in plugin.nl_handlers():
        _check_handler(nl.handler, 3, f"NL handler '{nl.intent_id or nl.description}'", plugin.name)
    for job in plugin.jobs():
        _check_handler(job.handler, 1, f"job '{job.name}'", plugin.name)
    for cb in plugin.callbacks():
        _check_handler(cb.handler, 3, f"callback '{cb.prefix}'", plugin.name)


# -- discovery ----------------------------------------------------------------


def discover_plugins(
    enabled: list[str] | None = None, ignore_broken: bool = False
) -> list[PluginBase]:
    """Scan pa/plugins/ for v2 plugins and validate each one.

    enabled: allowlist of plugin names (None = all found).
    ignore_broken: log-and-skip invalid plugins instead of raising.
    """
    plugins_dir = Path(__file__).parent
    found: list[PluginBase] = []

    for _, modname, ispkg in pkgutil.iter_modules([str(plugins_dir)]):
        if not ispkg:
            continue
        if enabled is not None and modname not in enabled:
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
                    instance = attr()
                    validate_plugin(instance)
                    found.append(instance)
        except Exception as e:
            if ignore_broken:
                logger.exception(
                    "Plugin %r failed to load and will be UNAVAILABLE", modname
                )
                continue
            raise PluginError(f"Plugin '{modname}' failed to load: {e}") from e

    return sorted(found, key=lambda p: p.name)
