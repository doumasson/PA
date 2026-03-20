from pathlib import Path
from pa.plugins import PluginBase, Command
from pa.plugins.finance.commands import (
    handle_balance, handle_debt, handle_due, handle_spending,
    handle_plan, handle_scrape, handle_schedule, handle_backup,
)
from pa.plugins.finance.jobs import get_finance_jobs
from pa.plugins.finance.tier_patterns import FINANCE_TIER_PATTERNS

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class FinancePlugin(PluginBase):
    name = "finance"
    description = "Financial tracking, analysis, and debt management"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="balance", description="Account balances", handler=handle_balance),
            Command(name="debt", description="Debt summary", handler=handle_debt),
            Command(name="due", description="Upcoming payments", handler=handle_due),
            Command(name="spending", description="Spending breakdown", handler=handle_spending, aliases=["spend"]),
            Command(name="plan", description="Debt payoff plan (AI)", handler=handle_plan),
            Command(name="scrape", description="Force a scrape", handler=handle_scrape),
            Command(name="schedule", description="View schedule", handler=handle_schedule),
            Command(name="backup", description="Backup database", handler=handle_backup),
        ]

    def jobs(self) -> list:
        return get_finance_jobs()

    def tier_patterns(self) -> dict[str, list[str]]:
        return FINANCE_TIER_PATTERNS

    def system_prompt_fragment(self) -> str:
        return (
            "Financial analysis module active. You have access to bank accounts, "
            "credit cards, and transaction data. Help the user understand their spending, "
            "track debt payoff progress, and make smart financial decisions. Be specific "
            "with numbers. Flag concerning patterns proactively."
        )
