"""Orchestration helpers for training runs on Vast.ai.

Split of duties:

- ``package()`` builds a self-contained tarball (dataset + track script + README)
  ready to upload and extract under ``/workspace/`` on a remote GPU host.
- ``offers()`` is a thin wrapper around ``vastai search offers`` with useful
  defaults for YOLO training (1× RTX 3090+/A-series, fast network).
- ``fetch()`` pulls ``/workspace/results/`` back into
  ``runs/<timestamp>-<zone>-<track>/`` using ``vastai ssh-url`` + rsync/scp.

Full lifecycle control (instance create/destroy) is intentionally NOT
automated — Vast.ai's pricing + availability varies; operator decides.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from training import DATASETS_DIR, RUNS_DIR


TRACK_SCRIPTS: dict[str, Path] = {
    "yolo": Path(__file__).resolve().parent / "tracks" / "yolo.py",
    "nanodet": Path(__file__).resolve().parent / "tracks" / "nanodet.py",
}

DEFAULT_IMAGE_YOLO = "pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime"
DEFAULT_IMAGE_NANODET = "pytorch/pytorch:2.4.1-cuda12.1-cudnn9-devel"
DEFAULT_OFFERS_QUERY = (
    "num_gpus=1 cpu_arch=amd64 reliability>0.98 disk_space>=60 inet_down>200 "
    "gpu_name in [RTX_3090,RTX_4090,RTX_A5000,RTX_A6000] rented=False"
)


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


def _copy_dataset_tree(src: Path, dst: Path) -> None:
    """Copy a built dataset dir, resolving symlinks so the archive is self-contained."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # symlinks get resolved to their real file; copy2 follows by default
        shutil.copy2(item, target, follow_symlinks=True)


def _rewrite_data_yaml(dataset_dir: Path) -> None:
    """Make data.yaml portable and also expose it as ``dataset.yaml``.

    The vastai track scripts reference ``dataset.yaml`` by convention, while the
    builder writes ``data.yaml``. Keep both so either name works.
    """
    import yaml

    data_yaml = dataset_dir / "data.yaml"
    if not data_yaml.exists():
        return
    payload = yaml.safe_load(data_yaml.read_text())
    payload["path"] = "/workspace/dataset"
    serialized = yaml.safe_dump(payload, sort_keys=False)
    data_yaml.write_text(serialized)
    (dataset_dir / "dataset.yaml").write_text(serialized)


def _package_readme(
    *,
    zone: str,
    dataset_name: str,
    track: str,
    model_ids: list[str] | None,
    workspace_name: str,
) -> str:
    image = DEFAULT_IMAGE_YOLO if track == "yolo" else DEFAULT_IMAGE_NANODET
    select_arg = (
        f" --model-ids {' '.join(model_ids)}" if model_ids else ""
    )
    return textwrap.dedent(
        f"""\
        # Vast.ai Training Session — {zone} · {dataset_name} · {track}

        Extracted into ``/workspace`` produces:

            /workspace/dataset/          (data.yaml + images/train,val + labels/train,val)
            /workspace/{track}.py        (training script)
            /workspace/README.md
            /workspace/run_metadata.json

        ## Recommended host

        - Image: `{image}`
        - Disk: 60 GB
        - GPU: RTX 3090 / 4090 / A5000 / A6000

        ## Launch

        ```bash
        # 1. Search offers
        vastai search offers '{DEFAULT_OFFERS_QUERY}' --raw -o dph_total | head
        # 2. Pick one offer id and create
        vastai create instance <OFFER_ID> --image {image} --disk 60 --label {workspace_name}
        # 3. Upload this archive
        vastai copy <TARBALL_PATH> <INSTANCE_ID>:/workspace/
        # 4. SSH in
        vastai ssh <INSTANCE_ID>
        # 5. On the remote:
        cd /workspace && tar xzf {workspace_name}.tar.gz --strip-components=1
        python {track}.py{select_arg}
        ```

        When training finishes, pull results locally:

        ```bash
        train vastai fetch --instance <INSTANCE_ID> --zone {zone} --track {track}
        ```
        """
    )


