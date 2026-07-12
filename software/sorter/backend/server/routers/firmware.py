"""Control board firmware endpoints — board info, GitHub releases, UF2 flashing."""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import server.shared_state as shared_state
from hardware import firmware_flash
from hardware.bus import MCUBus, MCUDevice
from hardware.firmware_flash import FlashCancelled, FlashError

router = APIRouter()

GITHUB_REPO = "basicallysource/sorter-v2"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
RELEASES_CACHE_TTL_S = 60.0
UPLOAD_DIR = "/tmp/sorter-firmware-uploads"
MAX_UF2_SIZE_BYTES = 16 * 1024 * 1024
MAX_UPLOADS_KEPT = 8
MAX_JOBS_KEPT = 10
BOARD_PROBE_CACHE_TTL_S = 3.0

_ASSET_PATTERNS: List[tuple[re.Pattern[str], str, str, str]] = [
    (re.compile(r"^basically-v1-1-feeder-.*\.uf2$"), "basically_rp2040", "feeder-v1-1", "feeder"),
    (re.compile(r"^basically-v1-1-distribution-.*\.uf2$"), "basically_rp2040", "distribution-v1-1", "distribution"),
    (re.compile(r"^basically-v1-2-distribution-.*\.uf2$"), "basically_rp2040", "distribution-v1-2", "distribution"),
    (re.compile(r"^feeder-skr-.*\.uf2$"), "skr_pico", "feeder-skr", "feeder"),
    (re.compile(r"^distribution-skr-.*\.uf2$"), "skr_pico", "distribution-skr", "distribution"),
]

_probe_lock = threading.Lock()
_probe_cache: Dict[str, Any] = {"ts": 0.0, "boards": None}
_releases_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_uploads: Dict[str, Dict[str, Any]] = {}
_uploads_lock = threading.Lock()
_jobs: Dict[str, "FlashJob"] = {}
_jobs_order: List[str] = []
_jobs_lock = threading.Lock()
# Held by the worker for the entire flash; start uses acquire(blocking=False)
# so a second flash is rejected instead of queued behind a possibly-wedged one.
_flash_lock = threading.Lock()


class FlashRequest(BaseModel):
    source: str  # "upload" | "release"
    upload_id: Optional[str] = None
    asset_url: Optional[str] = None
    asset_name: Optional[str] = None
    release_tag: Optional[str] = None
    board_port: Optional[str] = None
    expected_device_name: Optional[str] = None
    recovery: bool = False


