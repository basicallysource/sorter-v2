"""Application service for polygon save and rt refresh use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from blob_manager import setChannelPolygons, setClassificationPolygons


@dataclass(slots=True, kw_only=True)
class PolygonConfigService:
    rt_handle: Any | None

    def save(self, body: dict[str, Any]) -> dict[str, Any]:
        if "channel" in body:
            setChannelPolygons(body["channel"])
        if "classification" in body:
            setClassificationPolygons(body["classification"])

        rebuild = (
            self._rebuild_rt_perception_roles("c2", "c3", "c4")
            if "channel" in body
            else {"attempted": [], "rebuilt": [], "failed": []}
        )
        return {
            "ok": True,
            "requires_restart": bool(rebuild["failed"]),
            "rt_rebuild_attempted_roles": rebuild["attempted"],
            "rt_rebuilt_roles": rebuild["rebuilt"],
            "rt_rebuild_failed_roles": rebuild["failed"],
        }

    def _rebuild_rt_perception_roles(self, *roles: str) -> dict[str, list[str]]:
        """Best-effort refresh of live rt perception runners after zone edits."""
        handle = self.rt_handle
        if handle is None or not hasattr(handle, "rebuild_runner_for_role"):
            return {"attempted": [], "rebuilt": [], "failed": []}

        attempted: list[str] = []
        rebuilt: list[str] = []
        failed: list[str] = []
        for role in roles:
            attempted.append(role)
            try:
                runner = handle.rebuild_runner_for_role(role)
            except Exception:
                runner = None
            if runner is None:
                failed.append(role)
            else:
                rebuilt.append(role)
        return {
            "attempted": attempted,
            "rebuilt": rebuilt,
            "failed": failed,
        }
