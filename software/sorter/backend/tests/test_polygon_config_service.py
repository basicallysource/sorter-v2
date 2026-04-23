from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from server.services.polygon_config import PolygonConfigService  # noqa: E402


def test_polygon_config_service_saves_and_rebuilds_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "server.services.polygon_config.setChannelPolygons",
        lambda payload: recorded.append(("channel", payload)),
    )
    monkeypatch.setattr(
        "server.services.polygon_config.setClassificationPolygons",
        lambda payload: recorded.append(("classification", payload)),
    )

    handle = MagicMock()
    handle.rebuild_runner_for_role = MagicMock(
        side_effect=[object(), object(), object()]
    )

    payload = PolygonConfigService(rt_handle=handle).save(
        {
            "channel": {"polygons": {"classification_channel": []}},
            "classification": {"polygons": {"top": []}},
        }
    )

    assert recorded == [
        ("channel", {"polygons": {"classification_channel": []}}),
        ("classification", {"polygons": {"top": []}}),
    ]
    assert payload == {
        "ok": True,
        "requires_restart": False,
        "rt_rebuild_attempted_roles": ["c2", "c3", "c4"],
        "rt_rebuilt_roles": ["c2", "c3", "c4"],
        "rt_rebuild_failed_roles": [],
    }
    assert handle.rebuild_runner_for_role.call_args_list == [
        call("c2"),
        call("c3"),
        call("c4"),
    ]


def test_polygon_config_service_marks_failed_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.services.polygon_config.setChannelPolygons",
        lambda payload: None,
    )
    monkeypatch.setattr(
        "server.services.polygon_config.setClassificationPolygons",
        lambda payload: None,
    )

    handle = MagicMock()

    def _rebuild(role: str) -> Any:
        if role == "c2":
            return object()
        if role == "c3":
            return None
        raise RuntimeError("boom")

    handle.rebuild_runner_for_role = MagicMock(side_effect=_rebuild)

    payload = PolygonConfigService(rt_handle=handle).save(
        {"channel": {"polygons": {"classification_channel": []}}}
    )

    assert payload == {
        "ok": True,
        "requires_restart": True,
        "rt_rebuild_attempted_roles": ["c2", "c3", "c4"],
        "rt_rebuilt_roles": ["c2"],
        "rt_rebuild_failed_roles": ["c3", "c4"],
    }
