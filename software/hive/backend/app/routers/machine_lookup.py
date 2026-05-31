"""Ephemeral machine-IP rendezvous (zero-knowledge dead-drop).

Used by the SorterOS onboarding flow to bridge the "what's my Pi's LAN IP?"
gap. A fresh sorter has no Hive account and no mDNS guarantee, so:

  1. The onboarding portal (running on the Pi's AP) generates an RSA keypair
     in the user's browser and a random rendezvous id.
  2. The browser hands the PUBLIC key + id to the Pi, keeps the PRIVATE key
     locally (carried to /machine-ip-lookup via a URL fragment).
  3. Once the Pi joins the real Wi-Fi it reads its own LAN IP, encrypts it
     with the public key, and POSTs the ciphertext here under the id.
  4. The browser polls GET here, decrypts with the private key, and shows
     the user the sorter's address.

Hive only ever stores opaque ciphertext — it never sees the LAN IP in
clear. The id is the only access token; it is unguessable (≥16 random
bytes) and entries expire after a few minutes. A malicious POST with junk
just fails to decrypt in the browser and is ignored.

Storage is process-local and in-memory. The Hive backend runs a single
uvicorn worker (see docker-entrypoint.sh), so this is shared across all
requests. If Hive ever scales to multiple workers this must move to a
shared store (Redis / a tiny DB table).
"""

from __future__ import annotations

import re
import threading
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.errors import APIError

router = APIRouter(prefix="/api/machine-ip-lookup", tags=["machine-ip-lookup"])
limiter = Limiter(key_func=get_remote_address)

# A rendezvous entry lives this long. Long enough for a user to rejoin their
# Wi-Fi and open the lookup page; short enough that the dead-drop self-cleans.
TTL_SECONDS = 600
# Hard cap so a flood of junk POSTs can't exhaust memory. Each entry is tiny.
MAX_ENTRIES = 1000
# RSA-2048 OAEP ciphertext is 256 bytes → ~344 base64 chars. Cap generously
# but bounded so the store stays cheap.
MAX_CIPHERTEXT_LEN = 4096
# Browser-generated ids are base64url of ≥16 random bytes (~22 chars).
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

_store: dict[str, dict] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _prune_locked() -> None:
    """Drop expired entries. Caller must hold _lock."""
    cutoff = _now()
    expired = [k for k, v in _store.items() if v["expires_at"] <= cutoff]
    for k in expired:
        del _store[k]


def _validate_id(rendezvous_id: str) -> str:
    if not _ID_RE.match(rendezvous_id or ""):
        raise APIError(400, "Invalid rendezvous id", "INVALID_RENDEZVOUS_ID")
    return rendezvous_id


# Browser-side public keys (SPKI DER, base64) are small; RSA-2048 ≈ 400 chars.
MAX_PUBKEY_LEN = 2048


def _entry(rendezvous_id: str) -> dict:
    """Get-or-create the store entry for an id (caller holds _lock)."""
    entry = _store.get(rendezvous_id)
    if entry is None:
        if len(_store) >= MAX_ENTRIES:
            raise APIError(503, "Rendezvous store is full, retry shortly", "RENDEZVOUS_FULL")
        entry = {"pubkey": None, "ciphertext": None, "expires_at": _now() + TTL_SECONDS}
        _store[rendezvous_id] = entry
    return entry


class PubkeyPayload(BaseModel):
    # Browser's RSA-OAEP public key, SPKI DER as base64. The sorter fetches
    # this to encrypt its LAN IP; the matching private key never leaves the
    # browser, so Hive stays zero-knowledge.
    pubkey: str = Field(min_length=1, max_length=MAX_PUBKEY_LEN)


class PublishPayload(BaseModel):
    # Base64 ciphertext of the JSON {ip, hostname, port} blob, RSA-OAEP
    # encrypted with the browser's public key. Opaque to Hive.
    ciphertext: str = Field(min_length=1, max_length=MAX_CIPHERTEXT_LEN)


@router.post("/{rendezvous_id}/pubkey")
@limiter.limit("30/minute")
def put_pubkey(rendezvous_id: str, payload: PubkeyPayload, request: Request) -> dict:
    """Browser (on the https lookup page) uploads its public key."""
    _validate_id(rendezvous_id)
    with _lock:
        _prune_locked()
        entry = _entry(rendezvous_id)
        entry["pubkey"] = payload.pubkey
    return {"ok": True}


@router.get("/{rendezvous_id}/pubkey")
@limiter.limit("120/minute")
def get_pubkey(rendezvous_id: str, request: Request) -> dict:
    """Sorter fetches the browser's public key to encrypt its LAN IP."""
    _validate_id(rendezvous_id)
    with _lock:
        _prune_locked()
        entry = _store.get(rendezvous_id)
        return {"pubkey": entry["pubkey"] if entry else None}


@router.post("/{rendezvous_id}")
@limiter.limit("30/minute")
def publish_ip(rendezvous_id: str, payload: PublishPayload, request: Request) -> dict:
    """Sorter calls this once it has a LAN IP. Stores the encrypted blob."""
    _validate_id(rendezvous_id)
    with _lock:
        _prune_locked()
        entry = _entry(rendezvous_id)
        entry["ciphertext"] = payload.ciphertext
    return {"ok": True}


@router.get("/{rendezvous_id}")
@limiter.limit("120/minute")
def poll_ip(rendezvous_id: str, request: Request) -> dict:
    """Browser polls this until the sorter has published its IP."""
    _validate_id(rendezvous_id)
    with _lock:
        _prune_locked()
        entry = _store.get(rendezvous_id)
        ciphertext = entry["ciphertext"] if entry else None
        return {"ready": ciphertext is not None, "ciphertext": ciphertext}
