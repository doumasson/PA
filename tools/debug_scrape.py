"""Debug scrape tool — run manually to diagnose login issues.

Usage: PA_DEBUG_SCRAPER=1 .venv/bin/python tools/debug_scrape.py <institution>

Reads credentials from the vault (you must enter vault password).
Saves debug output to /tmp/pa_pilot_debug/
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    if len(sys.argv) < 2:
        print("Usage: PA_DEBUG_SCRAPER=1 .venv/bin/python tools/debug_scrape.py <institution>")
        sys.exit(1)

    import os
    os.environ["PA_DEBUG_SCRAPER"] = "1"

    # Load .env file
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    institution = sys.argv[1]

    # Load vault to get credentials — use same path as app.py
    from pa.vault.vault import Vault
    import getpass

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    vault = Vault(data_dir)
    password = getpass.getpass("Vault password: ")
    await vault.unlock(password)

    creds = vault.get(institution)
    if not creds:
        print(f"No credentials found for '{institution}'")
        print(f"Available: {[k for k in vault._data.keys() if not k.startswith('_')]}")
        sys.exit(1)

    url = creds.get("url", "")
    if not url:
        print(f"No URL stored for '{institution}'. Re-add with /addcred.")
        sys.exit(1)

    print(f"Institution: {institution}")
    print(f"URL: {url}")
    print(f"Username: {creds['username'][:2]}***")
    print(f"Debug output: /tmp/pa_pilot_debug/")
    print("Starting scrape...\n")

    from pa.plugins.finance.scraper_runner import run_scrape
    result = await run_scrape(
        url=url,
        credentials={"username": creds["username"], "password": creds["password"]},
        data_dir=".",
    )

    print(f"\n{'='*60}")
    print(f"Status: {result['status']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    if result.get("accounts"):
        for acct in result["accounts"]:
            print(f"  {acct['account_name']}: ${acct['balance']:,.2f}")
    if result.get("actions"):
        print(f"\nActions taken ({len(result['actions'])} steps):")
        for i, a in enumerate(result["actions"]):
            print(f"  {i+1}. {a.get('action')} -> {a.get('selector', a.get('reason', a.get('prompt', '')))}")

    # Show debug files
    debug_dir = Path("/tmp/pa_pilot_debug")
    if debug_dir.exists():
        print(f"\nDebug files in {debug_dir}:")
        for f in sorted(debug_dir.iterdir()):
            print(f"  {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
