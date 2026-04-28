from __future__ import annotations

from server.services.camera_settings import set_role_config_value


def test_set_role_config_value_replaces_legacy_c4_alias() -> None:
    config = {
        "machine_setup": {"type": "classification_channel"},
        "camera_picture_settings": {"carousel": {"brightness": 10}},
    }

    set_role_config_value(
        config,
        "camera_picture_settings",
        "classification_channel",
        {"brightness": 20},
    )

    assert config["camera_picture_settings"] == {
        "classification_channel": {"brightness": 20}
    }


def test_set_role_config_value_removes_current_stored_role_only() -> None:
    config = {
        "machine_setup": {"type": "classification_channel"},
        "camera_device_settings": {
            "classification_channel": {"focus": 12},
            "carousel": {"focus": 9},
        },
    }

    set_role_config_value(config, "camera_device_settings", "classification_channel", None)

    assert config["camera_device_settings"] == {"carousel": {"focus": 9}}
