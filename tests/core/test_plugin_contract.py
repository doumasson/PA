import pytest

from pa.plugins import (
    Command,
    Job,
    NLHandler,
    PluginBase,
    PluginError,
    _validate_ddl,
    discover_plugins,
    validate_plugin,
)


async def _cmd(ctx, update, context) -> str:
    return "ok"


async def _nl(ctx, text, update) -> str:
    return "ok"


async def _job(ctx) -> None:
    pass


class GoodPlugin(PluginBase):
    name = "good"
    description = "A well-behaved v2 plugin"

    def schema_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS good_items (id INTEGER PRIMARY KEY);\n"
            "CREATE INDEX IF NOT EXISTS good_items_idx ON good_items(id);"
        )

    def commands(self) -> list[Command]:
        return [Command(name="hello", description="Say hi", handler=_cmd)]

    def nl_handlers(self) -> list[NLHandler]:
        return [NLHandler(keywords=["hi"], handler=_nl, intent_id="good.hi")]

    def jobs(self) -> list[Job]:
        return [Job(name="tick", handler=_job, trigger="interval", kwargs={"minutes": 5})]


def test_good_plugin_passes():
    validate_plugin(GoodPlugin())  # must not raise


def test_plugin_base_defaults_pass():
    class Bare(PluginBase):
        name = "bare"

    validate_plugin(Bare())


def test_api_version_1_rejected():
    class Old(GoodPlugin):
        name = "old"
        api_version = 1

    with pytest.raises(PluginError, match="api_version=1; v2 required"):
        validate_plugin(Old())


def test_missing_api_version_defaults_pass():
    # PluginBase pins api_version = 2, so plain subclasses are fine.
    assert PluginBase.api_version == 2


def test_sync_command_handler_rejected():
    class Sync(PluginBase):
        name = "sync"

        def commands(self) -> list[Command]:
            return [Command(name="bad", description="", handler=lambda ctx, u, c: "hi")]

    with pytest.raises(PluginError, match="must be an async function"):
        validate_plugin(Sync())


def test_sync_nl_handler_rejected():
    class Sync(PluginBase):
        name = "sync"

        def nl_handlers(self) -> list[NLHandler]:
            return [NLHandler(keywords=[], handler=lambda ctx, t, u: "hi", intent_id="sync.x")]

    with pytest.raises(PluginError, match="must be an async function"):
        validate_plugin(Sync())


def test_command_wrong_arity_rejected():
    async def two_args(ctx, update) -> str:
        return "hi"

    class Arity(PluginBase):
        name = "arity"

        def commands(self) -> list[Command]:
            return [Command(name="bad", description="", handler=two_args)]

    with pytest.raises(PluginError, match="expected exactly 3 positional params"):
        validate_plugin(Arity())


def test_job_wrong_arity_rejected():
    async def no_args() -> None:
        pass

    class Arity(PluginBase):
        name = "arity"

        def jobs(self) -> list[Job]:
            return [Job(name="bad", handler=no_args, trigger="interval")]

    with pytest.raises(PluginError, match="expected exactly 1 positional param"):
        validate_plugin(Arity())


def test_keyword_only_params_do_not_count():
    async def kw_ok(ctx, update, context, *, extra: int = 0) -> str:
        return "hi"

    class Kw(PluginBase):
        name = "kw"

        def commands(self) -> list[Command]:
            return [Command(name="ok", description="", handler=kw_ok)]

    validate_plugin(Kw())  # must not raise


# -- DDL rules ---------------------------------------------------------------


def test_bad_ddl_prefix_rejected():
    class BadPrefix(PluginBase):
        name = "mine"

        def schema_sql(self) -> str:
            return "CREATE TABLE other_items (id INTEGER PRIMARY KEY);"

    with pytest.raises(PluginError, match="must be prefixed"):
        validate_plugin(BadPrefix())


def test_disallowed_ddl_statement_rejected():
    with pytest.raises(PluginError, match="disallowed statement"):
        _validate_ddl("DROP TABLE core_ledger;", "mine")


def test_validate_ddl_accepts_prefixed_create():
    _validate_ddl(
        "CREATE TABLE IF NOT EXISTS mine_things (id INTEGER PRIMARY KEY);"
        "CREATE INDEX mine_things_idx ON mine_things(id);",
        "mine",
    )  # must not raise


def test_validate_ddl_rejects_unprefixed_index():
    with pytest.raises(PluginError, match="must be prefixed"):
        _validate_ddl("CREATE INDEX idx_things ON mine_things(id);", "mine")


def test_validate_ddl_empty_ok():
    _validate_ddl("", "mine")


# -- discovery ------------------------------------------------------------------


def test_discover_plugins_empty_allowlist():
    assert discover_plugins(enabled=[]) == []


def test_discover_plugins_unknown_name_in_allowlist():
    assert discover_plugins(enabled=["no_such_plugin"]) == []
