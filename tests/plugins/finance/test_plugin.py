# tests/plugins/finance/test_plugin.py
from pa.plugins.finance.plugin import FinancePlugin


def test_plugin_identity():
    p = FinancePlugin()
    assert p.name == "finance"
    assert p.description


def test_plugin_has_schema():
    p = FinancePlugin()
    ddl = p.schema_sql()
    assert "finance_accounts" in ddl
    assert "finance_transactions" in ddl


def test_plugin_has_commands():
    p = FinancePlugin()
    cmds = p.commands()
    cmd_names = {c.name for c in cmds}
    assert "balance" in cmd_names
    assert "debt" in cmd_names
    assert "spending" in cmd_names


def test_plugin_has_jobs():
    p = FinancePlugin()
    jobs = p.jobs()
    job_names = {j.name for j in jobs}
    assert "bank_balance" in job_names
    assert "cc_balance" in job_names


def test_plugin_has_tier_patterns():
    p = FinancePlugin()
    patterns = p.tier_patterns()
    assert "fast" in patterns
    assert "deep" in patterns


def test_plugin_has_system_prompt():
    p = FinancePlugin()
    fragment = p.system_prompt_fragment()
    assert "financial" in fragment.lower()
