"""Service module for browsing and downloading Hive detection models.

Exposes a tiny service layer around the ``HiveClient`` shipped in
``software/hive/sorter-client`` so the sorter UI can browse the Hive catalog,
trigger downloads, and manage installed (downloaded) models locally.

Downloads are handled by a single daemon worker thread reading from a
``queue.Queue``; progress is reported through an in-memory status dict keyed by
a generated ``job_id`` so the UI can poll.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import shutil
import sys
import tarfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from local_state import get_hive_config

# ---------------------------------------------------------------------------
# Locate the Hive sorter-client package (hive_client.py)
# ---------------------------------------------------------------------------
#
# The sorter backend does not install the Hive client as a package; instead the
# sibling directory ``software/hive/sorter-client/`` lives alongside the sorter
# tree. Inject it onto ``sys.path`` once so ``import hive_client`` resolves.
_HIVE_CLIENT_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "hive" / "sorter-client"
)
if _HIVE_CLIENT_DIR.exists():
    _hive_client_path = str(_HIVE_CLIENT_DIR)
    if _hive_client_path not in sys.path:
        sys.path.insert(0, _hive_client_path)

from hive_client import HiveClient, HiveError  # noqa: E402

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

LOCAL_MODELS_DIR: Path = (
    Path(__file__).resolve().parent.parent / "blob" / "hive_detection_models"
)

# Key embedded in a synthesized ``run.json`` to mark a directory as
# originating from Hive. Presence of this key means the model was downloaded
# via this module and can be safely listed/removed.
HIVE_SENTINEL_KEY = "hive"


def set_local_models_dir(path: Path) -> None:
    """Test hook: override the installation directory at runtime.

    The ``DownloadJobManager`` singleton caches nothing that depends on this
    path, so monkeypatching directly on the module or calling this helper are
    equivalent.
    """
    global LOCAL_MODELS_DIR
    LOCAL_MODELS_DIR = Path(path)


# ---------------------------------------------------------------------------
# Hive target resolution
# ---------------------------------------------------------------------------


def resolve_targets() -> list[dict]:
    """Return enabled Hive targets with full secrets.

    Disabled targets (``enabled: False``) are dropped. Only sorter-local code
    should ever call this directly; the HTTP layer must hand out redacted
    copies without ``api_token``.
    """
    raw = get_hive_config()
    if not isinstance(raw, dict):
        return []
    targets = raw.get("targets")
    if not isinstance(targets, list):
        return []

    resolved: list[dict] = []
    for entry in targets:
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled", True):
            continue
        target_id = entry.get("id")
        url = entry.get("url")
        api_token = entry.get("api_token")
        if not isinstance(target_id, str) or not target_id:
            continue
        if not isinstance(url, str) or not url:
            continue
        if not isinstance(api_token, str) or not api_token:
            continue
        resolved.append(
            {
                "id": target_id,
                "name": entry.get("name") if isinstance(entry.get("name"), str) else url,
                "url": url,
                "api_token": api_token,
                "machine_id": entry.get("machine_id") if isinstance(entry.get("machine_id"), str) else None,
            }
        )
    return resolved


def _get_client_for_target(target_id: str) -> tuple[HiveClient, dict]:
    """Look up an enabled target and build a fresh ``HiveClient`` for it.

    Raises ``ValueError("unknown target")`` when the target is missing or
    disabled — callers can surface this as a 400/404 depending on context.
    """
    for target in resolve_targets():
        if target["id"] == target_id:
            return HiveClient(target["url"], target["api_token"]), target
    raise ValueError("unknown target")


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------

_HAS_HAILO_CACHE: bool | None = None


def _has_hailo() -> bool:
    """True if a Hailo accelerator appears to be present on this machine.

    Result is cached at module level since the hardware cannot appear/vanish
    without a reboot.
    """
    global _HAS_HAILO_CACHE
    if _HAS_HAILO_CACHE is None:
        _HAS_HAILO_CACHE = (
            Path("/dev/hailo0").exists() or Path("/sys/class/misc/hailo0").exists()
        )
    return _HAS_HAILO_CACHE


def _reset_hailo_cache_for_tests() -> None:
    global _HAS_HAILO_CACHE
    _HAS_HAILO_CACHE = None


def pick_runtime_for_this_machine(variant_runtimes: list[str]) -> str | None:
    """Pick the best runtime available for the local hardware.

    Priority:
      1. ``hailo`` when a Hailo device is present and offered
      2. ``ncnn`` on ARM (aarch64/armv7l) when offered
      3. ``onnx`` otherwise when offered
      4. ``pytorch`` only as a last-resort fallback

    Returns ``None`` when ``variant_runtimes`` is empty.
    """
    if not variant_runtimes:
        return None
    runtimes = set(variant_runtimes)

    if "hailo" in runtimes and _has_hailo():
        return "hailo"

    machine = platform.machine().lower()
    on_arm = machine in {"aarch64", "armv7l", "arm64"}
    if on_arm and "ncnn" in runtimes:
        return "ncnn"

    if "onnx" in runtimes:
        return "onnx"

    # Fallback order when none of the preferred runtimes are present.
    for candidate in ("ncnn", "hailo", "pytorch"):
        if candidate in runtimes:
            return candidate

    # variant_runtimes had at least one entry but none matched known runtimes.
    return variant_runtimes[0]


# ---------------------------------------------------------------------------
# Installed-model discovery
# ---------------------------------------------------------------------------


def _read_run_json(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _installed_variant_runtimes(model_dir: Path) -> list[str]:
    """Return artifact runtimes that are present in an installed model dir."""
    exports = model_dir / "exports"
    if not exports.exists():
        return []

    runtimes: list[str] = []
    if any(exports.rglob("*.onnx")):
        runtimes.append("onnx")
    if any(exports.rglob("*.param")) and any(exports.rglob("*.bin")):
        runtimes.append("ncnn")
    if any(exports.rglob("*.hef")):
        runtimes.append("hailo")
    if any(exports.rglob("*.pt")):
        runtimes.append("pytorch")
    return runtimes


def list_installed_models() -> list[dict]:
    """Scan ``LOCAL_MODELS_DIR`` for previously-downloaded Hive models.

    Directories are considered "installed from Hive" when their ``run.json``
    contains the ``HIVE_SENTINEL_KEY`` key. Directories without ``run.json``,
    with a corrupt ``run.json``, or without the sentinel are silently skipped
    so we don't clobber locally-trained model directories.
    """
    results: list[dict] = []
    if not LOCAL_MODELS_DIR.exists():
        return results

    for child in sorted(LOCAL_MODELS_DIR.iterdir()):
        if not child.is_dir():
            continue
        run_json = child / "run.json"
        if not run_json.exists():
            continue
        payload = _read_run_json(run_json)
        if payload is None:
            continue
        hive_meta = payload.get(HIVE_SENTINEL_KEY)
        if not isinstance(hive_meta, dict):
            continue

        active_runtime = hive_meta.get("variant_runtime")
        available_runtimes = _installed_variant_runtimes(child)
        if isinstance(active_runtime, str) and active_runtime not in available_runtimes:
            available_runtimes.insert(0, active_runtime)

        size_bytes = 0
        for path in child.rglob("*"):
            if path.is_file():
                try:
                    size_bytes += path.stat().st_size
                except OSError:
                    pass

        results.append(
            {
                "local_id": child.name,
                "target_id": hive_meta.get("target_id"),
                "model_id": hive_meta.get("model_id"),
                "variant_runtime": active_runtime,
                "available_variant_runtimes": available_runtimes,
                "sha256": hive_meta.get("sha256"),
                "downloaded_at": hive_meta.get("downloaded_at"),
                "name": payload.get("name"),
                "model_family": payload.get("model_family"),
                "size_bytes": size_bytes,
                "path": str(child),
            }
        )
    return results


def _installed_index() -> set[tuple[str, str]]:
    index: set[tuple[str, str]] = set()
    for installed in list_installed_models():
        target_id = installed.get("target_id")
        model_id = installed.get("model_id")
        if isinstance(target_id, str) and isinstance(model_id, str):
            index.add((target_id, model_id))
    return index


def list_remote_models(target_id: str, **filters: Any) -> dict:
    """Fetch the remote model catalog for ``target_id`` and tag installs."""
    client, _target = _get_client_for_target(target_id)
    page = client.list_models(**filters)

    installed = _installed_index()
    items = page.get("items") if isinstance(page, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str):
                item["installed"] = (target_id, model_id) in installed
            else:
                item["installed"] = False
    return page


def get_remote_model(target_id: str, model_id: str) -> dict:
    """Fetch a single model's detail and tag whether it's already installed."""
    client, _target = _get_client_for_target(target_id)
    detail = client.get_model(model_id)
    if isinstance(detail, dict):
        detail["installed"] = (target_id, model_id) in _installed_index()
    return detail


def remove_installed_model(local_id: str) -> None:
    """Delete an installed model directory under ``LOCAL_MODELS_DIR``.

    ``local_id`` must be a single path component (no traversal). Raises
    ``ValueError`` on invalid ids and ``FileNotFoundError`` when the directory
    does not exist.
    """
    if not isinstance(local_id, str) or not local_id:
        raise ValueError("local_id must be a non-empty string")
    if Path(local_id).name != local_id or local_id in (".", ".."):
        raise ValueError("local_id must be a single path component")

    target = LOCAL_MODELS_DIR / local_id
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"installed model not found: {local_id}")
    # Belt-and-suspenders: ensure the resolved path is still within
    # LOCAL_MODELS_DIR before rm -rf.
    resolved = target.resolve()
    models_root = LOCAL_MODELS_DIR.resolve()
    if models_root not in resolved.parents and resolved != models_root:
        raise ValueError("local_id resolves outside LOCAL_MODELS_DIR")
    shutil.rmtree(target)
    try:
        from rt.perception.detector_metadata import invalidate_cache
        invalidate_cache()
    except Exception:
        log.debug("detector metadata invalidation after remove failed", exc_info=True)


# ---------------------------------------------------------------------------
# Download worker
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_variant(detail: dict, requested_runtime: str | None) -> dict | None:
    variants = detail.get("variants") if isinstance(detail, dict) else None
    if not isinstance(variants, list) or not variants:
        return None
    normalized: list[dict] = [v for v in variants if isinstance(v, dict)]
    if not normalized:
        return None

    if requested_runtime:
        for variant in normalized:
            if variant.get("runtime") == requested_runtime:
                return variant
        return None

    runtimes = [
        v.get("runtime") for v in normalized if isinstance(v.get("runtime"), str)
    ]
    chosen = pick_runtime_for_this_machine(runtimes)
    if chosen is None:
        return None
    for variant in normalized:
        if variant.get("runtime") == chosen:
            return variant
    return None


class DownloadJobManager:
    """Single-worker download queue shared across the FastAPI process.

    Jobs are serialized through a ``queue.Queue`` to keep at most one active
    download — the Hive API streams large artifacts and we don't want to
    saturate bandwidth or disk IO.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="hive-model-downloader"
        )
        self._worker.start()

    # -- public API --------------------------------------------------------

    def enqueue(
        self,
        target_id: str,
        model_id: str,
        variant_runtime: str | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = _now_iso()

        try:
            client, _target = _get_client_for_target(target_id)
            detail = client.get_model(model_id)
        except Exception as exc:
            with self._lock:
                self._jobs[job_id] = {
                    "job_id": job_id,
                    "status": "failed",
                    "target_id": target_id,
                    "model_id": model_id,
                    "variant_runtime": variant_runtime,
                    "variant_id": None,
                    "file_name": None,
                    "total_bytes": 0,
                    "progress_bytes": 0,
                    "error": str(exc),
                    "created_at": now,
                    "updated_at": now,
                }
            return job_id

        variant = _pick_variant(detail, variant_runtime)
        if variant is None:
            with self._lock:
                self._jobs[job_id] = {
                    "job_id": job_id,
                    "status": "failed",
                    "target_id": target_id,
                    "model_id": model_id,
                    "variant_runtime": variant_runtime,
                    "variant_id": None,
                    "file_name": None,
                    "total_bytes": 0,
                    "progress_bytes": 0,
                    "error": "no variant for this hardware",
                    "created_at": now,
                    "updated_at": now,
                    "model_detail": detail,
                }
            return job_id

        file_name = variant.get("file_name") or f"{model_id}-{variant.get('runtime')}.bin"
        total_bytes = int(variant.get("file_size") or 0)

        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "target_id": target_id,
                "model_id": model_id,
                "variant_runtime": variant.get("runtime"),
                "variant_id": variant.get("id"),
                "file_name": file_name,
                "total_bytes": total_bytes,
                "progress_bytes": 0,
                "error": None,
                "created_at": now,
                "updated_at": now,
                "model_detail": detail,
                "variant": variant,
            }
        self._queue.put(job_id)
        return job_id

    def snapshot(self) -> list[dict]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        # Strip heavy internal fields; keep UI payload small and stable.
        for job in jobs:
            job.pop("model_detail", None)
            job.pop("variant", None)
        jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        return jobs

    def wait_for_terminal(self, job_id: str, timeout: float = 5.0) -> dict:
        """Test helper: block until ``job_id`` reaches ``done``/``failed``."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None and job.get("status") in {"done", "failed"}:
                    return dict(job)
            time.sleep(0.02)
        with self._lock:
            return dict(self._jobs.get(job_id) or {})

    # -- internals ---------------------------------------------------------

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            job["updated_at"] = _now_iso()

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._process(job_id)
            except Exception:  # pragma: no cover - defensive logging
                log.exception("hive download worker crashed on job %s", job_id)
                self._update(job_id, status="failed", error="internal error")

    def _process(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            snapshot = dict(job)

        target_id = snapshot["target_id"]
        model_id = snapshot["model_id"]
        variant = snapshot.get("variant") or {}
        detail = snapshot.get("model_detail") or {}
        variant_id = variant.get("id")
        runtime = variant.get("runtime")
        file_name = snapshot.get("file_name") or "model.bin"
        expected_sha = variant.get("sha256") if isinstance(variant.get("sha256"), str) else None

        try:
            client, _target = _get_client_for_target(target_id)
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))
            return

        dest_dir = LOCAL_MODELS_DIR / f"hive-{model_id}"
        exports_dir = dest_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        dest_path = exports_dir / file_name

        self._update(job_id, status="downloading")

        def _on_progress(written: int, total: int) -> None:
            # Hive streams with a Content-Length header; fall back to the
            # variant's declared size when the transfer encoding omits it.
            fields: dict[str, Any] = {"progress_bytes": int(written)}
            if total:
                fields["total_bytes"] = int(total)
            self._update(job_id, **fields)

        try:
            digest = client.download_model_variant(
                model_id,
                variant_id,
                dest_path,
                on_progress=_on_progress,
                expected_sha256=expected_sha,
            )
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))
            return

        # Post-processing: extract ncnn tarballs so the model is usable in-place.
        if runtime == "ncnn" and self._looks_like_tarball(dest_path):
            try:
                self._safe_extract_tarball(dest_path, exports_dir)
            except Exception as exc:
                self._update(
                    job_id,
                    status="failed",
                    error=f"ncnn extraction failed: {exc}",
                )
                return

        try:
            self._write_run_json(
                dest_dir=dest_dir,
                target_id=target_id,
                model_id=model_id,
                variant_runtime=runtime,
                sha256=digest,
                detail=detail,
            )
        except Exception as exc:
            self._update(job_id, status="failed", error=f"run.json write failed: {exc}")
            return

        self._update(
            job_id,
            status="done",
            progress_bytes=int(dest_path.stat().st_size) if dest_path.exists() else snapshot.get("progress_bytes", 0),
        )
        try:
            from rt.perception.detectors.hive_onnx import discover_and_register_hive_detectors
            from rt.perception.detector_metadata import invalidate_cache

            discover_and_register_hive_detectors()
            invalidate_cache()
        except Exception:
            log.debug("detector metadata invalidation after download failed", exc_info=True)

    @staticmethod
    def _looks_like_tarball(path: Path) -> bool:
        name = path.name.lower()
        if name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar"):
            return True
        try:
            return tarfile.is_tarfile(path)
        except Exception:
            return False

    @staticmethod
    def _safe_extract_tarball(archive_path: Path, dest_dir: Path) -> None:
        dest_root = dest_dir.resolve()
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getmembers()
            for member in members:
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"unsafe archive member: {member.name}")

                resolved_target = (dest_root / Path(*member_path.parts)).resolve()
                if resolved_target != dest_root and dest_root not in resolved_target.parents:
                    raise ValueError(f"unsafe archive member: {member.name}")

            tar.extractall(dest_root, filter="data")

    @staticmethod
    def _write_run_json(
        *,
        dest_dir: Path,
        target_id: str,
        model_id: str,
        variant_runtime: str | None,
        sha256: str,
        detail: dict,
    ) -> None:
        run_path = dest_dir / "run.json"
        # Merge with existing run.json if one was included inside a tarball.
        base: dict[str, Any] = {}
        existing = _read_run_json(run_path) if run_path.exists() else None
        if existing is not None:
            base.update(existing)

        training_metadata = detail.get("training_metadata") if isinstance(detail, dict) else None
        if isinstance(training_metadata, dict):
            for key, value in training_metadata.items():
                base.setdefault(key, value)

        name = detail.get("name") if isinstance(detail, dict) else None
        if isinstance(name, str) and name:
            base["name"] = name
        slug = detail.get("slug") if isinstance(detail, dict) else None
        if isinstance(slug, str) and slug:
            base.setdefault("run_name", slug)
        model_family = detail.get("model_family") if isinstance(detail, dict) else None
        if isinstance(model_family, str) and model_family:
            base["model_family"] = model_family
        scopes = detail.get("scopes") if isinstance(detail, dict) else None
        if isinstance(scopes, list):
            normalized_scopes = [s for s in scopes if isinstance(s, str) and s]
            if normalized_scopes:
                base["scopes"] = normalized_scopes
        if isinstance(training_metadata, dict):
            model_meta = training_metadata.get("model")
            if isinstance(model_meta, dict):
                imgsz = model_meta.get("imgsz")
                if isinstance(imgsz, int) and imgsz > 0:
                    base.setdefault("imgsz", imgsz)
        if variant_runtime and "runtime" not in base:
            base["runtime"] = variant_runtime

        version = detail.get("version") if isinstance(detail, dict) else None
        published_at = detail.get("published_at") if isinstance(detail, dict) else None

        base[HIVE_SENTINEL_KEY] = {
            "target_id": target_id,
            "model_id": model_id,
            "variant_runtime": variant_runtime,
            "sha256": sha256,
            "downloaded_at": _now_iso(),
            "version": version if isinstance(version, int) else None,
            "published_at": published_at if isinstance(published_at, str) else None,
        }

        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = run_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(base, indent=2, sort_keys=True))
        os.replace(tmp_path, run_path)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_job_manager: DownloadJobManager | None = None
_job_manager_lock = threading.Lock()


def get_job_manager() -> DownloadJobManager:
    global _job_manager
    if _job_manager is None:
        with _job_manager_lock:
            if _job_manager is None:
                _job_manager = DownloadJobManager()
    return _job_manager


def _reset_job_manager_for_tests() -> None:
    """Test hook: drop the singleton so tests start with a fresh worker."""
    global _job_manager
    with _job_manager_lock:
        _job_manager = None


__all__ = [
    "HIVE_SENTINEL_KEY",
    "LOCAL_MODELS_DIR",
    "DownloadJobManager",
    "HiveError",
    "get_job_manager",
    "get_remote_model",
    "list_installed_models",
    "list_remote_models",
    "pick_runtime_for_this_machine",
    "remove_installed_model",
    "resolve_targets",
    "set_local_models_dir",
]
