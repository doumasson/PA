from typing import Any
from collections import defaultdict

_DEBT_TYPES = {"credit_card", "mortgage", "loan"}


def format_balance_summary(balances: list[dict[str, Any]]) -> str:
    if not balances:
        return "No account data available."
    lines = ["**Account Balances**\n"]
    for b in balances:
        line = f"  {b['name']}: ${b['balance']:,.2f}"
        if b.get("credit_limit"):
            line += f" / ${b['credit_limit']:,.2f} limit"
        lines.append(line)
    return "\n".join(lines)


def format_debt_summary(balances: list[dict[str, Any]]) -> str:
    debt_accounts = [b for b in balances if b.get("type") in _DEBT_TYPES]
    if not debt_accounts:
        return "No debt accounts found."
    total = sum(b["balance"] for b in debt_accounts)
    lines = ["**Debt Summary**\n"]
    for b in sorted(debt_accounts, key=lambda x: x["balance"], reverse=True):
        line = f"  {b['name']}: ${b['balance']:,.2f}"
        if b.get("interest_rate"):
            line += f" @ {b['interest_rate']*100:.1f}% APR"
        lines.append(line)
    lines.append(f"\n  **Total Debt: ${total:,.2f}**")
    return "\n".join(lines)


def format_due_summary(balances: list[dict[str, Any]]) -> str:
    due_accounts = [b for b in balances if b.get("due_date") and b.get("minimum_payment")]
    if not due_accounts:
        return "No upcoming payments found."
    lines = ["**Upcoming Payments**\n"]
    for b in sorted(due_accounts, key=lambda x: x["due_date"]):
        lines.append(f"  {b['name']}: ${b['minimum_payment']:,.2f} due {b['due_date']}")
    return "\n".join(lines)


def format_spending_summary(transactions: list[dict[str, Any]], period: str) -> str:
    if not transactions:
        return f"No transactions found for {period}."
    by_category: dict[str, float] = defaultdict(float)
    for t in transactions:
        cat = t.get("category") or "uncategorized"
        by_category[cat] += abs(t["amount"])
    total = sum(by_category.values())
    lines = [f"**Spending for {period}**\n"]
    for cat, amount in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {cat}: ${amount:,.2f}")
    lines.append(f"\n  **Total: ${total:,.2f}**")
    return "\n".join(lines)
