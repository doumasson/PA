"""Merchant categorization with persistent learning.
Learns from corrections and builds a knowledge base over time."""
from __future__ import annotations


# Known merchant patterns — baseline knowledge, overridden by DB
_BUILTIN = {
    "hilltop liquor": "Liquor",
    "fizz liquor": "Liquor",
    "total wine": "Liquor",
    "maverik": "Gas/Convenience",
    "7-eleven": "Gas/Convenience",
    "loaf n jug": "Gas/Convenience",
    "shell": "Gas/Convenience",
    "instacart": "Groceries",
    "king soopers": "Groceries",
    "walmart": "Groceries/Shopping",
    "target": "Shopping",
    "amazon": "Shopping/Amazon",
    "grubhub": "Food/Delivery",
    "doordash": "Food/Delivery",
    "uber eats": "Food/Delivery",
    "chipotle": "Food/Dining",
    "mcdonald": "Food/Dining",
    "domino": "Food/Dining",
    "chick-fil": "Food/Dining",
    "starbucks": "Food/Coffee",
    "claude.ai": "Software/Claude AI",
    "anthropic": "Software/Claude AI",
    "openai": "Software/AI",
    "peacock": "Subscription/Streaming",
    "netflix": "Subscription/Streaming",
    "hulu": "Subscription/Streaming",
    "disney": "Subscription/Streaming",
    "spotify": "Subscription/Music",
    "amazon prime": "Subscription/Amazon Prime",
    "google storage": "Subscription/Cloud",
    "24hr fitness": "Subscription/Gym",
    "24 hour fitness": "Subscription/Gym",
    "planet fitness": "Subscription/Gym",
    "twitch": "Subscription/Streaming",
    "greenlight": "Kids/Allowance",
    "xfinity": "Bills/Internet",
    "comcast": "Bills/Internet",
    "core electric": "Bills/Electric",
    "vivint": "Bills/Security",
    "planet home": "Bills/Mortgage",
    "nelnet": "Bills/Student Loans",
    "cleo": "Cash Advance",
    "brigit": "Cash Advance",
    "dave": "Cash Advance",
    "earnin": "Cash Advance",
    "venmo": "Transfer/Venmo",
    "zelle": "Transfer/Zelle",
    "paypal": "Transfer/PayPal",
    "stolle": "Income/Payroll",
}


async def get_category(store, description: str) -> str | None:
    """Look up a merchant category. Checks DB first (learned), then builtins."""
    desc_lower = description.lower()

    # Check DB learned categories first (user corrections override everything)
    rows = await store.fetchall(
        "SELECT pattern, category FROM finance_merchant_categories ORDER BY confidence DESC, hit_count DESC"
    )
    for row in rows:
        if row['pattern'].lower() in desc_lower:
            # Bump hit count
            await store.execute(
                "UPDATE finance_merchant_categories SET hit_count = hit_count + 1 WHERE pattern = ?",
                (row['pattern'],)
            )
            return row['category']

    # Fall back to builtins
    for pattern, category in _BUILTIN.items():
        if pattern in desc_lower:
            return category

    return None


async def learn_category(store, pattern: str, category: str, source: str = "user") -> None:
    """Save a merchant→category mapping. User corrections have confidence 1.0, AI guesses 0.5."""
    confidence = 1.0 if source == "user" else 0.5
    await store.execute(
        """INSERT INTO finance_merchant_categories (pattern, category, confidence, source)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(pattern) DO UPDATE SET
           category=excluded.category, confidence=excluded.confidence, source=excluded.source""",
        (pattern.lower(), category, confidence, source)
    )


async def categorize_transactions(store, transactions: list[dict]) -> list[dict]:
    """Add category to a list of transactions using the learning system."""
    for t in transactions:
        cat = await get_category(store, t.get('description', ''))
        if cat:
            t['learned_category'] = cat
        else:
            t['learned_category'] = None
    return transactions


async def get_all_learned(store) -> list[dict]:
    """Get all learned merchant categories for display."""
    return await store.fetchall(
        "SELECT pattern, category, source, hit_count FROM finance_merchant_categories ORDER BY hit_count DESC"
    )
