from __future__ import annotations

import argparse
import re
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.client import Config


HIVE_SSH = "root@100.116.70.1"
S3_BUCKET = "sorter-hive"
S3_ENDPOINT = "https://nyc3.digitaloceanspaces.com"
S3_REGION = "nyc3"
S3_KEY = "DO801LY3QV2W4ZW6UB47"
S3_SECRET = "ywsx4pECfVhLwqWeFFJv8SEm2+3XSXaO/2a/c/QWOJY"

DEFAULT_OUT = Path("/Volumes/T7/sorter-v2-c4-spoke-orientation/hive-images")


@dataclass
class SampleRow:
    sample_id: str
    machine_name: str
    full_frame_path: str


def slugifyMachine(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_").lower()


def fetchSamples(per_machine: int) -> list[SampleRow]:
    sql = (
        "WITH ranked AS ("
        " SELECT s.id::text AS sid, m.name AS mname, s.full_frame_path AS ffp,"
        " row_number() OVER (PARTITION BY s.machine_id ORDER BY random()) AS rn"
        " FROM samples s JOIN machines m ON m.id = s.machine_id"
        " WHERE s.source_role = 'classification_channel'"
        "   AND s.full_frame_path IS NOT NULL"
        ") SELECT sid, mname, ffp FROM ranked WHERE rn <= "
        + str(per_machine) + " ORDER BY mname, sid;"
    )
    cmd = [
        "ssh", HIVE_SSH,
        "docker exec hive-postgres psql -U hive -d hive -At -F'|' -c \""
        + sql + "\"",
    ]
    out = subprocess.check_output(cmd, text=True)
    rows: list[SampleRow] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        rows.append(SampleRow(sample_id=parts[0], machine_name=parts[1], full_frame_path=parts[2]))
    return rows


def buildS3Client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=S3_REGION,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
        config=Config(signature_version="s3v4"),
    )


def downloadAll(rows: list[SampleRow], out_dir: Path) -> None:
    s3 = buildS3Client()
    out_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    n_skip = 0
    n_fail = 0
    for row in rows:
        sub = out_dir / slugifyMachine(row.machine_name)
        sub.mkdir(parents=True, exist_ok=True)
        dst = sub / (row.sample_id + ".jpg")
        if dst.exists() and dst.stat().st_size > 0:
            n_skip += 1
            continue
        try:
            s3.download_file(S3_BUCKET, row.full_frame_path, str(dst))
            n_ok += 1
            print(f"OK   {dst}")
        except Exception as e:
            n_fail += 1
            print(f"FAIL {row.full_frame_path}: {e}", file=sys.stderr)
    print(f"done. ok={n_ok} skip={n_skip} fail={n_fail} total={len(rows)}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--per-machine", type=int, default=15)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()
    rows = fetchSamples(args.per_machine)
    print(f"fetched {len(rows)} sample rows")
    downloadAll(rows, args.out)


if __name__ == "__main__":
    main()
