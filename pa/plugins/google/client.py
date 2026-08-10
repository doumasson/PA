"""Google API client — builds Gmail and Calendar services from vault credentials."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.events',
]


def _persist_token(vault: Any, token_data: dict) -> None:
    """Persist a refreshed OAuth token via the vault's public API.

    get_credentials is sync (Google client libs are sync), so schedule the
    async vault.add on the running loop when there is one; outside a loop
    (CLI tools) the refreshed token stays in memory only.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(vault.add('google_token', token_data))


def get_credentials(vault: Any) -> Credentials:
    token_data = vault.get('google_token')
    cred_data = vault.get('google_credentials')
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
        _persist_token(vault, token_data)
    return creds


def gmail_service(vault: Any):
    return build('gmail', 'v1', credentials=get_credentials(vault), cache_discovery=False)


def calendar_service(vault: Any):
    return build('calendar', 'v3', credentials=get_credentials(vault), cache_discovery=False)
