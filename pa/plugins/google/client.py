"""Google API client — builds Gmail and Calendar services from vault credentials."""
from __future__ import annotations
import json
from typing import Any
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

def get_credentials(vault: Any) -> Credentials:
    token_data = vault._data.get('google_token')
    cred_data = vault._data.get('google_credentials')
    if not token_data or not cred_data:
        raise RuntimeError("Google credentials not in vault. Run tools/google_auth.py first.")
    installed = cred_data.get('installed', cred_data)
    creds = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=installed.get('client_id'),
        client_secret=installed.get('client_secret'),
        scopes=token_data.get('scopes', SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token back to vault
        token_data.update(json.loads(creds.to_json()))
    return creds

def gmail_service(vault: Any):
    return build('gmail', 'v1', credentials=get_credentials(vault), cache_discovery=False)

def calendar_service(vault: Any):
    return build('calendar', 'v3', credentials=get_credentials(vault), cache_discovery=False)
