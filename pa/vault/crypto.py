import os
from typing import Any

from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Argon2id default parameters
_DEFAULT_TIME_COST = 3
_DEFAULT_MEMORY_COST = 65536  # 64 MB
_DEFAULT_PARALLELISM = 4
_SALT_LENGTH = 16
_KEY_LENGTH = 32
_NONCE_LENGTH = 12


def derive_key(
    password: str, params: dict[str, Any] | None = None
) -> tuple[bytes, dict[str, Any]]:
    if params is None:
        salt = os.urandom(_SALT_LENGTH)
        params = {
            "salt": salt.hex(),
            "time_cost": _DEFAULT_TIME_COST,
            "memory_cost": _DEFAULT_MEMORY_COST,
            "parallelism": _DEFAULT_PARALLELISM,
        }

    salt = bytes.fromhex(params["salt"])
    key = hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=_KEY_LENGTH,
        type=Type.ID,
    )
    return key, params


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(ciphertext_with_nonce: bytes, key: bytes) -> bytes:
    nonce = ciphertext_with_nonce[:_NONCE_LENGTH]
    ciphertext = ciphertext_with_nonce[_NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
