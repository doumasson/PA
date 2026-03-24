#!/usr/bin/env python3
"""One-time Google OAuth setup."""
import sys
from pathlib import Path

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

CREDS_FILE = Path.home() / 'pa/data/google/credentials.json'
TOKEN_FILE  = Path.home() / 'pa/data/google/token.json'

def main():
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDS_FILE.exists():
        print(f"ERROR: {CREDS_FILE} not found.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'

    auth_url, _ = flow.authorization_url(prompt='consent')
    print("\nOpen this URL in your browser:\n")
    print(auth_url)
    print()

    code = input("Paste the authorization code here: ").strip()
    flow.fetch_token(code=code)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(flow.credentials.to_json())
    print(f"\nDone. Token saved.")

if __name__ == '__main__':
    main()
