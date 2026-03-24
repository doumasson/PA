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


def format_trend_summary(monthly: list[dict[str, Any]], detail_month: str | None = None,
                         categories: list[dict[str, Any]] | None = None) -> str:
    if not monthly:
        return "No transaction history available for trends."
    lines = ["**Monthly Spending Trends**\n"]
    prev_spending = None
    for m in monthly:
        spending = m["spending"]
        income = m["income"]
        change = ""
        if prev_spending and prev_spending > 0:
            pct = ((spending - prev_spending) / prev_spending) * 100
            arrow = "📈" if pct > 0 else "📉"
            change = f" {arrow} {pct:+.0f}%"
        surplus = income - spending
        surplus_str = f"  (+${surplus:,.0f} surplus)" if surplus > 0 else f"  (-${abs(surplus):,.0f} deficit)" if surplus < 0 else ""
        lines.append(f"  {m['month']}: ${spending:,.0f} spent / ${income:,.0f} earned{change}{surplus_str}")
        prev_spending = spending

    if detail_month and categories:
        lines.append(f"\n**{detail_month} Breakdown**\n")
        for c in categories:
            lines.append(f"  {c['category']}: ${c['total']:,.2f} ({c['txn_count']} txns)")

    return "\n".join(lines)


def format_bills_summary(bills: list[dict[str, Any]]) -> str:
    if not bills:
        return "No bills tracked yet. Use /bill_add to add one."
    unpaid = [b for b in bills if not b.get("paid_this_cycle")]
    paid = [b for b in bills if b.get("paid_this_cycle")]
    unpaid.sort(key=lambda b: b.get("due_date") or "9999-99-99")
    lines = ["**Upcoming Bills**\n"]
    total_upcoming = 0.0
    for b in unpaid:
        amt_str = f"${b['amount']:,.2f}" if b.get("amount") else "amount TBD"
        due_str = f"due {b['due_date']}" if b.get("due_date") else "no due date"
        auto = " (auto-pay)" if b.get("auto_pay") else ""
        lines.append(f"  {b['name']}: {amt_str} — {due_str}{auto}")
        if b.get("amount"):
            total_upcoming += b["amount"]
    if total_upcoming > 0:
        lines.append(f"\n  **Total upcoming: ${total_upcoming:,.2f}**")
    if paid:
        lines.append("\n**Paid This Cycle**\n")
        for b in paid:
            amt_str = f"${b['amount']:,.2f}" if b.get("amount") else ""
            lines.append(f"  ~{b['name']}~ {amt_str}")
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
