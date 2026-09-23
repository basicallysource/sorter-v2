"""Service module for browsing and downloading Hive detection models.

Exposes a tiny service layer around the ``HiveClient`` shipped in
``software/hive/sorter-client`` so the sorter UI can browse the Hive catalog,
trigger downloads, and manage installed models locally: Hive downloads, and
local models someone put in ``LOCAL_MODELS_DIR`` by hand.

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
from typing import Any, Callable

from blob_manager import getHiveConfig

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

# The one place installed models live, one directory each: Hive downloads
# (``hive-<model_id>-<runtime>``) and local models put here by hand.
LOCAL_MODELS_DIR: Path = (
    Path(__file__).resolve().parent.parent / "blob" / "hive_detection_models"
)

# Key embedded in a synthesized ``run.json`` to mark a directory as
# originating from Hive. A directory without it is a local model when its
# run.json says enough to load it (``vision.detection_registry.local_model_artifact``).
HIVE_SENTINEL_KEY = "hive"

# Variant runtimes the sorter can actually load via the detection registry.
# Anything else (notably ``pytorch``) shows up in the catalog but cannot be
# activated — we filter those out of the auto-download and mark them
# ``compatible: False`` in the installed list so the UI can disable Activate.
DEPLOYABLE_RUNTIMES: frozenset[str] = frozenset({"onnx", "ncnn", "hailo", "rknn"})

# What a model is FOR. Hive publishes this per model; the download/install path
# is identical across purposes and only the consumer differs. Models installed
# before Hive grew the field predate any non-detection purpose, so absence reads
# as ``detection``.
PURPOSE_DETECTION = "detection"
PURPOSE_PIECE_LINK = "piece_link"
DEFAULT_PURPOSE = PURPOSE_DETECTION
# Purposes nothing on the machine consumes yet. They install and sit inert; the
# UI greys them out rather than offering an Activate that would do nothing.
INERT_PURPOSES: frozenset[str] = frozenset({PURPOSE_PIECE_LINK})


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
    raw = getHiveConfig()
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
_HAS_RKNN_NPU_CACHE: bool | None = None


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


def _has_rknn_npu() -> bool:
    """True when the RK3588-class NPU + librknnrt are present.

    Checked once per process — the kernel driver doesn't appear at runtime.
    Does NOT verify the Python bindings (``rknn-toolkit-lite2``); that gets
    surfaced separately by the runtimes/capabilities probe.
    """
    global _HAS_RKNN_NPU_CACHE
    if _HAS_RKNN_NPU_CACHE is None:
        _HAS_RKNN_NPU_CACHE = (
            Path("/sys/kernel/debug/rknpu/version").exists()
            or Path("/usr/lib/librknnrt.so").exists()
        )
    return _HAS_RKNN_NPU_CACHE


def _reset_hailo_cache_for_tests() -> None:
    global _HAS_HAILO_CACHE
    _HAS_HAILO_CACHE = None


def compatible_runtimes_for_this_machine() -> list[str]:
    """Deployable runtimes this machine can run, best first.

    ``hailo`` when a Hailo device is present, ``rknn`` when the RK3588 NPU is,
    then ``ncnn`` before ``onnx`` on ARM and ``onnx`` before ``ncnn`` elsewhere.
    """
    runtimes: list[str] = []
    if _has_hailo():
        runtimes.append("hailo")
    if _has_rknn_npu():
        runtimes.append("rknn")
    on_arm = platform.machine().lower() in {"aarch64", "armv7l", "arm64"}
    runtimes.extend(("ncnn", "onnx") if on_arm else ("onnx", "ncnn"))
    return runtimes


def pick_runtime_for_this_machine(variant_runtimes: list[str]) -> str | None:
    """Pick the best runtime available for the local hardware.

    The first of ``compatible_runtimes_for_this_machine()`` that is offered;
    otherwise ``hailo``, then ``pytorch``, then whatever was offered first.

    Returns ``None`` when ``variant_runtimes`` is empty.
    """
    if not variant_runtimes:
        return None
    runtimes = set(variant_runtimes)
    for candidate in (*compatible_runtimes_for_this_machine(), "hailo", "pytorch"):
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


def _dir_size(path: Path) -> int:
    size_bytes = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                size_bytes += child.stat().st_size
            except OSError:
                pass
    return size_bytes


def _local_model_entry(child: Path, payload: dict) -> dict | None:
    from vision.detection_registry import LOCAL_ID_PREFIX, local_model_artifact

    found = local_model_artifact(child, payload)
    if found is None:
        return None
    runtime, _artifact = found
    trained_at = payload.get("trained_at") or payload.get("created_at")
    return {
        "local_id": child.name,
        "algorithm_id": f"{LOCAL_ID_PREFIX}{child.name}",
        "source": "local",
        "target_id": None,
        "model_id": None,
        "codename": None,
        "codename_color": None,
        "variant_runtime": runtime,
        "purpose": DEFAULT_PURPOSE,
        "inert": False,
        "sha256": None,
        "downloaded_at": None,
        "source_url": None,
        "installed_as_default": False,
        "trained_at": trained_at if isinstance(trained_at, str) else None,
        "name": payload.get("name") or child.name,
        "model_family": payload.get("model_family"),
        "size_bytes": _dir_size(child),
        "path": str(child),
        "compatible": True,
    }


def _hive_model_entry(child: Path, payload: dict, hive_meta: dict) -> dict:
    from vision.detection_registry import HIVE_ID_PREFIX

    # Surface ``trained_at`` (preferred), falling back to ``created_at`` or
    # ``hive.published_at`` so the UI can show how fresh the model itself
    # is — distinct from when the operator pulled it.
    trained_at = (
        payload.get("trained_at")
        or payload.get("created_at")
        or hive_meta.get("published_at")
    )

    variant_runtime = hive_meta.get("variant_runtime")
    raw_purpose = hive_meta.get("purpose")
    purpose = raw_purpose if isinstance(raw_purpose, str) and raw_purpose else DEFAULT_PURPOSE
    compatible = (
        isinstance(variant_runtime, str)
        and variant_runtime.lower() in DEPLOYABLE_RUNTIMES
        # An inert-purpose model is installed correctly but has no consumer
        # on the machine yet, so it can't be activated against a scope.
        and purpose not in INERT_PURPOSES
    )

    return {
        "local_id": child.name,
        "algorithm_id": f"{HIVE_ID_PREFIX}{child.name}",
        "source": "hive",
        "target_id": hive_meta.get("target_id"),
        "model_id": hive_meta.get("model_id"),
        # Hive's human-friendly handle ("Ember") and its swatch color,
        # captured at download time so the installed list can identify a
        # model the same way Hive does without going back to the network.
        # Absent for installs that predate this field — see
        # ``_backfill_codenames``.
        "codename": hive_meta.get("codename"),
        "codename_color": hive_meta.get("codename_color"),
        "variant_runtime": variant_runtime,
        "purpose": purpose,
        "inert": purpose in INERT_PURPOSES,
        "sha256": hive_meta.get("sha256"),
        "downloaded_at": hive_meta.get("downloaded_at"),
        # The Hive it was downloaded from. Recorded since the default-model
        # install, which has no configured target to name the Hive by.
        "source_url": hive_meta.get("source_url"),
        # Installed by server.default_model as Hive's default for this machine.
        "installed_as_default": bool(hive_meta.get("installed_as_default")),
        "trained_at": trained_at if isinstance(trained_at, str) else None,
        "name": payload.get("name"),
        "model_family": payload.get("model_family"),
        "size_bytes": _dir_size(child),
        "path": str(child),
        "compatible": compatible,
    }


def list_installed_models() -> list[dict]:
    """Every model installed in ``LOCAL_MODELS_DIR``.

    Hive downloads carry ``source: "hive"`` and algorithm id ``hive:<local_id>``;
    models put there by hand carry ``source: "local"`` and ``local:<local_id>``.
    Both are removable.
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
        if isinstance(hive_meta, dict):
            results.append(_hive_model_entry(child, payload, hive_meta))
            continue
        local_entry = _local_model_entry(child, payload)
        if local_entry is not None:
            results.append(local_entry)
    return results


