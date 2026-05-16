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


def test_probe_auto_plan_uses_first_occupied_sector_to_exit(monkeypatch, capsys) -> None:
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
        if path == "/api/classification-channel/sector-occupancy":
            return {
                "ok": True,
                "exit_sector": 4,
                "sectors": [
                    {"sector_index": 0, "occupied": False},
                    {"sector_index": 1, "occupied": True},
                    {"sector_index": 2, "occupied": True},
                    {"sector_index": 3, "occupied": False},
                    {"sector_index": 4, "occupied": False},
                ],
            }
        return {"ok": True, "path": path}

    monkeypatch.setattr(c4_sector_probe, "_request_json", fake_request_json)

    args = c4_sector_probe.parse_args(["--auto-plan", "--direction", "cw"])
    assert c4_sector_probe.run_probe(args) == 0

    output = capsys.readouterr().out
    assert "c4_suggested_sector_move" in output
    assert calls[-1][2] == {
        "from_sector": 1,
        "to_sector": 4,
        "direction": "cw",
        "execute": "false",
    }


def test_probe_auto_plan_requires_occupied_sector(monkeypatch) -> None:
    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/classification-channel/sector-occupancy":
            return {
                "ok": True,
                "exit_sector": 4,
                "sectors": [{"sector_index": idx, "occupied": False} for idx in range(5)],
            }
        return {"ok": True}

    monkeypatch.setattr(c4_sector_probe, "_request_json", fake_request_json)

    args = c4_sector_probe.parse_args(["--auto-plan"])
    with pytest.raises(c4_sector_probe.ProbeError, match="no occupied sector"):
        c4_sector_probe.run_probe(args)


def test_probe_auto_plan_refuses_occupied_exit_sector(monkeypatch) -> None:
    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/classification-channel/sector-occupancy":
            return {
                "ok": True,
                "exit_sector": 4,
                "sectors": [
                    {"sector_index": 0, "occupied": True},
                    {"sector_index": 1, "occupied": False},
                    {"sector_index": 2, "occupied": False},
                    {"sector_index": 3, "occupied": False},
                    {"sector_index": 4, "occupied": True},
                ],
            }
        return {"ok": True}

    monkeypatch.setattr(c4_sector_probe, "_request_json", fake_request_json)

    args = c4_sector_probe.parse_args(["--auto-plan"])
    with pytest.raises(c4_sector_probe.ProbeError, match="exit sector is occupied"):
        c4_sector_probe.run_probe(args)
