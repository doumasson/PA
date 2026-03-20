import json
from pathlib import Path
from typing import Any

from pa.exceptions import VaultAuthError, VaultLockedError
from pa.vault.crypto import derive_key, encrypt, decrypt


class Vault:
    def __init__(self, directory: Path):
        self._dir = directory
        self._vault_path = directory / "vault.enc"
        self._params_path = directory / "vault.params.json"
        self._data: dict[str, Any] = {}
        self._key: bytes | None = None
        self._params: dict[str, Any] | None = None

    @property
    def is_unlocked(self) -> bool:
        return self._key is not None

    @property
    def derived_key(self) -> bytes | None:
        return self._key

    async def init(self, master_password: str) -> None:
        """Create a new vault with the given master password."""
        self._data = {}
        self._key, self._params = derive_key(master_password)
        self._params_path.write_text(
            json.dumps(self._params, indent=2), encoding="utf-8"
        )
        await self._save()

    async def unlock(self, master_password: str) -> None:
        """Unlock an existing vault."""
        if not self._params_path.exists():
            raise VaultAuthError("No vault found")
        params = json.loads(self._params_path.read_text(encoding="utf-8"))
        key, _ = derive_key(master_password, params=params)
        try:
            encrypted = self._vault_path.read_bytes()
            plaintext = decrypt(encrypted, key)
            self._data = json.loads(plaintext)
        except Exception as e:
            raise VaultAuthError("Wrong master password") from e
        self._key = key
        self._params = params

    def lock(self) -> None:
        """Wipe credentials from memory with best-effort secure clearing."""
        if self._key:
            import ctypes
            key_len = len(self._key)
            try:
                ctypes.memset(id(self._key) + 32, 0, key_len)
            except Exception:
                pass
        self._data = {}
        self._key = None

    def get(self, institution: str) -> dict[str, Any] | None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        return self._data.get(institution)

    async def add(self, institution: str, credentials: dict[str, Any]) -> None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        self._data[institution] = credentials
        await self._save()

    async def _save(self) -> None:
        plaintext = json.dumps(self._data).encode("utf-8")
        encrypted = encrypt(plaintext, self._key)
        self._vault_path.write_bytes(encrypted)
