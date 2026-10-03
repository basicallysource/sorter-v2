from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from server import shared_state
from server.routers import detection, hive_models
from toml_config import getDetectionConfig, setDetectionConfig
from vision import detection_registry as registry


@pytest.fixture
def configured_models(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_SPECIFIC_PARAMS_PATH", str(tmp_path / "machine_params.toml"))
    models = tuple(
        registry.DetectionAlgorithmDefinition(
            id=algorithm,
            label=algorithm,
            description="Installed model",
            supported_scopes=frozenset(scopes),
            kind="local",
        )
        for algorithm, scopes in (
            ("local:channels", {"feeder"}),
            ("local:all", {"feeder", "carousel"}),
            ("local:c4", {"carousel"}),
        )
    )
    monkeypatch.setattr(registry, "_cached_model_algorithms", models)
    perception = SimpleNamespace(request_reconcile=Mock())
    monkeypatch.setattr(shared_state, "gc_ref", SimpleNamespace(perception_service=perception))
    return perception


def test_model_assignment_updates_only_selected_feeder_and_reconciles(configured_models):
    detection.save_feeder_detection_config(
        detection.DetectionConfigPayload(algorithm="local:channels"), role=None,
    )
    detection.save_feeder_detection_config(
        detection.DetectionConfigPayload(algorithm="local:all"), role="c_channel_3",
    )

    saved = getDetectionConfig("feeder")
    assert saved["algorithm"] == "local:channels"
    assert saved["algorithm_by_role"] == {
        "c_channel_2": "local:channels",
        "c_channel_3": "local:all",
    }
    payload = detection.get_feeder_detection_config(role="c_channel_3")
    assert payload["algorithm"] == "local:all"
    assert {option["id"] for option in payload["available_algorithms"]} == {"local:channels", "local:all"}
    assert configured_models.request_reconcile.call_count == 2


def test_c4_assignment_uses_carousel_config(configured_models):
    response = detection.save_carousel_detection_config(
        detection.DetectionConfigPayload(algorithm="local:c4"),
    )
    assert response["algorithm"] == "local:c4"
    assert getDetectionConfig("carousel")["algorithm"] == "local:c4"
    assert not getDetectionConfig("feeder")
    configured_models.request_reconcile.assert_called_once_with()


def test_feeder_change_preserves_other_role_even_if_its_model_is_unavailable(configured_models):
    setDetectionConfig("feeder", {"algorithm_by_role": {"c_channel_2": "local:offline"}})

    detection.save_feeder_detection_config(
        detection.DetectionConfigPayload(algorithm="local:channels"), role="c_channel_3",
    )

    assert getDetectionConfig("feeder")["algorithm_by_role"] == {
        "c_channel_2": "local:offline",
        "c_channel_3": "local:channels",
    }


def test_no_assignment_does_not_select_legacy_or_arbitrary_model(configured_models):
    assert detection.get_feeder_detection_config(role="c_channel_2")["algorithm"] == ""
    assert detection.get_carousel_detection_config()["algorithm"] == ""


def test_hive_activation_reconciles_and_preserves_other_slots(configured_models):
    hive_models._apply_active_assignments("local:all", {"feeder", "carousel"})
    hive_models._apply_active_assignment_to_slot("local:channels", "feeder", "c_channel_2")

    assert getDetectionConfig("feeder")["algorithm_by_role"] == {
        "c_channel_2": "local:channels",
        "c_channel_3": "local:all",
    }
    assert getDetectionConfig("carousel")["algorithm"] == "local:all"
    assert configured_models.request_reconcile.call_count == 2


@pytest.mark.parametrize("algorithm", ["mog2", "gemini_sam", "local:c4", "local:missing"])
def test_feeder_rejects_unavailable_or_wrong_scope_model(configured_models, algorithm):
    with pytest.raises(HTTPException) as error:
        detection.save_feeder_detection_config(
            detection.DetectionConfigPayload(algorithm=algorithm), role="c_channel_2",
        )
    assert error.value.status_code == 400
    assert not getDetectionConfig("feeder")
    configured_models.request_reconcile.assert_not_called()
