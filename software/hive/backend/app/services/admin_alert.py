"""Telling the operator something they should know now.

``ADMIN_ALERT_URL`` is the whole address of a notification endpoint, path
included, and ``ADMIN_ALERT_TOKEN`` its bearer token; both are secrets set on
the server. With either unset, alerts are only logged. The body is a small
generic envelope: ``title``, ``message``, ``request_id`` (stable, so a retried
delivery is not shown twice) and ``urgency`` (``normal`` or
``time_sensitive``).

Sending never blocks a request and never raises: it runs on a short-lived
daemon thread with a short timeout, and a failure is a log line.
"""

from __future__ import annotations

import logging
import threading

import requests

from app.config import settings

log = logging.getLogger(__name__)

TIMEOUT_S = 10.0


def _send(title: str, message: str, request_id: str, urgency: str) -> None:
    url = (settings.ADMIN_ALERT_URL or "").strip()
    token = (settings.ADMIN_ALERT_TOKEN or "").strip()
    if not url or not token:
        log.info("admin alert (no endpoint configured): %s: %s", title, message)
        return
    try:
        response = requests.post(
            url,
            json={"title": title, "message": message, "request_id": request_id, "urgency": urgency},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_S,
        )
        if response.status_code >= 300:
            log.warning("admin alert %s: answered HTTP %s", request_id, response.status_code)
        else:
            log.info("admin alert %s: sent", request_id)
    except Exception as exc:
        log.warning("admin alert %s: could not send: %s", request_id, exc)


def send_in_background(*, title: str, message: str, request_id: str, urgency: str = "normal") -> None:
    threading.Thread(
        target=_send,
        args=(title, message, request_id, urgency),
        name="admin-alert",
        daemon=True,
    ).start()
