"""Client for the main hive's hosted-services layer (hive.basically.website).

Deliberately NOT the configured Hive targets: those are the operator's
account(s) on whichever hive(s) they chose, while this always points at the
main hive, which ships hosted functionality (the color prediction model today)
that works whether or not any account exists.

Identity is a silently enrolled "device": on first use we generate a secret
device_key, POST it to /api/devices/enroll, and persist the returned device id
+ bearer token in local state. Re-enrolling with the same key reuses the same
server-side device row (rotating the token), so a lost token never fragments
this machine's identity. Enrollment is invisible to the operator and implies
no account — if they later sign up on the main hive they go through the normal
registration flow.

Everything here is best-effort with tight timeouts: the caller (the
classification path) has a hard budget and always has Brickognize's color as a
fallback, so a failure here means "no answer", never an error the sorting loop
notices.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any, Optional

import requests

import local_state
from global_config import GlobalConfig

DEFAULT_ENDPOINT = "https://hive.basically.website"
ENROLL_PATH = "/api/devices/enroll"
COLOR_PREDICT_PATH = "/api/devices/color-predict"
PING_PATH = "/api/devices/ping"

# Tight on purpose — the classification path runs on a ~12 s total budget in
# parallel with Brickognize, and a fallback color always exists.
ENROLL_TIMEOUT_S = (5.0, 10.0)
PREDICT_TIMEOUT_S = (3.0, 8.0)
PING_TIMEOUT_S = (5.0, 15.0)
MAX_PREDICT_IMAGES = 8
# A prediction slower than this is logged: past it the piece is close to
# falling back to Brickognize's colour.
SLOW_PREDICT_S = 3.0

# After a failed enroll, don't retry on every piece — the service being down
# shouldn't add connect-timeout latency to each classification.
_ENROLL_RETRY_COOLDOWN_S = 300.0

# One session for every call to the main hive, so its connections stay open
# between pieces: a prediction then waits on neither a name lookup nor a new TLS
# handshake. A lookup is not covered by the request timeouts, and a stalled one
# (each name server that does not answer costs 5 s) held pieces past the colour
# budget with nothing logged.
_session = requests.Session()

_enroll_lock = threading.Lock()
_last_enroll_failure_at: float = 0.0


def _endpoint() -> str:
    override = os.getenv("SORTER_BASICALLY_SERVICES_URL")
    base = override.strip() if isinstance(override, str) and override.strip() else DEFAULT_ENDPOINT
    return base.rstrip("/")


# The status pinger runs without a GlobalConfig (it starts from the server's
# startup hook, before/independent of the machine loop), so gc is Optional
# everywhere here and logging degrades to silence without one.
def _logInfo(gc: Optional[GlobalConfig], message: str) -> None:
    if gc is not None:
        gc.logger.info(message)


def _logWarn(gc: Optional[GlobalConfig], message: str) -> None:
    if gc is not None:
        gc.logger.warn(message)


def _enroll(gc: Optional[GlobalConfig], state: dict[str, Any]) -> Optional[dict[str, Any]]:
    global _last_enroll_failure_at
    device_key = state.get("device_key")
    if not isinstance(device_key, str) or not device_key.strip():
        device_key = secrets.token_urlsafe(32)
    try:
        response = _session.post(
            _endpoint() + ENROLL_PATH,
            json={"device_key": device_key},
            timeout=ENROLL_TIMEOUT_S,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as e:
        _last_enroll_failure_at = time.time()
        _logWarn(gc, f"basically services: device enroll failed: {e}")
        return None
    record = {
        "device_key": device_key,
        "device_id": body.get("device_id"),
        "token": body.get("token"),
        "enrolled_at": time.time(),
    }
    local_state.set_basically_services_state(record)
    _logInfo(gc, f"basically services: enrolled device {record['device_id']}")
    return record


def _deviceState(gc: Optional[GlobalConfig]) -> Optional[dict[str, Any]]:
    with _enroll_lock:
        state = local_state.get_basically_services_state()
        token = state.get("token")
        if isinstance(token, str) and token.strip():
            return state
        if time.time() - _last_enroll_failure_at < _ENROLL_RETRY_COOLDOWN_S:
            return None
        return _enroll(gc, state)


def predictColor(
    gc: GlobalConfig,
    images: list[bytes],
    channels: list[int],
    client_info: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not images:
        return None
    state = _deviceState(gc)
    if state is None:
        return None
    images = images[:MAX_PREDICT_IMAGES]
    channels = channels[: len(images)]

    def send(token: str) -> requests.Response:
        files = [("images", (f"crop{i}.jpg", data, "image/jpeg")) for i, data in enumerate(images)]
        data: dict[str, str] = {"channels": json.dumps(channels)}
        if client_info:
            data["client_info"] = json.dumps(client_info)
        return _session.post(
            _endpoint() + COLOR_PREDICT_PATH,
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            data=data,
            timeout=PREDICT_TIMEOUT_S,
        )

    def post(token: str) -> requests.Response:
        try:
            return send(token)
        except requests.exceptions.ConnectionError as e:
            if isinstance(e, requests.exceptions.Timeout):
                raise
            # The kept-open connection had been closed at the other end before
            # this request got an answer: send it once more on a fresh one.
            return send(token)

    started = time.monotonic()
    try:
        response = post(state["token"])
        if response.status_code == 401:
            # Token rotated or revoked server-side — one silent re-enroll, then
            # give up for this piece.
            with _enroll_lock:
                refreshed = _enroll(gc, local_state.get_basically_services_state())
            if refreshed is None:
                return None
            response = post(refreshed["token"])
        response.raise_for_status()
        elapsed = time.monotonic() - started
        if elapsed > SLOW_PREDICT_S:
            _logWarn(gc, f"basically services: color predict took {elapsed:.1f} s")
        return response.json()
    except Exception as e:
        _logWarn(gc, f"basically services: color predict failed after {time.monotonic() - started:.1f} s: {e}")
        return None


def pingStatus(gc: Optional[GlobalConfig], payload: dict[str, Any]) -> bool:
    """Send the hourly machine status report (status_ping.buildPayload) to the
    device ping endpoint. Best-effort: enrolls the device if needed, retries
    once through a silent re-enroll on 401, and returns False on any failure
    without raising — a skipped ping loses nothing since the next one carries
    the same cumulative counters."""
    state = _deviceState(gc)
    if state is None:
        return False

    def post(token: str) -> requests.Response:
        return _session.post(
            _endpoint() + PING_PATH,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=PING_TIMEOUT_S,
        )

    try:
        response = post(state["token"])
        if response.status_code == 401:
            with _enroll_lock:
                refreshed = _enroll(gc, local_state.get_basically_services_state())
            if refreshed is None:
                return False
            response = post(refreshed["token"])
        response.raise_for_status()
        return True
    except Exception as e:
        _logWarn(gc, f"basically services: status ping failed: {e}")
        return False
