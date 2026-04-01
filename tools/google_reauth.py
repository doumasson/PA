#!/usr/bin/env python3
"""Re-authenticate Google OAuth using credentials already stored in the vault.

Usage (on the Pi, with SSH tunnel for port 8085):
    cd ~/pa && source .venv/bin/activate
    python tools/google_reauth.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

DATA_DIR = Path.home() / 'pa/data'


async def load_vault():
    from pa.vault.vault import Vault
    vault = Vault(DATA_DIR)
    password = os.environ.get("PA_VAULT_PASSWORD", "")
    if not password:
        password = input("Vault password: ")
    await vault.unlock(password)
    return vault


def main():
    vault = asyncio.run(load_vault())

    cred_data = vault._data.get('google_credentials')
    if not cred_data:
        print("ERROR: No google_credentials found in vault.")
        print("You need to create an OAuth app in Google Cloud Console first.")
        sys.exit(1)

    print("Found Google OAuth credentials in vault.")

    # Write credentials to a temp file for the OAuth library
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(cred_data, f)
        creds_path = f.name

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)

        print("\nStarting auth server on port 8085...")
        print("Make sure your SSH tunnel is active:")
        print("  ssh -L 8085:127.0.0.1:8085 admin@<pi-ip>")
        print()

        creds = flow.run_local_server(
            port=8085,
            open_browser=False,
            prompt='consent',
            access_type='offline',
        )

        # Save refreshed token back to vault
        token_data = json.loads(creds.to_json())
        vault._data['google_token'] = token_data
        asyncio.run(_save_vault(vault))
        print("\nGoogle token refreshed and saved to vault.")

    finally:
        os.unlink(creds_path)


async def _save_vault(vault):
    await vault._save()


if __name__ == '__main__':
    main()
