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
import binascii
import secrets
import sqlite3
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENCRYPTED_PREFIX = "fernet:v1:"
_SEED_STATE_KEY = "__secret_seed"
_SEED_CORRUPT_MSG = (
    "Stored secret seed at {path!r} exists but is unusable ({detail}). "
    "Silently regenerating would invalidate every encrypted secret in this "
    "database (Hive tokens, API keys, etc). Recover by either:\n"
    "  1. Restoring local_state.sqlite from a backup that has matching ciphertexts, OR\n"
    "  2. Deleting the __secret_seed row from state_entries (this forces a fresh "
    "seed on next start) AND re-issuing every encrypted secret afterwards."
)


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
        if row is not None:
            # Seed already exists. If it's malformed, refuse to overwrite —
            # silently regenerating would invalidate every existing ciphertext
            # in the database (and the operator would only find out when an
            # upload starts failing auth, like the 2026-05-24 Hive incident).
            raw = row[0].strip('"')
            try:
                data = base64.b64decode(raw)
            except (binascii.Error, ValueError) as exc:
                raise RuntimeError(
                    _SEED_CORRUPT_MSG.format(path=str(db_path), detail=f"base64 decode failed: {exc}")
                ) from exc
            if len(data) < 32:
                raise RuntimeError(
                    _SEED_CORRUPT_MSG.format(
                        path=str(db_path),
                        detail=f"got {len(data)} bytes, need >= 32",
                    )
                )
            return data[:32]
        # First-run path only: no seed yet. Generate one and persist.
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
