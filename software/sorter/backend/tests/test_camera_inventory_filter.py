from __future__ import annotations

from server.routers import cameras


def test_macbook_camera_names_are_hidden_from_picker() -> None:
    assert cameras._is_ignored_camera_name("MacBook Pro-Kamera")
    assert cameras._is_ignored_camera_name("MacBook\u00a0Pro-Kamera")


def test_external_camera_names_stay_visible() -> None:
    assert not cameras._is_ignored_camera_name("Logitech StreamCam")
    assert not cameras._is_ignored_camera_name("5MP USB Camera")
