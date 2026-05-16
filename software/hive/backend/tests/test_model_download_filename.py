from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.storage import build_download_filename


def _model(slug: str = "lego-detect", version: int = 3, date: str = "2026-04-28") -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        version=version,
        published_at=datetime.fromisoformat(f"{date}T12:00:00+00:00"),
    )


def _variant(runtime: str, file_name: str) -> SimpleNamespace:
    return SimpleNamespace(runtime=runtime, file_name=file_name)


def test_uses_original_extension_when_present() -> None:
    name = build_download_filename(_model(), _variant("onnx", "weights.onnx"))
    assert name == "lego-detect_v3_2026-04-28_onnx.onnx"


@pytest.mark.parametrize(
    "runtime,expected_ext",
    [("onnx", ".onnx"), ("ncnn", ".bin"), ("hailo", ".hef"), ("pytorch", ".pt")],
)
def test_runtime_fallback_extension_when_file_name_has_none(runtime: str, expected_ext: str) -> None:
    name = build_download_filename(_model(), _variant(runtime, "weights"))
    assert name.endswith(f"_{runtime}{expected_ext}")


def test_no_extension_at_all_when_file_name_blank_and_runtime_unknown() -> None:
    name = build_download_filename(_model(), _variant("custom-rt", ""))
    assert name == "lego-detect_v3_2026-04-28_custom-rt"


def test_date_uses_published_at_in_iso_format() -> None:
    model = _model(date="2026-01-09")
    name = build_download_filename(model, _variant("hailo", "model.hef"))
    assert "2026-01-09" in name
    assert name == "lego-detect_v3_2026-01-09_hailo.hef"


def test_preserves_compound_extension_first_segment_only() -> None:
    name = build_download_filename(_model(), _variant("pytorch", "weights.tar.gz"))
    assert name == "lego-detect_v3_2026-04-28_pytorch.gz"
