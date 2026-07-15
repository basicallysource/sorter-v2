"""Machine color-predict endpoint: auth + payload validation + no-model path.
The actual ONNX inference path is exercised in production against the active
model; building a valid model graph in-test would need the onnx package."""

from __future__ import annotations

from tests.conftest import make_test_image


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _files(n: int):
    return [("images", (f"crop{i}.png", make_test_image(), "image/png")) for i in range(n)]


def test_requires_machine_auth(client):
    # 422 = missing Authorization header (Header(...) is required); bad token = 401.
    resp = client.post("/api/machine/color-predict", files=_files(1))
    assert resp.status_code == 422
    resp = client.post("/api/machine/color-predict", headers=_bearer("bogus"), files=_files(1))
    assert resp.status_code == 401


def test_no_active_model_returns_503(client, machine_token):
    resp = client.post("/api/machine/color-predict", headers=_bearer(machine_token), files=_files(2))
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "NO_ACTIVE_MODEL"


def test_too_many_images_rejected(client, machine_token):
    resp = client.post("/api/machine/color-predict", headers=_bearer(machine_token), files=_files(9))
    assert resp.status_code == 400
    assert resp.json()["code"] == "TOO_MANY_IMAGES"


def test_bad_channels_rejected(client, machine_token):
    resp = client.post(
        "/api/machine/color-predict",
        headers=_bearer(machine_token),
        files=_files(2),
        data={"channels": "[2]"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BAD_CHANNELS"

    resp = client.post(
        "/api/machine/color-predict",
        headers=_bearer(machine_token),
        files=_files(2),
        data={"channels": "not json"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BAD_CHANNELS"