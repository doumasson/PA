import pytest
from pathlib import Path

from pa.vault.vault import Vault
from pa.exceptions import VaultAuthError, VaultLockedError


@pytest.fixture
def vault_dir(tmp_dir: Path) -> Path:
    return tmp_dir


async def test_new_vault_init_and_unlock(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("master-password-123")
    assert (vault_dir / "vault.enc").exists()
    assert (vault_dir / "vault.params.json").exists()

    vault2 = Vault(vault_dir)
    await vault2.unlock("master-password-123")
    assert vault2.is_unlocked


async def test_add_and_get_credentials(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    await vault.add("wellsfargo", {"username": "user1", "password": "pass1"})

    vault2 = Vault(vault_dir)
    await vault2.unlock("password")
    creds = vault2.get("wellsfargo")
    assert creds["username"] == "user1"
    assert creds["password"] == "pass1"


async def test_get_missing_institution_returns_none(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    assert vault.get("nonexistent") is None


async def test_unlock_wrong_password_raises(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("correct-password")

    vault2 = Vault(vault_dir)
    with pytest.raises(VaultAuthError):
        await vault2.unlock("wrong-password")


async def test_get_while_locked_raises(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")


async def test_lock_clears_data(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    await vault.add("bank", {"user": "u", "pass": "p"})
    assert vault.is_unlocked
    vault.lock()
    assert not vault.is_unlocked


async def test_derived_key_available_after_unlock(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    key = vault.derived_key
    assert key is not None
    assert len(key) == 32
