import pytest
from pa.plugins import PluginBase, Command, Job, AppContext, discover_plugins

def test_plugin_base_defaults():
    p = PluginBase()
    assert p.schema_sql() == ""
    assert p.commands() == []
    assert p.jobs() == []
    assert p.tier_patterns() == {}
    assert p.system_prompt_fragment() == ""

def test_command_dataclass():
    cmd = Command(name="test", description="A test command", handler=lambda: None)
    assert cmd.name == "test"
    assert cmd.aliases == []

def test_job_dataclass():
    job = Job(name="test_job", handler=lambda: None, trigger="cron", kwargs={"hour": 6})
    assert job.trigger == "cron"
    assert job.kwargs == {"hour": 6}

def test_app_context_fields():
    ctx = AppContext(store=1, vault=2, brain=3, bot=4, scheduler=5, config=6)
    assert ctx.store == 1
    assert ctx.config == 6

class FakePlugin(PluginBase):
    name = "fake"
    description = "A test plugin"
    def commands(self) -> list:
        return [Command(name="hello", description="Say hi", handler=lambda: "hi")]

def test_subclass_override():
    p = FakePlugin()
    assert p.name == "fake"
    assert len(p.commands()) == 1
    assert p.schema_sql() == ""

def test_discover_plugins_returns_list():
    plugins = discover_plugins()
    assert isinstance(plugins, list)