def package(
    *,
    zone: str,
    dataset_name: str = "v1",
    track: str = "yolo",
    model_ids: list[str] | None = None,
    output: Path | None = None,
) -> Path:
    if track not in TRACK_SCRIPTS:
        raise SystemExit(f"unknown track {track!r}; expected one of {list(TRACK_SCRIPTS)}")
    track_script = TRACK_SCRIPTS[track]
    if not track_script.exists():
        raise SystemExit(f"track script missing: {track_script}")

    dataset_src = (DATASETS_DIR / zone / dataset_name).resolve()
    if not dataset_src.exists():
        raise SystemExit(
            f"{dataset_src} not built. Run `train build --zone {zone} --name {dataset_name}` first."
        )

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace_name = f"{timestamp}-{zone}-{track}-{dataset_name}"
    if output is None:
        output = (RUNS_DIR / "staging" / f"{workspace_name}.tar.gz").resolve()
    else:
        output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with tempfile.TemporaryDirectory(prefix="train-vastai-") as tmp:
        workspace_dir = Path(tmp) / workspace_name
        workspace_dir.mkdir()

        _copy_dataset_tree(dataset_src, workspace_dir / "dataset")
        _rewrite_data_yaml(workspace_dir / "dataset")

        shutil.copy2(track_script, workspace_dir / f"{track}.py")

        run_metadata = {
            "zone": zone,
            "dataset_name": dataset_name,
            "track": track,
            "model_ids": model_ids,
            "packaged_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "workspace_name": workspace_name,
        }
        (workspace_dir / "run_metadata.json").write_text(
            json.dumps(run_metadata, indent=2, sort_keys=True)
        )
        (workspace_dir / "README.md").write_text(
            _package_readme(
                zone=zone,
                dataset_name=dataset_name,
                track=track,
                model_ids=model_ids,
                workspace_name=workspace_name,
            )
        )

        with tarfile.open(output, "w:gz") as handle:
            handle.add(workspace_dir, arcname=workspace_dir.name)

    size_mb = output.stat().st_size / (1024 * 1024)
    print(
        f"Packaged {output}\n  dataset={dataset_src}\n  track={track}.py\n  size={size_mb:.1f} MB",
        file=sys.stderr,
    )
    return output


# ---------------------------------------------------------------------------
# Offers pass-through
# ---------------------------------------------------------------------------


def _run(args: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=capture, check=check)


def offers(*, query: str = DEFAULT_OFFERS_QUERY, order: str = "dph_total", limit: int = 5) -> int:
    result = _run(
        ["vastai", "search", "offers", query, "--raw", "-o", order],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip() or "vastai command failed")
    payload = json.loads(result.stdout or "[]")
    print(f"offers={len(payload)} (showing {min(limit, len(payload))})")
    for offer in payload[:limit]:
        trimmed = {
            "id": offer.get("id"),
            "gpu_name": offer.get("gpu_name"),
            "num_gpus": offer.get("num_gpus"),
            "gpu_ram": offer.get("gpu_ram"),
            "cpu_ram": offer.get("cpu_ram"),
            "cuda_max_good": offer.get("cuda_max_good"),
            "dph_total": offer.get("dph_total"),
            "reliability": offer.get("reliability"),
            "inet_down": offer.get("inet_down"),
            "geolocation": offer.get("geolocation"),
        }
        print(json.dumps(trimmed, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Fetching results
# ---------------------------------------------------------------------------


def _parse_ssh_url(url: str) -> tuple[str, int]:
    """``ssh://root@ssh4.vast.ai:14345`` → (``root@ssh4.vast.ai``, 14345)."""
    if url.startswith("ssh://"):
        url = url[len("ssh://") :]
    if "@" not in url:
        raise SystemExit(f"Unexpected vastai ssh-url format: {url!r}")
    user_host, _, port_str = url.partition(":")
    port = int(port_str) if port_str else 22
    return user_host, port


def _get_ssh_target(instance_id: str | int) -> tuple[str, int]:
    """Call ``vastai ssh-url <id>`` and parse the result."""
    result = _run(["vastai", "ssh-url", str(instance_id)], check=True)
    url = result.stdout.strip().splitlines()[-1]
    return _parse_ssh_url(url)


def fetch(
    *,
    instance_id: str | int,
    zone: str,
    track: str,
    dataset_name: str | None = None,
    remote_results_dir: str = "/workspace/results",
    target_dir: Path | None = None,
) -> Path:
    user_host, port = _get_ssh_target(instance_id)

    timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{dataset_name}" if dataset_name else ""
    target = (target_dir or (RUNS_DIR / f"{timestamp}-{zone}-{track}{suffix}")).resolve()
    target.mkdir(parents=True, exist_ok=True)

    ssh_opts = ["-p", str(port), "-o", "StrictHostKeyChecking=accept-new"]
    rsync_cmd = [
        "rsync",
        "-avz",
        "-e",
        f"ssh {' '.join(ssh_opts)}",
        f"{user_host}:{remote_results_dir}/",
        str(target) + "/",
    ]
    if shutil.which("rsync"):
        print(f"Fetching {user_host}:{remote_results_dir}/ → {target}/", file=sys.stderr)
        _run(rsync_cmd, check=True, capture=False)
    else:
        scp_cmd = [
            "scp",
            "-r",
            *ssh_opts,
            f"{user_host}:{remote_results_dir}/",
            str(target) + "/",
        ]
        print(f"[scp fallback] fetching → {target}/", file=sys.stderr)
        _run(scp_cmd, check=True, capture=False)

    (target / "fetch_metadata.json").write_text(
        json.dumps(
            {
                "instance_id": str(instance_id),
                "remote_results_dir": remote_results_dir,
                "zone": zone,
                "track": track,
                "dataset_name": dataset_name,
                "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"Done → {target}", file=sys.stderr)
    return target
