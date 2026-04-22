"""At-rest encryption for sensitive values stored in local_state.sqlite.

Third-party API tokens (OpenRouter, Gemini, Brickognize, Hive) were previously
written to the SQLite state store as plaintext. A read of the file was therefore
a full secret disclosure. Values are now Fernet-encrypted with a key derived
from a per-install seed stored at ``.secret_seed`` next to the state database.

Threat model this addresses:
  * Backup / clone of ``local_state.sqlite`` alone no longer leaks tokens.
  * A full filesystem read (which also captures ``.secret_seed``) still does.
    The seed must stay on the machine; exclude it from any off-device backup.

Existing plaintext values are migrated transparently: decrypt_str() returns
legacy values unchanged, and the caller re-saves them encrypted on next write.
"""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENCRYPTED_PREFIX = "fernet:v1:"


def _seed_path() -> Path:
    override = os.getenv("SORTER_SECRET_SEED_PATH")
    if isinstance(override, str) and override.strip():
        return Path(override).expanduser()
    # Co-locate with the state database so tests that redirect LOCAL_STATE_DB_PATH
    # also redirect the seed — no repo pollution.
    from local_state import local_state_db_path

    return local_state_db_path().parent / ".secret_seed"


def _load_or_create_seed() -> bytes:
    path = _seed_path()
    if path.exists():
        data = path.read_bytes()
        if len(data) >= 32:
            return data[:32]
    path.parent.mkdir(parents=True, exist_ok=True)
    material = secrets.token_bytes(32)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(material)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return material


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
