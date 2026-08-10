"""One-time cleanup: delete scraper-era legacy rows that duplicate a Teller-feed row.

The Apr-2026 scraper wrote different description wording than Teller, so
normalize_merchant equality (reconcile_teller_phantoms) missed these twins.
Match instead on account + ABS(amount) + date within 3 days + at least one
shared merchant word. Greedy one-to-one: each teller row claims at most one
legacy row, closest date first.

Usage:  python tools/scraper_twin_cleanup.py [--apply]
"""
import asyncio
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pa.core.store import Store  # noqa: E402

GENERIC = {"PURCHASE", "AUTHORIZED", "ON", "RECURRING", "PAYMENT", "CARD",
           "CO", "CA", "WA", "UT", "NY", "INSTANT", "PMT", "FROM", "RETURN",
           "COM", "BILL", "AMZN"}


def words(desc: str) -> set[str]:
    return set(re.sub(r"[^A-Z ]", " ", desc.upper()).split()) - GENERIC


async def main(apply: bool) -> None:
    store = Store(Path("/home/admin/pa/data/pa.db"))
    await store.connect()
    try:
        d0 = (await store.fetchone(
            "SELECT MIN(date) AS d FROM finance_transactions "
            "WHERE teller_id IS NOT NULL AND account_id = 1"))["d"]
        teller = await store.fetchall(
            "SELECT id, date, description, amount FROM finance_transactions "
            "WHERE account_id = 1 AND teller_id IS NOT NULL ORDER BY date")
        legacy = await store.fetchall(
            "SELECT id, date, description, amount FROM finance_transactions "
            "WHERE account_id = 1 AND teller_id IS NULL AND date >= ? ORDER BY date",
            (d0,))

        pairs = []
        for t in teller:
            for l in legacy:
                if abs(abs(l["amount"]) - abs(t["amount"])) > 0.005:
                    continue
                gap = abs((datetime.date.fromisoformat(l["date"])
                           - datetime.date.fromisoformat(t["date"])).days)
                if gap > 3:
                    continue
                if not (words(l["description"]) & words(t["description"])):
                    continue
                pairs.append((gap, l, t))
        pairs.sort(key=lambda p: p[0])

        doomed: dict[int, str] = {}
        used_teller: set[int] = set()
        for gap, l, t in pairs:
            if l["id"] in doomed or t["id"] in used_teller:
                continue
            doomed[l["id"]] = (
                f"{l['date']} {l['description'][:45]} ${l['amount']:,.2f}"
                f"  (twin of teller {t['date']} ${t['amount']:,.2f})"
            )
            used_teller.add(t["id"])

        for line in doomed.values():
            print(("DELETE  " if apply else "would delete  ") + line)
        print(f"{len(doomed)} of {len(legacy)} legacy rows in coverage matched")
        if apply and doomed:
            await store.execute(
                f"DELETE FROM finance_transactions WHERE id IN ({','.join('?' * len(doomed))})",
                tuple(doomed))
            print(f"Deleted {len(doomed)} rows.")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
