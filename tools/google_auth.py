#!/usr/bin/env python3
"""One-time Google OAuth setup. Saves token to vault.

Usage (on the Pi):
    cd ~/pa && source .venv/bin/activate
    python tools/google_auth.py

If running headless, use --no-browser and paste the callback URL manually.
"""
import asyncio
import json
import sys
from pathlib import Path

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

DATA_DIR = Path.home() / 'pa/data'
CREDS_FILE = DATA_DIR / 'google/credentials.json'


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDS_FILE.exists():
        print(f"ERROR: {CREDS_FILE} not found.")
        print("Download your OAuth credentials from Google Cloud Console")
        print("and save them there.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDS_FILE), SCOPES,
    )

    # Run local server to handle callback (works headlessly with SSH tunnel)
    print("\nStarting local auth server on port 8085...")
    print("If running remotely, set up an SSH tunnel first:")
    print("  ssh -L 8085:127.0.0.1:8085 admin@<pi-ip>")
    print()

    creds = flow.run_local_server(
        port=8085,
        open_browser=False,
        prompt='consent',
        access_type='offline',
    )

    # Save to vault
    token_data = json.loads(creds.to_json())
    cred_data = json.loads(CREDS_FILE.read_text())

    # Try saving to vault directly
    try:
        from pa.vault.vault import Vault
        import os

        vault = Vault(DATA_DIR)
        password = os.environ.get("PA_VAULT_PASSWORD", "")
        if not password:
            password = input("Vault password: ")

        asyncio.run(_save_to_vault(vault, password, token_data, cred_data))
        print("\nToken saved to vault.")
    except Exception as e:
        # Fallback: save to file for manual import
        token_file = DATA_DIR / 'google/token.json'
        token_file.write_text(json.dumps(token_data, indent=2))
        print(f"\nCouldn't save to vault ({e}), saved to {token_file}")
        print("Import it manually with: /addcred google_token")


async def _save_to_vault(vault, password, token_data, cred_data):
    await vault.unlock(password)
    vault._data['google_token'] = token_data
    vault._data['google_credentials'] = cred_data
    await vault._save()


if __name__ == '__main__':
    main()
