from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from typing import Any

import requests

from local_state import (
    get_hive_config,
    get_sorting_profile_sync_state,
    set_sorting_profile_sync_state,
)
from server import shared_state

log = logging.getLogger(__name__)

SYNC_INTERVAL_S = 5.0


def _load_targets() -> list[dict[str, Any]]:
    config = get_hive_config() or {}
    targets = config.get("targets")
    if not isinstance(targets, list):
        return []
    return [target for target in targets if isinstance(target, dict)]


def _merge_sync_state(updates: dict[str, Any]) -> None:
    current = get_sorting_profile_sync_state() or {}
    next_state = dict(current)
    for key, value in updates.items():
        if value is None:
            next_state.pop(key, None)
        else:
            next_state[key] = value
    set_sorting_profile_sync_state(next_state)
    try:
        from server.routers.sorting_profiles import _current_local_profile_status

        shared_state.publishSortingProfileStatus(_current_local_profile_status())
    except Exception:
        pass


class SetProgressSyncWorker:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sent_signature: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="set-progress-sync",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def notify(self) -> None:
        self._wake_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._sync_once()
            except Exception as exc:
                self._record_failure(str(exc))
                log.exception("Set progress sync failed unexpectedly")
            self._wake_event.wait(SYNC_INTERVAL_S)
            self._wake_event.clear()

    def _sync_once(self) -> None:
        report = self._build_report()
        if report is None:
            self._last_sent_signature = None
            return
        if report["signature"] == self._last_sent_signature:
            return

        response = requests.post(
            report["url"],
            json=report["payload"],
            headers={
                "Authorization": f"Bearer {report['api_token']}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if not response.ok:
            raise RuntimeError(f"Progress sync failed: HTTP {response.status_code} {response.text}")
        self._last_sent_signature = report["signature"]
        self._record_success()

    def _build_report(self) -> dict[str, Any] | None:
        sync_state = get_sorting_profile_sync_state() or {}
        target_id = sync_state.get("target_id")
        version_id = sync_state.get("version_id")
        if not isinstance(target_id, str) or not target_id:
            return None
        if not isinstance(version_id, str) or not version_id:
            return None

        target = next(
            (
                item
                for item in _load_targets()
                if item.get("id") == target_id
                and bool(item.get("enabled", False))
                and isinstance(item.get("url"), str)
                and item.get("url")
                and isinstance(item.get("api_token"), str)
                and item.get("api_token")
            ),
            None,
        )
        if target is None:
            return None

        tracker = getattr(shared_state.gc_ref, "set_progress_tracker", None) if shared_state.gc_ref else None
        if tracker is None or not hasattr(tracker, "get_sync_payload"):
            return None

        tracker_payload = tracker.get_sync_payload()
        artifact_hash = str(tracker_payload.get("artifact_hash") or "")
        if not artifact_hash:
            raise RuntimeError("Set progress sync missing artifact hash for local tracker")
        items = tracker_payload.get("items") if isinstance(tracker_payload.get("items"), list) else []
        state_token = int(tracker_payload.get("state_token") or 0)
        signature = f"{target_id}:{version_id}:{artifact_hash}:set:{state_token}"

        return {
            "url": f"{str(target['url']).rstrip('/')}/api/machine/set-progress",
            "api_token": str(target["api_token"]),
            "payload": {
                "version_id": version_id,
                "artifact_hash": artifact_hash,
                "items": items,
            },
            "signature": signature,
        }

    def _record_success(self) -> None:
        _merge_sync_state(
            {
                "progress_last_synced_at": datetime.now(timezone.utc).isoformat(),
                "progress_last_error": None,
            }
        )

    def _record_failure(self, error: str) -> None:
        _merge_sync_state(
            {
                "progress_last_error": error,
            }
        )


_worker: SetProgressSyncWorker | None = None


def getSetProgressSyncWorker() -> SetProgressSyncWorker:
    global _worker
    if _worker is None:
        _worker = SetProgressSyncWorker()
    return _worker
