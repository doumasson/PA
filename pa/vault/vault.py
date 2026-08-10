import json
import os
from pathlib import Path
from typing import Any

from pa.core.exceptions import VaultAuthError, VaultLockedError
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
        """Create a new vault with the given master password.

        Refuses to run over an existing vault.enc — losing vault.params.json
        (SD corruption, accidental delete) must never silently destroy the
        stored credentials by re-initializing an empty vault on top of them.
        """
        if self._vault_path.exists() and not self._params_path.exists():
            raise VaultAuthError(
                "vault.enc exists but vault.params.json is missing — refusing to "
                "overwrite the vault. Restore vault.params.json from backup."
            )
        self._data = {}
        self._key, self._params = derive_key(master_password)
        self._params_path.write_text(
            json.dumps(self._params, indent=2), encoding="utf-8"
        )
        await self._save()

    async def unlock(self, master_password: str) -> None:
        """Unlock an existing vault, or create a new one on first use."""
        if not self._params_path.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            await self.init(master_password)
            return
        params = json.loads(self._params_path.read_text(encoding="utf-8"))
        key, _ = derive_key(master_password, params=params)
        try:
            encrypted = self._vault_path.read_bytes()
        except FileNotFoundError as e:
            raise VaultAuthError(
                "Vault file vault.enc is missing — restore it from backup."
            ) from e
        except OSError as e:
            raise VaultAuthError(f"Vault file unreadable ({e}) — check the disk.") from e
        try:
            plaintext = decrypt(encrypted, key)
            self._data = json.loads(plaintext)
        except Exception as e:
            raise VaultAuthError("Wrong master password") from e
        self._key = key
        self._params = params

    def lock(self) -> None:
        """Wipe credentials from memory.

        Note: CPython gives no reliable way to zero an immutable bytes
        object's buffer; dropping the references is the honest best effort.
        """
        self._data = {}
        self._key = None

    @property
    def exists(self) -> bool:
        """True once a vault has been created on disk."""
        return self._params_path.exists()

    def get(self, institution: str) -> dict[str, Any] | None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        return self._data.get(institution)

    def institutions(self) -> list[str]:
        """Names of stored credentials (internal '_'-prefixed keys hidden)."""
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        return sorted(k for k in self._data if not k.startswith("_"))

    async def add(self, institution: str, credentials: dict[str, Any]) -> None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        self._data[institution] = credentials
        await self._save()

    async def remove(self, institution: str) -> bool:
        """Delete stored credentials. Returns False if none existed."""
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        if institution not in self._data:
            return False
        del self._data[institution]
        await self._save()
        return True

    async def _save(self) -> None:
        """Atomic write (tmp + fsync + rename) with a rotating .bak so a
        power cut mid-write on the SD card can't corrupt the only copy."""
        plaintext = json.dumps(self._data).encode("utf-8")
        encrypted = encrypt(plaintext, self._key)
        tmp_path = self._vault_path.with_suffix(".enc.tmp")
        with open(tmp_path, "wb") as f:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())
        if self._vault_path.exists():
            self._vault_path.replace(self._vault_path.with_suffix(".enc.bak"))
        os.replace(tmp_path, self._vault_path)
