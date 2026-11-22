"""The inventory API: a machine sends its pieces, lots and runs, the pieces it
sent back, each emptying of a bin and every layout it ran; an inventory app
reads what each lot holds, what each bin holds now or got in a run, what each
emptying took, and what each bin was assigned, from the caller's own machines
only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from app.services import color_model_runs
from tests.conftest import _auth_headers

T0 = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def _at(minutes: float) -> float:
    return (T0 + timedelta(minutes=minutes)).timestamp()


def _iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _key(client: TestClient, scopes: list[str], machine_ids: list[str] | None = None) -> dict[str, str]:
    body = {"name": "inventory", "scopes": scopes}
    if machine_ids is not None:
        body["machine_ids"] = machine_ids
    response = client.post("/api/auth/api-keys", json=body, headers=_auth_headers(client))
    assert response.status_code == 200, response.text
    return _bearer(response.json()["raw_token"])


def _record(n: int, minutes: float, place: tuple[int, int, int] | None, **fields) -> dict:
    record = {
        "piece_uuid": f"p{n}",
        "local_id": n,
        "sync_seq": n,
        "seen_at": _at(minutes),
        "recorded_at": _at(minutes + 0.5),
        "classification_status": "classified",
        "part_id": "3001",
        "part_name": "Brick 2 x 4",
        "color_id": "5",
        "color_name": "Red",
        "category_id": "bl_5",
    }
    if place is not None:
        record.update(bin_x=place[0], bin_y=place[1], bin_z=place[2])
    record.update(fields)
    return record


def _send(client: TestClient, token: str, path: str, records: list[dict]) -> dict:
    response = client.post(f"/api/machine/sync/{path}", json={"records": records}, headers=_bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


LAYOUT = {
    "layers": [
        {"sections": [["medium", "medium"], ["medium", "medium"]], "enabled": True, "section_enabled": [True, False], "max_dimension_mm": 45.0},
        {"sections": [["large"]], "enabled": True, "max_dimension_mm": None},
    ],
    "bin_categories": [[[["bl_5"], ["bl_26"]], [[], []]], [[["misc"]]]],
    "not_in_inventory_bins": [[[False, False], [False, False]], [[False]]],
    "category_names": {"bl_5": "Brick", "bl_26": "Plate"},
    "profile": {"profile_id": "prof-1", "profile_name": "Bulk"},
}


def _machine_with_a_sort(client: TestClient, token: str) -> None:
    """Two lots on one machine. Run "first" adds to lot A from minute 0, a pass
    over lot A from minute 100, run "second" adds to lot B from minute 200. Bin
    L1-S1-B1 is emptied at minute 150, after the first run and the pass."""
    sent = {
        "version": 7,
        "lots": [
            {"id": "lot-a", "name": "fb marketplace", "created_at": _at(0)},
            {"id": "lot-b", "name": "fb marketplace 2", "created_at": _at(200)},
        ],
        "runs": [
            {"id": "run-1", "name": "first", "lot_id": "lot-a", "adds_to_lot": True, "started_at": _at(0)},
            {"id": "run-2", "name": "a pass", "lot_id": "lot-a", "adds_to_lot": False, "started_at": _at(100)},
            {"id": "run-3", "name": "second", "lot_id": "lot-b", "adds_to_lot": True, "started_at": _at(200)},
        ],
    }
    assert client.post("/api/machine/sync/sorting-runs", json=sent, headers=_bearer(token)).status_code == 200
    _send(client, token, "piece-records", [
        # The first run: three red 2x4s and a plate in L1-S1-B1, one stuck piece.
        _record(1, 1, (0, 0, 0)),
        _record(2, 2, (0, 0, 0)),
        _record(3, 3, (0, 0, 0), color_corrected_id="11", correction_updated_at=_at(5)),
        _record(4, 4, (0, 0, 1), part_id="3023", part_name="Plate 1 x 2", color_id="1", color_name="White", category_id="bl_26"),
        _record(5, 5, None, dead=True, classification_status="unknown", part_id=None),
        # The pass: one piece again, in L1-S1-B1.
        _record(6, 101, (0, 0, 0)),
        # The second run: two in L1-S1-B1 after its emptying, one unidentified,
        # one in L1-S1-B2 that is sent back, one in the big bin.
        _record(7, 201, (0, 0, 0)),
        _record(8, 202, (0, 0, 0), classification_status="unknown", part_id=None, part_name=None),
        _record(9, 203, (0, 0, 1), part_id="3023", part_name="Plate 1 x 2", color_id="1", color_name="White", category_id="bl_26"),
        _record(10, 204, (1, 0, 0), part_id="3001", part_correct=False),
    ])
    _send(client, token, "sent-back-pieces", [
        {"local_id": 1, "piece_uuid": "p9", "lot_id": "lot-b", "sent_back_at": _at(250), "note": "mixed"},
    ])
    _send(client, token, "bin-emptyings", [
        {"local_id": 1, "snapshot_id": "s1", "layer": 0, "section": 0, "bin": 0, "epoch": 0, "emptied_at": _at(150),
         "piece_count": 4, "category_ids": ["bl_5"], "scope": "all", "profile_id": "prof-1", "profile_name": "Bulk"},
        {"local_id": 2, "snapshot_id": "s1", "layer": 0, "section": 0, "bin": 1, "epoch": 0, "emptied_at": _at(150),
         "piece_count": 1, "category_ids": ["bl_26"], "scope": "all"},
    ])
    first = {**LAYOUT, "bin_categories": [[[["bl_5"], []], [[], []]], [[["misc"]]]]}
    _send(client, token, "bin-layouts", [
        {"local_id": 1, "changed_at": _at(-10), "layout": first},
        {"local_id": 2, "changed_at": _at(3.5), "layout": LAYOUT},
    ])


def test_the_sync_endpoints_keep_emptyings_and_layouts_once(client, test_machine, machine_token) -> None:
    row = {"local_id": 3, "layer": 0, "section": 1, "bin": 0, "emptied_at": _at(1), "piece_count": 2}
    assert _send(client, machine_token, "bin-emptyings", [row, {"local_id": 4, "layer": -1}]) == {
        "max_local_id": 4, "upserted": 1, "skipped": 1,
    }
    assert _send(client, machine_token, "bin-emptyings", [row])["max_local_id"] == 4
    too_big = {"local_id": 9, "changed_at": _at(0), "layout": {"layers": [], "blob": "x" * 300_000}}
    assert _send(client, machine_token, "bin-layouts", [{"local_id": 1, "changed_at": _at(0), "layout": LAYOUT}, too_big]) == {
        "max_local_id": 9, "upserted": 1, "skipped": 1,
    }
    state = client.get("/api/machine/sync/state", headers=_bearer(machine_token)).json()
    assert (state["bin_emptyings"], state["bin_layouts"]) == ({"max_local_id": 4}, {"max_local_id": 9})


def test_a_lot_counts_as_its_machine_counts_it(client, test_machine, machine_token, monkeypatch) -> None:
    monkeypatch.setattr(color_model_runs, "_palette", lambda: {11: {"id": 11, "name": "Black"}})
    _machine_with_a_sort(client, machine_token)
    key = _key(client, ["inventory:read"])
    base = f"/api/inventory/v1/machines/{test_machine['id']}"

    lot = client.get(f"{base}/lots/lot-a", headers=key).json()
    # The stuck piece and the pass are not the lot's.
    assert (lot["pieces"], lot["unidentified"], lot["sent_back"]) == (4, 0, 0)
    assert [(i["key"], i["color_name"], i["count"]) for i in lot["items"]] == [
        ("bricklink:3001/5", "Red", 2),
        ("bricklink:3001/11", "Black", 1),
        ("bricklink:3023/1", "White", 1),
    ]
    assert [r["id"] for r in lot["runs"]] == ["run-1", "run-2"]

    lot = client.get(f"{base}/lots/lot-b", headers=key).json()
    # A piece sent back is out of the lot; a part the operator said is wrong
    # leaves its piece unidentified.
    assert (lot["pieces"], lot["unidentified"], lot["sent_back"]) == (3, 2, 1)
    lots = client.get(f"{base}/lots", headers=key).json()["lots"]
    assert [(l["id"], [r["name"] for r in l["runs"]]) for l in lots] == [("lot-a", ["first", "a pass"]), ("lot-b", ["second"])]
    assert client.get(f"{base}/runs/run-2", headers=key).json()["pieces"] == 1


def test_what_each_bin_holds_now_and_got_in_a_run(client, test_machine, machine_token) -> None:
    _machine_with_a_sort(client, machine_token)
    key = _key(client, ["inventory:read"])
    base = f"/api/inventory/v1/machines/{test_machine['id']}/contents"

    now = client.get(base, headers=key).json()
    by_bin = {b["bin"]["key"]: b for b in now["bins"]}
    # Every bin of the layout, each counted from its own last emptying.
    assert list(by_bin) == ["L1-S1-B1", "L1-S1-B2", "L1-S2-B1", "L1-S2-B2", "L2-S1-B1"]
    assert (by_bin["L1-S1-B1"]["pieces"], by_bin["L1-S1-B1"]["unidentified"], by_bin["L1-S1-B1"]["since"]) == (2, 1, _iso(150))
    assert (by_bin["L1-S1-B2"]["pieces"], by_bin["L1-S1-B2"]["sent_back"]) == (0, 1)
    # Never emptied: everything it ever got.
    big = by_bin["L2-S1-B1"]
    assert (big["pieces"], big["unidentified"], big["since"]) == (1, 1, None)
    # Emptied by hand after the second run's first piece: the later moment counts.
    later = client.get(base, params={"bins": "L1-S1-B1", "put_in_after": _iso(201.6)}, headers=key).json()
    assert [(b["bin"]["key"], b["pieces"]) for b in later["bins"]] == [("L1-S1-B1", 1)]

    run = client.get(base, params={"run": "run-1"}, headers=key).json()
    assert run["run"]["name"] == "first"
    assert [(b["bin"]["key"], b["pieces"], [i["count"] for i in b["items"]]) for b in run["bins"]] == [
        ("L1-S1-B1", 3, [2, 1]),
        ("L1-S1-B2", 1, [1]),
    ]
    one = client.get(base, params={"run": "run-1", "bins": "l1-s1-b2", "put_in_before": _iso(3)}, headers=key).json()
    assert [(b["bin"]["key"], b["pieces"]) for b in one["bins"]] == [("L1-S1-B2", 0)]

    took = client.get(base, params={"emptying": 1}, headers=key).json()
    assert took["emptying"]["categories"] == [{"id": "bl_5", "name": "Brick"}]
    # The first run's three and the pass's one.
    assert [(b["bin"]["key"], b["pieces"]) for b in took["bins"]] == [("L1-S1-B1", 4)]

    assert client.get(base, params={"bins": "L0-S1-B1"}, headers=key).status_code == 400


def test_emptyings_page_with_the_pieces_each_took(client, test_machine, machine_token) -> None:
    _machine_with_a_sort(client, machine_token)
    key = _key(client, ["inventory:read"])
    base = f"/api/inventory/v1/machines/{test_machine['id']}/emptyings"
    page = client.get(base, params={"limit": 1}, headers=key).json()
    assert page["next"] == 1
    (first,) = page["emptyings"]
    assert (first["bin"]["key"], first["emptied_at"], first["scope"], first["machine_count"]) == ("L1-S1-B1", _iso(150), "all", 4)
    assert (first["pieces"], first["put_in_after"]) == (4, None)
    page = client.get(base, params={"after": page["next"]}, headers=key).json()
    assert page["next"] is None
    assert [(e["bin"]["key"], e["pieces"], e["categories"]) for e in page["emptyings"]] == [
        ("L1-S1-B2", 1, [{"id": "bl_26", "name": "Plate"}]),
    ]


def test_bins_say_what_they_were_assigned(client, test_machine, machine_token) -> None:
    _machine_with_a_sort(client, machine_token)
    key = _key(client, ["inventory:read"])
    base = f"/api/inventory/v1/machines/{test_machine['id']}/bins"
    body = client.get(base, headers=key).json()
    assert body["layout"]["profile"]["profile_name"] == "Bulk"
    bins = {b["bin"]["key"]: b for b in body["bins"]}
    assert bins["L1-S1-B2"]["categories"] == [{"id": "bl_26", "name": "Plate"}]
    assert (bins["L1-S2-B1"]["enabled"], bins["L1-S1-B1"]["bins_in_section"]) == (False, 2)
    assert bins["L1-S1-B1"]["last_emptying"] == {"id": "1", "emptied_at": _iso(150), "machine_count": 4}

    during = client.get(base, params={"run": "run-1"}, headers=key).json()
    assert {b["bin"]["key"]: b["assignments"] for b in during["bins"]}["L1-S1-B2"] == [
        {"categories": [], "since": _iso(0), "until": _iso(3.5)},
        {"categories": [{"id": "bl_26", "name": "Plate"}], "since": _iso(3.5), "until": _iso(100)},
    ]


def test_only_the_callers_machines_with_the_inventory_scope(client, test_machine, machine_token) -> None:
    _machine_with_a_sort(client, machine_token)
    machine_id = test_machine["id"]
    machines = client.get("/api/inventory/v1/machines", headers=_key(client, ["inventory:read"])).json()["machines"]
    assert [(m["id"], m["synced"]) for m in machines] == [
        (machine_id, {"pieces": 10, "sent_back": 1, "emptyings": 2, "layouts": 2, "runs": 7}),
    ]
    assert machines[0]["version"] == "10.1.2.2.7"
    assert client.get("/api/inventory/v1/machines", headers=_key(client, ["records:read"])).status_code == 403
    other = client.post("/api/machines", json={"name": "Other"}, headers=_auth_headers(client)).json()
    scoped = _key(client, ["inventory:read"], machine_ids=[other["id"]])
    assert [m["id"] for m in client.get("/api/inventory/v1/machines", headers=scoped).json()["machines"]] == [other["id"]]
    assert client.get(f"/api/inventory/v1/machines/{machine_id}/lots", headers=scoped).status_code == 404
    assert client.get(f"/api/inventory/v1/machines/{UUID(int=1)}/lots", headers=_key(client, ["inventory:read"])).status_code == 404
