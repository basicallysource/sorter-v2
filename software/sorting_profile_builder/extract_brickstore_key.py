import struct
import hashlib
import os
import sys

DB_PATH = os.path.expanduser("~/Library/Caches/BrickStore/database-v12")


def chunkId(s):
    b = s.encode('ascii')
    return (b[0] & 0x7f) | ((b[1] & 0x7f) << 8) | ((b[2] & 0x7f) << 16) | ((b[3] & 0x7f) << 24)


BSDB = chunkId("BSDB")
AKEY = chunkId("AKEY")


def extractAffiliateKey(db_path=DB_PATH):
    with open(db_path, "rb") as f:
        data = f.read()

    pos = 0
    root_id = struct.unpack_from('<I', data, pos)[0]; pos += 4
    root_ver = struct.unpack_from('<I', data, pos)[0]; pos += 4
    root_size = struct.unpack_from('<Q', data, pos)[0]; pos += 8

    if root_id != BSDB:
        print("not a BrickStore database file", file=sys.stderr)
        return None

    scramble_key = hashlib.blake2s(f"DBv{root_ver}".encode('ascii'), digest_size=16).digest()

    root_data_start = pos
    root_end = root_data_start + root_size

    while pos < root_end:
        cid = struct.unpack_from('<I', data, pos)[0]; pos += 4
        _cver = struct.unpack_from('<I', data, pos)[0]; pos += 4
        csize = struct.unpack_from('<Q', data, pos)[0]; pos += 8
        chunk_data_start = pos

        if cid == AKEY:
            count = struct.unpack_from('<I', data, pos)[0]; pos += 4
            for _ in range(count):
                id_len = struct.unpack_from('<I', data, pos)[0]; pos += 4
                id_scrambled = data[pos:pos + id_len] if id_len and id_len != 0xFFFFFFFF else b""
                pos += id_len if id_len and id_len != 0xFFFFFFFF else 0

                key_len = struct.unpack_from('<I', data, pos)[0]; pos += 4
                key_scrambled = data[pos:pos + key_len] if key_len and key_len != 0xFFFFFFFF else b""
                pos += key_len if key_len and key_len != 0xFFFFFFFF else 0

                xor = lambda d, k: bytes(d[j] ^ k[j % len(k)] for j in range(len(d)))
                key_id = xor(id_scrambled, scramble_key).decode('utf-8', errors='replace')
                key_val = xor(key_scrambled, scramble_key).decode('utf-8', errors='replace')

                if key_id == "affiliate":
                    return key_val
            return None

        # skip chunk
        end = chunk_data_start + csize
        pos = end
        if csize % 16:
            pos += 16 - (csize % 16)
        pos += 16  # footer

    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="extract BrickLink affiliate API key from BrickStore database")
    parser.add_argument("--db", default=DB_PATH, help=f"path to BrickStore database (default: {DB_PATH})")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"BrickStore database not found: {args.db}", file=sys.stderr)
        print("install BrickStore and open it once to download the database", file=sys.stderr)
        sys.exit(1)

    key = extractAffiliateKey(args.db)
    if key:
        print(key)
    else:
        print("no affiliate key found in database", file=sys.stderr)
        sys.exit(1)
