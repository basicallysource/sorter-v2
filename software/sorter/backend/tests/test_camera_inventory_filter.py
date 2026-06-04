from __future__ import annotations

from server.routers import cameras


def test_macbook_camera_names_are_hidden_from_picker() -> None:
    assert cameras._is_ignored_camera_name("MacBook Pro-Kamera")
    assert cameras._is_ignored_camera_name("MacBook\u00a0Pro-Kamera")


def test_external_camera_names_stay_visible() -> None:
    assert not cameras._is_ignored_camera_name("Logitech StreamCam")
    assert not cameras._is_ignored_camera_name("5MP USB Camera")


def test_v4l2_format_parser_accepts_capture_nodes() -> None:
    output = """
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture

        [0]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 1280x720
"""

    assert cameras._v4l2_formats_include_video_capture(output)


def test_v4l2_format_parser_rejects_metadata_only_nodes() -> None:
    output = """
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture
"""

    assert not cameras._v4l2_formats_include_video_capture(output)


def test_v4l2_size_parser_reads_current_format() -> None:
    output = """
Format Video Capture:
        Width/Height      : 1920/1080
        Pixel Format      : 'MJPG' (Motion-JPEG)
"""

    assert cameras._v4l2_size_from_output(output) == (1920, 1080)
