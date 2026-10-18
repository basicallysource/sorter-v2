import incident_records


def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    monkeypatch.setattr(incident_records, "_initialized", False)


def test_backend_restart_closes_incidents_left_active(tmp_path, monkeypatch) -> None:
    _fresh_db(tmp_path, monkeypatch)
    row_id = incident_records.openIncident({"kind": "exit_stuck", "channel": "c4", "triggered_at": 1000.0})
    assert incident_records.listIncidents(status="active")["items"][0]["id"] == row_id

    # A new process initialises the store again: the orphaned row is closed.
    monkeypatch.setattr(incident_records, "_initialized", False)
    incident_records._ensureInitialized()

    assert incident_records.listIncidents(status="active")["items"] == []
    resolved = incident_records.listIncidents(status="resolved")["items"][0]
    assert resolved["id"] == row_id
    assert resolved["resolved_by"] == "backend_restart"
    assert resolved["duration_s"] >= 0.0


def test_live_resolution_is_not_overwritten(tmp_path, monkeypatch) -> None:
    _fresh_db(tmp_path, monkeypatch)
    row_id = incident_records.openIncident({"kind": "exit_stuck", "channel": "c4"})
    incident_records.resolveIncident(row_id, resolved_by="operator")

    monkeypatch.setattr(incident_records, "_initialized", False)
    incident_records._ensureInitialized()

    assert incident_records.listIncidents(status="resolved")["items"][0]["resolved_by"] == "operator"
