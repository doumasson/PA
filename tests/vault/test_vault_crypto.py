import pytest

from pa.vault.crypto import derive_key, encrypt, decrypt


def test_derive_key_returns_32_bytes():
    key, params = derive_key("my-master-password")
    assert len(key) == 32
    assert isinstance(key, bytes)


def test_derive_key_deterministic_with_same_params():
    key1, params = derive_key("password123")
    key2 = derive_key("password123", params=params)[0]
    assert key1 == key2


def test_derive_key_different_passwords_different_keys():
    key1, _ = derive_key("password1")
    key2, _ = derive_key("password2")
    assert key1 != key2


def test_encrypt_decrypt_roundtrip():
    key, _ = derive_key("test-password")
    plaintext = b'{"wellsfargo": {"username": "user", "password": "pass"}}'
    ciphertext = encrypt(plaintext, key)
    assert ciphertext != plaintext
    result = decrypt(ciphertext, key)
    assert result == plaintext


def test_decrypt_wrong_key_raises():
    key1, _ = derive_key("correct-password")
    key2, _ = derive_key("wrong-password")
    ciphertext = encrypt(b"secret data", key1)
    with pytest.raises(Exception):  # GCM auth tag failure
        decrypt(ciphertext, key2)


def test_params_contain_required_fields():
    _, params = derive_key("password")
    assert "salt" in params
    assert "time_cost" in params
    assert "memory_cost" in params
    assert "parallelism" in params
