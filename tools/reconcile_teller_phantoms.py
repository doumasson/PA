"""One-time cleanup of pending/posted phantom duplicates.

Before teller_id, the sync stored a transaction twice: once while pending
(bank date D) and again after settlement (re-dated D+1). Run this AFTER a
sync has attached teller_ids: any teller_id row's legacy twin (teller_id
IS NULL, same account+amount+merchant, date within 3 days) is the phantom
pending copy and gets deleted. Legacy rows with no teller twin are left
alone — Teller's live feed is the source of truth for what's real.

Usage:  python tools/reconcile_teller_phantoms.py [--apply]
        (default is a dry run; --apply deletes)
"""
import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pa.core.config import Config  # noqa: E402
from pa.core.store import Store  # noqa: E402
from pa.plugins.finance.guardian import normalize_merchant  # noqa: E402

LOOKBACK_DAYS = 45
TWIN_WINDOW_DAYS = 3


async def main(apply: bool) -> None:
    base_dir = Path(__file__).resolve().parent.parent
    config = Config(base_dir / "config.json")
    await config.load()
    data_dir = Path(config.get("data_dir") or base_dir / "data")
    store = Store(data_dir / "pa.db")
    await store.connect()
    try:
        since = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
        anchors = await store.fetchall(
            "SELECT id, account_id, date, description, amount FROM finance_transactions "
            "WHERE teller_id IS NOT NULL AND date >= ?",
            (since,),
        )
        legacy = await store.fetchall(
            "SELECT id, account_id, date, description, amount FROM finance_transactions "
            "WHERE teller_id IS NULL AND date >= ?",
            (since,),
        )
        # Feed coverage start per account: inside this window Teller's feed is
        # the complete record, so every real charge has an anchor row and any
        # matching legacy row is a phantom. A single anchor can leave SEVERAL
        # phantoms — banks slide a pending charge's date forward daily until
        # it posts, stranding one copy per day.
        coverage_start: dict[int, str] = {}
        for a in anchors:
            cur = coverage_start.get(a["account_id"])
            if cur is None or a["date"] < cur:
                coverage_start[a["account_id"]] = a["date"]

        doomed: dict[int, str] = {}
        for a in anchors:
            a_date = datetime.date.fromisoformat(a["date"])
            a_merchant = normalize_merchant(a["description"])
            for l in legacy:
                if l["id"] in doomed or l["account_id"] != a["account_id"]:
                    continue
                if l["date"] <= coverage_start[l["account_id"]]:
                    continue  # older than feed coverage: can't prove phantom
                if round(l["amount"], 2) != round(a["amount"], 2):
                    continue
                gap = abs((datetime.date.fromisoformat(l["date"]) - a_date).days)
                if gap > TWIN_WINDOW_DAYS:
                    continue
                if normalize_merchant(l["description"]) != a_merchant:
                    continue
                doomed[l["id"]] = (
                    f"{l['date']} {l['description'][:50]} ${l['amount']:,.2f}"
                    f"  (twin of teller row {a['id']} on {a['date']})"
                )
        if not doomed:
            print("No phantom twins found.")
            return
        for line in doomed.values():
            print(("DELETE  " if apply else "would delete  ") + line)
        if apply:
            await store.execute(
                f"DELETE FROM finance_transactions WHERE id IN ({','.join('?' * len(doomed))})",
                tuple(doomed),
            )
            print(f"Deleted {len(doomed)} phantom rows.")
        else:
            print(f"{len(doomed)} phantom rows. Re-run with --apply to delete.")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
