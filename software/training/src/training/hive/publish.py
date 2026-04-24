"""Publish a locally trained detection model to Hive.

Usage:
    python -m hive_client.publish_model \\
      --run-dir .../local_detection_models/<run> \\
      [--hailo-bundle .../hailo_compile_bundles/<bundle>.tar.gz] \\
      --slug chamber-yolo11s-320 \\
      --scopes classification_chamber,c_channel \\
      --hive-url https://hive.example \\
      --email user@example [--password-env HIVE_PASSWORD | --password-stdin] \\
      [--name "Chamber detector"] [--description "..."] [--public|--private] \\
      [--family yolo]

Variants uploaded from the run dir:
  - exports/best.onnx  -> runtime=onnx
  - exports/*ncnn*/ or *_ncnn/  -> tarred to .tar.gz, runtime=ncnn
  - --hailo-bundle file -> runtime=hailo
  - exports/best.pt    -> runtime=pytorch (optional)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

_HIVE_CLIENT_DIR = Path(__file__).resolve().parents[4] / "hive" / "sorter-client"
if str(_HIVE_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(_HIVE_CLIENT_DIR))

from hive_client import HiveAdminClient, HiveError  # noqa: E402


def _progress(label: str):
    def cb(sent: int, total: int) -> None:
        if total <= 0:
            return
        pct = sent * 100 // total
        sys.stderr.write(f"\r  {label}: {pct:3d}% ({sent}/{total})")
        sys.stderr.flush()
        if sent >= total:
            sys.stderr.write("\n")

    return cb


def _find_ncnn_dir(exports_dir: Path) -> Path | None:
    for candidate in exports_dir.iterdir():
        if candidate.is_dir() and "ncnn" in candidate.name.lower():
            return candidate
    return None


def _tar_directory(src_dir: Path) -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz", prefix=f"{src_dir.name}-")
    tmp.close()
    with tarfile.open(tmp.name, "w:gz") as tar:
        tar.add(src_dir, arcname=src_dir.name)
    return Path(tmp.name)


def _load_run_metadata(run_dir: Path) -> dict:
    run_json = run_dir / "run.json"
    if not run_json.exists():
        raise SystemExit(f"run.json missing under {run_dir}")
    with open(run_json) as fh:
        return json.load(fh)


def _resolve_password(args: argparse.Namespace) -> str:
    if args.password_env:
        pw = os.environ.get(args.password_env)
        if not pw:
            raise SystemExit(f"env var {args.password_env} is empty")
        return pw
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("Hive password: ")


def _build_variants(run_dir: Path, hailo_bundle: Path | None) -> list[tuple[str, Path, dict | None, bool]]:
    """Returns list of (runtime, path, format_meta, is_temp)."""
    exports = run_dir / "exports"
    if not exports.is_dir():
        raise SystemExit(f"{exports} not found — expected exports dir in run-dir")

    variants: list[tuple[str, Path, dict | None, bool]] = []

    onnx = exports / "best.onnx"
    if not onnx.exists():
        onnx = exports / "model.onnx"
    if onnx.exists():
        variants.append(("onnx", onnx, None, False))

    ncnn_dir = _find_ncnn_dir(exports)
    if ncnn_dir is not None:
        tar_path = _tar_directory(ncnn_dir)
        inner = sorted(p.name for p in ncnn_dir.iterdir())
        variants.append(("ncnn", tar_path, {"archive": "tar.gz", "inner_files": inner, "dir_name": ncnn_dir.name}, True))

    if hailo_bundle is not None:
        if not hailo_bundle.exists():
            raise SystemExit(f"hailo bundle not found at {hailo_bundle}")
        variants.append(("hailo", hailo_bundle, {"archive": "tar.gz"}, False))

    pt = exports / "best.pt"
    if pt.exists():
        variants.append(("pytorch", pt, None, False))

    if not variants:
        raise SystemExit("No uploadable variants found")
    return variants


def _run_publish(
    *,
    run_dir: Path,
    hailo_bundle: Path | None,
    slug: str,
    name: str | None,
    description: str | None,
    family: str | None,
    scopes: list[str],
    hive_url: str,
    email: str | None = None,
    password: str | None = None,
    api_key: str | None = None,
    is_public: bool,
) -> int:
    run_dir = run_dir.resolve()
    meta = _load_run_metadata(run_dir)
    training_metadata = meta.get("training_metadata") if isinstance(meta.get("training_metadata"), dict) else meta
    model_family = family or meta.get("model_family") or "unknown"
    display_name = name or meta.get("run_name") or slug

    variants = _build_variants(run_dir, hailo_bundle)

    if api_key:
        client = HiveAdminClient(hive_url, api_key=api_key)
        print(f"Using API key for {hive_url}", file=sys.stderr)
    else:
        if not email or not password:
            raise SystemExit("Provide --token, or --email + --password-env for legacy login")
        client = HiveAdminClient(hive_url)
        print(f"Logging into {hive_url} as {email}", file=sys.stderr)
        client.login(email, password)

    payload = {
        "slug": slug,
        "name": display_name,
        "description": description,
        "model_family": model_family,
        "scopes": scopes,
        "training_metadata": training_metadata,
        "is_public": is_public,
    }
    print(f"Creating model slug={slug}", file=sys.stderr)
    created = client.create_model(payload)
    model_id = created["id"]
    print(f"  id={model_id} version={created['version']}", file=sys.stderr)

    try:
        for runtime, path, format_meta, is_temp in variants:
            print(f"Uploading {runtime} from {path.name} ({path.stat().st_size} bytes)", file=sys.stderr)
            try:
                client.upload_variant(
                    model_id=model_id,
                    runtime=runtime,
                    file_path=path,
                    format_meta=format_meta,
                    on_progress=_progress(runtime),
                )
            except HiveError as exc:
                print(f"  upload failed: {exc}", file=sys.stderr)
                return 2
    finally:
        for runtime, path, _fm, is_temp in variants:
            if is_temp:
                try:
                    path.unlink()
                except OSError:
                    pass

    print(f"Published {slug} v{created['version']} ({len(variants)} variants)", file=sys.stderr)
    return 0


def cli(kwargs: dict) -> int:
    """Entry used by `train publish`."""
    from training import auth as auth_store

    scopes_raw = kwargs.get("scopes") or ""
    scopes = [s.strip() for s in scopes_raw.split(",") if s.strip()]
    hive_url = kwargs["hive_url"]

    api_key = kwargs.get("token") or auth_store.get_token(hive_url)
    email = kwargs.get("email")
    password: str | None = None

    if not api_key:
        if not email:
            raise SystemExit(
                f"No stored API key for {hive_url}. Run `train auth login --hive-url {hive_url}` "
                f"or pass --token / --email + --password-env."
            )
        password_env = kwargs.get("password_env")
        if password_env:
            password = os.environ.get(password_env)
            if not password:
                raise SystemExit(f"env var {password_env} is empty")
        else:
            password = getpass.getpass("Hive password: ")

    return _run_publish(
        run_dir=Path(kwargs["run_dir"]),
        hailo_bundle=Path(kwargs["hailo_bundle"]) if kwargs.get("hailo_bundle") else None,
        slug=kwargs["slug"],
        name=kwargs.get("name"),
        description=kwargs.get("description"),
        family=kwargs.get("family"),
        scopes=scopes,
        hive_url=hive_url,
        email=email,
        password=password,
        api_key=api_key,
        is_public=kwargs.get("public", True),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--hailo-bundle", type=Path, default=None)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--family", default=None, help="Override model_family (default: from run.json)")
    parser.add_argument("--scopes", default="", help="Comma-separated list")
    parser.add_argument("--hive-url", required=True)
    parser.add_argument("--email", required=True)
    password_group = parser.add_mutually_exclusive_group()
    password_group.add_argument("--password-env", help="Env var containing password")
    password_group.add_argument("--password-stdin", action="store_true", help="Read password from stdin")
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--public", dest="is_public", action="store_true", default=True)
    visibility.add_argument("--private", dest="is_public", action="store_false")
    args = parser.parse_args()

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    password = _resolve_password(args)
    return _run_publish(
        run_dir=args.run_dir,
        hailo_bundle=args.hailo_bundle,
        slug=args.slug,
        name=args.name,
        description=args.description,
        family=args.family,
        scopes=scopes,
        hive_url=args.hive_url,
        email=args.email,
        password=password,
        is_public=args.is_public,
    )


if __name__ == "__main__":
    raise SystemExit(main())