def _same_hive(a: Any, b: Any) -> bool:
    return isinstance(a, str) and isinstance(b, str) and bool(a) and a.rstrip("/") == b.rstrip("/")


def _installed_model_ids(target: dict, entries: list[dict]) -> set[str]:
    """Model ids from ``target`` that are installed: downloaded through that
    target, or from the same Hive without one (the default-model install)."""
    return {
        entry["model_id"]
        for entry in entries
        if isinstance(entry.get("model_id"), str)
        and (
            entry.get("target_id") == target.get("id")
            or _same_hive(entry.get("source_url"), target.get("url"))
        )
    }


def _backfill_codenames(target_id: str, items: list[dict], entries: list[dict]) -> None:
    """Write codenames into run.json for installs that predate the field.

    Downloads have carried ``codename`` / ``codename_color`` in their run.json
    since those became part of the Hive payload, but anything installed before
    then knows only its model id. Rather than spend a network call on the
    Installed tab — which otherwise works with no Hive reachable — we top those
    entries up opportunistically while browsing the catalog, where the answer is
    already in hand. Best-effort: a run.json we cannot rewrite is left alone and
    retried on the next browse.
    """
    stale = [
        entry
        for entry in entries
        if not entry.get("codename")
        and entry.get("target_id") == target_id
    ]
    if not stale:
        return

    by_model_id = {
        item["id"]: item
        for item in items
        if isinstance(item.get("id"), str) and isinstance(item.get("codename"), str)
    }
    for entry in stale:
        remote = by_model_id.get(entry.get("model_id"))
        if remote is None:
            continue
        run_path = Path(entry["path"]) / "run.json"
        payload = _read_run_json(run_path)
        if payload is None or not isinstance(payload.get(HIVE_SENTINEL_KEY), dict):
            continue
        payload[HIVE_SENTINEL_KEY]["codename"] = remote.get("codename")
        payload[HIVE_SENTINEL_KEY]["codename_color"] = remote.get("codename_color")
        try:
            tmp_path = run_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
            os.replace(tmp_path, run_path)
        except OSError:
            log.debug("codename backfill failed for %s", run_path, exc_info=True)


