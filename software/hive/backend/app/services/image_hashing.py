"""Perceptual hashing for sample images.

We store an 8×8 DCT pHash per sample as a signed 64-bit int. The hash is
compact, fast to compute (~1ms per image), and well-suited to "find
near-duplicates" — two images with Hamming distance ≤ ~12 are usually
visually similar (same content, slight crop/exposure/JPEG variations).

The DB column is BIGINT (postgres native signed 64-bit); the upper bit
might flip the sign when packed, which is irrelevant because Hamming
distance via XOR + popcount is sign-agnostic.
"""

from __future__ import annotations

import io
import logging
from typing import IO

import imagehash
from PIL import Image, UnidentifiedImageError


logger = logging.getLogger(__name__)


# pHash hex string is 16 chars (64 bits). Anything that fits into BIGINT
# after the unsigned→signed wrap is valid; we mask to 64 bits defensively.
_SIGN_BIT = 1 << 63
_MASK_64 = (1 << 64) - 1


def _to_signed_64(value: int) -> int:
    """Wrap an unsigned 64-bit int into the signed range BIGINT can store."""

    value &= _MASK_64
    if value & _SIGN_BIT:
        value -= 1 << 64
    return value


def compute_phash_bytes(image_bytes: bytes) -> int | None:
    """Compute the 64-bit pHash of ``image_bytes``.

    Returns ``None`` if the image can't be decoded (corrupt upload, weird
    format) — callers should treat that as "no hash available" rather than
    failing the upload.
    """

    if not image_bytes:
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            h = imagehash.phash(img.convert("RGB"))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("compute_phash_bytes: skipping un-decodable image: %s", exc)
        return None
    # imagehash.ImageHash stringifies to a hex digest of len(hash)/4 chars
    # (default 8x8 = 64 bits = 16 hex chars). Parse to int, then wrap to
    # signed 64-bit for BIGINT storage.
    try:
        unsigned = int(str(h), 16)
    except ValueError:
        return None
    return _to_signed_64(unsigned)


def compute_phash_from_stream(stream: IO[bytes]) -> int | None:
    """Read the full stream, compute pHash, and rewind it to start.

    Used in the upload path where the same FastAPI ``UploadFile`` is
    passed straight on to ``write_stream`` afterwards.
    """

    pos = stream.tell()
    try:
        data = stream.read()
        return compute_phash_bytes(data)
    finally:
        try:
            stream.seek(pos)
        except (OSError, ValueError):
            pass


def hamming_distance(a: int, b: int) -> int:
    """Bit-count of the XOR — number of differing bits across two pHashes."""

    return ((a ^ b) & _MASK_64).bit_count()
