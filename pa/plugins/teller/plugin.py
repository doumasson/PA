from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.teller.commands import handle_sync, handle_teller_nl
from pa.plugins.teller.jobs import get_teller_jobs


class TellerPlugin(PluginBase):
    name = "teller"
    description = "Real-time bank data via Teller API"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return ""

    def commands(self) -> list:
        return [
            Command(name="sync", description="Sync bank accounts", handler=handle_sync),
        ]

    def jobs(self) -> list:
        return get_teller_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=["sync", "update accounts", "refresh balance", "pull transactions"],
                handler=handle_teller_nl,
                priority=15,
            ),
            NLHandler(
                keywords=["yesterday", "morning update", "how much did i spend", "last week", "weekly", "7 days", "spent at", "spend at", "spending at", "how much at", "how often at"],
                handler=handle_teller_nl,
                priority=15,
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Teller bank integration active. Wells Fargo is connected for real-time "
            "balances and transactions. Use /sync to refresh data."
        )
