"""At-rest encryption for sensitive values stored in local_state.sqlite.

Third-party API tokens (OpenRouter, Gemini, Brickognize, Hive) were previously
written to the SQLite state store as plaintext. A read of the file was therefore
a full secret disclosure. Values are now Fernet-encrypted with a key derived
from a per-install seed stored in local_state.sqlite itself.

Storing the seed in the same database means the key and ciphertext always fail
or survive together — crash-safe because SQLite's WAL durability covers both.

Existing plaintext values are migrated transparently: decrypt_str() returns
legacy values unchanged, and the caller re-saves them encrypted on next write.
"""
from __future__ import annotations

import base64
import secrets
import sqlite3
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENCRYPTED_PREFIX = "fernet:v1:"
_SEED_STATE_KEY = "__secret_seed"


def _load_or_create_seed() -> bytes:
    from local_state import local_state_db_path

    db_path = local_state_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS state_entries "
            "(key TEXT PRIMARY KEY, json_value TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        conn.commit()
        row = conn.execute(
            "SELECT json_value FROM state_entries WHERE key = ?", (_SEED_STATE_KEY,)
        ).fetchone()
        if row:
            raw = row[0].strip('"')
            data = base64.b64decode(raw)
            if len(data) >= 32:
                return data[:32]
        material = secrets.token_bytes(32)
        encoded = '"' + base64.b64encode(material).decode("ascii") + '"'
        conn.execute(
            "INSERT OR REPLACE INTO state_entries (key, json_value, updated_at) VALUES (?, ?, ?)",
            (_SEED_STATE_KEY, encoded, time.time()),
        )
        conn.commit()
        return material
    finally:
        conn.close()


def _fernet() -> Fernet:
    seed = _load_or_create_seed()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"lego-sorter-secrets-v1",
    )
    derived = hkdf.derive(seed)
    return Fernet(base64.urlsafe_b64encode(derived))


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(ENCRYPTED_PREFIX)


def encrypt_str(plaintext: str) -> str:
    if not isinstance(plaintext, str):
        raise TypeError("encrypt_str expects str")
    if is_encrypted(plaintext):
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def decrypt_str(value: str) -> str:
    """Decrypt a value. Plain strings (pre-migration) pass through unchanged.

    Returns empty string for ciphertexts that can't be decrypted (e.g. the
    seed was regenerated) so callers surface a clean "no credential" state
    instead of a corrupted string.
    """
    if not isinstance(value, str):
        return value
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
