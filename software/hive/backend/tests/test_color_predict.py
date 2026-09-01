"""Device color-predict endpoint: auth + payload validation + no-model path.
The actual ONNX inference path is exercised in production against the active
model; building a valid model graph in-test would need the onnx package."""

from __future__ import annotations

from tests.conftest import make_test_image


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _files(n: int):
    return [("images", (f"crop{i}.png", make_test_image(), "image/png")) for i in range(n)]


def test_requires_device_auth(client):
    # 422 = missing Authorization header (Header(...) is required); bad token = 401.
    resp = client.post("/api/devices/color-predict", files=_files(1))
    assert resp.status_code == 422
    resp = client.post("/api/devices/color-predict", headers=_bearer("bogus"), files=_files(1))
    assert resp.status_code == 401


def test_machine_token_rejected(client, machine_token):
    # Machine tokens are account objects; hosted services auth on device tokens only.
    resp = client.post("/api/devices/color-predict", headers=_bearer(machine_token), files=_files(1))
    assert resp.status_code == 401


def test_no_active_model_returns_503(client, device_token):
    resp = client.post("/api/devices/color-predict", headers=_bearer(device_token), files=_files(2))
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "NO_ACTIVE_MODEL"


def test_too_many_images_rejected(client, device_token):
    resp = client.post("/api/devices/color-predict", headers=_bearer(device_token), files=_files(9))
    assert resp.status_code == 400
    assert resp.json()["code"] == "TOO_MANY_IMAGES"


def test_prediction_logging_persists_row_and_images(client, db, upload_dir, device_token):
    # _log_prediction is only reached after a real ONNX predict, which tests
    # can't run — so exercise it directly with a canned result.
    from starlette.requests import Request

    from app.models.color_prediction import ColorPrediction
    from app.models.device import Device
    from app.routers.color_predict import _log_prediction
    from app.services.storage_backend import get_backend, reset_backend_for_tests

    reset_backend_for_tests()
    device = db.query(Device).first()
    request = Request({"type": "http", "headers": []})
    png = make_test_image().getvalue()
    result = {
        "method": "color_model",
        "model_name": "test-model",
        "model_id": None,
        "model_filename": "test-model.onnx",
        "model_sha256": "ab" * 32,
        "multiview": True,
        "color_id": 7,
        "color_name": "Blue",
        "confidence": 0.9,
        "top": [{"color_id": 7, "confidence": 0.9}],
        "sample_count": 2,
    }
    _log_prediction(db, device, request, [png, png], [4, 2], {"piece_uuid": "abc"}, result, 12.5)

    row = db.query(ColorPrediction).first()
    assert row is not None
    assert row.device_id == device.id
    assert row.color_model_sha256 == "ab" * 32
    assert row.predicted_color_id == 7
    assert row.channels == [4, 2]
    assert row.image_count == 2
    assert row.client_info == {"piece_uuid": "abc"}
    assert len(row.image_keys) == 2
    for key in row.image_keys:
        assert key.startswith(f"devices/{device.id}/color_predict/{row.id}/")
        assert get_backend().exists(key)
    reset_backend_for_tests()


def test_bad_channels_rejected(client, device_token):
    resp = client.post(
        "/api/devices/color-predict",
        headers=_bearer(device_token),
        files=_files(2),
        data={"channels": "[2]"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BAD_CHANNELS"

    resp = client.post(
        "/api/devices/color-predict",
        headers=_bearer(device_token),
        files=_files(2),
        data={"channels": "not json"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BAD_CHANNELS"
