"""The records API for a tool that keeps a catalog of what a machine sorted:
every colour people and later model runs gave each piece, the machine's lots
and sorting runs (which the machine sends whole), and an admin adding a later
run's predictions on Hive."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.color_model import ColorModel
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_prediction import MachinePiecePrediction
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_model_output import PieceModelColor
from app.models.user import User
from app.services import color_model_runs
from tests.conftest import _auth_headers

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
V6 = "c" * 64


def _key(client: TestClient, scopes: list[str]) -> dict[str, str]:
    response = client.post("/api/auth/api-keys", json={"name": "catalog", "scopes": scopes}, headers=_auth_headers(client))
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['raw_token']}"}


def _piece(db: Session, machine_id: UUID, puid: str, local_id: int, **fields) -> None:
    db.add(
        MachinePiece(
            machine_id=machine_id, piece_uuid=puid, local_id=local_id, seen_at=NOW + timedelta(minutes=local_id),
            part_id="3001", color_id="86", color_name="Light Bluish Gray", **fields,
        )
    )


def _prediction(machine_id: UUID, puid: str, source: str, value_id: str, *, kind="color", rank=0, at=NOW) -> MachinePiecePrediction:
    return MachinePiecePrediction(
        machine_id=machine_id, piece_uuid=puid, local_id=1, source=source, request="colorpred-v6", provider="basically",
        model=V6, model_name="colorpred-v6", kind=kind, rank=rank, value_id=value_id, value_name=None, score=0.9,
        predicted_at=at,
    )


def test_a_piece_carries_every_later_colour_and_label(client, db, test_user, test_machine, monkeypatch) -> None:
    machine_id = UUID(test_machine["id"])
    owner = db.query(User).filter(User.email == test_user["email"]).one()
    _piece(db, machine_id, "a", 1, color_corrected_id="11", correction_updated_at=NOW)
    _piece(db, machine_id, "b", 2, dead=True)
    db.add_all([
        # The live classification and a run's lower ranks and part answers are not later colours.
        _prediction(machine_id, "a", "live", "86"),
        _prediction(machine_id, "a", "colorpred-v6 rerun, 14 Oct", "11"),
        _prediction(machine_id, "a", "colorpred-v6 rerun, 14 Oct", "86", rank=1),
        _prediction(machine_id, "a", "colorpred-v6 rerun, 14 Oct", "3001", kind="part"),
        PieceColorLabel(machine_id=machine_id, piece_uuid="a", labeler_id=owner.id, color_id=11, updated_at=NOW),
        ColorModel(filename="colorpred-v6.onnx", name="colorpred-v6", sha256=V6, is_active=True, created_at=NOW),
    ])
    db.flush()
    db.add(PieceModelColor(
        machine_id=machine_id, piece_uuid="a", model_sha256=V6, model_name="colorpred-v6", color_id=11,
        confidence=0.97, top=[], seqs=[0, 1], created_at=NOW + timedelta(hours=1),
    ))
    db.commit()
    monkeypatch.setattr(color_model_runs, "_palette", lambda: {11: {"id": 11, "name": "Black"}})

    body = client.get(f"/api/records/machines/{machine_id}/pieces", headers=_key(client, ["records:read"])).json()
    b, a = body["items"]
    assert (b["piece_uuid"], b["local_id"], b["dead"], b["color_labels"], b["color_predictions"]) == ("b", 2, True, [], [])
    assert (a["local_id"], a["seen_at"], a["color_corrected_id"]) == (1, (NOW + timedelta(minutes=1)).isoformat(), "11")
    assert a["color_labels"] == [{"color_id": "11", "cant_tell": False, "by_owner": True, "at": NOW.isoformat()}]
    assert [(p["source"], p["color_id"], p["color_name"]) for p in a["color_predictions"]] == [
        ("colorpred-v6 rerun, 14 Oct", "11", None),
        ("hive", "11", "Black"),
    ]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_machine_sends_its_lots_and_runs_whole_and_a_reader_sees_them(client, test_machine, machine_token) -> None:
    t0 = NOW.timestamp()
    sent = {
        "version": 42,
        "lots": [{"id": "lot-1", "name": "Big box", "description": None, "created_at": t0}],
        "runs": [
            {"id": "run-1", "name": "Big box", "note": None, "lot_id": "lot-1", "adds_to_lot": True, "started_at": t0, "created_at": t0},
            {"id": "run-2", "name": "Finer pass", "note": None, "lot_id": "lot-1", "adds_to_lot": False, "started_at": t0 + 600, "created_at": t0},
            {"id": "run-3", "name": "Test", "note": None, "lot_id": None, "adds_to_lot": False, "started_at": t0 + 60, "created_at": t0},
        ],
    }
    response = client.post("/api/machine/sync/sorting-runs", json=sent, headers=_bearer(machine_token))
    assert response.status_code == 200, response.text
    assert client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()["sorting_runs"] == {"max_local_id": 42}

    key = _key(client, ["records:read"])
    body = client.get(f"/api/records/machines/{test_machine['id']}/sorting-runs", headers=key).json()
    assert [(lot["id"], lot["name"]) for lot in body["lots"]] == [("lot-1", "Big box")]
    assert [(r["id"], r["adds_to_lot"], r["ends_at"]) for r in body["runs"]] == [
        ("run-1", True, datetime.fromtimestamp(t0 + 60, timezone.utc).isoformat()),
        ("run-3", False, datetime.fromtimestamp(t0 + 600, timezone.utc).isoformat()),
        ("run-2", False, None),
    ]

    # A run deleted on the machine is gone from the next set.
    sent = {**sent, "version": 43, "runs": sent["runs"][:2]}
    assert client.post("/api/machine/sync/sorting-runs", json=sent, headers=_bearer(machine_token)).status_code == 200
    body = client.get(f"/api/records/machines/{test_machine['id']}/sorting-runs", headers=key).json()
    assert [r["id"] for r in body["runs"]] == ["run-1", "run-2"]


def test_only_an_admin_adds_a_runs_predictions(client, db, test_user, test_machine, monkeypatch) -> None:
    monkeypatch.setattr(color_model_runs, "_palette", lambda: {85: {"id": 85, "name": "Dark Bluish Gray"}})
    machine_id = UUID(test_machine["id"])
    _piece(db, machine_id, "a", 1)
    db.commit()
    url = f"/api/records/machines/{machine_id}/predictions"
    run = {
        "source": "colorpred-v7 rerun, 20 Oct", "provider": "basically", "model_name": "colorpred-v7", "model_sha": "d" * 64,
        "kind": "color", "made_at": NOW.timestamp(),
        "pieces": [
            {"piece_uuid": "a", "answers": [{"value_id": "11", "value_name": "Black", "score": 0.9}, {"value_id": "85", "score": 0.05}], "image_seqs": [4, 5]},
            {"piece_uuid": "nope", "answers": [{"value_id": "11"}]},
        ],
    }
    denied = client.post("/api/auth/api-keys", json={"name": "x", "scopes": ["predictions:write"]}, headers=_auth_headers(client))
    assert denied.status_code == 403
    assert client.post(url, json=run, headers=_auth_headers(client)).status_code == 403

    user = db.query(User).filter(User.email == test_user["email"]).one()
    user.role = "admin"
    db.commit()
    reader = _key(client, ["records:read"])
    assert client.post(url, json=run, headers=reader).status_code == 403
    writer = _key(client, ["predictions:write"])
    assert client.post(url, json={**run, "source": "live"}, headers=writer).status_code == 400

    response = client.post(url, json=run, headers=writer)
    assert response.status_code == 200, response.text
    assert response.json() == {"added": 1, "already": 0, "unknown": ["nope"]}
    assert client.post(url, json=run, headers=writer).json() == {"added": 0, "already": 1, "unknown": ["nope"]}

    [piece] = client.get(f"/api/records/machines/{machine_id}/pieces", headers=reader).json()["items"]
    assert [(p["source"], p["color_id"], p["color_name"], p["made_at"]) for p in piece["color_predictions"]] == [
        ("colorpred-v7 rerun, 20 Oct", "11", "Black", NOW.isoformat())
    ]
    stored = db.query(MachinePiecePrediction).filter(MachinePiecePrediction.piece_uuid == "a").order_by(MachinePiecePrediction.rank).all()
    # The unnamed colour took its BrickLink name.
    assert [(p.rank, p.value_id, p.value_name, p.local_id) for p in stored] == [
        (0, "11", "Black", 0),
        (1, "85", "Dark Bluish Gray", 0),
    ]
    assert stored[0].images == [{"set": "burst", "seq": 4, "channel": None}, {"set": "burst", "seq": 5, "channel": None}]
