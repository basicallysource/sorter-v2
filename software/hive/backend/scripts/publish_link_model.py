"""Publish a trained piece_link matcher to Hive as a downloadable model.

A link matcher is TWO onnx graphs (a shared CropEncoder and a LinkHead), while
``detection_model_variants`` is unique on (model, runtime) and stores one file
per row. Rather than widen that schema, the pair ships as a single ``.tar.gz``
under the ``onnx`` runtime — the same shape ncnn already uses, so the sorter's
existing download+extract path handles it unchanged.

Both graphs carry a ``hive.*`` metadata block baked in by the training repo's
export_onnx.py (color-model/piece_link). This reads that block, checks the two
files agree, and copies it into ``training_metadata`` so a consumer can verify
its meta feature builder matches what the model was trained on instead of
trusting a hardcoded constant.

Usage:
    python scripts/publish_link_model.py \
        --encoder ~/Documents/GitHub/color-model/runs/link-v3/encoder.onnx \
        --head    ~/Documents/GitHub/color-model/runs/link-v3/head.onnx \
        --hive-url https://hive.basically.website \
        --api-key $HIVE_API_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from pathlib import Path

import onnxruntime as ort

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "hive" / "sorter-client"))

from hive_client import HiveAdminClient  # noqa: E402

HIVE_KIND = "piece_link_matcher"
MODEL_FAMILY = "piece_link_matcher"
PURPOSE = "piece_link"
# Names inside the tarball. Fixed so the consumer resolves them without needing
# the publisher's on-disk filenames.
ENCODER_MEMBER = "encoder.onnx"
HEAD_MEMBER = "head.onnx"


def readHiveMetadata(path: Path) -> dict[str, str]:
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
    meta = dict(sess.get_modelmeta().custom_metadata_map or {})
    if meta.get("hive.kind") != HIVE_KIND:
        raise SystemExit(f"{path.name}: not a {HIVE_KIND} graph (hive.kind={meta.get('hive.kind')!r})")
    return meta


def asInt(meta: dict[str, str], key: str) -> int:
    try:
        return int(meta.get(key, "0"))
    except ValueError:
        return 0


def buildTarball(encoder: Path, head: Path, dest_dir: Path, slug: str) -> Path:
    tar_path = dest_dir / f"{slug}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(encoder, arcname=ENCODER_MEMBER)
        tar.add(head, arcname=HEAD_MEMBER)
    return tar_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--encoder", required=True, type=Path)
    ap.add_argument("--head", required=True, type=Path)
    ap.add_argument("--hive-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--slug", help="Defaults to the graphs' hive.name.")
    ap.add_argument("--name", help="Display name. Defaults to the slug.")
    ap.add_argument("--description")
    ap.add_argument(
        "--stable",
        action="store_true",
        help="Publish without the experimental flag. Link matchers are inert on machines "
             "for now, so the default is experimental.",
    )
    ap.add_argument("--private", action="store_true", help="Publish with is_public=false.")
    args = ap.parse_args()

    for p in (args.encoder, args.head):
        if not p.is_file():
            raise SystemExit(f"missing file: {p}")

    enc_meta = readHiveMetadata(args.encoder)
    head_meta = readHiveMetadata(args.head)
    if enc_meta.get("hive.role") != "encoder":
        raise SystemExit(f"--encoder has hive.role={enc_meta.get('hive.role')!r}, expected 'encoder'")
    if head_meta.get("hive.role") != "head":
        raise SystemExit(f"--head has hive.role={head_meta.get('hive.role')!r}, expected 'head'")

    # A mismatched pair scores garbage rather than failing loudly at inference,
    # so refuse to publish one.
    for key in ("hive.name", "hive.input_size", "hive.embed_dim", "hive.meta_dim"):
        if enc_meta.get(key) != head_meta.get(key):
            raise SystemExit(
                f"encoder/head disagree on {key}: {enc_meta.get(key)!r} vs {head_meta.get(key)!r}"
            )

    slug = args.slug or head_meta.get("hive.name")
    if not slug:
        raise SystemExit("no --slug and the graphs carry no hive.name")
    name = args.name or slug

    training_metadata = {
        "kind": HIVE_KIND,
        "input_size": asInt(head_meta, "hive.input_size"),
        "embed_dim": asInt(head_meta, "hive.embed_dim"),
        "meta_dim": asInt(head_meta, "hive.meta_dim"),
        # Human-readable ordered feature list from the training repo. The
        # consumer's meta builder must produce exactly this, in this order.
        "meta_features": head_meta.get("hive.meta_features"),
        "predict_threshold": float(head_meta.get("hive.predict_threshold", 0.5)),
        "encoder_member": ENCODER_MEMBER,
        "head_member": HEAD_MEMBER,
        "hive_metadata": {"encoder": enc_meta, "head": head_meta},
    }

    client = HiveAdminClient(args.hive_url, api_key=args.api_key)
    created = client.create_model(
        {
            "slug": slug,
            "name": name,
            "description": args.description or head_meta.get("hive.description"),
            "purpose": PURPOSE,
            "model_family": MODEL_FAMILY,
            "scopes": [],
            "training_metadata": training_metadata,
            "is_public": not args.private,
            "experimental": not args.stable,
        }
    )
    model_id = created["id"]
    print(f"created {slug} v{created['version']} ({created.get('codename')}) id={model_id}")

    with tempfile.TemporaryDirectory() as tmp:
        tar_path = buildTarball(args.encoder, args.head, Path(tmp), slug)
        size = tar_path.stat().st_size

        def progress(sent: int, total: int) -> None:
            pct = (sent / total * 100) if total else 0
            print(f"\r  uploading {pct:5.1f}%", end="", flush=True)

        client.upload_variant(
            model_id,
            "onnx",
            tar_path,
            format_meta={
                "archive": "tar.gz",
                "members": [ENCODER_MEMBER, HEAD_MEMBER],
                "label": "encoder+head",
            },
            on_progress=progress,
        )
        print(f"\r  uploaded {size} bytes            ")

    print(json.dumps({"id": model_id, "slug": slug, "version": created["version"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