def list_remote_models(target_id: str, **filters: Any) -> dict:
    """Fetch the remote model catalog for ``target_id`` and tag installs."""
    client, target = _get_client_for_target(target_id)
    page = client.list_models(**filters)

    # One scan feeds both the installed tagging and the codename backfill —
    # walking the model dirs means stat'ing every weight file, so don't do it
    # twice per browse.
    entries = list_installed_models()
    installed = _installed_model_ids(target, entries)
    items = page.get("items") if isinstance(page, dict) else None
    if isinstance(items, list):
        dicts = [item for item in items if isinstance(item, dict)]
        for item in dicts:
            item["installed"] = item.get("id") in installed
            item["target_id"] = target_id
            item["target_url"] = target.get("url")
            item["target_name"] = target.get("name")
        _backfill_codenames(target_id, dicts, entries)
    return page


def list_remote_models_all(**filters: Any) -> dict:
    """Aggregate the model catalog across every enabled Hive target.

    Each item is tagged with ``target_id`` / ``target_url`` / ``target_name``
    so the UI (and downstream download calls) can tell where it came from.
    Per-target failures are reported under ``errors`` so one unreachable Hive
    doesn't blank the entire list.
    """
    page = max(1, int(filters.pop("page", 1) or 1))
    page_size = max(1, int(filters.pop("page_size", 30) or 30))
    # Fetch up to (page * page_size) from each target so we can sort + slice
    # the combined view; gives us deterministic pagination without hammering.
    per_target_limit = max(page_size, page * page_size)
    per_target_filters = {**filters, "page": 1, "page_size": min(200, per_target_limit)}

    aggregated: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for target in resolve_targets():
        try:
            target_page = list_remote_models(target["id"], **per_target_filters)
        except Exception as exc:
            errors.append({"target_id": target["id"], "target_url": target.get("url") or "", "error": str(exc)})
            continue
        items = target_page.get("items") if isinstance(target_page, dict) else None
        if isinstance(items, list):
            aggregated.extend(item for item in items if isinstance(item, dict))

    def _published_key(item: dict[str, Any]) -> str:
        value = item.get("published_at")
        return value if isinstance(value, str) else ""

    aggregated.sort(key=_published_key, reverse=True)
    total = len(aggregated)
    pages = (total + page_size - 1) // page_size if total else 1
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": aggregated[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, pages),
        "errors": errors,
    }


def get_remote_model(target_id: str, model_id: str) -> dict:
    """Fetch a single model's detail and tag whether it's already installed."""
    client, target = _get_client_for_target(target_id)
    detail = client.get_model(model_id)
    if isinstance(detail, dict):
        detail["installed"] = model_id in _installed_model_ids(target, list_installed_models())
    return detail


