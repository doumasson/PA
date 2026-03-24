"""Teller API client using mutual TLS from vault credentials."""
from __future__ import annotations
import tempfile
import os
from pathlib import Path
import requests


class TellerClient:
    BASE = "https://api.teller.io"

    def __init__(self, vault):
        self._vault = vault
        self._cert_files = None

    def _get_cert(self):
        """Write cert/key to temp files and return paths."""
        cert = self._vault._data.get('teller_certificate', {}).get('pem', '')
        key = self._vault._data.get('teller_private_key', {}).get('pem', '')
        if not cert or not key:
            raise RuntimeError("Teller certificates not in vault.")
        cert_path = '/tmp/teller_cert.pem'
        key_path = '/tmp/teller_key.pem'
        Path(cert_path).write_text(cert)
        Path(key_path).write_text(key)
        return cert_path, key_path

    def _cleanup_cert(self, cert_path, key_path):
        try:
            Path(cert_path).unlink(missing_ok=True)
            Path(key_path).unlink(missing_ok=True)
        except Exception:
            pass

    def get(self, path: str, token: str) -> dict | list:
        cert_path, key_path = self._get_cert()
        try:
            r = requests.get(
                f"{self.BASE}{path}",
                auth=(token, ''),
                cert=(cert_path, key_path),
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        finally:
            self._cleanup_cert(cert_path, key_path)

    def get_accounts(self, token: str) -> list:
        return self.get('/accounts', token)

    def get_balances(self, token: str, account_id: str) -> dict:
        return self.get(f'/accounts/{account_id}/balances', token)

    def get_transactions(self, token: str, account_id: str, count: int = 50) -> list:
        return self.get(f'/accounts/{account_id}/transactions?count={count}', token)
