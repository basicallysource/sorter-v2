from __future__ import annotations

import pytest

from scripts import c4_sector_probe


def test_probe_defaults_to_plan_only(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        return {"ok": True, "path": path}

    monkeypatch.setattr(c4_sector_probe, "_request_json", fake_request_json)

    args = c4_sector_probe.parse_args([])
    assert c4_sector_probe.run_probe(args) == 0

    capsys.readouterr()
    assert [path for _, path, _ in calls] == [
        "/health",
        "/api/system/status",
        "/api/rt/status",
        "/api/classification-channel/sector-occupancy",
        "/api/classification-channel/sector-move",
    ]
    assert calls[-1][2] == {
        "from_sector": 0,
        "to_sector": 1,
        "direction": "shortest",
        "execute": "false",
    }


def test_probe_execute_requires_confirmation_before_network(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(c4_sector_probe, "_request_json", lambda *args, **kwargs: calls.append(args))

    args = c4_sector_probe.parse_args(["--execute"])

    with pytest.raises(c4_sector_probe.ProbeError, match="confirm-execute C4"):
        c4_sector_probe.run_probe(args)

    assert calls == []