def remove_installed_model(local_id: str) -> None:
    """Delete an installed model directory under ``LOCAL_MODELS_DIR``.

    ``local_id`` must be a single path component (no traversal). Raises
    ``ValueError`` on invalid ids and ``FileNotFoundError`` when the directory
    does not exist. Hive downloads and local models are removed the same way.
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
        from vision.detection_registry import invalidate_registry
        invalidate_registry()
    except Exception:
        log.debug("registry invalidation after remove failed", exc_info=True)


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
        v.get("runtime")
        for v in normalized
        if isinstance(v.get("runtime"), str)
        and v.get("runtime").lower() in DEPLOYABLE_RUNTIMES
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
        # Notified on every job update, so a waiter sleeps until one happens.
        self._changed = threading.Condition(self._lock)
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

    def enqueue_all_deployable_variants(
        self, target_id: str, model_id: str
    ) -> list[str]:
        """Enqueue one job per *deployable* variant runtime in parallel.

        Each variant lands in its own ``hive-<model_id>-<runtime>`` directory
        so the operator can later activate any of them independently. Pytorch
        and any other non-deployable runtime is skipped — the sorter cannot
        load them anyway.
        """
        try:
            client, _target = _get_client_for_target(target_id)
            detail = client.get_model(model_id)
        except Exception as exc:
            return [self._record_failure(target_id, model_id, None, str(exc))]

        variants = detail.get("variants") if isinstance(detail, dict) else None
        runtimes: list[str] = []
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict) and isinstance(variant.get("runtime"), str):
                    runtimes.append(variant["runtime"])

        deployable = [r for r in runtimes if r.lower() in DEPLOYABLE_RUNTIMES]
        if not deployable:
            offered = ", ".join(runtimes) if runtimes else "none"
            return [
                self._record_failure(
                    target_id,
                    model_id,
                    None,
                    f"no deployable variants for this sorter (offered: {offered})",
                )
            ]
        return [self.enqueue(target_id, model_id, runtime) for runtime in deployable]

    def enqueue_default(self, purpose: str, runtime: str, item: dict, base_url: str) -> str:
        """Queue the download of Hive's default ``purpose`` model for ``runtime``.

        ``item`` is Hive's answer to ``GET /api/model-defaults/{purpose}/{runtime}``
        (its ``model`` and ``variant``); ``base_url`` is that Hive. The file
        lands in the same ``hive-<model_id>-<runtime>`` directory a manual
        download would, and shows in the same downloads list.
        """
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        variant = item.get("variant") if isinstance(item.get("variant"), dict) else {}
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id:
            return self._record_failure(None, "", runtime, "Hive's default names no model id")
        job_id = uuid.uuid4().hex
        now = _now_iso()
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "target_id": None,
                "model_id": model_id,
                "variant_runtime": runtime,
                "variant_id": variant.get("id"),
                "file_name": variant.get("file_name") or f"{model_id}-{runtime}.bin",
                "total_bytes": int(variant.get("file_size") or 0),
                "progress_bytes": 0,
                "error": None,
                "created_at": now,
                "updated_at": now,
                "model_detail": {**model, "purpose": model.get("purpose") or purpose},
                "variant": {**variant, "runtime": runtime},
                "default_source": {"purpose": purpose, "runtime": runtime, "url": base_url},
            }
        self._queue.put(job_id)
        return job_id

    def _record_failure(
        self,
        target_id: str | None,
        model_id: str,
        variant_runtime: str | None,
        error: str,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = _now_iso()
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
                "error": error,
                "created_at": now,
                "updated_at": now,
            }
        return job_id

    def snapshot(self) -> list[dict]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        # Strip heavy internal fields; keep UI payload small and stable.
        for job in jobs:
            job.pop("model_detail", None)
            job.pop("variant", None)
            job.pop("default_source", None)
        jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        return jobs

    def wait_for_terminal(self, job_id: str, timeout: float = 5.0) -> dict:
        """Block until ``job_id`` reaches ``done``/``failed`` or ``timeout``
        passes; returns the job as it stands then."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while True:
                job = self._jobs.get(job_id)
                if job is not None and job.get("status") in {"done", "failed"}:
                    return dict(job)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return dict(job or {})
                self._changed.wait(remaining)

    # -- internals ---------------------------------------------------------

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            job["updated_at"] = _now_iso()
            self._changed.notify_all()

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
        default_source = snapshot.get("default_source")
        variant_id = variant.get("id")
        runtime = variant.get("runtime")
        file_name = snapshot.get("file_name") or "model.bin"
        expected_sha = variant.get("sha256") if isinstance(variant.get("sha256"), str) else None

        try:
            if default_source is not None:
                # Hive's public default needs no account, so no target.
                client = HiveClient(default_source["url"])
                source_url = default_source["url"]
            else:
                client, target = _get_client_for_target(target_id)
                source_url = target.get("url")
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))
            return

        # One directory per (model_id, variant_runtime) so simultaneous
        # downloads of multiple deployable formats coexist instead of
        # clobbering each other's run.json. The variant_runtime is the
        # actual format the worker is downloading right now.
        dest_dir = LOCAL_MODELS_DIR / f"hive-{model_id}-{runtime}"
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
            if default_source is not None:
                digest = client.download_default_model(
                    default_source["purpose"],
                    default_source["runtime"],
                    dest_path,
                    on_progress=_on_progress,
                    expected_sha256=expected_sha,
                )
            else:
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

        # Post-processing: extract tarballs so the model is usable in-place.
        # ncnn always ships this way; a piece_link model ships its encoder+head
        # pair as one onnx-runtime tarball. Gate on the file, not the runtime —
        # a plain single-file artifact is never a tarball.
        if self._looks_like_tarball(dest_path):
            try:
                self._safe_extract_tarball(dest_path, exports_dir)
            except Exception as exc:
                self._update(
                    job_id,
                    status="failed",
                    error=f"{runtime} extraction failed: {exc}",
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
                variant=variant,
                purpose=detail.get("purpose") if isinstance(detail, dict) else None,
                source_url=source_url,
                installed_as_default=default_source is not None,
            )
        except Exception as exc:
            self._update(job_id, status="failed", error=f"run.json write failed: {exc}")
            return

        # Rescan before reporting done, so whoever waits on the job can
        # resolve the new model's algorithm id straight away.
        try:
            from vision.detection_registry import invalidate_registry
            invalidate_registry()
        except Exception:
            log.debug("registry invalidation after download failed", exc_info=True)
        self._update(
            job_id,
            status="done",
            progress_bytes=int(dest_path.stat().st_size) if dest_path.exists() else snapshot.get("progress_bytes", 0),
        )

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
        target_id: str | None,
        model_id: str,
        variant_runtime: str | None,
        sha256: str,
        detail: dict,
        variant: dict | None = None,
        purpose: str | None = None,
        source_url: str | None = None,
        installed_as_default: bool = False,
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
        # Variant-level format_meta.label appends to the model name so the UI
        # surfaces operator-flagged caveats (e.g. "_MEDIOCRE_CONVERSION") in
        # the algorithm picker dropdown.
        variant_label: str | None = None
        if isinstance(variant, dict):
            meta = variant.get("format_meta")
            if isinstance(meta, dict):
                candidate = meta.get("label")
                if isinstance(candidate, str) and candidate.strip():
                    variant_label = candidate.strip()
        if isinstance(name, str) and name:
            base["name"] = f"{name} · {variant_label}" if variant_label else name
        model_family = detail.get("model_family") if isinstance(detail, dict) else None
        if isinstance(model_family, str) and model_family:
            base["model_family"] = model_family
        if variant_runtime and "runtime" not in base:
            base["runtime"] = variant_runtime

        codename = detail.get("codename") if isinstance(detail, dict) else None
        codename_color = detail.get("codename_color") if isinstance(detail, dict) else None

        base[HIVE_SENTINEL_KEY] = {
            "target_id": target_id,
            "model_id": model_id,
            "variant_runtime": variant_runtime,
            "purpose": purpose or DEFAULT_PURPOSE,
            "sha256": sha256,
            "downloaded_at": _now_iso(),
            "source_url": source_url,
            "installed_as_default": installed_as_default,
            # Carried over so the installed list can show the same identity Hive
            # does (codename + color swatch) with no network round-trip.
            "codename": codename if isinstance(codename, str) and codename else None,
            "codename_color": (
                codename_color if isinstance(codename_color, str) and codename_color else None
            ),
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
    "DEPLOYABLE_RUNTIMES",
    "HIVE_SENTINEL_KEY",
    "LOCAL_MODELS_DIR",
    "DownloadJobManager",
    "compatible_runtimes_for_this_machine",
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
