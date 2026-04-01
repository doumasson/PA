from pathlib import Path
from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.finance.nl import handle_finance_nl, handle_affordability_nl
from pa.plugins.finance.advisor_commands import handle_advisor, handle_debt_update, handle_advisor_nl
from pa.plugins.finance.commands import (
    handle_balance, handle_bill_add, handle_bill_paid, handle_bills,
    handle_budget, handle_budget_set, handle_budget_del,
    handle_debt, handle_due, handle_forecast, handle_spending, handle_trend,
    handle_plan, handle_recat, handle_scrape, handle_schedule, handle_backup,
)
from pa.plugins.finance.jobs import get_finance_jobs
from pa.plugins.finance.tier_patterns import FINANCE_TIER_PATTERNS

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_ADVISOR_SCHEMA_PATH = Path(__file__).parent / "advisor_schema.sql"


class FinancePlugin(PluginBase):
    name = "finance"
    description = "Financial tracking, analysis, debt management and Bart (financial advisor)"
    version = "0.2.0"

    def schema_sql(self) -> str:
        base = _SCHEMA_PATH.read_text(encoding="utf-8")
        advisor = _ADVISOR_SCHEMA_PATH.read_text(encoding="utf-8") if _ADVISOR_SCHEMA_PATH.exists() else ""
        return base + advisor

    def commands(self) -> list[Command]:
        return [
            Command(name="balance", description="Account balances", handler=handle_balance),
            Command(name="debt", description="Debt summary", handler=handle_debt),
            Command(name="due", description="Upcoming payments", handler=handle_due),
            Command(name="spending", description="Spending breakdown", handler=handle_spending, aliases=["spend"]),
            Command(name="trend", description="Monthly spending trends", handler=handle_trend, aliases=["trends"]),
            Command(name="plan", description="Debt payoff plan (AI)", handler=handle_plan),
            Command(name="scrape", description="Force a scrape", handler=handle_scrape),
            Command(name="schedule", description="View schedule", handler=handle_schedule),
            Command(name="backup", description="Backup database", handler=handle_backup),
            Command(name="advisor", description="Financial advisor", handler=handle_advisor),
            Command(name="debt_add", description="Add/update a debt manually", handler=handle_debt_update),
            Command(name="bills", description="View upcoming bills", handler=handle_bills),
            Command(name="bill_add", description="Add a recurring bill", handler=handle_bill_add),
            Command(name="bill_paid", description="Mark bill as paid", handler=handle_bill_paid),
            Command(name="forecast", description="Cash flow forecast", handler=handle_forecast, aliases=["cashflow"]),
            Command(name="budget", description="Budget vs actual spending", handler=handle_budget),
            Command(name="budget_set", description="Set a category budget", handler=handle_budget_set),
            Command(name="budget_del", description="Remove a budget", handler=handle_budget_del),
            Command(name="recat", description="Re-categorize uncategorized transactions", handler=handle_recat),
        ]

    def jobs(self) -> list:
        return get_finance_jobs()

    def tier_patterns(self) -> dict[str, list[str]]:
        return FINANCE_TIER_PATTERNS

    def nl_handlers(self) -> list:
        advisor_keywords = [
            "bart", "hey bart",
            "financial situation", "debt plan", "get out of debt", "what should i do",
            "financial advice", "advise me", "help me", "my finances", "overall",
            "complete picture", "everything", "total debt", "how bad", "what do i owe",
            "plan", "strategy", "priority", "mortgage", "student loan",
            "collections", "charged off", "settlement", "negotiate", "pay off",
            "where do i stand", "how much do i owe", "what should i pay",
            "analyze my", "where can i save", "subscription",
        ]
        return [
            NLHandler(keywords=advisor_keywords, handler=handle_advisor_nl, priority=20),
            NLHandler(keywords=["is a ", "is an ", "is not ", "categorize ", "that's actually", "isnt a"], handler=handle_finance_nl, priority=18),
            NLHandler(keywords=["can i afford", "should i buy", "do i have enough", "enough for", "enough to buy"], handler=handle_affordability_nl, priority=15),
            NLHandler(keywords=["i paid", "i just paid", "paid off", "made a payment", "balance is now", "new balance"], handler=handle_finance_nl, priority=15),
            NLHandler(keywords=["balance", "how much", "account", "checking", "savings", "credit card"], handler=handle_finance_nl, priority=10),
            NLHandler(keywords=["debt", "owe", "loan", "payoff"], handler=handle_finance_nl, priority=10),
            NLHandler(keywords=["spending", "spent", "expenses", "transactions", "charges", "subscription"], handler=handle_finance_nl, priority=10),
            NLHandler(keywords=["due", "payment", "bill", "upcoming"], handler=handle_finance_nl, priority=10),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Bart is Steven's financial advisor. Address him as Bart or 'hey Bart' for financial questions. "
            "You have access to Steven's real bank accounts, "
            "credit cards, and transaction data via Teller API. "
            "Steven is in financial difficulty — be honest, specific, and actionable. "
            "Never give generic advice. Use /advisor for full financial analysis. "
            "Steven can say 'I paid X on Y' to record payments."
        )
