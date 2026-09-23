"""Hive's default detection model, installed when a slot has none.

No model ships with the sorter. At startup a background thread looks at every
detection slot of this machine setup (the rows of the Models page). A slot
needs a model when the machine TOML leaves it unset or names an id the registry
cannot resolve, such as a model that has since been deleted. When one does, the
thread:

1. reuses a Hive default installed earlier, when one for a runtime this machine
   runs is still on disk; otherwise
2. asks the main Hive for its default ``detection`` model for each runtime this
   machine runs, best first (``compatible_runtimes_for_this_machine``). That
   endpoint is public, so a machine with no Hive account gets it too; a 404
   means no default is set for that runtime, and the next one is tried;
3. downloads it through the normal download queue, so it shows in the downloads
   list and lands where a manual download would, unless that exact file is
   already installed; and
4. assigns it to every slot that still needs a model, through the same path as
   activating a model for one subsystem on the Models page, so it applies
   without a restart.

A slot whose model resolves (a Hive model, a local one, or a built-in such as
mog2) is the operator's choice and is never touched. Offline or on any Hive
error the thread logs one line and tries again every five minutes, until it
succeeds or no slot needs a model any more.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

PURPOSE = "detection"
RETRY_INTERVAL_S = 300.0
# How long one wait on the download job blocks before checking for shutdown.
_JOB_POLL_S = 5.0


class NoDefaultModel(Exception):
    pass


def slots_needing_model() -> list[dict[str, Any]]:
    """The slots of this machine setup whose detection model is unset or does
    not resolve, one per TOML slot (two rows of the Models page can share one)."""
    from server.routers.hive_models import _collect_active_assignments
    from vision.detection_registry import detection_algorithm_definition

    needing: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for slot in _collect_active_assignments():
        key = (slot["scope"], slot["role"])
        if key in seen:
            continue
        seen.add(key)
        if detection_algorithm_definition(slot["algorithm_id"]) is None:
            needing.append(slot)
    return needing


def _resolves(algorithm_id: str) -> bool:
    from vision.detection_registry import detection_algorithm_definition

    return detection_algorithm_definition(algorithm_id) is not None


class DefaultModelInstaller:
    def __init__(self, logger: Any = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="hive-default-model", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _sleep(self, seconds: float) -> None:
        self._stop.wait(timeout=seconds)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.run_once():
                    return
            except Exception as exc:
                self._logger.warning(
                    f"Hive default detection model not installed yet ({exc}); "
                    f"trying again in {RETRY_INTERVAL_S / 60:.0f} minutes"
                )
            self._sleep(RETRY_INTERVAL_S)

    def run_once(self) -> bool:
        """One attempt. True when nothing is left to do; raises when the model
        could not be had this time."""
        if not slots_needing_model():
            return True

        from server.hive_models import compatible_runtimes_for_this_machine

        runtimes = compatible_runtimes_for_this_machine()
        reused = self._installed_default(runtimes)
        if reused is not None:
            algorithm_id, name, runtime = reused
            downloaded = False
        else:
            algorithm_id, name, runtime, downloaded = self._fetch_default(runtimes)

        labels = self._assign(algorithm_id)
        if labels:
            if downloaded:
                what = f"Installed Hive default detection model {name} ({runtime}) and assigned it to"
            else:
                what = f"Assigned Hive default detection model {name} ({runtime}, already installed) to"
            self._logger.info(f"{what}: {', '.join(labels)}")
        return True

    # -- the model --------------------------------------------------------

    @staticmethod
    def _installed_default(runtimes: list[str]) -> tuple[str, str, str] | None:
        """A Hive default installed earlier that this machine can run, best
        runtime first and the newest download among equals."""
        from server.hive_models import list_installed_models

        candidates = [
            entry
            for entry in list_installed_models()
            if entry.get("installed_as_default")
            and entry.get("variant_runtime") in runtimes
            and _resolves(entry["algorithm_id"])
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry.get("downloaded_at") or "", reverse=True)
        best = min(candidates, key=lambda entry: runtimes.index(entry["variant_runtime"]))
        return best["algorithm_id"], str(best.get("name") or best["local_id"]), best["variant_runtime"]

    def _fetch_default(self, runtimes: list[str]) -> tuple[str, str, str, bool]:
        import basically_services
        from server import hive_models
        from vision.detection_registry import HIVE_ID_PREFIX

        base_url = basically_services._endpoint()
        client = hive_models.HiveClient(base_url)
        for runtime in runtimes:
            try:
                item = client.get_default_model(PURPOSE, runtime)
            except hive_models.HiveError as exc:
                if getattr(exc, "status_code", None) == 404:
                    continue
                raise
            model = item.get("model") if isinstance(item.get("model"), dict) else {}
            variant = item.get("variant") if isinstance(item.get("variant"), dict) else {}
            name = str(model.get("name") or model.get("id"))
            local_id = f"hive-{model.get('id')}-{runtime}"
            algorithm_id = f"{HIVE_ID_PREFIX}{local_id}"

            installed = next(
                (e for e in hive_models.list_installed_models() if e["local_id"] == local_id),
                None,
            )
            expected_sha = variant.get("sha256")
            if (
                installed is not None
                and (not expected_sha or installed.get("sha256") == expected_sha)
                and _resolves(algorithm_id)
            ):
                return algorithm_id, name, runtime, False

            manager = hive_models.get_job_manager()
            job_id = manager.enqueue_default(PURPOSE, runtime, item, base_url)
            job = self._wait_for_job(manager, job_id)
            if job.get("status") != "done":
                raise RuntimeError(f"download of {name} ({runtime}) failed: {job.get('error')}")
            if not _resolves(algorithm_id):
                raise RuntimeError(f"{name} ({runtime}) downloaded but this machine cannot load it")
            return algorithm_id, name, runtime, True
        raise NoDefaultModel(f"Hive has no default {PURPOSE} model for {', '.join(runtimes)}")

    def _wait_for_job(self, manager: Any, job_id: str) -> dict:
        while True:
            job = manager.wait_for_terminal(job_id, timeout=_JOB_POLL_S)
            if job.get("status") in {"done", "failed"}:
                return job
            if self._stop.is_set():
                raise RuntimeError("shutting down")

    # -- the slots --------------------------------------------------------

    @staticmethod
    def _assign(algorithm_id: str) -> list[str]:
        """Give ``algorithm_id`` to every slot that still needs a model,
        whatever scopes the model declares. Re-read now: the operator may have
        picked something while the download ran."""
        from server.routers.hive_models import _apply_active_assignment_to_slot

        labels: list[str] = []
        for slot in slots_needing_model():
            _apply_active_assignment_to_slot(algorithm_id, slot["scope"], slot["role"])
            labels.append(slot["label"])
        return labels


_installer: DefaultModelInstaller | None = None
_installer_lock = threading.Lock()


def start(logger: Any = None) -> None:
    """Start the one installer thread of this process (later calls no-op)."""
    global _installer
    with _installer_lock:
        if _installer is None:
            _installer = DefaultModelInstaller(logger)
            _installer.start()