class FlashJob:
    def __init__(self, request: FlashRequest):
        self.id = uuid.uuid4().hex[:12]
        self.request = request
        self.created_ts = time.time()
        self.phase = "queued"
        self.progress: Optional[float] = None
        self.status = "running"  # running | done | failed | cancelled
        self.error: Optional[str] = None
        self.retryable = False
        self.log: List[str] = []
        self.result: Dict[str, Any] = {}
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()

    def setPhase(self, phase: str, message: Optional[str] = None) -> None:
        with self._lock:
            self.phase = phase
            self.progress = None
            if message:
                self.log.append(message)

    def setProgress(self, progress: float) -> None:
        with self._lock:
            self.progress = max(0.0, min(1.0, progress))

    def addLog(self, message: str) -> None:
        with self._lock:
            self.log.append(message)

    def finish(
        self,
        status: str,
        error: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.retryable = retryable
            if error:
                self.log.append(error)

    def toPayload(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.id,
                "created_ts": self.created_ts,
                "phase": self.phase,
                "progress": self.progress,
                "status": self.status,
                "error": self.error,
                "retryable": self.retryable,
                "log": list(self.log[-40:]),
                "result": dict(self.result),
                "source": self.request.source,
                "asset_name": self.request.asset_name,
                "release_tag": self.request.release_tag,
                "board_port": self.request.board_port,
                "recovery": self.request.recovery,
            }


def _gc() -> Any:
    gc = shared_state.gc_ref
    if gc is None:
        raise HTTPException(status_code=503, detail="Backend not fully initialized yet.")
    return gc


def _activeFlashJob() -> Optional[FlashJob]:
    with _jobs_lock:
        for job_id in reversed(_jobs_order):
            job = _jobs[job_id]
            if job.status == "running":
                return job
    return None


def _hardwareBusyReason() -> Optional[str]:
    worker = shared_state.hardware_worker_thread
    if worker is not None and worker.is_alive():
        return f"hardware worker is active ({shared_state.hardware_state})"
    if shared_state.hardware_state in {"homing", "initializing"}:
        return f"hardware is {shared_state.hardware_state}"
    return None


def _steppersInfo(interface: Any) -> List[Dict[str, Any]]:
    steppers = []
    for stepper in getattr(interface, "steppers", ()):
        steppers.append(
            {
                "name": getattr(stepper, "_hardware_name", None) or getattr(stepper, "_name", None),
                "channel": getattr(stepper, "_channel", None),
                "microsteps": getattr(stepper, "_microsteps", None),
                "stallguard_enabled": getattr(stepper, "stallguard_enabled", None),
                "stallguard_sgthrs": getattr(stepper, "stallguard_sgthrs", None),
                "stallguard_tcoolthrs": getattr(stepper, "stallguard_tcoolthrs", None),
            }
        )
    return steppers


def _liveBoards() -> Optional[List[Dict[str, Any]]]:
    irl = shared_state.getActiveIRL()
    control_boards = getattr(irl, "control_boards", None) if irl is not None else None
    if not control_boards:
        return None
    boards = []
    for board in control_boards.values():
        identity = board.identity
        version: Optional[dict] = None
        try:
            version = board.interface.get_version()
        except Exception:
            pass
        boards.append(
            {
                "device_name": identity.device_name,
                "family": identity.family,
                "role": identity.role,
                "port": identity.port,
                "address": identity.address,
                "version": version,
                "stepper_names": list(board.logical_stepper_names),
                "steppers": _steppersInfo(board.interface),
                "source": "live",
            }
        )
    return boards


def _probeBoards(gc: Any) -> List[Dict[str, Any]]:
    boards: List[Dict[str, Any]] = []
    for port in MCUBus.enumerate_buses():
        bus: Optional[MCUBus] = None
        try:
            bus = MCUBus(port=port)
            for address in bus.scan_devices():
                dev = MCUDevice(bus, address)
                try:
                    info = dev.detect()
                except Exception as exc:
                    gc.logger.info(f"Probe: detect failed on {port}@{address}: {exc}")
                    continue
                version: Optional[dict] = None
                try:
                    version = dev.get_version()
                except Exception:
                    pass
                boards.append(
                    {
                        "device_name": info.get("device_name", f"unknown@{address}"),
                        "family": None,
                        "role": _roleFromDeviceName(info.get("device_name", "")),
                        "port": port,
                        "address": address,
                        "version": version,
                        "stepper_names": info.get("stepper_names", []),
                        "steppers": [],
                        "source": "probe",
                    }
                )
        except Exception as exc:
            gc.logger.info(f"Probe: could not open {port}: {exc}")
        finally:
            if bus is not None:
                bus.close()
    return boards


def _roleFromDeviceName(device_name: str) -> Optional[str]:
    lowered = device_name.lower()
    if "feeder" in lowered:
        return "feeder"
    if "distribution" in lowered:
        return "distribution"
    return None


@router.get("/api/firmware/boards")
def get_firmware_boards(refresh: bool = False) -> Dict[str, Any]:
    gc = _gc()
    live = _liveBoards()
    if live is not None:
        return {
            "boards": live,
            "hardware_state": shared_state.hardware_state,
            "bootloader_present": firmware_flash.bootloaderPresent(),
            "flash_allowed": False,
            "flash_blocked_reason": "Hardware is initialized. Reset to standby before flashing.",
        }

    busy = _hardwareBusyReason()
    if busy is not None:
        return {
            "boards": [],
            "hardware_state": shared_state.hardware_state,
            "bootloader_present": False,
            "flash_allowed": False,
            "flash_blocked_reason": f"Cannot probe boards: {busy}.",
        }

    active_job = _activeFlashJob()
    if active_job is not None:
        return {
            "boards": [],
            "hardware_state": shared_state.hardware_state,
            "bootloader_present": firmware_flash.bootloaderPresent(),
            "flash_allowed": False,
            "flash_blocked_reason": "A flash is in progress.",
            "active_job_id": active_job.id,
        }

    with _probe_lock:
        now = time.monotonic()
        if (
            not refresh
            and _probe_cache["boards"] is not None
            and now - _probe_cache["ts"] < BOARD_PROBE_CACHE_TTL_S
        ):
            boards = _probe_cache["boards"]
        else:
            boards = _probeBoards(gc)
            _probe_cache["ts"] = now
            _probe_cache["boards"] = boards

    return {
        "boards": boards,
        "hardware_state": shared_state.hardware_state,
        "bootloader_present": firmware_flash.bootloaderPresent(),
        "flash_allowed": True,
        "flash_blocked_reason": None,
    }


@router.get("/api/firmware/config")
def get_firmware_config() -> Dict[str, Any]:
    gc = _gc()
    payload: Dict[str, Any] = {
        "hardware_state": shared_state.hardware_state,
        "no_power_development_mode": bool(getattr(gc, "no_power_development_mode", False)),
        "machine_setup": None,
        "feeder_mode": None,
        "classification_channel_mode": None,
    }
    try:
        from machine_setup import DEFAULT_MACHINE_SETUP

        payload["machine_setup"] = (
            DEFAULT_MACHINE_SETUP
            if isinstance(DEFAULT_MACHINE_SETUP, str)
            else getattr(DEFAULT_MACHINE_SETUP, "key", None)
        )
    except Exception:
        pass
    try:
        from toml_config import loadTomlFile

        params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
        if params_path and os.path.exists(params_path):
            raw = loadTomlFile(params_path)
            payload["machine_setup"] = raw.get("machine_setup", payload["machine_setup"])
            payload["feeder_mode"] = raw.get("feeder", {}).get("mode")
            payload["classification_channel_mode"] = raw.get(
                "classification_channel", {}
            ).get("mode")
            payload["machine_toml_present"] = True
        else:
            payload["machine_toml_present"] = False
    except Exception as exc:
        gc.logger.warning(f"Firmware config: could not read machine params: {exc}")
    return payload


def _parseAsset(asset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = asset.get("name", "")
    for pattern, family, variant, role in _ASSET_PATTERNS:
        if pattern.match(name):
            return {
                "name": name,
                "size": asset.get("size"),
                "download_url": asset.get("browser_download_url"),
                "family": family,
                "variant": variant,
                "role": role,
            }
    return None


def _parseChangelog(body: str) -> Optional[Dict[str, Any]]:
    if not body:
        return None
    match = re.search(r"^## (Firmware changes[^\n]*)$", body, re.MULTILINE)
    if not match:
        return None
    heading = match.group(1).strip()
    entries: List[str] = []
    for line in body[match.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            entries.append(stripped[2:].strip())
    if not entries:
        return None
    return {"heading": heading, "entries": entries}


@router.get("/api/firmware/releases")
def get_firmware_releases(refresh: bool = False) -> Dict[str, Any]:
    gc = _gc()
    now = time.monotonic()
    if (
        not refresh
        and _releases_cache["data"] is not None
        and now - _releases_cache["ts"] < RELEASES_CACHE_TTL_S
    ):
        return _releases_cache["data"]

    try:
        res = requests.get(
            GITHUB_RELEASES_URL,
            params={"per_page": 20},
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        res.raise_for_status()
        raw_releases = res.json()
    except Exception as exc:
        if _releases_cache["data"] is not None:
            stale = dict(_releases_cache["data"])
            stale["stale"] = True
            stale["fetch_error"] = str(exc)
            return stale
        raise HTTPException(
            status_code=502, detail=f"Could not reach GitHub releases: {exc}"
        )

    releases = []
    for release in raw_releases:
        tag = release.get("tag_name", "")
        if not tag.startswith("firmware/"):
            continue
        assets = [
            parsed
            for parsed in (_parseAsset(a) for a in release.get("assets", []))
            if parsed is not None
        ]
        if not assets:
            continue
        releases.append(
            {
                "tag": tag,
                "version": tag.removeprefix("firmware/"),
                "name": release.get("name"),
                "published_at": release.get("published_at"),
                "prerelease": bool(release.get("prerelease")),
                "changelog": _parseChangelog(release.get("body") or ""),
                "assets": assets,
            }
        )

    payload = {"releases": releases, "repo": GITHUB_REPO, "stale": False}
    _releases_cache["ts"] = now
    _releases_cache["data"] = payload
    gc.logger.info(f"Fetched {len(releases)} firmware releases from GitHub")
    return payload


@router.post("/api/firmware/upload")
async def upload_firmware(request: Request, filename: str = "firmware.uf2") -> Dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(data) > MAX_UF2_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="UF2 file too large (max 16 MB).")
    problem = firmware_flash.validateUf2(data)
    if problem is not None:
        raise HTTPException(status_code=400, detail=f"Invalid UF2: {problem}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    path = os.path.join(UPLOAD_DIR, f"{upload_id}.uf2")
    with open(path, "wb") as f:
        f.write(data)

    with _uploads_lock:
        _uploads[upload_id] = {
            "upload_id": upload_id,
            "path": path,
            "filename": os.path.basename(filename),
            "size": len(data),
            "uploaded_ts": time.time(),
        }
        while len(_uploads) > MAX_UPLOADS_KEPT:
            oldest_id = min(_uploads, key=lambda k: _uploads[k]["uploaded_ts"])
            stale = _uploads.pop(oldest_id)
            try:
                os.unlink(stale["path"])
            except OSError:
                pass

    return {
        "upload_id": upload_id,
        "filename": os.path.basename(filename),
        "size": len(data),
    }


def _downloadReleaseAsset(gc: Any, job: FlashJob, url: str) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, f"release-{job.id}.uf2")
    with requests.get(url, stream=True, timeout=30) as res:
        res.raise_for_status()
        total = int(res.headers.get("Content-Length") or 0)
        written = 0
        with open(path, "wb") as f:
            for chunk in res.iter_content(chunk_size=64 * 1024):
                if job.cancel_event.is_set():
                    raise FlashCancelled()
                f.write(chunk)
                written += len(chunk)
                if total:
                    job.setProgress(written / total)
    with open(path, "rb") as f:
        data = f.read()
    problem = firmware_flash.validateUf2(data)
    if problem is not None:
        raise FlashError(f"Downloaded asset is not a valid UF2: {problem}")
    gc.logger.info(f"Firmware flash {job.id}: downloaded {written} bytes from {url}")
    return path


def _resolveUf2Path(gc: Any, job: FlashJob) -> str:
    req = job.request
    if req.source == "upload":
        if not req.upload_id:
            raise FlashError("No upload_id given for an upload-sourced flash.")
        with _uploads_lock:
            upload = _uploads.get(req.upload_id)
        if upload is None or not os.path.exists(upload["path"]):
            raise FlashError(
                "Uploaded file no longer available — upload it again and retry."
            )
        return upload["path"]
    if req.source == "release":
        if not req.asset_url:
            raise FlashError("No asset_url given for a release-sourced flash.")
        job.setPhase("downloading", f"Downloading {req.asset_name or req.asset_url}...")
        return _downloadReleaseAsset(gc, job, req.asset_url)
    raise FlashError(f"Unknown flash source '{req.source}'.")


def _runFlashJob(gc: Any, job: FlashJob) -> None:
    try:
        uf2_path = _resolveUf2Path(gc, job)

        already_in_bootloader = firmware_flash.bootloaderPresent()
        if job.request.recovery or already_in_bootloader:
            job.addLog(
                "Bootloader already present — skipping reboot command."
                if already_in_bootloader
                else "Recovery mode — waiting for a board in bootloader (RPI-RP2)."
            )
        else:
            port = job.request.board_port
            if not port:
                raise FlashError("No board_port given (required unless recovery mode).")
            job.setPhase("identifying", f"Checking board on {port}...")
            info = firmware_flash.identifyBoard(gc, port)
            if info is None:
                raise FlashError(
                    f"No responsive board on {port}. If it is blank or wedged, "
                    "hold BOOTSEL while replugging and use a recovery flash."
                )
            device_name = info.get("device_name", "?")
            expected = job.request.expected_device_name
            if expected and device_name != expected:
                raise FlashError(
                    f"Board on {port} identifies as '{device_name}', expected "
                    f"'{expected}'. Refusing to flash the wrong board."
                )
            job.result["previous_version"] = info.get("version")
            job.setPhase("rebooting", f"Rebooting '{device_name}' into bootloader...")
            firmware_flash.rebootToBootloader(gc, port)

        job.setPhase("waiting_bootloader", "Waiting for RPI-RP2 drive...")
        mount = firmware_flash.waitForBootloaderMount(gc, job.cancel_event)
        job.addLog(f"Bootloader mounted at {mount}")

        job.setPhase("copying", f"Copying {os.path.basename(uf2_path)}...")
        firmware_flash.copyUf2ToMount(
            gc, uf2_path, mount, job.cancel_event, job.setProgress
        )

        job.setPhase("waiting_reboot", "Waiting for the board to reboot...")
        firmware_flash.waitForBootloaderGone(gc, job.cancel_event)

        job.setPhase("verifying", "Looking for the board on serial...")
        info = firmware_flash.waitForSerialBoard(gc, job.cancel_event)
        if info is None:
            raise FlashError(
                "Flash copy completed but the board did not reappear on serial. "
                "It may still boot fine — power-cycle it or retry with recovery mode."
            )
        job.result["board"] = {
            "device_name": info.get("device_name"),
            "port": info.get("port"),
            "version": info.get("version"),
        }
        version = (info.get("version") or {}).get("firmware_version")
        job.addLog(
            f"Board is back: {info.get('device_name', '?')} on {info.get('port', '?')}"
            + (f", firmware {version}" if version else "")
        )
        job.setPhase("done", "Flash complete.")
        job.finish("done")
        gc.logger.info(f"Firmware flash {job.id}: done ({job.result.get('board')})")
    except FlashCancelled:
        job.finish(
            "cancelled",
            error=(
                "Cancelled. If the board was already rebooted to bootloader it is "
                "waiting in RPI-RP2 — use a recovery flash to finish."
            ),
            retryable=True,
        )
        gc.logger.warning(f"Firmware flash {job.id}: cancelled during {job.phase}")
    except FlashError as exc:
        job.finish("failed", error=str(exc), retryable=True)
        gc.logger.error(f"Firmware flash {job.id} failed during {job.phase}: {exc}")
    except Exception as exc:
        job.finish("failed", error=f"Unexpected error: {exc}", retryable=True)
        gc.logger.error(f"Firmware flash {job.id} crashed during {job.phase}: {exc}")
    finally:
        _flash_lock.release()


def _registerJob(job: FlashJob) -> None:
    with _jobs_lock:
        _jobs[job.id] = job
        _jobs_order.append(job.id)
        while len(_jobs_order) > MAX_JOBS_KEPT:
            dropped = _jobs_order.pop(0)
            _jobs.pop(dropped, None)


def _startFlash(gc: Any, request: FlashRequest) -> FlashJob:
    with shared_state.hardware_lifecycle_lock:
        busy = _hardwareBusyReason()
        if busy is not None:
            raise HTTPException(status_code=409, detail=f"Cannot flash: {busy}.")
        if shared_state.hardware_state not in {"standby", "error"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot flash while hardware is '{shared_state.hardware_state}'. "
                    "Reset the system to standby first."
                ),
            )
        if not _flash_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="A flash is already in progress.")

    try:
        job = FlashJob(request)
        _registerJob(job)
        thread = threading.Thread(
            target=_runFlashJob, args=(gc, job), daemon=True, name=f"firmware-flash-{job.id}"
        )
        thread.start()
    except Exception:
        # The worker's finally owns the release once the thread is running; on
        # any failure before that, release here or no flash can ever start again.
        _flash_lock.release()
        raise
    gc.logger.info(
        f"Firmware flash {job.id} started: source={request.source} "
        f"asset={request.asset_name} port={request.board_port} recovery={request.recovery}"
    )
    return job


@router.post("/api/firmware/flash")
def start_firmware_flash(request: FlashRequest) -> Dict[str, Any]:
    gc = _gc()
    if request.source not in {"upload", "release"}:
        raise HTTPException(status_code=400, detail="source must be 'upload' or 'release'")
    job = _startFlash(gc, request)
    return {"job_id": job.id, "job": job.toPayload()}


@router.get("/api/firmware/flash/jobs")
def list_firmware_flash_jobs() -> Dict[str, Any]:
    with _jobs_lock:
        jobs = [_jobs[job_id].toPayload() for job_id in reversed(_jobs_order)]
    return {"jobs": jobs}


@router.get("/api/firmware/flash/{job_id}")
def get_firmware_flash_job(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown flash job '{job_id}'")
    return job.toPayload()


@router.post("/api/firmware/flash/{job_id}/cancel")
def cancel_firmware_flash_job(job_id: str) -> Dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown flash job '{job_id}'")
    if job.status != "running":
        return {"ok": False, "message": f"Job is already {job.status}.", "job": job.toPayload()}
    job.cancel_event.set()
    return {"ok": True, "message": "Cancel requested.", "job": job.toPayload()}


@router.post("/api/firmware/flash/{job_id}/retry")
def retry_firmware_flash_job(job_id: str) -> Dict[str, Any]:
    gc = _gc()
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown flash job '{job_id}'")
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job is still running.")
    new_job = _startFlash(gc, job.request)
    return {"job_id": new_job.id, "job": new_job.toPayload()}
