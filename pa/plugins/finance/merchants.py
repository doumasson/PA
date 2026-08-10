"""Merchant categorization with persistent learning.
Learns from corrections and builds a knowledge base over time."""
from __future__ import annotations


# Known merchant patterns — baseline knowledge, overridden by DB
_BUILTIN = {
    # Liquor
    "hilltop liq": "Liquor", "fizz liquor": "Liquor", "total wine": "Liquor",
    "liquor": "Liquor", "wine & spirits": "Liquor", "bevmo": "Liquor",
    # Gas / Convenience
    "maverik": "Gas", "7-eleven": "Gas/Convenience", "loaf n jug": "Gas",
    "shell": "Gas", "chevron": "Gas", "exxon": "Gas", "bp ": "Gas",
    "circle k": "Gas/Convenience", "kum & go": "Gas/Convenience",
    "conoco": "Gas", "sinclair": "Gas", "murphy": "Gas", "phillips 66": "Gas",
    "speedway": "Gas/Convenience", "wawa": "Gas/Convenience",
    "quiktrip": "Gas/Convenience", "qt ": "Gas/Convenience",
    # Groceries
    "instacart": "Groceries", "king soopers": "Groceries", "kroger": "Groceries",
    "safeway": "Groceries", "albertson": "Groceries", "aldi": "Groceries",
    "costco": "Groceries", "sam's club": "Groceries", "trader joe": "Groceries",
    "whole foods": "Groceries", "sprouts": "Groceries", "natural grocer": "Groceries",
    "grocery": "Groceries", "food lion": "Groceries", "publix": "Groceries",
    "heb ": "Groceries", "h-e-b": "Groceries", "winco": "Groceries",
    # Shopping
    "walmart": "Shopping", "target": "Shopping", "amazon": "Shopping/Amazon",
    "best buy": "Shopping/Electronics", "home depot": "Shopping/Home",
    "lowes": "Shopping/Home", "lowe's": "Shopping/Home",
    "ikea": "Shopping/Home", "dollar tree": "Shopping", "dollar general": "Shopping",
    "ross": "Shopping/Clothing", "marshalls": "Shopping/Clothing",
    "tjx": "Shopping/Clothing", "tj maxx": "Shopping/Clothing",
    "kohls": "Shopping/Clothing", "kohl's": "Shopping/Clothing",
    "old navy": "Shopping/Clothing", "nike": "Shopping/Clothing",
    "walgreens": "Shopping/Pharmacy", "cvs": "Shopping/Pharmacy",
    # Food / Dining
    "grubhub": "Food/Delivery", "doordash": "Food/Delivery",
    "uber eats": "Food/Delivery", "postmates": "Food/Delivery",
    "chipotle": "Food/Dining", "mcdonald": "Food/Dining",
    "domino": "Food/Dining", "chick-fil": "Food/Dining",
    "taco bell": "Food/Dining", "wendy": "Food/Dining",
    "subway": "Food/Dining", "panda express": "Food/Dining",
    "papa john": "Food/Dining", "pizza hut": "Food/Dining",
    "five guys": "Food/Dining", "in-n-out": "Food/Dining",
    "sonic": "Food/Dining", "popeye": "Food/Dining",
    "arby": "Food/Dining", "jack in the box": "Food/Dining",
    "burger king": "Food/Dining", "kfc": "Food/Dining",
    "panera": "Food/Dining", "olive garden": "Food/Dining",
    "applebee": "Food/Dining", "chili's": "Food/Dining", "chilis": "Food/Dining",
    "ihop": "Food/Dining", "denny": "Food/Dining",
    "waffle house": "Food/Dining", "cracker barrel": "Food/Dining",
    "restaurant": "Food/Dining", "cafe": "Food/Dining",
    # Coffee
    "starbucks": "Food/Coffee", "dutch bros": "Food/Coffee",
    "dunkin": "Food/Coffee", "coffee": "Food/Coffee",
    # Software / AI
    "claude.ai": "Software/AI", "anthropic": "Software/AI",
    "openai": "Software/AI", "github": "Software/Dev",
    "digitalocean": "Software/Cloud", "aws ": "Software/Cloud",
    "google cloud": "Software/Cloud", "azure": "Software/Cloud",
    "heroku": "Software/Cloud",
    # Subscriptions
    "peacock": "Subscription/Streaming", "netflix": "Subscription/Streaming",
    "hulu": "Subscription/Streaming", "disney": "Subscription/Streaming",
    "hbo": "Subscription/Streaming", "paramount": "Subscription/Streaming",
    "apple tv": "Subscription/Streaming", "youtube premium": "Subscription/Streaming",
    "spotify": "Subscription/Music", "apple music": "Subscription/Music",
    "amazon prime": "Subscription/Amazon", "audible": "Subscription/Amazon",
    "google storage": "Subscription/Cloud", "icloud": "Subscription/Cloud",
    "dropbox": "Subscription/Cloud",
    "24hr fitness": "Subscription/Gym", "24 hour fitness": "Subscription/Gym",
    "planet fitness": "Subscription/Gym", "la fitness": "Subscription/Gym",
    "twitch": "Subscription/Streaming",
    "xbox": "Subscription/Gaming", "playstation": "Subscription/Gaming",
    "nintendo": "Subscription/Gaming",
    # Kids
    "greenlight": "Kids/Allowance",
    # Bills / Utilities
    "xfinity": "Bills/Internet", "comcast": "Bills/Internet",
    "centurylink": "Bills/Internet", "att ": "Bills/Phone",
    "t-mobile": "Bills/Phone", "verizon": "Bills/Phone",
    "core electric": "Bills/Electric", "xcel energy": "Bills/Electric",
    "vivint": "Bills/Security", "adt ": "Bills/Security",
    "progressive": "Bills/Insurance", "state farm": "Bills/Insurance",
    "geico": "Bills/Insurance", "allstate": "Bills/Insurance",
    "usaa": "Bills/Insurance",
    "planet home": "Bills/Mortgage", "mortgage": "Bills/Mortgage",
    "nelnet": "Bills/Student Loans", "navient": "Bills/Student Loans",
    "great lakes": "Bills/Student Loans", "mohela": "Bills/Student Loans",
    # Cash Advance
    "cleo": "Cash Advance", "brigit": "Cash Advance",
    "dave": "Cash Advance", "earnin": "Cash Advance",
    # Transfers
    "venmo": "Transfer/Venmo", "zelle": "Transfer/Zelle",
    "paypal": "Transfer/PayPal", "cash app": "Transfer/CashApp",
    "inst xfer": "Transfer", "transfer": "Transfer",
    # Income
    "stolle": "Income/Payroll", "payroll": "Income/Payroll",
    "direct dep": "Income/Payroll", "direct deposit": "Income/Payroll",
    "irs treas": "Income/Tax Refund",
    # Recreation
    "golf": "Recreation/Golf", "saddler": "Recreation/Golf",
    "topgolf": "Recreation/Golf",
    # Medical
    "adventhealth": "Medical", "hospital": "Medical",
    "urgent care": "Medical", "pharmacy": "Medical",
    "doctor": "Medical", "dental": "Medical", "dentist": "Medical",
    "optometrist": "Medical", "vision": "Medical",
    # Auto
    "jiffy lube": "Auto/Maintenance", "autozone": "Auto/Parts",
    "o'reilly": "Auto/Parts", "tire": "Auto/Tires",
    "carwash": "Auto/Wash", "car wash": "Auto/Wash",
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
