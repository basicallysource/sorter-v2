"""Read-only view of the anonymous status ping for the hidden /telemetry UI page.

Shows the operator exactly what their machine reports and lets them copy the
install id they'd paste into the Hive "forget" form. No writes, no toggles here
— reporting is turned off with SORTER_BASE_REPORTING_OFF=1, which this endpoint
just reflects.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import basically_services
import status_ping

router = APIRouter()


@router.get("/api/status-ping/status")
def get_status_ping_status() -> dict[str, Any]:
    install = status_ping._get_install()
    enabled = status_ping.reportingEnabled()
    return {
        "enabled": enabled,
        "install_id": install["install_id"],
        "created_at": install.get("created_at"),
        "endpoint": basically_services._endpoint() + basically_services.PING_PATH,
        "sample_payload": status_ping.buildPayload("preview"),
    }
